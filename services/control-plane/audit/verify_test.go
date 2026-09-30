package audit

import (
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

var checkpointTime = contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z")

// sealed builds a chain of n records in one partition plus a signed checkpoint covering
// all of them. It is the honest baseline every attack test then departs from.
func sealed(t *testing.T, n int) (*KeyRing, *LocalSigner, []Record, []Checkpoint) {
	t.Helper()
	ring, signer := fixtureRing(t)
	records := batchOf(t, "tenant-a", n)
	cp, err := NewCheckpoint(records, signer, checkpointTime)
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}
	return ring, signer, records, []Checkpoint{cp}
}

func hasKind(v Verification, kind FindingKind) bool {
	for _, f := range v.Findings {
		if f.Kind == kind {
			return true
		}
	}
	return false
}

func kinds(v Verification) []FindingKind {
	out := make([]FindingKind, 0, len(v.Findings))
	for _, f := range v.Findings {
		out = append(out, f.Kind)
	}
	return out
}

// The baseline must pass, or every attack test below would pass for the wrong reason.
func TestAnUntouchedChainVerifies(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)
	v := NewVerifier(ring).Verify(records, checkpoints)
	if !v.OK {
		t.Fatalf("an untouched chain must verify, got findings: %v", kinds(v))
	}
	if v.RecordsChecked != 5 || v.CheckpointsChecked != 1 {
		t.Fatalf("unexpected counts: records=%d checkpoints=%d", v.RecordsChecked, v.CheckpointsChecked)
	}
}

// AC5: tamper. Altering a field without recomputing the hash must be detected.
func TestTamperIsDetected(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)

	tampered := append([]Record(nil), records...)
	tampered[2].Action = "ORDER_CANCELLED"

	v := NewVerifier(ring).Verify(tampered, checkpoints)
	if v.OK {
		t.Fatal("an altered record must not verify")
	}
	if !hasKind(v, FindingTamper) {
		t.Fatalf("expected a tamper finding, got %v", kinds(v))
	}
}

// Recomputing the hash after altering a field is the sophisticated attack: it defeats a
// per-record check but cannot defeat the previous-hash link, because the successor still
// names the old hash.
func TestTamperWithARehashedRecordIsStillDetected(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)

	tampered := append([]Record(nil), records...)
	tampered[2].Action = "ORDER_CANCELLED"
	tampered[2].RecordHash = tampered[2].ComputeHash()

	v := NewVerifier(ring).Verify(tampered, checkpoints)
	if v.OK {
		t.Fatal("a re-hashed tamper must not verify")
	}
	if !hasKind(v, FindingReorder) {
		t.Fatalf("expected a reorder/breakage finding for the rehashed record, got %v", kinds(v))
	}
}

// AC5: deletion. Removing a record leaves a gap.
func TestDeletionIsDetected(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)

	deleted := append([]Record(nil), records[:2]...)
	deleted = append(deleted, records[3:]...) // drop sequence 3

	v := NewVerifier(ring).Verify(deleted, checkpoints)
	if v.OK {
		t.Fatal("a chain with a removed record must not verify")
	}
	if !hasKind(v, FindingDeletion) {
		t.Fatalf("expected a deletion finding, got %v", kinds(v))
	}
}

// Deleting every record for a checkpointed partition must also be caught, even though
// the remaining chain is internally consistent.
func TestDeletingAnEntirePartitionIsDetected(t *testing.T) {
	ring, _, _, checkpoints := sealed(t, 5)
	v := NewVerifier(ring).Verify(nil, checkpoints)
	if v.OK {
		t.Fatal("presenting no records for a signed checkpoint must not verify")
	}
	if !hasKind(v, FindingDeletion) {
		t.Fatalf("expected a deletion finding, got %v", kinds(v))
	}
}

// AC5: reorder. Presenting records out of sequence order must be detected, which is why
// the verifier never sorts its input.
func TestReorderIsDetected(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)

	reordered := append([]Record(nil), records...)
	reordered[1], reordered[3] = reordered[3], reordered[1]

	v := NewVerifier(ring).Verify(reordered, checkpoints)
	if v.OK {
		t.Fatal("records presented out of order must not verify")
	}
	if !hasKind(v, FindingReorder) {
		t.Fatalf("expected a reorder finding, got %v", kinds(v))
	}
}

// AC5: replay. Re-presenting a record that is already in the chain must be detected.
func TestReplayIsDetected(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)

	replayed := append([]Record(nil), records...)
	replayed = append(replayed, records[2]) // sequence 3 a second time

	v := NewVerifier(ring).Verify(replayed, checkpoints)
	if v.OK {
		t.Fatal("a replayed record must not verify")
	}
	if !hasKind(v, FindingReplay) {
		t.Fatalf("expected a replay finding, got %v", kinds(v))
	}
}

// AC5: signature failure. A checkpoint signed by a key the ring does not trust must not
// verify, however well-formed it is.
func TestSignatureFailureIsDetected(t *testing.T) {
	ring, _, records, _ := sealed(t, 5)

	attacker, err := NewLocalSigner("key-attacker")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	cp, err := NewCheckpoint(records, attacker, checkpointTime)
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}

	v := NewVerifier(ring).Verify(records, []Checkpoint{cp})
	if v.OK {
		t.Fatal("a checkpoint signed by an untrusted key must not verify")
	}
	if !hasKind(v, FindingSignature) {
		t.Fatalf("expected a signature finding, got %v", kinds(v))
	}
}

// AC5 / restore. docs/22 section 7 requires verifying chain continuity from the last
// signed checkpoint after a restore. A record that follows a checkpoint but does not
// resume from its LastHash means the restore lost or reordered evidence.
func TestAChainThatDoesNotResumeFromItsCheckpointIsDetected(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 3)

	// Build a second batch whose first record does not link to the signed LastHash, as a
	// restore that resumed from the wrong point would produce.
	second := batchOf(t, "tenant-b", 2)
	second[0].Partition = "tenant-a"
	second[0].Sequence = 4
	second[0].PreviousHash = Hash{0xDE} // not the checkpoint's LastHash
	second[0].RecordHash = second[0].ComputeHash()
	second[1].Partition = "tenant-a"
	second[1].Sequence = 5
	second[1].PreviousHash = second[0].RecordHash
	second[1].RecordHash = second[1].ComputeHash()

	presented := append(append([]Record(nil), records...), second...)
	v := NewVerifier(ring).Verify(presented, checkpoints)
	if v.OK {
		t.Fatal("a chain that does not resume from its checkpoint must not verify")
	}
	if !hasKind(v, FindingReorder) {
		t.Fatalf("expected a continuity finding, got %v", kinds(v))
	}
}

// A checkpoint whose covered range is not fully presented must be reported, not skipped.
func TestACheckpointOverAMissingRangeIsDetected(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)
	v := NewVerifier(ring).Verify(records[:2], checkpoints)
	if v.OK {
		t.Fatal("a partially presented checkpointed range must not verify")
	}
	if !hasKind(v, FindingCheckpoint) {
		t.Fatalf("expected a checkpoint finding, got %v", kinds(v))
	}
}

// A checkpoint that miscounts the records it covers must be reported, not skipped.
func TestACheckpointWithAWrongCountIsDetected(t *testing.T) {
	ring, signer, records, _ := sealed(t, 5)
	cp, err := NewCheckpoint(records, signer, checkpointTime)
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}
	// Altering the count invalidates the signature as well as the count, so both are
	// reported; the count finding is the one that names the data problem.
	cp.Count = 4

	v := NewVerifier(ring).Verify(records, []Checkpoint{cp})
	if v.OK {
		t.Fatal("a miscounting checkpoint must not verify")
	}
	if !hasKind(v, FindingCheckpoint) {
		t.Fatalf("expected a checkpoint finding, got %v", kinds(v))
	}
}

// Empty input is vacuously consistent: there is no evidence to be inconsistent with, so
// OK is true. What matters is that RecordsChecked is zero, so a caller that expected
// evidence can see that nothing was actually checked rather than being handed a bare OK.
//
// The dangerous wipe case is not this one. It is a chain emptied while its signed
// checkpoints survive in the independent copy, which is what
// TestDeletingAnEntirePartitionIsDetected covers.
func TestEmptyEvidenceReportsNothingChecked(t *testing.T) {
	ring, _, _, _ := sealed(t, 1)
	v := NewVerifier(ring).Verify(nil, nil)
	if v.RecordsChecked != 0 || v.CheckpointsChecked != 0 {
		t.Fatalf("expected nothing checked, got records=%d checkpoints=%d", v.RecordsChecked, v.CheckpointsChecked)
	}
	if !v.OK {
		t.Fatalf("empty input is vacuously consistent, got findings: %v", kinds(v))
	}
}

func TestEveryFindingIsSev1(t *testing.T) {
	ring, _, records, checkpoints := sealed(t, 5)
	broken := append([]Record(nil), records...)
	broken[1].Action = "TAMPERED"

	v := NewVerifier(ring).Verify(broken, checkpoints)
	if len(v.Findings) == 0 {
		t.Fatal("expected findings")
	}
	for _, f := range v.Findings {
		if f.Severity() != "SEV-1" {
			t.Fatalf("finding %s has severity %s, want SEV-1", f.Kind, f.Severity())
		}
	}
}
