"""One-off: reference EV-069 from WI-141.

The evidence audit reported WI-141 as owning 31 records while listing 30, missing EV-069. That is
the audit working correctly: EV-069 was appended to the ledger but nothing linked it back to the
work item, so a reader arriving at WI-141 would not have found the record that says the work was
committed, and would have had to know to look at the tail of the log.

Scoped to the single missing reference rather than running a blanket reconcile. A reconcile
rewrites evidence_ref from whatever the ledger says an item owns, which would silently absorb any
future accidental misattribution instead of reporting it; here the script asserts that the edited
list equals the owned set exactly, so a genuine misattribution would fail loudly rather than be
papered over.

The completion note gains one sentence saying the work is committed and that the sqlc gate went
red to green as a result. Status is deliberately left IN_PROGRESS and human_reviewer null: the
commit is not a sign-off, and nothing about this change should make the gap look smaller.

Idempotent, and written to preserve the file's existing serialization exactly: indent=2,
ensure_ascii=False, LF line endings, no BOM, single trailing newline.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
WORK_ITEM = "WI-141"
NEW_EVIDENCE = "EV-069"

ADDENDUM = (
    " The work is committed as 758ce11 and every step of both CI job sequences passes against "
    "the committed tree, including sqlc is up to date, which was the last red step in the "
    "workflow and went green because the regenerated output and its callers are now both "
    "committed rather than untracked."
)


def owned_evidence_ids() -> list:
    rows = [
        json.loads(line)
        for line in (BRAIN / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return sorted({r["evidence_id"] for r in rows if r.get("work_item") == WORK_ITEM})


def reconcile() -> bool:
    store = BRAIN / "work-items.json"
    data = json.loads(store.read_text(encoding="utf-8"))

    item = next(i for i in data["items"] if i["id"] == WORK_ITEM)
    current = list(item.get("evidence_ref", []))

    if NEW_EVIDENCE in current:
        print("unchanged: " + NEW_EVIDENCE + " already referenced from " + WORK_ITEM)
        return False

    current.append(NEW_EVIDENCE)
    current.sort()
    item["evidence_ref"] = current

    # Assert rather than trust: the edited list must equal the owned set exactly. If a record
    # were ever misattributed to this item, this raises instead of absorbing the mistake.
    owned = owned_evidence_ids()
    if current != owned:
        raise SystemExit(
            "refusing to write: " + WORK_ITEM + " would list "
            + repr(current)
            + " but owns "
            + repr(owned)
        )

    note = item.get("completion_note", "")
    if ADDENDUM.strip() not in note:
        item["completion_note"] = note.rstrip() + ADDENDUM

    with io.open(store, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print("updated " + WORK_ITEM + " evidence_ref: added " + NEW_EVIDENCE)
    print("  now lists " + str(len(current)) + " records, which equals the owned set")
    return True


if __name__ == "__main__":
    reconcile()