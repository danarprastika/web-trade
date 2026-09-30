"""One-off: append EV-027 and close WI-117.

Follows the same pattern as scripts/record_ev026.py: idempotent, auditable, and kept in
the repository so the Project Brain edit is reproducible rather than an opaque mutation.

It writes JSON without a BOM on purpose. PowerShell 5.1 `Set-Content -Encoding UTF8` adds
one, and a BOM at the start of a JSONL line corrupts the record it introduces.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-027"
STAMP = "2026-09-28T18:45:00Z"

CLAIM = (
    "The tamper-evident audit chain is implemented in services/control-plane/audit as a Go "
    "domain package, and the same append-only, chain-linkage, and checkpoint-agreement "
    "properties are enforced independently by db/migrations/0002_audit.sql. Tamper, deletion, "
    "reorder, replay, and signature failure are each detected by name, and the detection is "
    "proved non-vacuous by deliberately breaking the verifier and observing which tests fail."
)

METHOD = (
    "Read docs/22 sections 2 through 4 and 7 for the record schema, the hash-chain and "
    "checkpoint rules, the retention and deletion policy, and the required acceptance tests, "
    "and ADR-022 for the decision to use signed hash-chain checkpoints plus independent "
    "immutable retention rather than a public blockchain. Implemented the Go package across "
    "record and canonical serialization, the per-partition chain, the key ring and rotation, "
    "signed checkpoints, the verifier, the evidence guard, and the retention and deletion "
    "policy. Wrote six test files covering the canonical form, the chain, checkpoints and key "
    "rotation, the verifier's detection of each attack class, the guard and deletion policy, "
    "and a migration contract test that keeps the Go and SQL closed sets in agreement. Then "
    "deliberately disabled the verifier's previous-hash check and its sequence-gap check in "
    "turn, and confirmed the matching tests failed and no others, proving the attack tests are "
    "not passing vacuously. Finally wrote the PostgreSQL migration and 20 database assertions, "
    "ran them against a real postgres:17-alpine container, and ran the full repository gate."
)

RESULT = (
    "Audit package: 90.5% statement coverage, go test -race -count=1 clean, go vet clean, "
    "gofmt clean. Database: ALL 20 AUDIT DATABASE ASSERTIONS PASSED against PostgreSQL 17.11 on "
    "x86_64-pc-linux-musl, and the ledger migration still passes its 18 assertions unchanged; "
    "both migrations apply in order against an empty database. Full repository gate: all four Go "
    "modules pass under -race; gofmt and go vet clean; toolchain gate 14/14 PASS; spec gate 7/7 "
    "mechanical with G0.8 REQUIRES_HUMAN_ATTESTATION and an overall PENDING_HUMAN_ATTESTATION "
    "verdict as expected; project brain PASS; 100 tests/ci tests and 35 workers/research tests "
    "pass; ledger coverage unchanged at 86.9%; git status --porcelain -- docs is clean. AC1 "
    "(append-only hash chain with signed checkpoints): TestCanonicalJSONIsPinnedToExactBytes "
    "pins the hashed payload to exact bytes so a change to field order is a test failure rather "
    "than a silent re-hashing of the chain, TestEveryFieldAffectsTheHash proves all 21 record "
    "fields are covered by the hash, TestSequenceIsMonotonicWithinAPartition and "
    "TestPreviousHashLinksToThePrecedingRecord prove ordering and linkage, and "
    "TestASignedCheckpointVerifies proves a signed batch closes and verifies. The canonical "
    "schema version is inside the hashed payload, so a record written under a different version "
    "cannot be re-encoded into a matching hash. AC2 (independent immutable retention and "
    "integrity verifier): TestDeletionIsRefusedWithoutEveryPrecondition checks retention expiry, "
    "legal-hold clearance, and two named distinct people independently, and "
    "TestAnApprovedDeletionProducesARetainedEvent proves the deletion itself leaves a retained "
    "identified record that a retry does not duplicate. AC3 (key rotation): "
    "TestRotationDemotesTheOldKeyAndKeepsItVerifying proves rotation moves signing to a new key "
    "while everything the old key signed still verifies, TestRotationRefusesToReintroduceARetiredKey "
    "proves a retired key cannot be quietly reactivated, and "
    "TestACompromisedKeyCanNeitherSignNorVerify proves a compromised key stops vouching for "
    "anything. AC4 (bounded durable buffering, never silently drop): "
    "TestSensitiveOperationsAreBlockedWhenTheBacklogIsFull proves the backlog is bounded and that "
    "overflow blocks rather than discards, TestGuardLatchRequiresAnExplicitClear proves draining "
    "the backlog does not silently reopen the platform, and the Guard has no drop, truncate, or "
    "overwrite-oldest method at all. AC5 (tamper, deletion, reorder, replay, restore detection): "
    "one named test per class, plus TestTamperWithARehashedRecordIsStillDetected for the "
    "sophisticated attack that recomputes the hash, plus "
    "TestDeletingAnEntirePartitionIsDetected for a chain emptied while its checkpoints survive, "
    "plus TestAChainThatDoesNotResumeFromItsCheckpointIsDetected for the restore case docs/22 "
    "section 7 requires. Every finding is SEV-1 and a SEV-1 failure halts risk-increasing and "
    "privileged work even when the evidence backlog is empty."
)

DEFECT = (
    "One Go design defect, one verifier parse defect in the test, and three migration or "
    "fixture defects, all found by executing rather than by reading. (1) Record.Validate "
    "rejected any sequence below 1 while Chain.Append is the thing that assigns the sequence, "
    "so every first append was refused as invalid. Validation was split so the sequence is "
    "checked on the record as written, after the chain has placed it, and the pre-chain check "
    "covers every other field. (2) The duplicate-delivery check first compared a candidate's "
    "hash against a stored record's, but a genuine redelivery does not restate its chain-assigned "
    "sequence or previous hash, so every retry looked like a conflict and the idempotency "
    "docs/22 section 7 requires was impossible. The candidate is now normalised to the position "
    "its identity was actually written at before comparison. (3) KeyRing.Rotate refused to rotate "
    "when no key was currently permitted to sign, which is exactly the state a platform is in "
    "immediately after marking its active key compromised; the operation rotation exists to "
    "perform was the one it refused. (4) The checkpoint coverage trigger derived its boundary "
    "hashes with min() and an array_agg over bytea, which orders by byte value rather than by "
    "sequence, so it read the wrong record's hash and refused a perfectly valid checkpoint; the "
    "boundary hashes are now looked up at their exact sequences. (5) Two audit assertions were "
    "passing for the wrong reason: the checkpoint fixtures used decode('sig','hex'), which is not "
    "valid hex, so every checkpoint insert failed at the signature column before reaching the "
    "coverage guard it was meant to be testing. A third fixture was mislabelled: it was intended "
    "to be an overlapping checkpoint but, because the preceding invalid one had been refused, it "
    "was in fact the first checkpoint of its range and was correctly accepted. Separately, two "
    "faults were injected into the Go verifier on purpose: disabling the previous-hash check made "
    "exactly TestTamperWithARehashedRecordIsStillDetected and "
    "TestAChainThatDoesNotResumeFromItsCheckpointIsDetected fail, and disabling the sequence-gap "
    "check made exactly TestDeletionIsDetected fail, so each detection is independently covered."
)

SIGNIFICANCE = (
    "The chain assigns the sequence and the previous hash itself and verifies any caller-stated "
    "sequence against the partition's state, so an out-of-order or re-parented record cannot be "
    "written at all rather than being detectable afterwards. The verifier is deliberately given "
    "data rather than a Chain and never sorts its input, because sorting first would make "
    "reordering invisible by construction; that is why reorder detection works at all. Every field "
    "is present in the canonical form even when empty, so a record that says nothing about a field "
    "cannot hash identically to one that was never asked. The hash, not the database, is the "
    "evidence: the verifier reaches its own conclusion from records and checkpoints alone, which "
    "is what makes a rewritten-from-the-top chain detectable through a signed checkpoint. The "
    "Guard is latched and has no drop method, so there is no code path by which evidence "
    "disappears without a decision by someone; and a SEV-1 integrity failure routes through the "
    "same guard as a full evidence backlog, so there is one fail-closed path rather than two that "
    "could disagree about whether the platform may trade. Key rotation demotes rather than "
    "removes, because evidence signed by a retired key is still evidence."
)

CAVEATS = (
    "The store is in-memory and the chain is not yet wired into the control plane, so durability, "
    "transactional write-alongside-mutation, and restart recovery are proven only by the "
    "migration, not by Go. The cross-region immutable WORM export that docs/22 section 4 requires "
    "is not implemented: the Guard models the bounded backlog and the fail-closed blocking, and "
    "the KeyRing holds Ed25519 keys in process, but the actual KMS or HSM signer, the object-lock "
    "retention bucket, and the separate-account exporter do not exist and cannot be exercised "
    "here. LocalSigner is explicitly a test double for the KMS, named so it is not mistaken for the "
    "production path. The verifier is exercised against in-memory records and a hand-built key "
    "ring, not against a KMS-backed signature, so the signature check proves the mechanism and not "
    "the integration. Coverage is 90.5%; the uncovered statements are not individually "
    "identified. The migration contract test reads the SQL as text rather than executing both "
    "sides against one database, which is weaker than the real-database assertions that accompany "
    "it. scripts/verify_ledger_db.py was generalised to take a migration and verification path so "
    "the audit pair could use it; its default behaviour and the ledger's 18 assertions are "
    "unchanged and were re-run after the change, and the container port binding was tightened to "
    "loopback in the same edit. I also found that the script's version banner intermittently "
    "printed 'unknown version' although the assertions themselves were unaffected; this is a "
    "cosmetic reporting race in parsing psql's output and is not fixed. No live venue "
    "connectivity, production credentials, or Terraform was involved, and G0.8 human attestation "
    "remains outstanding. No commit has been made."
)

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-117",
    "claim": CLAIM,
    "status": "RESOLVED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECT,
    "significance": SIGNIFICANCE,
    "caveats": CAVEATS,
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-117-COMPLETED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-117",
    "event": "work_item_completed",
    "status": "COMPLETED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "WI-117 Tamper-evident audit chain completed. Go audit package at 90.5% coverage; 20 of 20 "
        "audit database assertions pass against real PostgreSQL 17.11 and the ledger's 18 still pass; "
        "full repository gate green with the spec gate mechanically complete and G0.8 outstanding. "
        "Verifier detection proven non-vacuous by deliberate fault injection. The cross-region WORM "
        "export and the KMS-backed signer remain unimplemented and are disclosed in the caveats."
    ),
}


def append_jsonl(path: Path, obj: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, ensure_ascii=True) + "\n")


def main() -> int:
    evidence_path = BRAIN / "evidence.jsonl"
    existing = [
        json.loads(line)
        for line in io.open(evidence_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(r.get("evidence_id") == EVIDENCE_ID for r in existing):
        print(f"{EVIDENCE_ID} already recorded; nothing appended.")
    else:
        append_jsonl(evidence_path, RECORD)
        print(f"appended {EVIDENCE_ID} to {evidence_path.name}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] == "WI-117":
            # evidence_ref is a list: the gate iterates it, so a bare string would be
            # read one character at a time as several unknown evidence ids.
            if item.get("status") != "COMPLETED" or item.get("evidence_ref") != [EVIDENCE_ID]:
                item["status"] = "COMPLETED"
                item["evidence_ref"] = [EVIDENCE_ID]
                item["completed_at"] = STAMP
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print("WI-117 -> COMPLETED")
    else:
        print("WI-117 already COMPLETED")

    events_path = BRAIN / "events.jsonl"
    seen = [
        json.loads(line)
        for line in io.open(events_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(e.get("event_id") == EVENT["event_id"] for e in seen):
        print(f"{EVENT['event_id']} already recorded; nothing appended.")
    else:
        append_jsonl(events_path, EVENT)
        print(f"appended {EVENT['event_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
