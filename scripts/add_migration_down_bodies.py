"""Add down bodies to the three existing migrations.

Written as a script rather than three hand edits so the transaction handling is identical in
all three files, and so the change is reviewable as a whole rather than as three diffs that
happen to look similar.

The bodies are the exact inverse of their up bodies, in the reverse of the order the objects
were created. Each file is left self-contained: it carries its own BEGIN/COMMIT, so applying
it with the runner, with psql, or by hand all give the same atomicity. A migration that is
atomic only when a particular runner happens to wrap it is atomic by accident.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Imported rather than redefined so the convention has exactly one owner. This script edits
# the same files pgverify parses, and a second copy of the marker is a second thing to forget
# to update.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pgverify import DOWN_MARKER, migration_bodies  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"

# 0001 created a schema; 0002 and 0003 created unqualified tables in the default search_path
# with name prefixes rather than a namespace. That inconsistency is noted in the WI-106
# findings and left alone here, because moving three tables into new schemas is a breaking
# change that belongs in its own migration, not inside the addition of down bodies.
DOWNS = {
    "0001_ledger.sql": """
-- The reverse of the migration above.
--
-- Dropping the schema drops its tables, their indexes, their triggers, and the functions
-- those triggers used. Naming them again first is only a way to fail: a table's triggers go
-- with the table, and PostgreSQL will refuse to drop a function that is still referenced.
--
-- The schema is dropped rather than emptied. A down migration that drops the tables and
-- leaves the namespace behind hands the next up migration a schema it will satisfy with IF
-- NOT EXISTS and then silently adopt, which is the same disagreement between the database
-- and the repository that the drift check exists to catch.
BEGIN;

DROP SCHEMA IF EXISTS ledger CASCADE;

COMMIT;
""",
    "0002_audit.sql": """
-- The reverse of the migration above.
--
-- These tables are append-only by trigger, so a normal DELETE is refused by the very guards
-- this migration installs. The drops work anyway: DROP TABLE does not fire the row triggers
-- it is about to remove. That asymmetry is correct, and it is also why a down migration is
-- not evidence that append-only is negotiable -- the reversal is a schema operation performed
-- deliberately by a migration runner, not a write any application role can perform.
BEGIN;

DROP TABLE IF EXISTS audit_records CASCADE;
DROP TABLE IF EXISTS audit_checkpoints CASCADE;
DROP TABLE IF EXISTS audit_deletion_events CASCADE;

-- Dropped after the tables, because each function is referenced by triggers on them and
-- PostgreSQL refuses to drop a function that still has dependents.
DROP FUNCTION IF EXISTS audit_check_checkpoint_coverage() CASCADE;
DROP FUNCTION IF EXISTS audit_check_chain_link() CASCADE;
DROP FUNCTION IF EXISTS audit_refuse_mutation() CASCADE;

COMMIT;
""",
    "0003_authz.sql": """
-- The reverse of the migration above.
--
-- Same ordering rule as the audit down body: tables first, then the functions their triggers
-- referenced, then nothing left behind in the namespace.
--
-- authz_decisions holds the append-only authorization decision record. Reverting it is a
-- deliberate schema rollback performed by an operator with the runner, and it discards the
-- decision history along with it. That is a real cost and the reason this down body is
-- exercised in rehearsal rather than in production: docs/09 lists migration rehearsal as a
-- release gate precisely so that the cost of a rollback is known before it is chosen.
BEGIN;

DROP TABLE IF EXISTS authz_decisions CASCADE;
DROP TABLE IF EXISTS authz_approvals CASCADE;
DROP TABLE IF EXISTS authz_sessions CASCADE;
DROP TABLE IF EXISTS authz_role_grants CASCADE;
DROP TABLE IF EXISTS authz_permission_state CASCADE;
DROP TABLE IF EXISTS authz_policy_bundles CASCADE;
DROP TABLE IF EXISTS authz_role_action_exclusion CASCADE;
DROP TABLE IF EXISTS authz_session_policy CASCADE;

DROP FUNCTION IF EXISTS authz_bump_revision_on_session_revocation() CASCADE;
DROP FUNCTION IF EXISTS authz_check_session_age() CASCADE;
DROP FUNCTION IF EXISTS authz_check_wildcard_scope() CASCADE;
DROP FUNCTION IF EXISTS authz_bump_revision_on_grant_change() CASCADE;
DROP FUNCTION IF EXISTS authz_check_rule_against_exclusions() CASCADE;
DROP FUNCTION IF EXISTS authz_check_bundle_retirement() CASCADE;
DROP FUNCTION IF EXISTS authz_check_approval_immutability() CASCADE;
DROP FUNCTION IF EXISTS authz_refuse_exclusion_mutation() CASCADE;

COMMIT;
""",
}


def main() -> int:
    # The up body ends at whichever comes first: the marker, or the first line of a down
    # body that was written without one. Cutting on the down body's own opening comment as
    # well makes the script idempotent and self-healing, which matters because this file
    # edits migrations in place: a run that only looked for the marker would treat an
    # un-marked down body as part of the up body and then append a second copy of it.
    DOWN_START = "-- The reverse of the migration above."

    changed = []
    for name, down in DOWNS.items():
        path = MIGRATIONS / name
        text = path.read_text(encoding="utf-8")

        cuts = [i for i in (text.find(DOWN_MARKER), text.find(DOWN_START)) if i != -1]
        if cuts:
            first = min(cuts)
            up = text[:first].rstrip() + "\n"
            note = "trimmed the existing down body"
        else:
            up = text.rstrip() + "\n"
            note = "no existing down body"

        # 0001 was written without transaction boundaries, which means a failure halfway
        # through leaves objects behind with no record of the migration being applied. The
        # other two files already carry BEGIN/COMMIT. Adding it to 0001 makes the file
        # self-contained and matches the set.
        if name == "0001_ledger.sql" and "BEGIN;" not in up:
            lines = up.split("\n")
            # After the header comment block, before the first statement.
            for i, line in enumerate(lines):
                if line.strip() and not line.lstrip().startswith("--"):
                    lines.insert(i, "BEGIN;\n")
                    break
            up = "\n".join(lines)

        if name == "0001_ledger.sql" and "COMMIT;" not in up:
            up = up.rstrip() + "\n\nCOMMIT;\n"

        # The marker is prepended here rather than stored inside each DOWNS entry, so the
        # bodies below read as SQL and the marker stays a property of the format instead of
        # something that has to be repeated correctly in three places. Omitting it is not a
        # cosmetic slip: the file would parse as one long up body, and the down statements
        # would run immediately after the up statements that created what they drop.
        body = up + "\n" + DOWN_MARKER + "\n" + down.lstrip("\n")

        # Verified before writing, not after. A down body that leaks into the up body is the
        # failure this script is able to cause, and it is silent: the file still parses, the
        # marker is still present, and the damage only shows up as a schema that no longer
        # exists once the assertions run against it.
        written_up, written_down = migration_bodies(body)
        for leaked in ("DROP SCHEMA", "DROP TABLE"):
            if leaked in written_up:
                print(f"{name}: REFUSING to write, the up body contains {leaked}", file=sys.stderr)
                return 1
        if not any(l.strip() and not l.strip().startswith("--")
                   for l in written_down.split("\n")):
            print(f"{name}: REFUSING to write, the down body has no statement", file=sys.stderr)
            return 1

        path.write_text(body, encoding="utf-8", newline="\n")
        changed.append(name)
        print(f"{name}: down body written ({note})")
    if not changed:
        print("no migrations changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
