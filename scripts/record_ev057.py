"""One-off: append EV-057.

Produces the G5 gate report, corrects a gate reference that was wrong in four prior records,
and records a verdict of FAIL that is honest about which criterion is unmet and who owns it.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-057"
STAMP = "2026-10-01T02:36:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The G5 gate report now exists, with a content digest for every artifact it rests on, and it "
    "reads FAIL. docs/11_EXECUTION_GATES.md closes by requiring that each gate report identify its "
    "evidence artifacts by immutable URI or repository path and content digest, that a gate be "
    "PASS only when every listed criterion is satisfied, and that partial completion be FAIL "
    "rather than a percentage. The five subsystems the G5 criterion names all pass. Audit-trail "
    "completeness across a process restart does not, and that is WI-117's AC4, which is not "
    "implemented. Separately: four records from this work item said WI-141 awaits 'human G4 "
    "review'. WI-141 is a G5 item and G4 belongs to WI-140, which is already BLOCKED. That error "
    "is corrected here and in the work item."
)

METHOD = (
    "Did not assume the G5 blocker would resemble WI-140's, because checking first was cheap and "
    "assuming would have been a fabrication. WI-140's blocker cites 'the two G4 report fields that "
    "docs/11 requires', so the natural move was to copy that shape onto G5. Searching docs/11 "
    "showed reviewer and commit appear exactly once in the whole file, inside the G0 section, as "
    "fields the G0 report must record. They are not G5 requirements, so that blocker was not "
    "copied. What docs/11 does require of every gate is a digest-identified artifact list, and "
    "that was built. The artifact set is hashed by a generator that recomputes each digest and "
    "re-verifies it after writing rather than restating a digest measured earlier, and it was "
    "then cross-checked against PowerShell's Get-FileHash, an independent implementation. Every "
    "test name the report cites was confirmed to exist in the tree; a first pass reported two "
    "missing tests that turned out to be the English words in 'attestation' and 'tests' matched "
    "by an over-broad pattern."
)

RESULT = (
    "evidence/gates/G5-gate-report.json and .md, matching the shape G0 established, with six "
    "criteria and 56 artifacts totalling the model package, the audit package, migration 0004, "
    "the registry queries and the generated registry code - each with a SHA-256 over its exact "
    "bytes. Digests re-verified after write and independently cross-checked. Generation is "
    "deterministic: regenerating over an unchanged tree produces byte-identical files. All 15 "
    "cited test names exist. The verdict is FAIL, on G5.6, audit-trail completeness across a "
    "process restart. The five named subsystems pass with mechanically verified criteria naming "
    "the tests that establish each. human_reviewer is null. WI-141's completion_note now records "
    "the report path, the verdict, its reason, and the correction. All 13 gates pass after the "
    "brain edit."
)

DEFECT_FOUND_AND_FIXED = (
    "One, in my own records rather than in the product. WI-141's completion_note stated 'The item "
    "remains IN_PROGRESS because human G4 review is outstanding', and I copied that phrasing into "
    "the closing sentence of EV-053, EV-054, EV-055 and EV-056 without checking it. The work item "
    "is G5; G4 is WI-140's gate, a separate prior item already marked BLOCKED. Corrected in "
    "work-items.json by scripts/correct_wi141_gate_reference.py, which replaces exactly one "
    "sentence, refuses to edit if that sentence is not present exactly once, and re-parses the "
    "file afterwards to confirm the correction survived and the error did not. The four evidence "
    "records are not edited, because the evidence log is append-only; this record is the "
    "correction. The product code is unchanged and no test changed behaviour."
)

SIGNIFICANCE = (
    "The gate report exists now, and it exists because the rule was read rather than assumed. The "
    "tempting move was to carry WI-140's blocker across verbatim - same shape, same author, same "
    "reviewer-plus-commit structure - and it would have produced a report that read "
    "convincingly and cited two fields docs/11 does not ask of G5. That is the failure mode this "
    "project's evidence discipline exists to prevent: a plausible record, matching its neighbour, "
    "restating a requirement nobody checked. The more useful point is about the FAIL. It would "
    "have been easy to report the five passing subsystems and mark G5 PASS, which is what the "
    "work item's own partial_results invites, since all four of its acceptance criteria are "
    "verified. But the G5 criterion asks that these systems operate with complete audit trails, "
    "and a trail that cannot be reconstructed after a restart is not complete in the sense that "
    "matters for an audit system. docs/11 already supplies the rule - partial completion is FAIL, "
    "not a percentage - so recording G5.6 as FAIL rather than omitting it is following the "
    "document rather than inventing a stricter one, and naming WI-117 as the owner keeps it from "
    "reading as work abandoned here."
)

CAVEATS = (
    "Four limitations. First, and unchanged across every record since EV-046: no Go process has "
    "connected to PostgreSQL, so none of the refusal, resolution, or rehydration paths has run "
    "against a live timestamptz or a real transaction. The database gates verify the schema "
    "through their own harness and sqlc-vet verifies that the generated code matches the queries; "
    "neither shows the Go persistence layer behaving correctly against a live database. This "
    "report's criteria G5.1 through G5.5 rest on in-process tests. Second, the artifact digests "
    "are over a working tree that no commit contains, so they identify the bytes but do not "
    "establish provenance; HEAD remains ca4eacfa7d1f3c6f481a37fff66ffa83f7a07fa0 and the "
    "implementation paths remain untracked or unstaged, so a reviewer has no baseline diff to "
    "read. No commit was requested and none was made. Third, the report's criteria were derived by "
    "reading the G5 criterion and the test suite, not from a pre-existing G5 checklist - "
    "docs/11 states one sentence for G5, and this decomposes it into six mechanically checkable "
    "criteria, which is an interpretation a reviewer may reasonably disagree with. It is offered "
    "as a proposal for attestation, not as an agreed decomposition. Fourth, unchanged: no "
    "composition root constructs any rehydrated object, which is the mechanism behind the G5.6 "
    "failure; atomicity between audit acceptance and registry persistence remains WI-121's; the "
    "EV-048 schema-version forward problem remains unresolved and human-owned; RISK-14's six "
    "deferred scaling findings are open; no specification file was modified; docs/ remains clean "
    "at zero changes; nothing was staged; and nothing was committed. WI-141 remains IN_PROGRESS "
    "pending a named human reviewer, and this record does not attest to it."
)

EXCEPTION = ""

ARTIFACTS = [
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    "scripts/generate_g5_gate_report.py",
    "scripts/correct_wi141_gate_reference.py",
    "scripts/record_ev057.py",
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
            "corrects": ["EV-053", "EV-054", "EV-055", "EV-056"],
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