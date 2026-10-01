"""One-off: append EV-071.

Records what the re-review found and what it cost. The nine fixes of EV-070 were largely correct,
and the verification pass then found that the single most important one of them - the audit
truncation anchor - had been shipped without a producer, so in production it did nothing at all.

That is recorded here at the same length as the successes because it is the more important
record. The fix added a consumer: restore now compares a rehydrated partition's head against a
signed checkpoint in audit_checkpoints, and refuses when the head is behind it. Nothing wrote
that table. `AppendAuditCheckpoint` and `NewCheckpoint` were referenced only from dbgen's own
accessor definition and from _test.go files, so against a real database GetLatestAuditCheckpoint
returns sql.ErrNoRows, the anchors map comes back empty, and Rehydrate took precisely the
unanchored path the original finding was about. A truncated archive still rehydrated as VERIFIED.

It passed its own tests because every test that "proved" the fix inserted the checkpoint itself.
A test that supplies the thing whose absence it is meant to detect cannot detect its absence.
This is the sharpest instance of a pattern the ledger has hit repeatedly - EV-051 corrected an
overstated verification claim, EV-067 recorded four checks that reported failure while
establishing nothing - and the distinguishing feature here is that nothing looked wrong. The
gate was green, the tests were green, the digests were current, and the CRITICAL was still open.

The fix wires the producer into the sink: Export groups its records by partition, signs one
checkpoint per partition before the transaction opens, and inserts records and checkpoints in the
same transaction, so there is no window in which records are committed without their anchor or an
anchor exists for records that were never written. A signer is now a required dependency of both
the sink and the composition root, on the same footing as Clock and Environment, because a sink
that quietly declines to anchor is the hole being closed. The worker that implemented it ran out
of steps before performing the negative control, so it was run here: disabling the checkpoint loop
makes four audit unit tests and the end-to-end integration test fail, and the source restores
byte-identically. That is the evidence EV-070's version of this fix conspicuously lacked.

The re-review also found a bypass in the guard added for finding 3: the destructive-target guard
read the database name from the URL path only, while lib/pq applies every query parameter after
the path with last write winning. `webtrade_test?dbname=webtrade` passed the disposable check
while the driver connected to webtrade, and `localhost/webtrade_test?host=db.internal` passed the
local-host check while the driver left the machine. Both now refuse by name, with the same
negative control run by hand.

human_reviewer is still null. An agent reviewing the agent that wrote the fix is not the
independent check the field exists for, and the person who has to look at this has not.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-071"
STAMP = "2026-10-02T01:05:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The re-review of the nine EV-070 fixes found the most important one of them - the audit "
    "truncation anchor - was shipped without a producer, so in production it did nothing and a "
    "truncated archive still rehydrated as verified. The anchor now has a producer in the sink, "
    "and the absence of that producer is demonstrated to be detected rather than merely asserted."
)

METHOD = (
    "Two independent read-only reviews were run over commit d688e02: one asking, per finding, "
    "whether it is closed or only claimed closed; one attacking the new enforcement adversarially. "
    "The adversarial one returned nothing, which is recorded rather than treated as a pass. The "
    "first found the anchor had no producer, and that claim was then verified by hand before "
    "acting on it - AppendAuditCheckpoint and NewCheckpoint were searched across the module and "
    "the only non-test references were dbgen's own accessor definition, so the table was never "
    "written in production. The fix was implemented in the sink and then negative-controlled by "
    "hand, because the implementing agent ran out of steps before doing it: disabling the "
    "checkpoint loop must make the new tests fail. It does - four audit unit tests and the "
    "end-to-end integration test - and the file restores byte-identically. The same treatment was "
    "given to the destructive-guard fix, where removing the override check makes the new bypass "
    "tests fail."
)

RESULT = (
    "The sink now anchors what it writes. SQLSink.Export groups its records by partition, builds "
    "one signed checkpoint per partition before the transaction opens so a batch that cannot be "
    "anchored writes no records at all, and inserts the records and their checkpoints in the same "
    "transaction, so there is no window in which records are committed without their anchor or an "
    "anchor vouches for records that were never written. One checkpoint per partition per export "
    "rather than per record, which is what GetLatestAuditCheckpoint's ordering by last_sequence "
    "expects and what the table's uniqueness and deferred coverage trigger expect. A signer is a "
    "required dependency of both the sink constructor and the composition root, on the same footing "
    "as Clock and Environment, because a sink that quietly declines to anchor is the hole being "
    "closed. A new end-to-end integration test writes through the real SQLSink against live "
    "PostgreSQL and then rehydrates through the real SQLChainReader, confirming the anchor row "
    "exists, is found at the right sequence and hash, and verifies against a ring. Negative "
    "control observed directly: disabling the checkpoint loop fails "
    "TestTheSinkWritesACheckpointCoveringTheRecordsItJustStored, "
    "TestTheSinkCheckpointsEveryPartitionOfAMultiPartitionExport, "
    "TestASecondExportAdvancesThePartitionAnchor, "
    "TestACheckpointThatCannotBeWrittenFailsTheWholeExport and "
    "TestTheSinkWritesACheckpointThatARehydrationFinds; restoring the file byte-for-byte returns "
    "them to green. Separately, the destructive-target guard no longer reads the database from the "
    "URL path alone: a query string carrying dbname, host, port or user that could redirect the "
    "connection is refused by name, because lib/pq applies path first and parameters after it with "
    "last write winning, so `webtrade_test?dbname=webtrade` and `localhost/webtrade_test?host="
    "db.internal` both pointed the reset at a database the guard had never seen. A dbname that "
    "merely restates the path is still accepted, and sslmode and friends are not mistaken for "
    "redirectors, so the guard does not become unusable. Negative control observed: removing the "
    "override check fails the new bypass test. Full sweep after both fixes: gofmt clean; vet, "
    "vet -tags=integration, build, unit -race, integration -race and go mod verify all 6 of 6 "
    "modules; sqlc regeneration produces no drift; drain mutation gate PASS, now crediting only a "
    "failing assertion; bash gate PASS across 40 run blocks; toolchain 14 of 14; migration rehearsal "
    "up/down/up; tests/ci 124 passed; contracts VALID; research 109; backtest 47; project brain "
    "PASS; evidence audit 0 drifted; all five proof scripts hold. The G5 report was regenerated "
    "over the fixed tree and now digests 88 artifacts."
)

DEFECT_FOUND_AND_FIXED = (
    "Two. The severe one: the audit truncation anchor had a consumer and no producer, so the "
    "critical finding it was written to close was still open in production and would have stayed "
    "open indefinitely, because nothing in the system would ever have complained. It passed "
    "because every test supplied the checkpoint it was supposed to prove was required. The second: "
    "the destructive-target guard could be bypassed by any query parameter that redirects the "
    "connection, which is not a hypothetical - it is how lib/pq resolves a DSN - so the guard "
    "would report that it had protected a disposable local database while the reset destroyed a "
    "production one elsewhere. Also fixed: a dbname that restates the path is accepted, and a "
    "parameter that cannot redirect is not treated as one that can, so the guard stays usable. "
    "One scope exception taken and flagged: the sink change required a signer argument, and "
    "integration/restart_test.go could not compile without a two-site update. Recorded because a "
    "minimal edit to an out-of-scope test is still an edit to an out-of-scope test."
)

SIGNIFICANCE = (
    "The generalisable point is narrow and uncomfortable: a test that supplies the thing whose "
    "absence it exists to detect cannot detect its absence. Every signal this repository has was "
    "green - the gate, the tests, the digests, the report asserting PASS on all seven criteria - "
    "and the defect it was built to prevent was still fully reachable. Ceremony is not coverage, "
    "and the second half of that is the part that costs: a check whose fixture provides the "
    "answer is not a weaker check, it is a check pointed at itself. The negative control is the "
    "cheapest available instrument and it was the one step skipped, both by the agent that wrote "
    "the fix and, earlier, by the gate design that would have caught a neutered test. A durable "
    "answer is a mutation gate over the anchoring code itself, on the same pattern as the drain "
    "gate, so that removing the producer is a thing the pipeline is required to notice."
)

CAVEATS = (
    "Six limitations. First, and the one that matters most: human_reviewer is still null. Two "
    "agent reviews found this defect only after it had been written, reviewed and committed, so "
    "the reviews are catching things slowly and the person the field exists for has not looked at "
    "any of it. Second, the anchor's signature is produced by audit.LocalSigner, which is in-"
    "process and ephemeral: a restart mints a new key, so checkpoints written by a previous "
    "process cannot be verified against the new process's ring. Nothing is functionally broken "
    "because the anchored restore compares sequence and hash and does not verify signatures - that "
    "boundary is documented - but a KMS-backed Signer is outstanding work, not a detail. Third, "
    "the re-review is not the same as a human review, and the two agent reviews disagree in "
    "coverage: one ran only a subset of the gates because two of them rewrite tracked source. "
    "Fourth, three subagent sessions across this work returned empty results with no changes made, "
    "which is recorded because it means delegation is not yet reliable enough to leave unattended "
    "- the N+1 fix was implemented directly for that reason and has a different author and a "
    "different verification route from the other eight. Fifth, unchanged and still owned "
    "elsewhere: cross-store atomicity remains WI-120 and WI-121's, WI-117 and RISK-14 are other "
    "owners', the schema-version forward problem is untouched, the write path is still not exposed "
    "over HTTP, and ApprovalRecord is still not persisted, so a restored approval retry still "
    "differs from a live one. Sixth, the adversarial review returned nothing and its four attack "
    "surfaces - empty anchor sets, cross-partition anchors, the lock under a panicking migration, "
    "and degenerate workflow shapes - were not independently covered by the second opinion."
)

EXCEPTION = (
    "integration/restart_test.go was edited outside the delegated write scope, because the "
    "required-signer design made it fail to compile and leaving it would have broken the "
    "integration build. The edit was two call sites: the sink argument and Deps.CheckpointSigner."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    "services/control-plane/audit/sink.go",
    "services/control-plane/audit/sink_checkpoint_test.go",
    "services/control-plane/audit/sink_test.go",
    "services/control-plane/bootstrap/bootstrap.go",
    "services/control-plane/bootstrap/bootstrap_test.go",
    "services/control-plane/cmd/control-plane/main.go",
    "services/control-plane/integration/audit_test.go",
    "services/control-plane/integration/harness_test.go",
    "services/control-plane/integration/destructive_guard_test.go",
    "services/control-plane/integration/restart_test.go",
    "scripts/record_ev071.py",
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
