"""Rehearse the migration set up, down, and up again against a real PostgreSQL 17.

docs/09 lists migration rehearsal as a release gate and docs/24 requires expand/contract
discipline. Neither can be satisfied by a runner that only goes one way: a schema change that
cannot be reversed cannot be rehearsed, and a rehearsal that has never run is a claim rather
than a result.

This proves three things, in order, against one container:

  1. the whole set applies from empty;
  2. the whole set reverts, newest first, leaving nothing behind;
  3. the whole set applies again onto the reverted database.

The third step is the one that catches the failure that matters. A down body that drops a
table but leaves a function behind, or a dependency that only resolves on a clean database,
produces a first up that works and a second up that does not. Verifying only that the down
ran would pass that.

Existence is checked against the system catalog rather than by re-running the domain
assertions, because the question here is whether the objects exist, not whether the ledger
still balances.

Exit codes:
    0  the set applied, fully reverted to a clean catalog, and applied again
    1  a step failed or left residue behind
    2  the check could not run (docker unavailable, migration missing, not reversible)

Usage:
    python scripts/rehearse_migrations.py
    python scripts/rehearse_migrations.py --keep     # leave the container for inspection
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pgverify import (  # noqa: E402
    DEFAULT_IMAGE,
    DOWN_MARKER,
    Postgres,
    PsqlError,
    docker_available,
    migration_bodies,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"

# The objects whose presence proves the set applied, and whose absence proves the down
# actually reverted. Every one of them is a named object created by a migration up body; a
# rehearsal that only checked "did the down statement run" would not notice a down body
# that silently skipped one of these.
#
# The qualification is not uniform, and that is deliberate rather than an oversight. 0001
# creates a real `ledger` schema; 0002 and 0003 create unqualified tables that land in
# `public` and use a name prefix instead of a namespace. Listing them as `public.` states
# where they actually are, which is the form the catalog lookup can match and the form the
# finding about schema ownership is written against. Moving the nine tables into proper
# schemas is a breaking change and belongs in its own migration, not here.
EXPECTED_OBJECTS = [
    ("schema", "ledger"),
    ("table", "ledger.entry"),
    ("table", "ledger.line"),
    ("table", "public.audit_records"),
    ("table", "public.audit_checkpoints"),
    ("table", "public.audit_deletion_events"),
    ("table", "public.authz_session_policy"),
    ("table", "public.authz_role_action_exclusion"),
    ("table", "public.authz_policy_bundles"),
    ("table", "public.authz_permission_state"),
    ("table", "public.authz_role_grants"),
    ("table", "public.authz_sessions"),
    ("table", "public.authz_approvals"),
    ("table", "public.authz_decisions"),
    ("table", "public.model_registry"),
    ("table", "public.workload_identities"),
    ("table", "public.workload_revocations"),
    ("table", "public.model_transition_idempotency"),
]

# Functions are tracked separately from tables because the failure mode differs. A down body
# that drops its tables but leaves a function behind is the classic incomplete reversal, and
# it is invisible if the check only counts tables.
#
# All but the two ledger functions are in `public`, for the same reason as the tables above.
EXPECTED_FUNCTIONS = [
    "ledger.assert_entry_balances()",
    "ledger.refuse_mutation()",
    "public.audit_refuse_mutation()",
    "public.audit_check_chain_link()",
    "public.audit_check_checkpoint_coverage()",
    "public.authz_refuse_exclusion_mutation()",
    "public.authz_check_bundle_retirement()",
    "public.authz_check_rule_against_exclusions()",
    "public.authz_bump_revision_on_grant_change()",
    "public.authz_check_wildcard_scope()",
    "public.authz_check_session_age()",
    "public.authz_bump_revision_on_session_revocation()",
    "public.authz_check_approval_immutability()",
    "public.model_registry_check_transition()",
    "public.model_registry_refuse_identity_mutation()",
    "public.workload_revocations_refuse_mutation()",
    "public.workload_identities_refuse_revoked_reissue()",
    "public.model_transition_idempotency_refuse_mutation()",
]

# A single quote, because that is what delimits a string literal in SQL.
#
# This was a double quote in the first version, which is the identifier quote in PostgreSQL:
# every probe compiled to `schema_name = "ledger"`, compared the column against a column that
# does not exist, returned no rows, and the rehearsal reported all 27 objects absent after a
# perfectly good apply. The failure looked like a broken migration rather than a broken query.
QUOTE = "'"

# The sqlc query files are compiled against the live schema, not merely checked in.
#
# This is the check that would have caught a real defect. AppendEntry originally used
# `ON CONFLICT (idempotency_key)`, while the unique index is on the pair
# (source_command_id, idempotency_key). That statement is syntactically valid, sqlc parses it,
# sqlc vet passes, and it fails only at runtime with "there is no unique or exclusion
# constraint matching the ON CONFLICT specification". Neither the generator nor the query
# contract test can see it, because the defect is a disagreement between the SQL and an index
# rather than a disagreement with the SQL grammar.
QUERIES_DIR = ROOT / "services" / "control-plane" / "db" / "queries"

QUERY_HEADER = re.compile(
    r"(?ms)^--\s+name:\s+(?P<name>\w+)\s+:(?P<verb>\w+)\s*$(?P<body>.*?)(?=^--\s+name:|\Z)")

CONFLICT_TARGET = re.compile(r"(?i)ON\s+CONFLICT\s*\((?P<cols>[^)]*)\)")
INSERT_TARGET = re.compile(r"(?i)INSERT\s+INTO\s+(?P<table>[\w\".]+)")


def load_queries() -> list[tuple[str, str, str]]:
    """Return (name, verb, body) for every declared sqlc query."""
    if not QUERIES_DIR.is_dir():
        return []
    queries = []
    for path in sorted(QUERIES_DIR.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for m in QUERY_HEADER.finditer(text):
            queries.append((m.group("name"), m.group("verb"), m.group("body").strip()))
    return queries


# One row per unique index, carrying that index's own column list in index order.
#
# The indkey array is read with `indnkeyatts` so that a partial or expression index's
# included columns are not mistaken for key columns, and the ordinality join keeps each
# index's columns contiguous. Reading pg_attribute directly without the index grouping merges
# every unique index on a table into one list, which then matches nothing -- or, worse, matches
# a suffix of a real index and passes a query that PostgreSQL would refuse.
UNIQUE_INDEX_SQL = """
select ns.nspname || '|' || cls.relname || '|' || idx.indexrelid::text || '|' ||
  array_to_string((
    select array_agg(att.attname order by k.ord)
    from unnest(idx.indkey[0:idx.indnkeyatts - 1]) with ordinality as k(attnum, ord)
    join pg_attribute att on att.attrelid = cls.oid and att.attnum = k.attnum
  ), ',')
from pg_index idx
join pg_class cls on cls.oid = idx.indrelid
join pg_namespace ns on ns.oid = cls.relnamespace
where idx.indisunique and idx.indpred is null
order by 1
"""


def unique_indexes(pg: Postgres) -> set[frozenset[str]]:
    """Every unique index, as a set of qualified column names.

    A frozenset because PostgreSQL's inference is order-insensitive: `ON CONFLICT (a, b)` and
    `ON CONFLICT (b, a)` both match a unique index on (a, b), and both were confirmed against
    a live PostgreSQL 17. A tuple would report one of those as an error.
    """
    indexes: set[frozenset[str]] = set()
    for line in pg.psql(UNIQUE_INDEX_SQL, tuples_only=True).stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 4 or not parts[3]:
            continue
        schema, table, _index_oid, columns = parts
        cols = frozenset(f"{schema}.{c.strip().lower()}"
                         for c in columns.split(",") if c.strip())
        if cols:
            indexes.add(cols)
    return indexes


TABLE_SCHEMAS_SQL = """
select n.nspname || '|' || c.relname
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relkind = 'r' and n.nspname not in ('pg_catalog', 'information_schema')
order by 1
"""


def table_schemas(pg: Postgres) -> dict[str, str | None]:
    """Unqualified table name -> schema, or None where the name is ambiguous.

    The None matters: resolving an ambiguous name to whichever schema sorted first would let a
    conflict target validate against the wrong table, which is precisely the kind of wrong
    answer a schema check must not give.
    """
    found: dict[str, str | None] = {}
    for line in pg.psql(TABLE_SCHEMAS_SQL, tuples_only=True).stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 2:
            continue
        schema, table = parts
        if table in found:
            found[table] = None
        else:
            found[table] = schema
    return found


def strip_sql_comments(sql: str) -> str:
    """Remove `--` and `/* */` comments, leaving string literals intact.

    Necessary because the checks below match on SQL keywords, and these query files explain
    their own design in comments that quote the very statements they are discussing. Without
    this, the comment "Writing ON CONFLICT (idempotency_key) looks equivalent and is" is
    indistinguishable from a real statement, and the check reports a defect in a file that has
    none.

    Quoted text is tracked so that a `--` inside a string literal is not mistaken for a
    comment; a query that stores a reason containing a dash would otherwise have the rest of
    its statement deleted before being checked.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    in_single = in_line = in_block = False
    while i < n:
        c = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if in_single:
            out.append(c)
            if c == "'":
                # A doubled quote is an escaped quote, not the end of the literal.
                if nxt == "'":
                    out.append(nxt)
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if c == "-" and nxt == "-":
            in_line = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == "'":
            in_single = True
        out.append(c)
        i += 1
    return "".join(out)


def check_conflict_targets(pg: Postgres) -> list[str]:
    """Every ON CONFLICT target that no unique index backs.

    Type-independent by design. The alternative, preparing each statement, cannot cover
    parameterised queries: PostgreSQL refuses to infer the type of a $1 placeholder, so a
    prepared form would have to hand-write the parameter types and would then be verifying
    the harness rather than the schema. Matching the conflict target against the catalog
    tests the actual invariant and needs no types.
    """
    known = unique_indexes(pg)
    schemas = table_schemas(pg)
    failures: list[str] = []

    for name, verb, raw_body in load_queries():
        body = strip_sql_comments(raw_body)
        targets = list(CONFLICT_TARGET.finditer(body))
        if not targets:
            continue
        target = INSERT_TARGET.search(body)
        if not target:
            failures.append(f"{name} ({verb}): has an ON CONFLICT but no readable INSERT "
                            f"target, so it could not be checked")
            continue

        table = target.group("table").strip('"')
        if "." in table:
            schema, bare = table.rsplit(".", 1)
        else:
            schema, bare = schemas.get(table), table

        if schema is None:
            failures.append(f"{name} ({verb}): table {table!r} is missing or ambiguous in the "
                            f"schema, so its conflict target could not be checked")
            continue

        for m in targets:
            cols = frozenset(
                f"{schema}.{c.strip().strip(chr(34)).lower()}"
                for c in m.group("cols").split(",") if c.strip()
            )
            if not cols:
                continue
            if cols in known:
                continue
            # Reported with the indexes that do exist, because "matches no unique index"
            # without saying what does exist sends the reader back to the catalog.
            available = sorted(
                ".".join(sorted(c.split(".", 1)[1]))
                for c in known if any(col.endswith("." + table) for col in c)
            )
            hint = (f"; unique indexes on {table}: " + ", ".join(available)) if available else ""
            failures.append(
                f"{name} ({verb}): ON CONFLICT ({', '.join(sorted(m.group('cols').split(',')))}) "
                f"matches no unique index on {table}{hint}"
            )
    return failures


def prepare_parameterless(pg: Postgres) -> list[str]:
    """PREPARE every query that takes no parameters. Returns the ones that failed.

    Parameterised queries are deliberately not prepared here: PostgreSQL refuses to infer the
    type of a $1 placeholder, so a prepared form would need hand-written parameter types and
    would then be verifying this harness rather than the schema.

    That leaves a visible gap, and it is covered by a different tool rather than left open.
    Confirmed by mutation against this repository's own queries:

        mutation                            sqlc generate   this rehearsal
        unknown column in a query           CAUGHT          (not reached)
        unknown table                       CAUGHT          (not reached)
        ON CONFLICT on an unindexed column  ACCEPTED        CAUGHT

    sqlc resolves every query against the schema, so it refuses an unknown column, an unknown
    table, a wrong type, and a wrong parameter count. It does not look at conflict targets,
    because an ON CONFLICT clause is syntactically valid against any table; only the live
    index list can say whether the inference will succeed. So the two checks are complementary
    rather than overlapping, and a third class of defect would need a third check rather than
    more effort in either of these.
    """
    failures = []
    for name, verb, raw_body in load_queries():
        body = strip_sql_comments(raw_body).strip().rstrip(";")
        if not body or re.search(r"\$\d+", body):
            continue
        result = pg.psql(f"PREPARE _rehearsal AS {body}", on_error_stop=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            failures.append(f"{name} ({verb}): {detail[0] if detail else 'failed'}")
        else:
            pg.psql("DEALLOCATE _rehearsal")
    return failures


def load_set() -> list[tuple[str, str, str]]:
    """Load the migration set in ascending version order as (name, up, down).

    Ordered by the parsed numeric version rather than by filename, for the same reason
    services/control-plane/migrate does it: lexical ordering puts 00010 before 0002.
    """
    entries: list[tuple[int, str, str, str]] = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        up, down = migration_bodies(path.read_text(encoding="utf-8"))
        entries.append((version, path.name, up, down))
    entries.sort(key=lambda e: e[0])
    return [(name, up, down) for _, name, up, down in entries]


def object_exists(pg: Postgres, kind: str, name: str) -> bool:
    if kind == "schema":
        sql = f"select 1 from information_schema.schemata where schema_name = {QUOTE}{name}{QUOTE}"
    else:
        sql = (f"select 1 from information_schema.tables "
               f"where table_schema || '.' || table_name = {QUOTE}{name}{QUOTE}")
    return pg.psql(sql, tuples_only=True).stdout.strip() == "1"


def function_exists(pg: Postgres, signature: str) -> bool:
    # Matched on the argument types rather than the name alone, because several of these
    # functions share a basename across schemas and a name-only match would report a
    # survivor in the wrong namespace as the object still being present.
    sql = (f"select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
           f"where n.nspname || '.' || p.proname || '()' = {QUOTE}{signature}{QUOTE}")
    return pg.psql(sql, tuples_only=True).stdout.strip() == "1"


def survivors(pg: Postgres) -> list[str]:
    """Everything still in the database that a full revert should have removed."""
    left = [f"{kind} {name}" for kind, name in EXPECTED_OBJECTS if object_exists(pg, kind, name)]
    left += [f"function {sig}" for sig in EXPECTED_FUNCTIONS if function_exists(pg, sig)]
    return left


def apply_all(pg: Postgres, migrations, bodies: str) -> None:
    for (name, up, down) in migrations:
        body = up if bodies == "up" else down
        if not body.strip():
            raise PsqlError(f"{name} has no {bodies} body",
                            type("R", (), {"stderr": "", "stdout": ""})())
        pg.apply(body, action=f"applying {name} ({bodies})")
        print(f"  {bodies:>4}  {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE,
                        help="PostgreSQL image to rehearse against (must be 17)")
    parser.add_argument("--keep", action="store_true",
                        help="leave the container running after the rehearsal")
    args = parser.parse_args()

    if "17" not in args.image:
        print(f"refusing to rehearse against {args.image}: the migrations target "
              f"PostgreSQL 17", file=sys.stderr)
        return 2

    migrations = load_set()
    if not migrations:
        print(f"no migrations found in {MIGRATIONS}", file=sys.stderr)
        return 2

    # Refuse before touching a database. A set that cannot be fully reverted cannot satisfy
    # the rehearsal, and discovering that after applying three migrations leaves the operator
    # with a half-migrated database and the same question.
    missing = [name for name, _, down in migrations if not down.strip()]
    if missing:
        print("cannot rehearse, these migrations declare no "
              f"{DOWN_MARKER} body: {', '.join(missing)}", file=sys.stderr)
        return 2

    available, version = docker_available()
    if not available:
        print(f"docker is unavailable: {version}", file=sys.stderr)
        return 2

    print(f"rehearsing {len(migrations)} migration(s) against {args.image}")
    pg = Postgres(image=args.image, label="webtrade-rehearse").__enter__()
    try:
        print(f"verified against {pg.version} (docker {version})")

        print("\n[1/4] applying the set from empty")
        apply_all(pg, migrations, "up")
        left = survivors(pg)
        if len(left) != len(EXPECTED_OBJECTS) + len(EXPECTED_FUNCTIONS):
            missing_objects = _absent(pg)
            print(f"  {len(missing_objects)} expected object(s) absent after the up pass: "
                  f"{', '.join(missing_objects)}", file=sys.stderr)
            return 1
        print(f"  all {len(left)} expected objects present")

        print("\n[2/4] compiling the sqlc queries against the live schema")
        query_failures = check_conflict_targets(pg) + prepare_parameterless(pg)
        if query_failures:
            print(f"  {len(query_failures)} query/queries do not match the schema:",
                  file=sys.stderr)
            for failure in query_failures:
                print(f"    - {failure}", file=sys.stderr)
            return 1
        print(f"  all {len(load_queries())} declared queries match the schema")

        print("\n[3/4] reverting the set, newest first")
        for (name, _, down) in reversed(migrations):
            pg.apply(down, action=f"reverting {name}")
            print(f"  down  {name}")

        # The assertion that makes step 3 meaningful. Checking that the down statements ran
        # would pass a reversal that left residue and then failed on the way back up.
        residue = survivors(pg)
        if residue:
            print(f"  the revert left {len(residue)} object(s) behind: "
                  f"{', '.join(residue)}", file=sys.stderr)
            return 1
        print("  catalog is clean: no migration object survives the revert")

        print("\n[4/4] applying the set again onto the reverted database")
        apply_all(pg, migrations, "up")
        left = survivors(pg)
        if len(left) != len(EXPECTED_OBJECTS) + len(EXPECTED_FUNCTIONS):
            missing_objects = _absent(pg)
            print(f"  {len(missing_objects)} expected object(s) absent after the second up "
                  f"pass: {', '.join(missing_objects)}", file=sys.stderr)
            return 1
        print(f"  all {len(left)} expected objects present again")

        print(f"\nMIGRATION REHEARSAL PASSED: up, down to a clean catalog, and up again")
        return 0
    except PsqlError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if not args.keep:
            pg.__exit__()


def _absent(pg: Postgres) -> list[str]:
    """The expected objects that are not present, for a message that says which."""
    out = [f"{kind} {name}" for kind, name in EXPECTED_OBJECTS
           if not object_exists(pg, kind, name)]
    out += [f"function {sig}" for sig in EXPECTED_FUNCTIONS if not function_exists(pg, sig)]
    return out


if __name__ == "__main__":
    sys.exit(main())
