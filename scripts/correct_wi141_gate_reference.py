"""Correct a factual error in WI-141's completion note.

The note said "The item remains IN_PROGRESS because human G4 review is outstanding". WI-141 is a
G5 item; G4 is WI-140, a separate prior item that is already BLOCKED. The error also appears in
EV-053 through EV-056, which cannot be edited because the evidence log is append-only, so those
records are corrected by EV-057 rather than by rewriting them.

Idempotent, surgical: it replaces one sentence and touches nothing else in the file.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / ".kilo" / "ecc" / "project-brain" / "work-items.json"

OLD = (
    "The item remains IN_PROGRESS because human G4 review is outstanding, not because G5 "
    "evidence is incomplete."
)

NEW = (
    "The G5 gate report is at evidence/gates/G5-gate-report.json and .md, with a content digest "
    "for every artifact the gate rests on. Its verdict is FAIL, and the reason is not work left "
    "undone here: the five subsystems the G5 criterion names all pass, but audit-trail "
    "completeness across a process restart does not, because that is WI-117's AC4 and is not "
    "implemented. docs/11 requires that a gate be PASS only when every listed criterion is "
    "satisfied and that partial completion be FAIL rather than a percentage, so the report "
    "records that criterion as FAIL rather than omitting it. The item remains IN_PROGRESS "
    "pending a named human reviewer, who is not the author of this work; the report's "
    "human_reviewer field is null on purpose. Correction: this note previously said 'human G4 "
    "review'. WI-141 is a G5 item and G4 belongs to WI-140, which is already BLOCKED. The same "
    "error was carried into EV-053, EV-054, EV-055 and EV-056 and is corrected by EV-057, since "
    "the evidence log is append-only."
)


def main() -> None:
    raw = ITEMS.read_text(encoding="utf-8")

    # Refuse to touch the file unless the target sentence appears exactly once, so a malformed
    # or already-edited file is reported rather than silently rewritten.
    count = raw.count(OLD)
    if count == 0:
        if NEW.split(",")[0] in raw:
            print("unchanged: correction already applied")
            return
        raise SystemExit("target sentence not found; refusing to edit")
    if count != 1:
        raise SystemExit(f"target sentence appears {count} times; refusing to edit")

    updated = raw.replace(OLD, NEW)

    # Confirm the file is still valid JSON and the field still parses to the intended text.
    parsed = json.loads(updated)
    item = next(i for i in parsed["items"] if i["id"] == "WI-141")
    if "G5 gate report is at evidence/gates" not in item["completion_note"]:
        raise SystemExit("edit applied but the parsed field does not contain it; refusing")
    if "human G4 review is outstanding" in item["completion_note"]:
        raise SystemExit("the incorrect gate reference survived; refusing")

    with io.open(ITEMS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(updated)
    print("corrected WI-141 completion_note: G4 -> G5, with the gate-report verdict")


if __name__ == "__main__":
    main()