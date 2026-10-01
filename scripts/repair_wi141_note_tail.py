"""One-off: repair WI-141's completion_note tail.

record_wi141_g5_pass.py replaced the phrase 'The item remains IN_PROGRESS because human G4 review
is outstanding' with a full EV-062 paragraph, but the original sentence continued ', not because
G5 evidence is incomplete.' after the phrase it replaced. That continuation was left dangling, so
the note currently ends with the clause twice.

The fix is to drop the orphaned tail. It is written as its own script rather than folded into
record_wi141_g5_pass.py because that script is idempotent and this repair is a one-time
correction of its output; folding them together would mean the idempotent script could mutate a
field it has already written.

Idempotent, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"

WORK_ITEM = "WI-141"

# The orphaned continuation, and the doubled result it produced.
ORPHAN = ", not because G5 evidence is incomplete."
DANGLING = ORPHAN + ORPHAN
REPAIRED = ORPHAN


def repair() -> bool:
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    item = next(i for i in items if i["id"] == WORK_ITEM)

    note = item.get("completion_note") or ""
    if DANGLING not in note:
        if ORPHAN in note:
            print("note ends with a single, correctly-placed clause; nothing to repair")
        else:
            print("no orphaned clause found; nothing to repair")
        return False

    # Only the doubled form at the very end is repaired. A single occurrence elsewhere in the
    # note is legitimate prose and must not be touched.
    if not note.endswith(DANGLING):
        raise SystemExit(
            "refusing to repair: the doubled clause is present but not at the end of the "
            "note, so this script cannot tell which occurrence is the orphan"
        )

    item["completion_note"] = note[: -len(DANGLING)] + REPAIRED

    # ensure_ascii=True matches HEAD's storage; see restore_work_items_style.py for why a
    # re-encoding writer is a problem even when every value is unchanged.
    payload = json.dumps(data, ensure_ascii=True, indent=2) + "\n"
    with io.open(ITEMS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    print("repaired " + WORK_ITEM + " completion_note tail")
    return True


if __name__ == "__main__":
    repair()
