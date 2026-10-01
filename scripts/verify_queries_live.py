"""Execute every sqlc query body against a live schema and report which ones fail.

EV-060 disclosed that the queries in services/control-plane/db/queries had never been run
against a real database, only the Go code that calls them. This closes that gap for the
read paths the rehydration work depends on: a query that references a column the migration
never creates would pass every unit test and fail on first production use.

Queries are extracted using the same `-- name: X :one` convention sqlc itself uses, and each
is PREPAREd rather than executed. PREPARE forces PostgreSQL to parse, resolve and plan the
statement - so a bad column, a bad type or a bad ON CONFLICT target is caught - without
requiring rows to exist, and without writing anything.

Read-only with respect to the database: PREPARE/DEALLOCATE only.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "aitc-pg17"
DB = "wi141_verify"

NAME_RE = re.compile(r"^--\s*name:\s*(\S+)\s*:(\w+)\s*$", re.MULTILINE)
# sqlc's inline arg comments (sqlc.arg(x), @x) are not PostgreSQL syntax.
ARG_RE = re.compile(r"sqlc\.arg\(([^)]*)\)|sqlc\.narg\(([^)]*)\)")


def psql(sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-tAc", sql],
        capture_output=True,
        text=True,
    )


def split_queries(text: str) -> list[tuple[str, str, str]]:
    """Return (name, return_kind, sql) for every named query, in file order."""
    found: list[tuple[str, str, str]] = []
    marks = list(NAME_RE.finditer(text))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[mark.end():end].strip()
        # Drop a trailing comment block belonging to the next section, not to this query.
        body = re.sub(r"^--\s*name:.*$", "", body, flags=re.MULTILINE).strip()
        if body.endswith(";"):
            body = body[:-1]
        found.append((mark.group(1), mark.group(2), body))
    return found


def prepare_check() -> str:
    """Prove the harness can fail: a bogus column must be rejected by PREPARE."""
    return psql("PREPARE _harness_control AS SELECT no_such_column FROM model_registry;")


def main() -> int:
    files = sorted((ROOT / "services" / "control-plane" / "db" / "queries").glob("*.sql"))
    if not files:
        print("no query files found", file=sys.stderr)
        return 1

    # Teeth first. Without this a harness that accepts everything would look like a pass.
    control = prepare_check()
    if control.returncode == 0:
        print("HARNESS INVALID: control query with a bogus column was accepted")
        return 2
    print("harness control rejected a bogus column as expected")

    total = 0
    failures: list[tuple[str, str, str]] = []

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        queries = split_queries(path.read_text(encoding="utf-8"))
        print(f"\n{rel}  ({len(queries)} queries)")
        for name, kind, body in queries:
            total += 1
            # Named placeholders are not valid SQL; bind them positionally as NULL so the
            # statement is parseable without inventing data.
            prepared = ARG_RE.sub("NULL", body)
            prepared = re.sub(r"@[a-z_][a-z0-9_]*", "NULL", prepared)
            if not prepared.strip():
                failures.append((rel, name, "empty query body"))
                print(f"  [EMPTY] {name}")
                continue
            result = psql(f"PREPARE _q AS {prepared};")
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip().splitlines()
                message = detail[0] if detail else "failed"
                failures.append((rel, name, message))
                print(f"  [FAIL ] {name} (:{kind}) {message}")
            else:
                psql("DEALLOCATE _q;")
                print(f"  [ok   ] {name} (:{kind})")

    print(f"\ntotal queries: {total}")
    print(f"failed: {len(failures)}")
    for rel, name, message in failures:
        print(f"  {rel} :: {name} :: {message}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
