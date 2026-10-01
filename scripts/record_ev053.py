"""One-off: append EV-053, superseding EV-052.

EV-052 fixed three defects and recorded them as VERIFIED. One of those fixes was incomplete in
a way that made it introduce a new falsehood while removing an old one, and nothing in the seven
mutations EV-052 ran could have found it, because the question was never asked.

This is also the record of a mistake in the harness used to prove the earlier fix: it counted a
mutation that did not compile as a detected mutant.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-053"
STAMP = "2026-09-30T21:14:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "EV-052's audit-refusal correction was incomplete, and the incompleteness was worse than "
    "the defect it fixed. The refusal record it added is terminal - an append-only chain cannot "
    "retract one - so the retry that EV-052's second fix made possible left the contradiction "
    "standing permanently: the last evidence for a transition said it was refused while the "
    "durable registry said it was applied, and nothing detected the disagreement. Not the chain "
    "restore, and not the registry's corroboration check, because the registry row cites the "
    "accepted record and verifyAgainstChain is right to accept it. The contradiction was "
    "invisible precisely because both halves were individually correct. A resolution record is "
    "now written when the retry lands, and this record supersedes EV-052."
)

METHOD = (
    "Did not re-read the fix. Had a review sub-agent attack the three fixes specifically, on the "
    "reasoning that the same author wrote both the defects and the fixes and so nobody else had "
    "read them without already holding the same assumption. It returned one high-confidence "
    "finding: the refusal is terminal and nothing resolves it. Confirmed that by executing a "
    "probe rather than by believing the report, and the probe printed the contradiction "
    "directly - sequence 3 SUCCEEDED, sequence 4 REFUSED, zero records citing the refusal, a "
    "durable row in the new state, and a clean archive restore. The probe needed two corrections "
    "before it ran, both of which had the same shape as earlier ones: it guessed a store API "
    "that does not exist, and then looked for records under the wrong partition and would have "
    "reported a clean result from an empty read. Then fixed the gap, and probed the fix the same "
    "way. The lesson of EV-051 repeated in the harness one level down: a result the harness "
    "cannot vouch for is not a result."
)

RESULT = (
    "The retry now resolves the refusal it was waiting for. recordApplication appends nothing "
    "on the ordinary path, so a transition the store accepted first time is still exactly one "
    "record; when a refusal exists it appends a SUCCEEDED record citing that refusal as its "
    "cause and inverting the digests, so the chain ends on the state the model actually reached "
    "and an investigator walking forward from the refusal reaches the resolution rather than "
    "walking past it. Two regression tests: one asserts the refusal is resolved, that the "
    "resolution carries the digest of the state the transition reached, and that the durable row "
    "and the journal agree; the other asserts the ordinary path appends no repair record and "
    "every record on it is SUCCEEDED. Five mutations against the repair, five detections, each "
    "with a named failing test - including the one asserting the ordinary path stays quiet, "
    "which is the property that would otherwise be traded away silently to solve the coherence "
    "gap. All 13 project gates pass; vet, gofmt and the race detector are clean."
)

DEFECT_FOUND_AND_FIXED = (
    "Two. The first is in the code. EV-052 added a terminal REFUSED record to correct a false "
    "SUCCEEDED, and did not consider what the retry then does - which is the entire purpose of "
    "EV-052's second fix, so the two fixes were developed in sequence and their interaction was "
    "never examined. Commit rebuilds a record that is now byte-identical to the one already "
    "stored, takes the chain's duplicate-delivery branch, and appends nothing. The store write "
    "then succeeds, the journal advances, and the chain's last word on the transition is that "
    "it was refused. The refusal was also a leaf: because the retry does not update auditIDs, "
    "the next transition's causation cites the accepted record and the refusal is skipped "
    "entirely by anything walking causation forward. Neither half of this is wrong on its own - "
    "the refusal was honest about its own attempt, and the retry genuinely succeeded - which is "
    "why it survived seven mutations and a recorded VERIFIED. The second is in the harness. Its "
    "build-failure guard looked for the strings 'cannot' and 'undefined', and one mutation "
    "failed to compile with Go's 'multiple-value ... in single-value context', so a build "
    "failure was scored as a detected mutant and the run reported 5 of 5 when the honest count "
    "was 4. Caught because the harness printed '(failed without a named test)' instead of a "
    "test name, which is the same tell that exposed the empty-output probe in EV-051. The guard "
    "now keys off the build-failure signal, and a mutation that fails without a named test is "
    "recorded as unverified rather than detected."
)

SIGNIFICANCE = (
    "The transferable finding is that two individually correct fixes were jointly inconsistent, "
    "and that no amount of testing the first would have found it. The refusal correction and the "
    "retry repair were verified independently - seven mutations for the first set, each reverted "
    "and each caught - and both passed, and together they produce a state where the evidence and "
    "the registry disagree and every check in the system reports agreement. Verification that "
    "proves each claim is sound is not verification that the claims compose, and the failures "
    "this project has now found repeatedly are all compositional: a durable write that fails, a "
    "retry that follows it, a snapshot taken after both. The second point is about review "
    "economics. A subagent given one high-confidence finding against code that had already been "
    "mutation-verified found in a single pass a defect that seven targeted mutations missed - "
    "not because the mutations were weak but because the question they asked was narrower than "
    "the defect. Adversarial review of one's own fix is worth more than more mutation testing of "
    "it, because the second repeats the first author's assumptions about what matters. And the "
    "harness defect is the same lesson a third time, now at the level of the tooling rather than "
    "the code: a check that cannot distinguish the two ways a probe can end is not a check."
)

CAVEATS = (
    "Four limitations. First, EV-052 is superseded rather than edited, because the evidence log "
    "is append-only: its three fixes stand, its seven-mutation result was sound for what it "
    "tested, but its refusal correction was incomplete and any reviewer reading it must read "
    "this alongside it. What EV-052 did not do wrong is claim more than it checked - it "
    "described the refusal as correcting a false success, which is true, and never claimed the "
    "retry left the evidence coherent. The record was accurate; it was incomplete in the same "
    "way the code was. Second, unchanged from EV-046 and EV-048 onward: no Go process has "
    "connected to PostgreSQL, so none of the refusal or resolution paths has run against a live "
    "timestamptz or a real transaction, and the resolution record's audit identity is by "
    "convention a suffix chain - original, then '.refused', then '.applied' - rather than a "
    "derived digest. That is deterministic and stable across repeats, but it is a naming "
    "convention rather than a value derived from content. Third, RISK-14's six deferred scaling "
    "findings remain open and unchanged, and the refusal/resolution work has not touched them. "
    "Fourth, and unchanged: no composition root constructs any rehydrated object, so rehydration "
    "is still explicit rather than automatic; atomicity between audit acceptance and registry "
    "persistence remains WI-121's; the EV-048 schema-version forward problem remains "
    "unresolved and human-owned; no specification file was modified; docs/ remains clean; "
    "nothing was staged; and nothing was committed. The mutation harness for this record was run "
    "as a verification activity and its script and scratch files were deleted. WI-141 remains "
    "IN_PROGRESS pending human G4 review."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/model/journal.go",
    "services/control-plane/model/store_test.go",
    "scripts/record_ev053.py",
]

SUPERSEDES = ["EV-052"]


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