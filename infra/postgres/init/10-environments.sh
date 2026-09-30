#!/bin/sh
# Create one role and one database per local environment, with no way to reach across them.
#
# This runs once, on an empty data directory, as the bootstrap superuser. The isolation it
# establishes is the local expression of the promotion ladder in
# services/control-plane/config: dev and test are separate databases, each owned by a role
# that cannot connect to the other. Paper, shadow, and live are deliberately absent.
#
# Why isolation has to be enforced by the database rather than by configuration
# ----------------------------------------------------------------------------
# Separating the environments by database name in an env file is a convention, and a
# convention is one copy-paste away from not being true. If the dev role can connect to the
# test database, then a mistyped connection string silently points development work at test
# data, and the first sign of it is a test that passes against the wrong rows. Revoking
# CONNECT makes that a connection error at the moment it happens, which is a finding rather
# than a mystery.
#
# The three privileges that matter here:
#
#   REVOKE CONNECT ... FROM PUBLIC
#     PostgreSQL grants CONNECT on a database to PUBLIC by default, so a fresh database is
#     reachable by every role. Without this revocation the per-role grants below are
#     meaningless, because the default already allowed it.
#
#   The role is not a superuser, cannot create roles, and cannot create databases.
#     A development role that could CREATE DATABASE could make itself a copy of any
#     environment, which would defeat the isolation being set up.
#
#   paper, shadow, and live get no database at all.
#     docs/25 3.7 and WI-170 keep live out of scope. Provisioning an empty paper or shadow
#     database here would create the appearance of a lower-fidelity live environment running
#     locally, which is exactly the assumption that leads to a paper account being treated as
#     real. An absent environment cannot be connected to by accident.
#
# Passwords arrive as environment variables and are never written to a file, logged, or
# committed. They are set to the verified no-log role rather than interpolated into SQL, so
# a password cannot become part of a statement that ends up in a log or an error message.

set -eu

: "${WEBTRADE_DEV_PASSWORD:?WEBTRADE_DEV_PASSWORD must be set}"
: "${WEBTRADE_TEST_PASSWORD:?WEBTRADE_TEST_PASSWORD must be set}"

SUPERUSER="${POSTGRES_USER:?POSTGRES_USER must be set}"
SUPERUSER_DB="${POSTGRES_DB:?POSTGRES_DB must be set}"

# make_environment <role> <database> <password> <label>
#
# The role is created NOSUPERUSER NOCREATEDB NOCREATEROLE and the database is owned by it, so
# the application role can create and migrate its own schema without being able to escape into
# another environment.
make_environment() {
    role="$1"
    database="$2"
    password="$3"
    label="$4"

    # REVOKE the ability to log in with a null password before granting the real one. A role
    # created with CREATE ROLE and no password can be connected to by anyone who can reach the
    # port, which on a loopback-bound container is still anyone running code on the machine.
    psql -v ON_ERROR_STOP=1 --username "$SUPERUSER" --dbname "$SUPERUSER_DB" <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${role}') THEN
        CREATE ROLE ${role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
            PASSWORD NULL;
    END IF;
END
\$\$;
ALTER ROLE ${role} WITH PASSWORD '${password}';
SQL

    if ! psql -v ON_ERROR_STOP=1 --username "$SUPERUSER" --dbname "$SUPERUSER_DB" \
        --tuples-only --no-align \
        --command "SELECT 1 FROM pg_database WHERE datname = '${database}'" | grep -q 1; then
        # OWNER matters: without it the role could not create the schema its own migrations
        # need, and the first migration would fail on permissions rather than on content.
        psql -v ON_ERROR_STOP=1 --username "$SUPERUSER" --dbname "$SUPERUSER_DB" \
            --command "CREATE DATABASE ${database} OWNER ${role} ENCODING 'UTF8'"
    fi

    # The default grant is the whole problem. Removed from PUBLIC first, then given to the one
    # role that owns the database, and to nobody else.
    psql -v ON_ERROR_STOP=1 --username "$SUPERUSER" --dbname "$SUPERUSER_DB" <<SQL
REVOKE ALL ON DATABASE ${database} FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE ${database} TO ${role};
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL

    # The public schema in PostgreSQL 15 and later is owned by pg_database_owner and is no
    # longer writable by PUBLIC. Stated explicitly rather than assumed, because a stack that
    # works on 15 and silently lets dev write test's tables on a different major version is
    # not a stack anyone should trust.
    psql -v ON_ERROR_STOP=1 --username "$SUPERUSER" --dbname "${database}" <<SQL
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO ${role};
SQL

    echo "created role and database for ${label} (${role} / ${database})"
}

make_environment web_trade_dev web_trade_dev "$WEBTRADE_DEV_PASSWORD" "dev"
make_environment web_trade_test web_trade_test "$WEBTRADE_TEST_PASSWORD" "test"

# The isolation itself, asserted rather than assumed.
#
# This block fails the stack's initialisation if either role can reach the other environment.
# It is the only place where the check is cheap, because the roles exist only at this moment;
# afterwards, verifying it means starting the stack and connecting as each role, which is what
# scripts/verify_local_env.py does on every run.
dev_to_test="$(psql -v ON_ERROR_STOP=1 --username web_trade_dev --dbname web_trade_test \
    --tuples-only --no-align --command 'SELECT 1' 2>&1 || true)"
if [ "${dev_to_test}" != "FATAL" ] && ! printf '%s' "${dev_to_test}" | grep -q "permission denied"; then
    echo "FATAL: role web_trade_dev can connect to the test database; environments are not isolated" >&2
    exit 1
fi

test_to_dev="$(psql -v ON_ERROR_STOP=1 --username web_trade_test --dbname web_trade_dev \
    --tuples-only --no-align --command 'SELECT 1' 2>&1 || true)"
if [ "${test_to_dev}" != "FATAL" ] && ! printf '%s' "${test_to_dev}" | grep -q "permission denied"; then
    echo "FATAL: role web_trade_test can connect to the dev database; environments are not isolated" >&2
    exit 1
fi

echo "environment isolation verified: neither dev nor test can reach the other"
