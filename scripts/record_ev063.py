"""One-off: append EV-063.

EV-062 is append-only and cannot be edited, but writing it and then finalising the repository
surfaced five defects, four of them in tooling written during that same entry. Recording them here
rather than leaving them in a chat transcript is the point: the evidence log has to be a truthful
account of what was verified, including about the work that verified it.

The most consequential finding is not one of the four tooling bugs. It is that two of the
repository's own .gitignore patterns had never worked.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-063"
STAMP = "2026-10-01T09:55:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "Finalising the repository after EV-062 found and fixed five defects, one of them a "
    "pre-existing repository bug rather than anything introduced in this work: the two Project "
    "Brain scratch patterns in .gitignore, '.kilo/ecc/project-brain/*.tmp' and "
    "'.kilo/ecc/project-brain/*.append.tmp', had never worked, because every line in that final "
    "section of the file carries two leading spaces and a leading space in .gitignore is part of "
    "the pattern rather than indentation. The patterns matched a file whose name literally begins "
    "with two spaces and nothing else, so Project Brain scratch files were never ignored. Both "
    "are now verified ignored. Four further defects were in the tooling that wrote EV-062's own "
    "records, all of the same family as the untested-check failures EV-060 and EV-061 recorded: "
    "work that was believed to be doing the right thing and had never been shown to."
)

METHOD = (
    "Verify-then-fix, in that order, because two of these had already been written into tracked "
    "state. First, scripts/compare_work_items_to_head.py was written to answer one question - "
    "whether work-items.json differed from HEAD in any field beyond the three intended - by "
    "comparing parsed values per item per field rather than reading the diff, because the diff "
    "was unreadable. It reported 8 differing fields, 3 expected and 5 on WI-117, and it "
    "separately reported that HEAD stored the file ASCII-escaped while the rewritten file stored "
    "literal UTF-8. Second, the WI-117 differences were traced to EV-044 rather than assumed "
    "legitimate: that record's claim was read back and confirms it found WI-117's fourth "
    "acceptance criterion unimplemented and reopened the item, so those five fields are a "
    "correction, not drift. Third, scripts/restore_work_items_style.py reproduced HEAD's own "
    "serialisation by dumping HEAD's parsed values at each candidate setting and comparing bytes, "
    "so the style was discovered rather than assumed, and it refuses to write unless the parsed "
    "content is unchanged. Fourth, the .gitignore defect was confirmed mechanically rather than "
    "by eye: git check-ignore -v reported no match for a file inside _driver_probe, and the "
    "leading-whitespace measurement showed exactly which lines were indented. The fix was then "
    "verified by git check-ignore matching a created scratch file, and by _driver_probe/"
    "disappearing from git status."
)

RESULT = (
    "work-items.json: partial_results restored from a 3916-element list of single characters to "
    "the 4221-character string it had been, with the stale 'Gate verdict FAIL; work item remains "
    "IN_PROGRESS' tail replaced and the EV-062 REMAINING list applied; completion_note's "
    "duplicated trailing clause reduced to one; evidence_ref carrying 24 references including "
    "EV-062; status left IN_PROGRESS. The file now differs from HEAD in exactly 8 fields - "
    "WI-141's three intended ones and WI-117's five, each accounted for by name - and the diff "
    "is 68 lines rather than the whole file. .gitignore: 12 non-blank lines de-indented, "
    "verified by check-ignore matching '.kilo/ecc/project-brain/*.tmp' for a real scratch file "
    "and '_driver_probe/' for a real probe module, with lines 1-69 untouched because they had no "
    "leading whitespace. Two integration test files that failed CI's gofmt gate are formatted, "
    "and gofmt -l is now empty repository-wide. EV-060 remains re-verifiable: "
    "scripts/probe_driver_pinning.py still reports libpq PASS, pgx FAIL on the pseudo-versioned "
    "pgservicefile, and all three controls FAIL. Full re-verification after every change: "
    "gofmt clean; go vet exit 0 with and without the integration tag; default suite -race 9 "
    "packages ok; integration suite -race 16 of 16 ok on a fresh -count=1 run; toolchain gate 14 "
    "of 14; tests/ci 115 passed; project brain PASS; contracts VALID; research 109 passed; "
    "backtest 47 passed; migration rehearsal PASSED; G5 report regenerated with all seven criteria "
    "PASS across 58 artifact digests. evidence.jsonl and events.jsonl verified append-only by "
    "numstat: 21 additions and 0 deletions, 5 additions and 0 deletions. docs/ clean at zero "
    "changes, nothing staged, nothing committed."
)

DEFECT_FOUND_AND_FIXED = (
    "Five. One in the repository: the two Project Brain .gitignore patterns never worked, for the "
    "indentation reason above, and both are now verified working. Four in tooling written during "
    "EV-062, each of which had passed a run without having been checked for passing correctly. "
    "First, record_wi141_g5_pass.py iterated partial_results, which was a single string, and "
    "assigned the resulting list of characters back to the field - turning a 3916-character "
    "prose field into a 3916-element array in a tracked governance file, and never applying the "
    "replacement text it was written to apply. Repaired by joining the list back and, this time, "
    "comparing before assigning so the script is idempotent rather than rewriting on every run. "
    "Second, the same script's completion_note replacement consumed a phrase that sat mid-sentence "
    "and left the rest of the sentence dangling, so the note ended with its final clause twice; "
    "repaired by a separate script that refuses to act unless the doubled clause is at the very "
    "end, because a single occurrence elsewhere would be legitimate prose. Third, the same script "
    "wrote the file with json.dumps(ensure_ascii=False) where HEAD used ASCII escapes, re-encoding "
    "every non-ASCII character in every work item; the values were equal but the diff was "
    "unreadable, and restored. Fourth, two integration test files were left unformatted after "
    "earlier line insertions, which would have failed CI's gofmt gate on a run where every "
    "functional test passed. All four are recorded rather than quietly repaired because the "
    "recurring theme is exactly the one EV-060 and EV-061 identified: something written to record "
    "or verify state, never checked against what it actually produced."
)

SIGNIFICANCE = (
    "The .gitignore defect is the one that matters beyond this work item, and it is instructive "
    "rather than embarrassing. Two hygiene patterns sat in a tracked file, syntactically "
    "indistinguishable from correct ones to a reader, doing nothing at all - and the failure mode "
    "is silent in the worst direction, because a developer checking whether a scratch file is "
    "ignored sees a normal-looking rule and concludes it is covered. It survived because nobody "
    "had asked the question that would have exposed it: not 'does this line look right' but 'does "
    "git actually ignore the thing'. That is the same lesson as EV-060's overturned driver "
    "argument and EV-061's migration runner that reported success while creating nothing: a "
    "control nobody has seen fail is not known to work, and in this repository the evidence log "
    "is the place that fact has to be written down. The four tooling defects matter for a "
    "different reason. Each one wrote something plausible into a tracked governance file and would "
    "have been reported as done; three of the four were caught only because the result was "
    "compared against HEAD field by field rather than eyeballed, which is the check that a "
    "reviewer would otherwise have had to do by hand."
)

CAVEATS = (
    "Four limitations. First, the comparison script is a one-shot tool written after the fact, so "
    "it proves this session's work-items.json changes were accounted for rather than preventing "
    "the next writer from re-encoding the file; the durable fix is to have one writer for that "
    "file that owns its serialisation, which does not exist yet. Second, the .gitignore fix was "
    "verified for the two patterns that were broken and for the one that was added; it was not "
    "verified pattern-by-pattern for the whole file, though lines 1-69 had no leading whitespace "
    "and so were unaffected. Third, EV-062's product code is unchanged by this record - nothing "
    "here alters behaviour, the G5 verdict, or any test outcome - and its claims stand as written. "
    "Fourth, the human_reviewer field of the G5 report remains null, WI-141 remains IN_PROGRESS "
    "for that reason, and the schema-version forward problem remains human-owned, as do the "
    "unqualified audit and authz tables (WI-117) and RISK-14's deferred scaling findings. Cross-"
    "store atomicity remains WI-120 and WI-121's and is still not claimed. The graceful SIGTERM "
    "drain remains unproven by test on Windows. Nothing was staged and nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    ".gitignore",
    ".kilo/ecc/project-brain/work-items.json",
    "scripts/compare_work_items_to_head.py",
    "scripts/restore_work_items_style.py",
    "scripts/repair_wi141_note_tail.py",
    "scripts/fix_gitignore_indentation.py",
    "scripts/record_wi141_g5_pass.py",
    "scripts/record_ev063.py",
    "services/control-plane/integration/atomicity_test.go",
    "services/control-plane/integration/audit_test.go",
]

SUPERSEDES = []


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    line = json.dumps(
        {
            "schema": "ecc.project-brain/evidence/v7",
            "evidence_id": EVIDENCE_ID,
            "recorded_at": STAMP,
            "recorded_by": "team-lead",
            "work_item": WORK_ITEM,
            "claim": CLAIM,
            "status": "VERIFIED",
            "method": METHOD,
            "result": RESULT,
            "defect_found_and_fixed": DEFECT_FOUND_AND_FIXED,
            "significance": SIGNIFICANCE,
            "caveats": CAVEATS,
            "exception": EXCEPTION,
            "artifacts": ARTIFACTS,
            "supersedes": SUPERSEDES,
        },
        ensure_ascii=False,
    )

    if store.exists():
        for existing in store.read_text(encoding="utf-8").splitlines():
            if existing.strip() and json.loads(existing).get("evidence_id") == EVIDENCE_ID:
                print("unchanged: " + EVIDENCE_ID + " already recorded")
                return False

    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print("recorded " + EVIDENCE_ID)
    return True


if __name__ == "__main__":
    record()
