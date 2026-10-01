"""Reference an evidence record from the work item that owns it.

The evidence audit reports a work item as owning N records while listing N-1 when a record is
appended to the ledger without being linked back. The record is then invisible to anyone arriving
at the work item, who has to know to look at the tail of the log.

    python scripts/reference_evidence_from_wi141.py EV-070

This replaces two near-identical one-off scripts, each hardcoded to a single record id. Three
records have now needed the same edit, and a fourth one-off would be a fourth place for the same
rule to be written slightly differently. The rule is the same either way, so it should have one
implementation.

Scoped to WI-141 on purpose. A blanket reconcile across every work item would silently absorb a
genuine misattribution instead of reporting it: after the edit, the script asserts the listed set
equals the set the ledger says this item owns, so a record attributed to the wrong item fails
loudly rather than being papered over.

Idempotent, and written to preserve work-items.json's existing serialization exactly: indent=2,
ensure_ascii=False, LF line endings, no BOM, single trailing newline.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
WORK_ITEM = "WI-141"


def owned_evidence_ids() -> list:
    rows = [
        json.loads(line)
        for line in (BRAIN / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return sorted({r["evidence_id"] for r in rows if r.get("work_item") == WORK_ITEM})


def reference(record: str) -> bool:
    store = BRAIN / "work-items.json"
    data = json.loads(store.read_text(encoding="utf-8"))
    item = next(i for i in data["items"] if i["id"] == WORK_ITEM)

    current = list(item.get("evidence_ref", []))
    if record in current:
        print("unchanged: " + record + " is already referenced from " + WORK_ITEM)
        return False

    ledger = [
        json.loads(line)
        for line in (BRAIN / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    known = {r["evidence_id"]: r for r in ledger}
    if record not in known:
        raise SystemExit("refusing to reference " + record + ": no such record in the ledger")
    if known[record].get("work_item") != WORK_ITEM:
        raise SystemExit(
            "refusing to reference " + record + ": it is owned by "
            + repr(known[record].get("work_item"))
            + ", not by "
            + WORK_ITEM
        )

    current.append(record)
    current.sort()
    item["evidence_ref"] = current

    owned = owned_evidence_ids()
    if current != owned:
        raise SystemExit(
            "refusing to write: " + WORK_ITEM + " would list " + repr(current) + " but owns " + repr(owned)
        )

    with io.open(store, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print("updated " + WORK_ITEM + " evidence_ref: added " + record)
    print("  now lists " + str(len(current)) + " records, which equals the owned set")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: reference_evidence_from_wi141.py EV-nnn")
    sys.exit(0 if reference(sys.argv[1]) else 0)
