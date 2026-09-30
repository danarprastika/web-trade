"""One-off: normalise field names on two existing evidence records.

EV-007 and EV-013 both explain themselves, but under field names that differ from the
ones scripts/verify_project_brain.py requires. Rather than loosen the check to accept any
of several names, the records are normalised so the vocabulary stays consistent and the
check can remain strict.

This script is idempotent and reports what it changed. It is kept in the repository so
the edit is auditable and reproducible rather than an opaque mutation of state.
"""

from __future__ import annotations

import json
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain" / "evidence.jsonl"

# Field name -> the explanatory text it should carry, for records that explain
# themselves under a different key today.
ADDITIONS = {
    "EV-007": {
        "defect_found_and_fixed": (
            "Three real defects, all fixed and re-verified: (1) four identifiers were 25 "
            "characters where the schema requires 26; (2) the event-envelope fixture omitted "
            "the required `payload` property; (3) `idempotency_key` was absent from the "
            "command envelope's `required` list. The third was a genuine safety gap, not a "
            "cosmetic one: without it, a replayed mutating command would not have been "
            "rejected by schema validation, which is the database-level duplicate-exposure "
            "control described in docs/03."
        ),
    },
    "EV-013": {
        "exception": (
            "eslint is pinned to 9.39.5 rather than the latest 10.11.0. This deviates from "
            "the docs/00 rule prohibiting unsupported versions and from the docs/02 rule "
            "requiring the latest security-supported release. It is recorded here as an "
            "open, unaccepted exception (RISK-11) rather than absorbed silently, and it is "
            "not claimed as compliant."
        ),
    },
}


def main() -> int:
    lines = [
        json.loads(line)
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    changed: list[str] = []
    for record in lines:
        for key, value in ADDITIONS.get(record["evidence_id"], {}).items():
            if key in record:
                continue
            record[key] = value
            changed.append(f"{record['evidence_id']}.{key}")

    if changed:
        EVIDENCE.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n",
            encoding="utf-8",
        )
        print("added fields: " + ", ".join(changed))
    else:
        print("no changes needed; records already normalised")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
