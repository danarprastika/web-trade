"""Compare the generated ModelRegistry struct's field order to the live column order.

A SELECT * is resolved by column position, so the generated struct and the migration's column
order are a positional contract. sqlc generates the struct from the same migration that creates
the table, which is why they agree; this checks the agreement rather than assuming it, because a
later migration that reorders columns would break every SELECT * reader at runtime and no unit
test that uses a fake would notice.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "aitc-pg17"
DB = "wi141_verify"
TABLE = "model_registry"


def live_columns() -> list[str]:
    sql = (
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='public' AND table_name='{TABLE}' ORDER BY ordinal_position;"
    )
    out = subprocess.run(
        ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DB, "-tAc", sql],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def struct_fields() -> list[str]:
    src = (ROOT / "services" / "control-plane" / "db" / "dbgen" / "models.go").read_text(
        encoding="utf-8"
    )
    match = re.search(r"type ModelRegistry struct \{(.*?)\n\}", src, re.S)
    if not match:
        raise SystemExit("ModelRegistry struct not found in dbgen/models.go")
    # The json tag is the column name sqlc was given; the Go field name is derived from it.
    return re.findall(r'json:"([a-z0-9_]+)"', match.group(1))


def main() -> int:
    live = live_columns()
    fields = struct_fields()

    print(f"live columns: {len(live)}")
    print(f"struct fields: {len(fields)}")

    if len(live) != len(fields):
        print("MISMATCH: different arity, so the positional contract cannot hold")
        return 1

    differences = [
        (index, field, column)
        for index, (field, column) in enumerate(zip(fields, live), start=1)
        if field != column
    ]

    if differences:
        print(f"MISMATCH at {len(differences)} position(s):")
        for index, field, column in differences:
            print(f"  position {index}: struct={field} live={column}")
        return 1

    print("PASS: struct field order is identical to the live column order")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
