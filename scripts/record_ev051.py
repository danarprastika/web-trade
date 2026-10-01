"""One-off: append EV-051, correcting and superseding EV-050.

EV-050 recorded the identity rehydration work and stated that all ten mutations applied to
the new code were detected. That number was wrong, and in a way that mattered: the probe set
behind it did not contain the two checks that this record's own documentation claims. Both
of those checks were then run against the test suite as it stood, and both survived - each
breaking a property Restore's comments assert in prose and no test enforced.

The implementation was correct in both cases. What was overstated is the verification, and
since the evidence record is what a later reviewer relies on, the record is what gets fixed.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-051"
STAMP = "2026-09-30T17:29:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "EV-050 overstated its own verification, and this record corrects it. EV-050 stated that "
    "all ten mutations applied to the new code were detected against a verified-pristine "
    "baseline. Ten is the wrong number in a way that is not merely arithmetic: the two checks "
    "that Restore's own documentation makes load-bearing claims about - that a refused restore "
    "changes nothing, and that a refused rehydration returns an error rather than an empty "
    "registry - were not in that probe set at all. Re-run against the suite as it stood, both "
    "survived. Each surviving probe removes a guarantee the code comments assert in prose, and "
    "neither guarantee had a test. The production code was correct in both cases: Restore does "
    "stage its maps and publish only at the end, and RehydratedWorkloadRegistry does return the "
    "error. What was wrong was the claim about what had been checked. Both are now covered, and "
    "the corrected probe set detects twelve of twelve."
)

METHOD = (
    "Started by refusing to trust the earlier number rather than re-deriving it. EV-050's "
    "mutation figure came from a probe whose output was empty, read as a detected mutant. Empty "
    "output is equally consistent with a harness that never ran, wrote somewhere else, or "
    "targeted a file that was not there, so the reading was not evidence of anything. Rebuilt "
    "the harness so that each probe reports whether its edit actually applied before the test "
    "result is recorded, and made the harness refuse to report a result at all if any edit "
    "failed to apply or any file failed to restore byte-for-byte. Then read the existing tests "
    "before writing mutations, which is what exposed the gap: every refusal test in "
    "identity_restore_test.go built a freshly created empty registry and asserted only that an "
    "error came back. A Restore that replaced the live set and then failed on a later field "
    "would have passed all of them. Two probes were written specifically for the claims the "
    "comments make, and each was verified to survive before any test was added, so that the "
    "gap was demonstrated rather than asserted."
)

RESULT = (
    "Twelve of twelve probes now detected, each by the intended test, with the twenty-seven "
    "source files restored byte-for-byte afterwards and the unmutated package confirmed to pass "
    "before the run so the harness could not report green against a red baseline. The two "
    "surviving probes were each live gaps in the suite rather than in the code, and each is "
    "now closed by a test that fails when the guarantee is deleted. The atomicity test is the "
    "mirror of the journal's existing TestARefusedAuditChainLeavesTheStateUnchanged, which is "
    "the convention this codebase already follows for exactly this property, so the omission "
    "here was a departure from an established pattern rather than an unknown. The rehydration "
    "test needed a stub reader serving a snapshot the registry cannot restore, because the "
    "in-memory store cannot produce one - everything it holds already passed the validation "
    "Restore repeats. All 13 project gates pass, vet and gofmt are clean, and the race detector "
    "is clean across both packages."
)

DEFECT_FOUND_AND_FIXED = (
    "Two defects in the verification, and neither in the code under test. The first is the "
    "reading of empty probe output as detection. A probe returning nothing is not a mutant that "
    "was caught; it is an observation that proves nothing, and it was counted as though it "
    "proved something. The second follows from it: because the ambiguous reading was never "
    "challenged, the probe set was believed complete when it was not, and a later probe run "
    "with an explicit apply-check found two mutations that the existing suite could not catch. "
    "What makes the second worth more than a bookkeeping note is the shape of the two failures. "
    "Publishing the identity map before the revocation loop runs, and dropping the error from "
    "Restore, are both single-line edits to correct code, and both would have shipped silently. "
    "Neither changes any type, breaks any build, or alters any other test - they fail only the "
    "assertion nobody had written. A comment saying a restore is all-or-nothing is a claim; "
    "these two properties were claims for the entire life of the code, and the evidence record "
    "asserted they had been verified. They had not. Both tests are now in place and both probes "
    "are caught, so the comments and the suite finally say the same thing."
)

SIGNIFICANCE = (
    "The transferable part is that a green mutation run is only worth the probes in it, and a "
    "probe whose result cannot be distinguished from a harness failure is worse than no probe, "
    "because it inflates the count while adding no coverage. This codebase already had the "
    "right pattern for the atomicity property - the journal test named for it - and the identity "
    "restore simply never received the equivalent. That is the more useful finding: the "
    "convention existed, the omission was local, and nothing in the workflow noticed, because "
    "twelve passing tests and a recorded claim of ten detected mutations look identical whether "
    "the two load-bearing checks are present or not. Nothing here contradicts EV-050's "
    "substantive findings, which stand: identity rehydration is implemented, revocation is "
    "durable across a restart, and the removal rule is the correct reading of the additive "
    "store. What is withdrawn is the completeness of its verification."
)

CAVEATS = (
    "Three limitations, and one correction to the record itself. First, the correction: EV-050 "
    "remains in the append-only log and still carries the overstated ten-probe claim, which is "
    "why this row supersedes it rather than editing it. Any reviewer reading EV-050 must read "
    "this row alongside it. Second, unchanged from EV-046, EV-048, EV-049 and EV-050: no Go "
    "process has connected to PostgreSQL, and ListAllWorkloadIdentities and ListAllWorkloadRevocations "
    "have never been executed by anything except sqlc's type checking - the mapping is verified "
    "against the generated dbgen types and the 45 database assertions in db-0004-model-registry "
    "cover the statements and the schema, but the Go mapping itself remains unproven against a "
    "live instance. Third, unchanged: nothing constructs a RehydratedWorkloadRegistry, no "
    "composition root exists, and rehydration is therefore explicit rather than automatic; the "
    "revoked_by column is still read and discarded by design; and the EV-048 schema-version "
    "forward problem still constrains three stores and remains unresolved and human-owned. Also "
    "unchanged: no specification file was modified, docs/ remains clean, nothing was staged, and "
    "nothing was committed. WI-141 remains IN_PROGRESS with human G4 review outstanding. Note on "
    "scope: the twelve probes cover identity_restore.go only; this row makes no new claim about "
    "the audit or journal harnesses recorded in EV-047 through EV-049."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/model/identity_restore_test.go",
    "services/control-plane/model/identity_restore.go",
    "scripts/record_ev051.py",
]

SUPERSEDES = ["EV-050"]


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