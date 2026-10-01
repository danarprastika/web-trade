"""One-off: reconcile WI-141's evidence_ref with the evidence it actually owns.

Scoped to WI-141 on purpose. An audit showed the same drift on WI-000, WI-102 and WI-107,
but those belong to other owners and are left alone; WI-140 additionally references EV-033,
which it does not own, and that looks deliberate because EV-033 supersedes EV-031.

WI-141 listed eight evidence records while owning thirteen, so the five most recent - the
entire rehydration line of work - were invisible to anyone reading the work item rather than
the log. Idempotent, append-only with respect to the log itself, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
WORK_ITEM = "WI-141"


def owned_evidence_ids() -> list:
    rows = [
        json.loads(l)
        for l in (BRAIN / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    return sorted({r["evidence_id"] for r in rows if r.get("work_item") == WORK_ITEM})


def reconcile() -> bool:
    store = BRAIN / "work-items.json"
    data = json.loads(store.read_text(encoding="utf-8"))

    item = next(i for i in data["items"] if i["id"] == WORK_ITEM)
    want = owned_evidence_ids()
    if item.get("evidence_ref") == want:
        print("unchanged: " + WORK_ITEM + " evidence_ref already current")
        return False

    item["evidence_ref"] = want

    note = item.get("completion_note", "")
    addendum = (
        " Rehydration evidence is now complete: EV-047 through EV-051 cover audit chain "
        "restoration, audit SQL rehydration, journal rehydration, identity rehydration, and "
        "EV-051's correction of an overstated verification claim in EV-050. The item remains "
        "IN_PROGRESS because human G4 review is outstanding, not because G5 evidence is "
        "incomplete."
    )
    if addendum.strip() not in note:
        item["completion_note"] = note.rstrip() + addendum

    with io.open(store, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("updated " + WORK_ITEM + " evidence_ref -> " + ", ".join(want))
    return True


if __name__ == "__main__":
    reconcile()