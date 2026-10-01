"""One-off: append EV-052, recording three real defects an independent review found in the
durable-write failure path, and the six scaling findings deliberately left open.

The defects were not found by re-reading the code carefully. They were found by running
review sub-agents over the uncommitted diff, then confirming each candidate by executing a
temporary probe rather than by believing the report. One of them had a green test that depended
on it.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-052"
STAMP = "2026-09-30T17:58:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "An independent review of the uncommitted rehydration work found three real defects, all "
    "of them in the path that runs when a durable write is refused, and all three are now fixed "
    "and covered by regression tests that fail when the fix is reverted. The durable-write "
    "guarantee recorded across EV-041 through EV-045 was true of the success path and untrue of "
    "the failure path: a refused durable write left the append-only audit chain permanently "
    "certifying a governance event that never happened, and the documented recovery - the caller "
    "retrying - was itself permanently broken. It was broken invisibly, because the one test "
    "covering it installs a frozen clock, which is the only reason it passed."
)

METHOD = (
    "Ran review sub-agents over the uncommitted diff across all six tracks, then treated every "
    "candidate as a hypothesis rather than a conclusion. Three business-logic candidates came "
    "back, and the instinct was to check the strongest one by writing a temporary probe rather "
    "than by re-reading the code a fourth time. That probe had to be corrected twice first - "
    "the first attempt guessed a journal API that does not exist, and the second used the "
    "partition name 'model' where the partition is actually the model owner, which made the "
    "chain appear to hold zero records and would have produced a confident false negative on "
    "the most serious finding. Only when the probe read through the journal's own accessor did "
    "the orphan record appear. The discipline that mattered throughout was refusing to accept a "
    "probe result the harness had not shown to be real, which is the same lesson EV-051 "
    "recorded from the opposite direction. Having confirmed all three by execution, each fix "
    "was written to preserve the invariant the surrounding comments depend on, and each was "
    "then re-verified by reverting it and requiring a named regression test to fail."
)

RESULT = (
    "Three defects, three regression tests, seven mutations, seven detections. First, a refused "
    "durable write no longer leaves the chain's SUCCEEDED record uncorrected: commit now appends "
    "a REFUSED record that cites the acceptance as its cause and inverts the digests, so the "
    "chain shows the state the model was actually left in rather than the state the transition "
    "would have reached, and the audit sink can no longer export a false success. Second, a "
    "retry after a refused write now succeeds on a clock that moves: the record reuses the "
    "timestamps already stored under that audit identity, which is sound precisely because one "
    "identity can never legitimately carry two different contents - the chain still refuses that "
    "case - so reusing the recorded times is not a way of concealing a difference but the only "
    "way to hand back the record the chain already holds. Third, MemoryStore.ApplyTransition now "
    "advances the stored model row, matching SQLStore and the Store contract's own wording, so "
    "a snapshot read reports where the model is rather than where it was registered. Each fix "
    "was proven load-bearing by reverting it: two probes against the refusal correction, two "
    "against the timestamp reuse, and two against the model-row update, with every one detected "
    "and both files restored byte-for-byte. All 13 project gates pass, including the migration "
    "rehearsal, and vet, gofmt and the race detector are clean."
)

DEFECT_FOUND_AND_FIXED = (
    "Three defects in the code, and a fourth finding that is arguably worse than any of them. "
    "First, the audit record was stamped SUCCEEDED and appended before the durable write, so a "
    "store refusal left the chain holding a success for a transition that never took effect, and "
    "the comment at journal.go:308-313 claimed this was 'recorded honestly below' when nothing "
    "below recorded it - an append-only chain cannot retract it, so the audit sink would have "
    "exported a false governance event to durable storage. Second, and the sharpest: the audit "
    "identity is derived from stable inputs while the timestamps are read from the clock on "
    "every attempt and the chain hashes them, so a retry reached the same identity with different "
    "content and was refused as a conflicting reuse - permanently, because every subsequent "
    "retry re-derives the same identity. A single transient storage failure therefore wedged a "
    "governance transition for the life of the process, and the operator-facing error pointed at "
    "an audit conflict rather than at the storage fault that caused it. Third, "
    "MemoryStore.ApplyTransition recorded the transition but never advanced the model row, "
    "which is a contract violation against SQLStore and against the port's own documentation. "
    "The fourth finding: TestRestoreRecoversTheIdempotencyLedger was passing because of that "
    "third defect. It read the restored model's state and used it as the 'from' state for the "
    "replayed transition; because the store reported REGISTERED forever, it passed a valid edge "
    "instead of an invalid one. A test green on a defect is worse than a test red, because it "
    "converts a bug into a specification. The test was corrected to replay the identical request "
    "- which is what a retry is - and now asserts the restored state is the one the transition "
    "actually reached."
)

SIGNIFICANCE = (
    "The pattern across EV-047 through EV-052 is that every defect found so far has lived in a "
    "failure path, and every one of them was masked by a test that passed for the wrong reason. "
    "The frozen clock in newDurableJournal is the clearest instance: it is a reasonable test "
    "fixture, and it made a guarantee that only holds under a frozen clock look like a guarantee "
    "that holds. The deeper point is about what durability claims mean. This work spent seven "
    "evidence records establishing that state is written only after evidence is accepted - and "
    "that claim was never in question on the success path, where the code does exactly what it "
    "says. What was untested was the moment the guarantee exists to cover: the storage layer "
    "saying no. A durability guarantee that has only been demonstrated when the write succeeds is "
    "not a durability guarantee, because the failure is the only case where the ordering "
    "decides whether the system lies. The review also surfaced a limit worth stating: two of the "
    "six sub-agents returned empty output. That was not read as a clean result, and the "
    "highest-value duplication risk among those - whether the identity write path and the "
    "identity restore path validate the same rules - was checked by hand instead. It turned out "
    "the restore path omits a blank-model-version check the write path has, and that this is "
    "unreachable because the database enforces it, which is exactly the kind of finding that "
    "should not be reported and would not have been had the empty output been trusted."
)

CAVEATS = (
    "Five limitations. First, and the largest: six review findings remain unfixed and are "
    "recorded as RISK-14 rather than dropped. They are an N+1 startup read over "
    "model_transition_idempotency with no index on model_id; the registry mutex held across "
    "InsertIdentity and the journal mutex held across the durable transaction, so Authenticate "
    "and every journal reader serialise behind storage latency; rehydration holding roughly three "
    "times the retained audit archive in memory; one round trip per record on audit export; and "
    "workload_identities, which grows one row per mint forever with nothing pruning it, loaded "
    "in full at every startup. These are scaling and latency rather than correctness and none "
    "blocks a gate, and they were deferred deliberately rather than for time: the index fix "
    "requires amending or superseding migration 0004, which the rehearsal gate already "
    "exercises, so it needs an explicit deploy decision; and the two mutex changes would narrow "
    "the deliberate 'durable write precedes in-memory state' ordering, which is worth doing "
    "deliberately. Second, unchanged from EV-046 and EV-048 through EV-051: no Go process has "
    "connected to PostgreSQL, so the refusal-record path has never been exercised against a live "
    "timestamptz or a real transaction. Third, unchanged: no composition root constructs any "
    "rehydrated object, so rehydration is still explicit rather than automatic; atomicity between "
    "audit acceptance and registry persistence remains WI-121's, not this item's; and the EV-048 "
    "schema-version forward problem remains unresolved and human-owned. Fourth, the refusal "
    "record deliberately carries a fixed reason rather than the store's error text, because that "
    "text goes to the caller and the logs and evidence outliving the process should not carry "
    "database internals; an operator wanting the underlying cause reads the error, not the chain. "
    "Fifth, the refusal record's audit identity is the original's plus a '.refused' suffix, which "
    "is deterministic and stable across repeated refusals of the same transition but is a "
    "convention rather than a derived digest. Also unchanged: the mutation harness was run as a "
    "verification activity and its script and scratch files were deleted; no specification file "
    "was modified; docs/ remains clean; nothing was staged; and nothing was committed. WI-141 "
    "remains IN_PROGRESS pending human G4 review."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/model/journal.go",
    "services/control-plane/model/store.go",
    "services/control-plane/model/store_test.go",
    "services/control-plane/model/restore_test.go",
    ".kilo/ecc/project-brain/risks.md",
    "scripts/record_ev052.py",
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