#!/usr/bin/env python3
"""Apply and verify the ledger migration against a real PostgreSQL 17 instance.

The Go tests prove the ledger's domain rules. They cannot prove that the *database*
enforces them, and that is the whole point of db/migrations/0001_ledger.sql: a ledger whose
append-only property is only a Go convention is one SQL statement away from being a table.

This script therefore does something the Go tests deliberately do not: it starts a real
PostgreSQL, applies the migration, and asserts that each guard actually refused the write it
was supposed to refuse. Every bug found while building WI-116 was found here and would not
have been found by reading the SQL: the constraint triggers referenced functions declared
below them, `||` was used outside a RAISE string literal, and the correction trigger matched
each new row against itself so that no compensating entry could ever be written.

Assertions are read back from the database rather than parsed from psql's output, because
psql reports failures on stderr and results on stdout and the two interleave unpredictably. A
guard that did not fire leaves a row behind, and the assertion catches it.

Exit codes:
    0  migration applied and every assertion passed
    1  at least one assertion failed
    2  the script could not run (docker unavailable, image missing, missing files)

Usage:
    python scripts/verify_ledger_db.py [--image postgres:17-alpine] [--keep]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The container lifecycle and the migration split live in pgverify so that this script and
# scripts/rehearse_migrations.py cannot drift into being two different harnesses. They are
# re-exported here because this module is the one other scripts and tests already import.
from pgverify import (  # noqa: F401  (re-exported deliberately)
    DEFAULT_IMAGE,
    DOWN_MARKER,
    Postgres,
    PsqlError,
    docker_available,
    migration_bodies,
    run,
)

MIGRATION = Path("db/migrations/0001_ledger.sql")
VERIFY = Path("db/tests/0001_ledger_verify.sql")

# The marker that separates a migration's up body from its down body.
#
# This constant and the split below have to agree with services/control-plane/migrate, which
# parses the same files. When the harness applied whole files, the 0001 down body dropped the
# ledger schema immediately after the up body created it, and the suite failed with "the
# verification script produced no summary" -- an error that points at the assertions rather
# than at the migration. Two parsers disagreeing about where a file ends is the kind of thing
# that must not be left to convention.
DOWN_MARKER = "-- migrate:down"


def migration_bodies(text: str) -> tuple[str, str]:
    """Split a migration file into (up, down).

    A file with no marker has an empty down body, which is a migration that cannot be
    reverted rather than one whose down half happens to be blank.
    """
    up, marker, down = text.partition(DOWN_MARKER)
    return up, (down if marker else "")
VERIFY = Path("db/tests/0001_ledger_verify.sql")

# The summary line the verification script prints when every assertion passed.
ALL_PASSED = re.compile(r"ALL\s+(\d+)\s+ASSERTIONS\s+PASSED")
ANY_FAILED = re.compile(r"(\d+)\s+OF\s+(\d+)\s+ASSERTIONS\s+FAILED")
ASSERTION_LINE = re.compile(r"^(PASS|FAIL)\s{2}(.+?)\s{2}\(")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE,
                        help="PostgreSQL image to verify against (must be 17)")
    parser.add_argument("--keep", action="store_true",
                        help="leave the container running after the check")
    parser.add_argument("--migration", default=str(MIGRATION),
                        help="migration to apply, relative to the repository root")
    parser.add_argument("--verify", default=str(VERIFY),
                        help="verification script to run, relative to the repository root")
    parser.add_argument("--direction", default="up", choices=("up", "down"),
                        help="which half of the migration to apply; 'up' (the default) "
                             "applies everything before the -- migrate:down marker")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    migration = root / args.migration
    verify = root / args.verify
    for path in (migration, verify):
        if not path.is_file():
            print(f"missing {path.relative_to(root)}", file=sys.stderr)
            return 2

    if "17" not in args.image:
        print(f"refusing to verify against {args.image}: the migration targets PostgreSQL 17",
              file=sys.stderr)
        return 2

    ok, version = docker_available()
    if not ok:
        print(f"docker is unavailable: {version}", file=sys.stderr)
        print("The Go tests still cover the domain rules; only the database enforcement is "
              "unverified.", file=sys.stderr)
        return 2

    try:
        pg = Postgres(image=args.image, label="webtrade-ledger-verify").__enter__()
    except PsqlError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        print(f"verified against {pg.version} (docker {version})")

        up_body, down_body = migration_bodies(migration.read_text(encoding="utf-8"))
        body = up_body if args.direction == "up" else down_body
        if args.direction == "down" and not down_body.strip():
            print(f"{args.migration} declares no {DOWN_MARKER} body, so there is nothing "
                  f"to revert", file=sys.stderr)
            return 2
        print(f"applying {args.migration} ({args.direction})")

        try:
            pg.apply(body, action=f"the migration did not apply ({args.direction})")
        except PsqlError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        result = pg.psql(file=verify)
        assertions: list[tuple[str, str]] = []
        for line in result.stdout.splitlines():
            match = ASSERTION_LINE.match(line)
            if match:
                assertions.append((match.group(1), match.group(2).strip()))

        print()
        for status, name_ in assertions:
            print(f"  {status}  {name_}")

        summary = ALL_PASSED.search(result.stdout)
        failed = ANY_FAILED.search(result.stdout)

        print()
        # A summary claiming zero assertions is not a pass. It is what a transaction that was
        # aborted and rolled back looks like: the assertion table goes back to empty, and the
        # COUNT query still dutifully reports that everything it can see passed. The two failure
        # modes are indistinguishable unless the count itself is checked, and the harness is the
        # only place that can see it.
        if summary and int(summary.group(1)) == 0:
            print("the verification script reported ALL 0 ASSERTIONS PASSED, which means it "
                  "asserted nothing", file=sys.stderr)
            print("this is what a rolled-back assertion table looks like: a statement in the "
                  "script errored under ON_ERROR_STOP off, every later statement was refused "
                  "with 'current transaction is aborted', and COMMIT became a rollback.",
                  file=sys.stderr)
            if result.stderr.strip():
                print()
                print("psql reported:", file=sys.stderr)
                print(result.stderr.strip()[:4000], file=sys.stderr)
            return 1
        if summary:
            print(f"ALL {summary.group(1)} DATABASE ASSERTIONS PASSED")
            return 0
        if failed:
            print(f"{failed.group(1)} OF {failed.group(2)} DATABASE ASSERTIONS FAILED")
            if result.stderr.strip():
                print()
                print("psql reported:", file=sys.stderr)
                print(result.stderr.strip()[:4000], file=sys.stderr)
            return 1

        print("the verification script produced no summary; the check is not trustworthy",
              file=sys.stderr)
        print(result.stdout[-2000:], file=sys.stderr)
        return 1
    finally:
        if not args.keep:
            pg.__exit__()


if __name__ == "__main__":
    sys.exit(main())
