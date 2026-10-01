package audit

import (
	"context"
	"errors"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// The tests in this file exist because of a gap no other test could see.
//
// The truncation fix added a consumer for audit_checkpoints: Rehydrate reads each partition's
// latest signed checkpoint and refuses to load an archive whose head falls behind it. But
// nothing wrote that table. Every test of the fix inserted its own checkpoint by hand, so
// against a real database GetLatestAuditCheckpoint returned sql.ErrNoRows, the anchors map was
// empty, and Rehydrate took exactly the unanchored path the fix was about - a truncated audit
// archive still restored as VERIFIED.
//
// So none of these tests insert a checkpoint. They drive the sink and then read back what it
// wrote, which is the only way to see whether a producer exists at all.

// exportedBatch returns n accepted records for one partition, appended through the chain so the
// sequences and hashes are the ones a real export would carry.
func exportedBatch(t *testing.T, partition string, n int) []Record {
	t.Helper()
	return appendTo(t, NewChain(), partition, 0, n)
}

// appendTo appends n further records to c in partition, starting from the sequence the chain
// currently ends at. Sharing one chain across two exports is what lets a test observe that the
// second anchor advances rather than restating the first.
func appendTo(t *testing.T, c *Chain, partition string, first, n int) []Record {
	t.Helper()
	staged := make([]Record, 0, n)
	for i := first; i < first+n; i++ {
		staged = append(staged, stagedRecord("aud-"+partition+"-"+strconv.Itoa(i), partition))
	}
	accepted, err := c.Append(staged)
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	return accepted
}

// assertVerifiable re-derives the stored checkpoint and checks its signature.
//
// checkpointFrom is the exact inverse of the mapping the sink uses, so going through it proves
// every column arrived. Verifying afterwards is what makes "signed" mean something rather than
// "a non-empty bytea was written": a checkpoint nobody can verify is not an anchor.
func assertVerifiable(t *testing.T, ring *KeyRing, cp dbgen.AppendAuditCheckpointParams) Checkpoint {
	t.Helper()
	got, err := checkpointFrom(dbgen.AuditCheckpoint{
		Partition:     cp.Partition,
		FirstSequence: cp.FirstSequence,
		LastSequence:  cp.LastSequence,
		FirstHash:     cp.FirstHash,
		LastHash:      cp.LastHash,
		RecordCount:   cp.RecordCount,
		CreatedAtUtc:  cp.CreatedAtUtc,
		SigningKeyID:  cp.SigningKeyID,
		Signature:     cp.Signature,
		SchemaVersion: cp.SchemaVersion,
	})
	if err != nil {
		t.Fatalf("the stored checkpoint cannot be re-derived: %v", err)
	}
	if got.SigningKeyID != "key-0001" {
		t.Errorf("checkpoint names signing key %q, want key-0001", got.SigningKeyID)
	}
	if err := got.Verify(ring); err != nil {
		t.Fatalf("the checkpoint the sink stored does not verify against its own key: %v", err)
	}
	return got
}

// The core of the gap: the sink must produce the anchor its records need.
//
// The assertions are about the boundary matching the records that were actually written, not
// merely about a call having happened. A checkpoint over the wrong range is worse than none:
// restore compares the head against it, so an anchor naming a sequence nothing reaches refuses
// an intact archive, and one naming a shorter range leaves the deleted tail undetectable while
// looking like a working fix.
func TestTheSinkWritesACheckpointCoveringTheRecordsItJustStored(t *testing.T) {
	ring, signer := fixtureRing(t)
	q := &recordingQuerier{}
	sink, err := NewSQLSinkInTx(q, testAnchor(t, signer))
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}

	accepted := exportedBatch(t, "tenant-a", 3)
	if err := sink.Export(context.Background(), accepted); err != nil {
		t.Fatalf("Export: %v", err)
	}

	if len(q.calls) != len(accepted) {
		t.Fatalf("stored %d record(s), want %d", len(q.calls), len(accepted))
	}

	// Once per export, not once per record: an anchor closes a range, and a row per record
	// would be three rows saying the same thing with only the last one carrying any weight.
	if len(q.checkpoints) != 1 {
		t.Fatalf("wrote %d checkpoint(s) for %d record(s) in one partition, want exactly 1: %v",
			len(q.checkpoints), len(accepted), partitionsOf(q.checkpoints))
	}

	cp := q.checkpointFor(t, "tenant-a")
	head := accepted[len(accepted)-1]
	if cp.LastSequence != head.Sequence {
		t.Errorf("checkpoint last_sequence = %d, want %d (the last record actually written)",
			cp.LastSequence, head.Sequence)
	}
	if got := hashOf(t, cp.LastHash); got != head.RecordHash {
		t.Errorf("checkpoint last_hash = %s, want %s (the hash of the record at that sequence); "+
			"restore compares exactly this pair", got, head.RecordHash)
	}
	if cp.FirstSequence != accepted[0].Sequence {
		t.Errorf("checkpoint first_sequence = %d, want %d", cp.FirstSequence, accepted[0].Sequence)
	}
	if got := hashOf(t, cp.FirstHash); got != accepted[0].RecordHash {
		t.Errorf("checkpoint first_hash = %s, want %s", got, accepted[0].RecordHash)
	}
	if cp.RecordCount != int32(len(accepted)) {
		t.Errorf("checkpoint record_count = %d, want %d; the database's deferred coverage "+
			"check refuses a checkpoint whose count disagrees with the rows it covers",
			cp.RecordCount, len(accepted))
	}
	if cp.SchemaVersion != int32(CheckpointSchemaVersion) {
		t.Errorf("checkpoint schema_version = %d, want %d; a row written under another "+
			"version cannot be re-derived by a reader", cp.SchemaVersion, CheckpointSchemaVersion)
	}
	assertVerifiable(t, ring, cp)
}

// A batch is not confined to one partition - the journal derives the partition from the model's
// owner, so a single export routinely spans several - and a checkpoint covers exactly one
// partition's range. So the sink groups by partition and emits one anchor per partition.
//
// Grouping by partition rather than checkpointing the batch as a whole is forced by
// NewCheckpoint, which refuses a batch spanning two partitions. Emitting one per partition
// rather than one per record is the same rule for the same reason: an anchor names a range.
func TestTheSinkCheckpointsEveryPartitionOfAMultiPartitionExport(t *testing.T) {
	ring, signer := fixtureRing(t)
	q := &recordingQuerier{}
	sink, err := NewSQLSinkInTx(q, testAnchor(t, signer))
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}

	chain := NewChain()
	var batch []Record
	batch = append(batch, appendTo(t, chain, "tenant-a", 0, 2)...)
	batch = append(batch, appendTo(t, chain, "tenant-b", 0, 3)...)
	batch = append(batch, appendTo(t, chain, "tenant-c", 0, 1)...)
	if err := sink.Export(context.Background(), batch); err != nil {
		t.Fatalf("Export: %v", err)
	}

	if len(q.checkpoints) != 3 {
		t.Fatalf("wrote %d checkpoint(s) for 3 partitions in one export, want 3: %v",
			len(q.checkpoints), partitionsOf(q.checkpoints))
	}

	// Each anchor must describe its own partition's range, and must be anchored at the head of
	// the records that partition contributed - not at the head of the batch.
	wants := map[string]int64{"tenant-a": 2, "tenant-b": 3, "tenant-c": 1}
	seen := make([]string, 0, 3)
	for _, cp := range q.checkpoints {
		seen = append(seen, cp.Partition)
		want, known := wants[cp.Partition]
		if !known {
			t.Fatalf("a checkpoint was written for partition %q, which this export never "+
				"touched", cp.Partition)
		}
		if cp.FirstSequence != 1 || cp.LastSequence != want {
			t.Errorf("partition %s anchored at %d..%d, want 1..%d",
				cp.Partition, cp.FirstSequence, cp.LastSequence, want)
		}
		if cp.RecordCount != int32(want) {
			t.Errorf("partition %s covers %d record(s), want %d",
				cp.Partition, cp.RecordCount, want)
		}
		var head Record
		for _, r := range batch {
			if r.Partition == cp.Partition && r.Sequence == cp.LastSequence {
				head = r
			}
		}
		if got := hashOf(t, cp.LastHash); got != head.RecordHash {
			t.Errorf("partition %s anchored at hash %s, want %s (its own last record)",
				cp.Partition, got, head.RecordHash)
		}
		assertVerifiable(t, ring, cp)
	}
	// Sorted, so a failing batch always names the same partition rather than whichever the
	// map iteration happened to yield.
	sorted := append([]string(nil), seen...)
	for i := 1; i < len(sorted); i++ {
		if sorted[i-1] > sorted[i] {
			t.Fatalf("checkpoints were written out of partition order: %v", sorted)
		}
	}
}

// A second export of the same partition must advance the anchor to the records it just added.
//
// GetLatestAuditCheckpoint orders by last_sequence DESC, so what matters is that the newest row
// describes how far the partition actually went. A sink that re-stamped the old boundary would
// leave the newest records unanchored, which is the same hole as no producer at all - the
// restore would compare the head against a checkpoint from before those records existed.
func TestASecondExportAdvancesThePartitionAnchor(t *testing.T) {
	_, signer := fixtureRing(t)
	q := &recordingQuerier{}
	sink, err := NewSQLSinkInTx(q, testAnchor(t, signer))
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}

	chain := NewChain()
	first := appendTo(t, chain, "tenant-a", 0, 3)
	if err := sink.Export(context.Background(), first); err != nil {
		t.Fatalf("Export first batch: %v", err)
	}
	second := appendTo(t, chain, "tenant-a", 3, 2)
	if err := sink.Export(context.Background(), second); err != nil {
		t.Fatalf("Export second batch: %v", err)
	}

	if len(q.checkpoints) != 2 {
		t.Fatalf("two exports wrote %d checkpoint(s), want 2 (one per export, not one per record "+
			"and not one per partition ever seen)", len(q.checkpoints))
	}
	latest := q.checkpoints[1]
	if latest.FirstSequence != 4 || latest.LastSequence != 5 {
		t.Fatalf("the second anchor covers %d..%d, want 4..5; an anchor that restates an older "+
			"boundary leaves the newest records unvouched for",
			latest.FirstSequence, latest.LastSequence)
	}
	if latest.RecordCount != int32(len(second)) {
		t.Errorf("the second anchor covers %d record(s), want %d", latest.RecordCount, len(second))
	}
	if got := hashOf(t, latest.LastHash); got != second[len(second)-1].RecordHash {
		t.Errorf("the second anchor ends at hash %s, want %s", got, second[len(second)-1].RecordHash)
	}
}

// Records committed without their anchor is the state this whole change exists to eliminate,
// so a checkpoint that cannot be written must fail the export rather than be swallowed. The
// records in the same transaction go with it; against PostgreSQL that is the rollback this
// path returns into.
func TestACheckpointThatCannotBeWrittenFailsTheWholeExport(t *testing.T) {
	_, signer := fixtureRing(t)
	q := &recordingQuerier{checkpointErr: errors.New("audit_checkpoints refused the write")}
	sink, err := NewSQLSinkInTx(q, testAnchor(t, signer))
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}

	err = sink.Export(context.Background(), exportedBatch(t, "tenant-a", 3))
	if err == nil {
		t.Fatal("an export whose checkpoint could not be written reported success; the records " +
			"would be durable and unanchored, and a truncated archive would restore as verified")
	}
	if !strings.Contains(err.Error(), "checkpoint") {
		t.Fatalf("the refusal must name what failed, got: %v", err)
	}
	if !strings.Contains(err.Error(), "tenant-a") {
		t.Fatalf("the refusal must name the partition it was anchoring, got: %v", err)
	}
}

// One checkpoint per partition means a batch spanning several has several chances to fail
// part-way. The first refusal has to stop the batch there rather than leave some partitions
// anchored and the rest not.
func TestAFailedAnchorStopsTheRestOfTheBatch(t *testing.T) {
	_, signer := fixtureRing(t)
	// Sorted order is tenant-a, tenant-b, tenant-c, so the second write is the failure.
	q := &recordingQuerier{checkpointFailAt: 2}
	sink, err := NewSQLSinkInTx(q, testAnchor(t, signer))
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}

	chain := NewChain()
	var batch []Record
	batch = append(batch, appendTo(t, chain, "tenant-a", 0, 1)...)
	batch = append(batch, appendTo(t, chain, "tenant-b", 0, 1)...)
	batch = append(batch, appendTo(t, chain, "tenant-c", 0, 1)...)

	if err := sink.Export(context.Background(), batch); err == nil {
		t.Fatal("a batch whose second anchor failed must not report success")
	}
	if len(q.checkpoints) != 2 {
		t.Fatalf("the sink attempted %d anchor write(s) after the failure, want 2; it continued "+
			"past a partition whose evidence would have been left unanchored", len(q.checkpoints))
	}
}

// A batch the signer cannot vouch for is refused before a single record is written. The
// contiguity check in NewCheckpoint is what catches this, and the ordering matters: refusing
// after the inserts would depend entirely on the rollback to undo them.
func TestABatchThatCannotBeAnchoredIsRefusedBeforeAnyRecordIsStored(t *testing.T) {
	_, signer := fixtureRing(t)
	q := &recordingQuerier{}
	sink, err := NewSQLSinkInTx(q, testAnchor(t, signer))
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}

	accepted := exportedBatch(t, "tenant-a", 3)
	// The middle record is missing, so the range 1..3 is not contiguous. A checkpoint that
	// vouched for it would claim to have seen a hole.
	withHole := []Record{accepted[0], accepted[2]}

	err = sink.Export(context.Background(), withHole)
	if err == nil {
		t.Fatal("a batch with a hole in it must be refused rather than anchored")
	}
	if len(q.calls) != 0 {
		t.Fatalf("%d record(s) were stored before the refusal; the anchor is decided before "+
			"anything is written", len(q.calls))
	}
}

// No signer, no sink. The requirement is enforced at construction rather than at export,
// because a sink that exists and cannot anchor is a sink whose every export quietly produces
// the unanchored archive this refuses - and it would look healthy doing it.
func TestTheSinkRefusesToBeBuiltWithoutASigner(t *testing.T) {
	_, signer := fixtureRing(t)
	q := &recordingQuerier{}

	if _, err := NewSQLSinkInTx(q, nil); err == nil {
		t.Fatal("a sink with no anchor must be refused at construction; an export with no " +
			"signer would commit records nothing says how far they reach")
	}

	if _, err := NewAnchor(nil, time.Now); err == nil {
		t.Fatal("an anchor with no signer must be refused")
	}
	if _, err := NewAnchor(signer, nil); err == nil {
		t.Fatal("an anchor with no clock must be refused; created_at is part of the signed payload")
	}

	// And the audit still works with one, so the refusals above are about the missing
	// dependency rather than about the constructor.
	if _, err := NewSQLSinkInTx(q, testAnchor(t, signer)); err != nil {
		t.Fatalf("a sink with an anchor must be constructible: %v", err)
	}
}
