"""Apply only the migrate:up half of each migration to a scratch database.

These files carry both directions, so piping a whole file through psql runs the up section and
then the down section, which drops everything the up section just built. That is a property of
the migration format, not a defect in it: services/control-plane/migrate and
scripts/rehearse_migrations.py both split on the marker first.

This reuses the repository's own splitter rather than reimplementing the split, so a change to
the marker convention cannot silently make this harness disagree with the real migrator.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rehearse_migrations import migration_bodies  # noqa: E402

CONTAINER = "aitc-pg17"
DB = "wi141_verify"


def main() -> int:
    import subprocess

    migrations = sorted((ROOT / "db" / "migrations").glob("*.sql"))
    if not migrations:
        print("no migrations found", file=sys.stderr)
        return 1

    # These migrations assume a fresh database: 0001 uses CREATE SCHEMA IF NOT EXISTS, which
    # is idempotent, but then CREATE SEQUENCE, which is not, so re-running against an already
    # migrated database fails on the first sequence. Owning the reset here is what makes this
    # script re-runnable, and it also guarantees the verification starts from the same empty
    # state every time rather than inheriting whatever a previous run left behind.
    drop = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", "postgres",
         "-c", f"DROP DATABASE IF EXISTS {DB};"],
        capture_output=True, text=True,
    )
    create = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", "postgres",
         "-c", f"CREATE DATABASE {DB};"],
        capture_output=True, text=True,
    )
    if drop.returncode != 0 or create.returncode != 0:
        print(f"  could not reset {DB}")
        print((drop.stderr or drop.stdout).strip()[:500])
        print((create.stderr or create.stdout).strip()[:500])
        return 1
    print(f"reset {DB} to an empty database")

    for path in migrations:
        up, _down = migration_bodies(path.read_text(encoding="utf-8"))
        if not up.strip():
            print(f"  {path.name}: EMPTY UP BODY", file=sys.stderr)
            return 1

        target = f"/tmp/up_{path.name}"
        # Written through a host temp file then copied, because piping through PowerShell
        # re-encodes the bytes and mangles the SQL.
        scratch = ROOT / ".mig_up.sql"
        scratch.write_text(up, encoding="utf-8", newline="\n")
        try:
            subprocess.run(
                ["docker", "cp", str(scratch), f"{CONTAINER}:{target}"],
                check=True,
                capture_output=True,
            )
            result = subprocess.run(
                [
                    "docker", "exec", CONTAINER,
                    "psql", "-U", "postgres", "-d", DB,
                    "-v", "ON_ERROR_STOP=1", "-q",
                    "-f", target,
                ],
                capture_output=True,
                text=True,
            )
        finally:
            scratch.unlink(missing_ok=True)

        if result.returncode != 0:
            print(f"  {path.name}: FAIL exit={result.returncode}")
            print((result.stderr or result.stdout).strip()[:1500])
            return 1
        print(f"  {path.name}: applied ({len(up.splitlines())} lines)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
