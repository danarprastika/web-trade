"""Bring up the local PostgreSQL 17 stack and prove it is what it claims to be.

docs/05 makes PostgreSQL the system of record, and WI-108 asks for three things: a compose
stack that comes up healthy, no credential in the repository, and local environments isolated
from anything that is not local. The first and the third are checked here against a running
stack. The second is a repository property and is asserted by tests/ci, which can read the
committed tree without needing Docker.

What is actually proven
-----------------------
  healthy        the healthcheck passes and the database answers a real statement
  migratable     the full migration set applies into the dev database as the dev role
  isolated       the dev role is refused by the test database, and the reverse
  local only     paper, shadow, and live do not exist as databases

The isolation assertions are the reason this is more than a smoke test. Naming the test
database in a connection string is a convention; being refused by the server is a control. If
this only checked that `docker compose up` returns zero, a stack with no isolation at all
would pass it.

The credentials come from the environment, never from a file this script writes. The script
generates them into a process-local environment if they are not already set, so it is runnable
without a populated .env while still exercising the same compose file an operator uses. A
generated value is a throwaway for a loopback-bound development database and is never printed.

Exit codes:
    0  the stack is healthy, migratable, and isolated
    1  a required property did not hold
    2  the check could not run (docker or compose unavailable, compose file invalid)

Usage:
    python scripts/verify_local_env.py
    python scripts/verify_local_env.py --keep     # leave the stack running
    python scripts/verify_local_env.py --no-fresh # reuse the existing volume
    python scripts/verify_local_env.py --down     # tear down and exit

The default run destroys the local volume. That is intended: init scripts only run against an
empty data directory, so a verification that reuses an existing volume can report results that
depend on whatever the previous run left behind. This stack is local-only and holds no data
that is not reproducible from the migrations. Use --no-fresh to keep the volume, and --keep
to inspect the stack by hand afterwards.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pgverify import Postgres  # noqa: E402  (shared container conventions)

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "infra" / "compose.yaml"
PROJECT = "webtrade"

DEV_DB = "web_trade_dev"
TEST_DB = "web_trade_test"
DEV_ROLE = "web_trade_dev"
TEST_ROLE = "web_trade_test"

# Never provisioned locally. docs/25 3.7 and WI-170 keep live out of scope, and an empty
# paper or shadow database would create the impression of a lower-fidelity live environment
# running on a laptop.
FORBIDDEN_DATABASES = ["web_trade_paper", "web_trade_shadow", "web_trade_live", "paper", "shadow", "live"]


def compose(*args: str, env: dict | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", PROJECT, *args]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout, env=env, check=False)


def compose_env() -> dict:
    """The environment compose needs, generating throwaway values for anything unset.

    Generation rather than a hardcoded default is the point: a literal password here would be
    a credential in the repository, which is the thing WI-108's second criterion forbids. The
    generated value lives only in this process's environment for a container bound to
    loopback.
    """
    env = dict(os.environ)
    generated = {
        "WEBTRADE_PG_SUPERUSER": "web_trade_bootstrap",
        "WEBTRADE_PG_SUPERUSER_DB": "postgres",
        "WEBTRADE_PG_PORT": "5432",
    }
    for name in ("WEBTRADE_PG_SUPERUSER_PASSWORD", "WEBTRADE_DEV_PASSWORD",
                 "WEBTRADE_TEST_PASSWORD"):
        if not env.get(name):
            env[name] = secrets.token_urlsafe(24)
    env.update({k: v for k, v in generated.items() if not env.get(k)})
    return env


def check_compose_file_is_valid(env: dict) -> tuple[bool, str]:
    """`docker compose config` parses and resolves the file.

    Run before anything is started, because a compose file that does not resolve is a much
    cheaper failure than one that half-starts a stack.
    """
    result = compose("config", "--quiet", env=env, timeout=120)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:500]
    return True, "resolves"


def check_credentials_are_required(env: dict) -> tuple[bool, str]:
    """The stack must refuse to start when a credential is unset.

    This is the compose file's own contract: every secret uses ${VAR:?message}. A stack that
    starts with a default password is a stack whose password is in git history, so this asserts
    the refusal rather than trusting that the syntax is right.
    """
    stripped = dict(env)
    for name in ("WEBTRADE_DEV_PASSWORD", "WEBTRADE_TEST_PASSWORD",
                 "WEBTRADE_PG_SUPERUSER_PASSWORD"):
        stripped.pop(name, None)
    result = compose("config", "--quiet", env=stripped, timeout=120)
    if result.returncode == 0:
        return False, "compose resolved with no credentials set; it would start with defaults"
    message = (result.stderr or result.stdout)
    if "WEBTRADE_DEV_PASSWORD" not in message:
        return False, f"compose failed but not for the expected reason: {message.strip()[:300]}"
    return True, "refuses to start without credentials, naming the missing variable"


def check_healthy(env: dict, fresh: bool) -> tuple[bool, str]:
    """Start the stack and require the healthcheck to pass.

    `fresh` tears down the volume first. This is not tidiness — it is correctness. The
    `/docker-entrypoint-initdb.d` script only ever runs against an *empty* data directory, so
    on a volume that already exists the roles are never created or re-passworded. Start on a
    stale volume and every role login fails while the compose file and the init script both
    look correct, which is a genuinely confusing failure to debug. Verification that can
    inherit state from a previous run is not verification.
    """
    if fresh:
        compose("down", "--volumes", "--remove-orphans", env=env, timeout=180)
    result = compose("up", "--wait", "--wait-timeout", "120", env=env, timeout=300)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[-800:]
    ps = compose("ps", "--format", "{{.Name}}\t{{.Health}}", env=env, timeout=60)
    health = [l for l in ps.stdout.splitlines() if l.strip()]
    if not health or not any("healthy" in l for l in health):
        return False, f"stack started but reports no healthy service: {health}"
    return True, "; ".join(health)


def psql(role: str, database: str, env: dict, password: str, *, sql: str | None = None,
         stdin: str | None = None) -> tuple[int, str]:
    """Run psql as `role` and return (exit code, combined output).

    Deliberately not `docker exec`: a psql container makes a real TCP connection, so it
    exercises port publication and pg_hba authentication — the path an application uses.
    `docker exec` would sit inside the container as the superuser and prove nothing about the
    role being tested.

    Two details are load-bearing:

    `-e PGPASSWORD` is passed with no `=value`, which tells Docker to copy the variable out
    of *this process's* environment. Writing `-e PGPASSWORD=$PGPASSWORD` instead sets the
    container variable to the literal seven-character string `$PGPASSWORD`, and every
    connection then fails with a password error that looks like a broken role.

    The client container is on the default bridge and reaches the server through
    `host.docker.internal`, because `127.0.0.1` inside a container is that container, not
    the host. `--add-host ...:host-gateway` supplies the name on Linux Docker, where it is
    not provided by default.
    """
    port = env.get("WEBTRADE_PG_PORT", "5432")
    url = f"postgres://{role}@host.docker.internal:{port}/{database}?sslmode=disable"
    # Docker flags must precede the image name; anything after it is an argument to psql.
    cmd = [
        "docker", "run", "--rm",
        "--add-host", "host.docker.internal:host-gateway",
        "-e", "PGPASSWORD",
    ]
    if stdin is not None:
        cmd += ["--interactive"]
    cmd += [
        "postgres:17-alpine",
        "psql", url, "--tuples-only", "--no-align", "-v", "ON_ERROR_STOP=1",
    ]
    cmd += ["-f", "-"] if stdin is not None else ["-c", sql or ""]
    result = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                            timeout=180, check=False,
                            env={**env, "PGPASSWORD": password})
    return result.returncode, (result.stdout + result.stderr).strip()


def check_migrations_apply(env: dict) -> tuple[bool, str]:
    """The full migration set applies into the dev database as the dev role.

    Applied as the application role rather than the bootstrap superuser, because a migration
    that needs superuser rights would mean the production role lacks the permissions its own
    schema requires.
    """
    from rehearse_migrations import load_set

    applied = []
    for name, up, _down in load_set():
        code, output = psql(DEV_ROLE, DEV_DB, env, env["WEBTRADE_DEV_PASSWORD"], stdin=up)
        if code != 0:
            return False, f"{name} failed as {DEV_ROLE}: {output[-400:]}"
        applied.append(name)
    return True, f"{len(applied)} migration(s) applied as {DEV_ROLE}: {', '.join(applied)}"


def check_isolation(env: dict) -> tuple[bool, str]:
    """Each role must be refused by the other environment's database.

    The refusal has to say `permission denied` specifically. Accepting any non-zero exit
    would also accept "connection refused", which means the port is wrong or the server is
    down — a check that passes because it never reached PostgreSQL proves nothing about
    isolation.
    """
    results = []
    for role, target, password in (
        (DEV_ROLE, TEST_DB, env["WEBTRADE_DEV_PASSWORD"]),
        (TEST_ROLE, DEV_DB, env["WEBTRADE_TEST_PASSWORD"]),
    ):
        code, output = psql(role, target, env, password, sql="SELECT 1")
        if code == 0:
            return False, (f"{role} connected to {target}; environments are not isolated. "
                           f"PostgreSQL grants CONNECT to PUBLIC by default, so the REVOKE "
                           f"in the init script is what this proves is present.")
        if "permission denied" not in output.lower():
            return False, f"{role} failed to reach {target}, but not by permission denial: {output[:300]}"
        results.append(f"{role} refused by {target}")
    return True, "; ".join(results)


def check_nonlocal_environments_absent(env: dict) -> tuple[bool, str]:
    """No database may exist for paper, shadow, or live.

    The connection itself is verified first. Reading the catalog and finding nothing is only
    evidence if the read happened; without that check a refused connection produces an empty
    result set and the check passes while proving nothing.
    """
    probe_code, probe_output = psql(DEV_ROLE, DEV_DB, env, env["WEBTRADE_DEV_PASSWORD"],
                                    sql="SELECT 1")
    if probe_code != 0:
        return False, f"could not read the database catalog as {DEV_ROLE}: {probe_output[:300]}"

    present = []
    for database in FORBIDDEN_DATABASES:
        code, output = psql(DEV_ROLE, DEV_DB, env, env["WEBTRADE_DEV_PASSWORD"],
                            sql=f"SELECT 1 FROM pg_database WHERE datname = '{database}'")
        if code != 0:
            return False, f"catalog query for {database} failed: {output[:200]}"
        if output.strip() == "1":
            present.append(database)
    if present:
        return False, f"these environments are provisioned locally: {', '.join(present)}"
    return True, f"catalog readable and none of {len(FORBIDDEN_DATABASES)} paper/shadow/live names exist"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="leave the stack running")
    parser.add_argument("--down", action="store_true", help="tear the stack down and exit")
    parser.add_argument("--no-fresh", action="store_true",
                        help="reuse the existing volume instead of recreating it. Discouraged: "
                             "the init script only runs on an empty volume, so a reused one "
                             "keeps whatever roles and passwords it had.")
    args = parser.parse_args()

    if not COMPOSE_FILE.is_file():
        print(f"missing {COMPOSE_FILE}", file=sys.stderr)
        return 2

    env = compose_env()
    failures = 0

    if args.down:
        compose("down", "--volumes", "--remove-orphans", env=env, timeout=180)
        print("local stack torn down")
        return 0

    try:
        checks = [
            ("compose resolves", lambda: check_compose_file_is_valid(env)),
            ("credentials required", lambda: check_credentials_are_required(env)),
            ("stack healthy", lambda: check_healthy(env, fresh=not args.no_fresh)),
            ("migrations apply", lambda: check_migrations_apply(env)),
            ("environments isolated", lambda: check_isolation(env)),
            ("paper/shadow/live absent", lambda: check_nonlocal_environments_absent(env)),
        ]
        for label, check in checks:
            try:
                ok, detail = check()
            except subprocess.TimeoutExpired as exc:
                ok, detail = False, f"timed out: {exc}"
            if not ok:
                failures += 1
            print(f"  {'PASS' if ok else 'FAIL'}  {label:28} {detail}")
    finally:
        if not args.keep:
            compose("down", "--volumes", "--remove-orphans", env=env, timeout=180)
    print()
    if failures:
        print(f"{failures} local-environment check(s) FAILED")
        return 1
    print("all local-environment checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
