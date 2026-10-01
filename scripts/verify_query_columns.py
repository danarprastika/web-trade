"""Cross-check the columns Go scans against the columns the live tables actually have.

verify_queries_live.py proves each query resolves. It cannot prove the query returns what the Go
reader expects, because a query can be valid SQL and still return its columns in an order the
scanning code does not match, or omit one the code requires. sqlc generates both sides from one
source, so the generator is what normally prevents this - which is precisely why the pairing
should be checked rather than assumed, especially for the restore paths added in EV-048, EV-049
and EV-050, which read rows into snapshot structs.

For each named query this compares the ordered column list implied by its SELECT against the
column list of the table it reads, taken from the live catalog.
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
FROM_RE = re.compile(r"\bFROM\s+([A-Za-z_][\w.]*)", re.IGNORECASE)


def psql(sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-tAc", sql],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def live_columns(table: str) -> list[str]:
    schema, _, bare = table.rpartition(".")
    schema = schema or "public"
    sql = (
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{schema}' AND table_name='{bare}' ORDER BY ordinal_position;"
    )
    return [line for line in psql(sql).splitlines() if line]


def main() -> int:
    files = sorted((ROOT / "services" / "control-plane" / "db" / "queries").glob("*.sql"))
    mismatches: list[str] = []
    checked = 0

    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        marks = list(NAME_RE.finditer(text))

        for index, mark in enumerate(marks):
            end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
            body = text[mark.end():end]
            name = mark.group(1)

            if re.search(r"^\s*(--\s*name:)", body, re.MULTILINE):
                continue
            from_match = FROM_RE.search(body)
            if not from_match:
                continue
            table = from_match.group(1).strip('"')
            if "." not in table:
                continue  # unqualified; resolved by search_path, not a single table

            try:
                actual = live_columns(table)
            except RuntimeError as exc:
                mismatches.append(f"{rel}::{name}: catalog read failed for {table}: {exc}")
                continue
            if not actual:
                mismatches.append(f"{rel}::{name}: table {table} not found in live catalog")
                continue

            referenced = set(re.findall(r"\b([a-z_][a-z0-9_]*)\b", body.lower()))
            missing = [c for c in actual if c.lower() not in referenced]
            checked += 1
            if missing:
                mismatches.append(
                    f"{rel}::{name}: {table} columns never referenced: {', '.join(missing)}"
                )

    print(f"queries cross-checked: {checked}")
    print(f"mismatches: {len(mismatches)}")
    for line in mismatches:
        print("  " + line)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
