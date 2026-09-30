package audit

import (
	"strconv"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// fixtureRing returns a ring holding one active signing key and its signer.
func fixtureRing(t *testing.T) (*KeyRing, *LocalSigner) {
	t.Helper()
	signer, err := NewLocalSigner("key-0001")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	ring := NewKeyRing()
	if err := signer.Register(ring, KeySigning); err != nil {
		t.Fatalf("Register: %v", err)
	}
	return ring, signer
}

// batchOf returns n contiguous records appended to a fresh chain.
func batchOf(t *testing.T, partition string, n int) []Record {
	t.Helper()
	c := NewChain()
	records := make([]Record, 0, n)
	for i := 0; i < n; i++ {
		r := stagedRecord("aud-"+partition+"-"+strconv.Itoa(i), partition)
		records = append(records, r)
	}
	out, err := c.Append(records)
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	return out
}

func TestASignedCheckpointVerifies(t *testing.T) {
	ring, signer := fixtureRing(t)
	records := batchOf(t, "tenant-a", 3)

	cp, err := NewCheckpoint(records, signer, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z"))
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}
	if err := cp.Verify(ring); err != nil {
		t.Fatalf("a freshly signed checkpoint must verify: %v", err)
	}
	if cp.Count != 3 || cp.FirstSequence != 1 || cp.LastSequence != 3 {
		t.Fatalf("unexpected bounds: count=%d first=%d last=%d", cp.Count, cp.FirstSequence, cp.LastSequence)
	}
	if cp.FirstHash != records[0].RecordHash || cp.LastHash != records[2].RecordHash {
		t.Fatal("checkpoint must carry the hashes at its bounds")
	}
}

func TestATamperedCheckpointFailsVerification(t *testing.T) {
	ring, signer := fixtureRing(t)
	records := batchOf(t, "tenant-a", 3)
	cp, err := NewCheckpoint(records, signer, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z"))
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}

	cp.LastSequence = 4
	if err := cp.Verify(ring); err == nil {
		t.Fatal("a checkpoint whose fields were altered must not verify")
	}
}

func TestACheckpointSignedByAnUnknownKeyIsRefused(t *testing.T) {
	ring, _ := fixtureRing(t)
	other, err := NewLocalSigner("key-9999")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	cp, err := NewCheckpoint(batchOf(t, "tenant-a", 2), other, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z"))
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}
	if err := cp.Verify(ring); err == nil {
		t.Fatal("a checkpoint signed by a key the ring does not hold must not verify")
	}
}

func TestACheckpointMustCoverAContiguousRange(t *testing.T) {
	_, signer := fixtureRing(t)
	records := batchOf(t, "tenant-a", 4)
	// Remove the middle record.
	gapped := []Record{records[0], records[2], records[3]}

	if _, err := NewCheckpoint(gapped, signer, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z")); err == nil {
		t.Fatal("a checkpoint must not be able to vouch for a range with a hole in it")
	}
}

func TestACheckpointMustCoverOnePartition(t *testing.T) {
	_, signer := fixtureRing(t)
	records := batchOf(t, "tenant-a", 2)
	other := batchOf(t, "tenant-b", 2)

	if _, err := NewCheckpoint(append(records, other...), signer, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z")); err == nil {
		t.Fatal("a checkpoint must not cover more than one partition")
	}
}

func TestAnEmptyBatchCannotBeCheckpointed(t *testing.T) {
	_, signer := fixtureRing(t)
	if _, err := NewCheckpoint(nil, signer, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z")); err == nil {
		t.Fatal("a checkpoint must cover at least one record")
	}
}

func TestAnUnsignedCheckpointIsRefused(t *testing.T) {
	ring, _ := fixtureRing(t)
	cp := Checkpoint{Partition: "tenant-a", SigningKeyID: "key-0001"}
	if err := cp.Verify(ring); err == nil {
		t.Fatal("an unsigned checkpoint must not verify")
	}
}

// AC3: rotation must keep past evidence verifiable while moving signing to a new key.
func TestRotationDemotesTheOldKeyAndKeepsItVerifying(t *testing.T) {
	ring, oldSigner := fixtureRing(t)
	oldCP, err := NewCheckpoint(batchOf(t, "tenant-a", 2), oldSigner, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z"))
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}

	newSigner, err := NewLocalSigner("key-0002")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	if _, err := ring.Rotate(newSigner, newSigner.PublicKey()); err != nil {
		t.Fatalf("Rotate: %v", err)
	}

	// The old key still verifies what it signed while it was active.
	if err := oldCP.Verify(ring); err != nil {
		t.Fatalf("rotation must not retroactively invalidate prior evidence: %v", err)
	}
	if status, _ := ring.Status("key-0001"); status != KeyVerifyOnly {
		t.Fatalf("old key status is %q, want %q", status, KeyVerifyOnly)
	}
	if status, _ := ring.Status("key-0002"); status != KeySigning {
		t.Fatalf("new key status is %q, want %q", status, KeySigning)
	}
	if got := ring.SigningKeys(); len(got) != 1 || got[0] != "key-0002" {
		t.Fatalf("exactly one key may sign; got %v", got)
	}
}

func TestRotationRefusesToReintroduceARetiredKey(t *testing.T) {
	ring, _ := fixtureRing(t)
	newSigner, err := NewLocalSigner("key-0002")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	if _, err := ring.Rotate(newSigner, newSigner.PublicKey()); err != nil {
		t.Fatalf("Rotate: %v", err)
	}
	// Rotating back to key-0001 would undo the exposure rotation was performed to remove.
	if _, err := ring.Rotate(newSigner, newSigner.PublicKey()); err == nil {
		t.Fatal("rotating to a key already in the ring must be refused")
	}
}

func TestACompromisedKeyCanNeitherSignNorVerify(t *testing.T) {
	ring, signer := fixtureRing(t)
	cp, err := NewCheckpoint(batchOf(t, "tenant-a", 2), signer, contracts.MustParseTimestamp("2026-09-28T11:00:00.000000000Z"))
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}
	if err := cp.Verify(ring); err != nil {
		t.Fatalf("checkpoint must verify before compromise: %v", err)
	}

	if err := ring.SetStatus("key-0001", KeyCompromised); err != nil {
		t.Fatalf("SetStatus: %v", err)
	}
	if err := cp.Verify(ring); err == nil {
		t.Fatal("a checkpoint signed by a compromised key must not verify")
	}
	if got := ring.SigningKeys(); len(got) != 0 {
		t.Fatalf("a compromised key must not be permitted to sign; signing keys: %v", got)
	}
}

func TestRotationOutOfACompromisedKeyInstallsItsSuccessor(t *testing.T) {
	ring, _ := fixtureRing(t)
	if err := ring.SetStatus("key-0001", KeyCompromised); err != nil {
		t.Fatalf("SetStatus: %v", err)
	}

	newSigner, err := NewLocalSigner("key-0002")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	if _, err := ring.Rotate(newSigner, newSigner.PublicKey()); err != nil {
		t.Fatalf("Rotate: %v", err)
	}
	if got := ring.SigningKeys(); len(got) != 1 || got[0] != "key-0002" {
		t.Fatalf("the successor must be the signing key; got %v", got)
	}
}

func TestRingRejectsAMalformedKey(t *testing.T) {
	ring := NewKeyRing()
	if err := ring.Add(KeyEntry{KeyID: "key-1", PublicKey: []byte{1, 2, 3}}); err == nil {
		t.Fatal("a short public key must be refused")
	}
	if err := ring.Add(KeyEntry{PublicKey: make([]byte, 32)}); err == nil {
		t.Fatal("a key with no id must be refused")
	}
	signer, err := NewLocalSigner("key-dup")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	ring2 := NewKeyRing()
	if err := signer.Register(ring2, KeySigning); err != nil {
		t.Fatalf("Register: %v", err)
	}
	if err := signer.Register(ring2, KeySigning); err == nil {
		t.Fatal("registering the same key id twice must be refused")
	}
}

func TestSignerRefusesToSignAnEmptyPayload(t *testing.T) {
	signer, err := NewLocalSigner("key-empty")
	if err != nil {
		t.Fatalf("NewLocalSigner: %v", err)
	}
	if _, err := signer.Sign(nil); err == nil {
		t.Fatal("signing an empty payload must be refused")
	}
}
