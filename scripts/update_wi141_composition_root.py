"""De-duplicate WI-141's completion_note, then record the composition-root outcome.

The note had grown a duplicated tail: a paragraph repeating the EV-044 rehydration summary
followed by the original closing sentence, which is also the sentence that carried the G4 error
corrected by EV-057. Leaving it in place means the file states the corrected gate in one place and
the incorrect one in another, which is worse than either alone.

Idempotent, and it refuses rather than guesses: every replacement must match exactly once and
must land where the script says it will.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / ".kilo" / "ecc" / "project-brain" / "work-items.json"

# The repeated tail. It is the EV-044 rehydration summary plus the original closing sentence, and
# it appears exactly once - as the end of the note.
DUPLICATE_TAIL = (
    " Rehydration evidence is now complete: EV-047 through EV-051 cover audit chain restoration, "
    "audit SQL rehydration, journal rehydration, identity rehydration, and EV-051's correction "
    "of an overstated verification claim in EV-050. The item remains IN_PROGRESS because human "
    "G4 review is outstanding, not because G5 evidence is incomplete."
)

MARKER = "services/control-plane/bootstrap"

ADDITION = (
    " The composition root is no longer missing: services/control-plane/bootstrap assembles the "
    "durable stack and is the first code in the repository to construct an audit Exporter or a "
    "rehydrated journal, which closes WI-117's AC4 wiring gap and lets the G5 restart criterion "
    "be met at the composition level. The G5 report's criterion was split accordingly, with "
    "rebuild-from-persisted-state now passing and startup-in-a-running-process recorded FAIL, "
    "because no entrypoint calls the composition root and no Go process has connected to "
    "PostgreSQL. The gate verdict is therefore still FAIL, for a narrower and better-stated "
    "reason than before."
)

# What the note must end with once the duplicate is gone and the addition is applied.
EXPECTED_END = (
    "is corrected by EV-057, since the evidence log is append-only." + ADDITION
)


def main() -> None:
    raw = ITEMS.read_text(encoding="utf-8")
    note = next(
        i for i in json.loads(raw)["items"] if i["id"] == "WI-141"
    )["completion_note"]

    if MARKER in note and note.endswith(EXPECTED_END.strip()):
        print("unchanged: note is already de-duplicated and current")
        return

    if note.count(DUPLICATE_TAIL) != 1:
        raise SystemExit(
            f"expected the duplicated tail exactly once, found {note.count(DUPLICATE_TAIL)}; "
            "refusing to edit"
        )
    if not note.endswith(DUPLICATE_TAIL):
        raise SystemExit("the duplicated text is not at the end of the note; refusing to edit")

    trimmed = note[: -len(DUPLICATE_TAIL)]

    # After trimming, the note must end where EV-057 left it, or the two edits do not compose and
    # appending anyway would produce a note nobody can read.
    if not trimmed.endswith("is corrected by EV-057, since the evidence log is append-only."):
        raise SystemExit(
            f"after removing the duplicate the note ends with: ...{trimmed[-90:]!r}; refusing"
        )

    updated_note = trimmed + ADDITION
    updated = raw.replace(note, updated_note, 1)

    recheck = json.loads(updated)
    recheck_note = next(
        i for i in recheck["items"] if i["id"] == "WI-141"
    )["completion_note"]

    problems = []
    if recheck_note != updated_note:
        problems.append("the parsed note does not match what was written")
    if "human G4 review is outstanding" in recheck_note:
        problems.append("the incorrect gate reference is still present")
    if "Correction: this note previously said" not in recheck_note:
        problems.append("the EV-057 correction was lost")
    if MARKER not in recheck_note:
        problems.append("the composition-root outcome is missing")
    if recheck_note.count("Rehydration evidence is now complete") != 1:
        problems.append(
            "the EV-044 rehydration summary still appears "
            f"{recheck_note.count('Rehydration evidence is now complete')} times"
        )
    if problems:
        raise SystemExit("refusing to keep the edit: " + "; ".join(problems))

    with io.open(ITEMS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(updated)
    print(
        f"WI-141 completion_note: removed the duplicated tail, recorded the composition-root "
        f"outcome ({len(note)} -> {len(updated_note)} chars)"
    )


if __name__ == "__main__":
    main()