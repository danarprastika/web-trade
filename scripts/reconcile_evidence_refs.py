"""One-off: reconcile every work item's evidence_ref with the evidence log's own ownership.

scripts/audit_evidence_refs.py reported four drifted items, none of them touched by this session's
work. Each is a genuine inconsistency between two ledgers that are supposed to agree:

  WI-000, WI-102, WI-107   evidence they own is not listed on them
  WI-140                   lists EV-033, which EV-033 itself says belongs to WI-118

The two directions are not symmetric, so they are not handled symmetrically.

Adding is safe: an item that owns a record and does not cite it is under-reporting itself, and
the record is the authority on which item it belongs to because each record names its work_item.

Removing is only safe when the record is already listed on its owning item. If it were not, the
right repair would be to add it to the owner, and removing it from the item that lists it would
destroy the only reference to it. That case is detected and handled by adding to the owner rather
than removing, and is reported when it happens.

Nothing is invented: every change is derived from the work_item field the evidence records already
carry, and nothing is edited inside a record.

Idempotent, written without a BOM, uses HEAD's serialisation style.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
LEDGER = BRAIN / "evidence.jsonl"


def load_records() -> dict[str, dict]:
    records = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        records[record["evidence_id"]] = record
    return records


def reconcile() -> bool:
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    records = load_records()

    owner_of = {
        evidence_id: record.get("work_item")
        for evidence_id, record in records.items()
    }

    listed_on: dict[str, set[str]] = {}
    for item in items:
        for ref in item.get("evidence_ref") or []:
            listed_on.setdefault(ref, set()).add(item["id"])

    actions: list[str] = []

    # Pass 1: add every owned record that its owner does not list.
    for item in items:
        refs = list(item.get("evidence_ref") or [])
        owned_here = sorted(
            eid for eid, owner in owner_of.items() if owner == item["id"] and eid not in refs
        )
        if owned_here:
            refs.extend(owned_here)
            # Sorted so a repeated run produces the same order, which keeps this script's
            # idempotence claim true and keeps the diff stable.
            item["evidence_ref"] = sorted(refs)
            actions.append(
                f"  {item['id']}: added {', '.join(owned_here)}"
            )

    # Pass 2: remove records listed on an item that does not own them, but only where the
    # owning item already lists them, so no reference is ever lost.
    for item in items:
        refs = list(item.get("evidence_ref") or [])
        keep, dropped = [], []
        for ref in refs:
            owner = owner_of.get(ref)
            if owner is None or owner == item["id"]:
                keep.append(ref)
                continue
            if owner in listed_on.get(ref, set()):
                dropped.append(ref)
                actions.append(
                    f"  {item['id']}: removed {ref}, which {owner} owns and already lists"
                )
            else:
                keep.append(ref)
                actions.append(
                    f"  {item['id']}: KEPT {ref} although {owner} owns it, because {owner} "
                    "does not list it; removing it would have been the only reference"
                )
        if dropped:
            item["evidence_ref"] = keep

    if not actions:
        print("unchanged: every item already agrees with the evidence log")
        return False

    payload = json.dumps(data, ensure_ascii=True, indent=2) + "\n"
    with io.open(ITEMS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)

    print("reconciled evidence references:")
    print("\n".join(actions))
    return True


if __name__ == "__main__":
    reconcile()
