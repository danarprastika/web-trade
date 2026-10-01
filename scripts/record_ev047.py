"""One-off: append EV-047 recording Chain.Restore and the two tests that passed for the wrong reason.

The rehydration blocker had been carried as a limitation for several work items without anyone
checking whether the missing piece was an algorithm or just a method. It was just a method. The
interesting part of this record is not the method: it is that the first version of the test suite
was green, passed every gate, and still failed to detect two of the eight guarantees it appeared
to be pinning.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-047"
STAMP = "2026-09-30T12:41:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The audit chain can now be rebuilt from durable storage: Chain.Restore reconstructs a "
    "chain from stored records, verifies integrity and linkage as it goes, and refuses a "
    "tampered, truncated, reordered or relinked archive rather than loading it. The "
    "rehydration blocker is narrowed, not closed - there is still no reader that loads records "
    "out of PostgreSQL to feed it, so the gap that is actually load-bearing is one thin mapping "
    "layer rather than a missing capability. Separately and more usefully: the first version of "
    "this test suite was green, passed all thirteen gates, and detected only six of the eight "
    "guarantees it appeared to be pinning."
)

METHOD = (
    "Stopped treating 'no restore path exists' as a property of the design and searched the audit "
    "package for one. The search found that detection and restoration had been conflated: "
    "verify.go exposes FindingRestore and Verify(records, checkpoints), which detects a chain that "
    "does not resume from its checkpoint, but it takes records and checkpoints as arguments and is "
    "read-only, so it can tell a reader that an archive is broken and cannot make one chain live "
    "again. A grep for non-test restore, resume, rehydrate, seek and load paths returned nothing, "
    "which established that the gap was real and, more usefully, that it was a method rather than an "
    "algorithm. Implemented Chain.Restore on the model Append already uses: stage every record into "
    "throwaway maps, refusing on any violation, and commit to the chain only after the whole batch "
    "passes, so a refused restore leaves nothing behind. Then treated the passing tests as claims "
    "rather than results and wrote a mutation harness alongside them, replacing each of the eight "
    "guarantees with a version that does not hold and checking whether the suite noticed."
)

RESULT = (
    "All 15 restore tests pass, the package passes under -race, go vet and gofmt are clean, and all "
    "13 project gates pass. The mutation harness detected 6 of 8 mutations on its first run. The "
    "two survivors were the interesting result. M3 removes the sequence-contiguity check and M8 "
    "removes the duplicate-audit_id check, and in both cases the suite stayed green - not because "
    "the guarantees are vacuous but because the tests I wrote to pin them were tripping a different "
    "check first. The gap test deleted a record from a real archive, which leaves the survivor's "
    "previous-hash pointing at a hash no earlier record in the batch produces, so the link check "
    "fired and the test passed for a reason unrelated to the check under test. The duplicate test "
    "submitted the same record twice, which fails the sequence check because the copy's sequence is "
    "1 where 2 is required, so again the wrong check caught it. Both tests were real assertions "
    "about the right behaviour and neither would have caught the deletion of the guarantee it was "
    "written for. Two replacement tests were added that isolate each check: one deletes a record "
    "and then relinks the survivor, so the hash chain is completely intact and only the sequence "
    "check can refuse, and one submits a well-formed record that reuses an audit_id already in the "
    "archive, with correct sequence and correct linkage, so only the identity check can refuse. "
    "With those in place the harness reports 8 of 8 detected and restore.go restored "
    "byte-for-byte between runs. The property that matters operationally is that a restored chain "
    "continues the same history: the next append receives sequence 4 after three stored records, "
    "links to the third stored record's hash, and the extended chain verifies clean, so "
    "rehydration is now possible rather than merely detectable."
)

DEFECT_FOUND_AND_FIXED = (
    "The defect is in how the tests were built, and it is the same shape as the one in EV-046: a "
    "result that was propagated instead of tested. Here it took the form of tests that were "
    "written to describe a scenario and not to pin a check. Building a gap by deleting a record "
    "from a genuine chain produces a fixture that violates two invariants at once, so any suite "
    "containing that fixture is satisfied by either check alone and the two checks become "
    "indistinguishable to it. The tests read as independent coverage of contiguity and of linkage, "
    "and were in fact a single check seen twice. The general form is that a test suite whose "
    "fixtures are derived from realistic corruption is at risk of having its checks co-satisfied, "
    "because realistic corruption tends to violate several invariants at the same time. The fix is "
    "to construct each fixture so that exactly one invariant is violated and every other one holds, "
    "which means deliberately repairing the collateral damage - relinking a survivor, correcting a "
    "sequence - so the test is aimed at one thing. This is only discoverable by mutation testing, "
    "because the tests are green either way; nothing about running them reveals that two of them "
    "would continue to pass if the code they were written against were deleted."
)

SIGNIFICANCE = (
    "Two things worth carrying forward. The first is that the rehydration gap was smaller than it "
    "had been described, and that matters for planning rather than for history: three work items "
    "recorded 'cannot rehydrate after restart' as a limitation, and the accurate statement is that "
    "the chain lacked one method and the storage layer already had the queries to supply it. "
    "Naming a gap accurately determines whether it is scheduled as work or accepted as a limit, "
    "and a limit that is actually half a mapping layer will otherwise be accepted indefinitely. The "
    "second is the co-satisfaction result, which is the reason this record leads with the failures "
    "rather than the passes. Eight mutations, six detected, and a fully green suite that passed "
    "every gate in the repository is a stronger demonstration of the gap's subtlety than eight of "
    "eight would have been: it shows that the two survivors were not an oversight in the "
    "implementation but a property of realistic fixtures, and that property will recur in every "
    "suite that tests corruption of a linked structure unless the fixtures are aimed."
)

CAVEATS = (
    "Four limitations, and the first is the one that governs the status. The blocker is NARROWED, "
    "not closed. Chain.Restore can rebuild a chain from records, and the SQL layer already exposes "
    "ListAuditRecordsInPartitionRange ordered by sequence plus GetLatestAuditCheckpoint, so the "
    "reader that connects the two is a port definition and a row mapping rather than new "
    "infrastructure. But no such reader exists: the audit Sink remains write-only by design, no "
    "ChainReader port has been declared, and no composition root calls Restore. Until that exists, "
    "a process that restarts still begins with an empty chain. Second, nothing here has touched a "
    "database. As EV-046 records, no Go process has connected to PostgreSQL and called SQLSink, and "
    "that remains true; Restore is verified against in-memory fixtures and the SQL statements it "
    "would depend on are covered separately by the 20 database assertions in db-0002-audit, so the "
    "gap is the Go mapping layer rather than the schema. Third, the restore accepts records and does "
    "not verify checkpoints; a caller that has a checkpoint available should still pass it to "
    "Verify, because Restore's own linkage check proves internal consistency and not that the chain "
    "reaches a signed closure. That is a deliberate separation and worth stating rather than leaving "
    "implicit. Fourth, scope was held to the chain. The model journal's own rehydration is now "
    "possible but not implemented, the identity store still has no read side, and audit acceptance "
    "still does not share a transaction with the registry write, so none of the other three blockers "
    "moved. Also unchanged: no specification file was modified, docs/ remains clean, the mutation "
    "harness was run as a verification activity and its scratch script and backup were deleted, "
    "nothing was staged, and nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/audit/restore.go",
    "services/control-plane/audit/restore_test.go",
    "services/control-plane/audit/verify.go",
    "services/control-plane/db/queries/audit.sql",
    "scripts/record_ev047.py",
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
