package audit

import (
	"context"
	"database/sql"
	"strings"
	"testing"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// archiveFor builds one partition of n linked records, the rows a database would hold for
// them, and the signed checkpoint that was written while all n of them were still present.
//
// The three are built from the same records rather than separately, because the anchor is
// only meaningful if it really is the hash of the row at the sequence it names. A fixture
// whose checkpoint was made from a different chain would test nothing: the comparison would
// refuse for the wrong reason, or pass for one.
func archiveFor(t *testing.T, partition string, n int) ([]Record, []dbgen.AuditRecord, Checkpoint) {
	t.Helper()
	records := batchOf(t, partition, n)

	rows := make([]dbgen.AuditRecord, 0, len(records))
	for _, r := range records {
		rows = append(rows, applyDriverStorage(rowFor(r)))
	}

	_, signer := fixtureRing(t)
	cp, err := NewCheckpoint(records, signer, checkpointTime)
	if err != nil {
		t.Fatalf("NewCheckpoint: %v", err)
	}
	return records, rows, cp
}

// checkpointRowFor is the inverse of checkpointFrom, expressed at the driver boundary.
func checkpointRowFor(cp Checkpoint) dbgen.AuditCheckpoint {
	return dbgen.AuditCheckpoint{
		Partition:     cp.Partition,
		FirstSequence: cp.FirstSequence,
		LastSequence:  cp.LastSequence,
		FirstHash:     append([]byte(nil), cp.FirstHash[:]...),
		LastHash:      append([]byte(nil), cp.LastHash[:]...),
		RecordCount:   int32(cp.Count),
		CreatedAtUtc:  cp.CreatedAt.Time(),
		SigningKeyID:  cp.SigningKeyID,
		Signature:     append([]byte(nil), cp.Signature...),
		SchemaVersion: CheckpointSchemaVersion,
	}
}

// The regression this file exists for. Deleting the newest rows of a partition leaves an
// archive that is contiguous, correctly linked and correctly hashed, so every check Restore
// makes on the records themselves passes and the process goes on to report a verified chain
// over evidence that is gone. The signed checkpoint is the only durable thing that knows how
// far the partition went, so rehydration has to compare against it and refuse.
func TestRehydrateRefusesATruncatedArchive(t *testing.T) {
	_, rows, cp := archiveFor(t, "tenant-a", 4)
	kept := rows[:2] // the newest two records were deleted
	q := &fakeReaderQuerier{
		rows:        map[string][]dbgen.AuditRecord{"tenant-a": kept},
		checkpoints: map[string]dbgen.AuditCheckpoint{"tenant-a": checkpointRowFor(cp)},
	}

	chain := NewChain()
	err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"})
	if err == nil {
		t.Fatalf("an archive missing its tail rehydrated as a %d-record chain and would have "+
			"reported a verified chain over %d deleted record(s)",
			chain.LastSequence("tenant-a"), len(rows)-len(kept))
	}
	if !strings.Contains(err.Error(), "checkpoint") {
		t.Fatalf("the refusal should name the checkpoint that proves the loss, got: %v", err)
	}
	// A refusal that still applied the prefix would leave the process running on a chain
	// that is short of its evidence, which is the state the check exists to prevent.
	if got := chain.LastSequence("tenant-a"); got != 0 {
		t.Fatalf("a refused rehydrate left sequence %d behind; it must apply nothing at all", got)
	}
}

// The other half of the gate: it must not refuse the archive it is meant to protect. Without
// this the fix could be "refuse every anchored archive" and the suite would be green.
func TestRehydrateAcceptsAnIntactArchiveAgainstItsCheckpoint(t *testing.T) {
	_, rows, cp := archiveFor(t, "tenant-a", 4)
	q := &fakeReaderQuerier{
		rows:        map[string][]dbgen.AuditRecord{"tenant-a": rows},
		checkpoints: map[string]dbgen.AuditCheckpoint{"tenant-a": checkpointRowFor(cp)},
	}

	chain := NewChain()
	if err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"}); err != nil {
		t.Fatalf("an unmodified archive must still rehydrate: %v", err)
	}
	if got := chain.LastSequence("tenant-a"); got != 4 {
		t.Fatalf("rehydrated to sequence %d, want 4", got)
	}
}

// A partition whose records were all removed presents as an empty partition, which is the
// same state as a first boot. The checkpoint is what tells those apart.
func TestRehydrateRefusesAnArchiveWhosePartitionIsEntirelyGone(t *testing.T) {
	_, _, cp := archiveFor(t, "tenant-a", 2)
	q := &fakeReaderQuerier{
		checkpoints: map[string]dbgen.AuditCheckpoint{"tenant-a": checkpointRowFor(cp)},
	}

	chain := NewChain()
	err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"})
	if err == nil {
		t.Fatal("a partition with a signed checkpoint and no records at all must be refused; " +
			"otherwise a partition can be emptied completely without anything noticing")
	}
}

// Reaching the anchored sequence is not the same as being the archive that was signed. A
// chain rewritten from genesis can arrive at the same sequence number with different
// content, so the hash at the anchor is compared as well as the sequence.
func TestRehydrateRefusesAnArchiveWhoseAnchoredHeadDoesNotMatch(t *testing.T) {
	records, _, cp := archiveFor(t, "tenant-a", 3)
	forged := records[2]
	forged.AuditID = "aud-tenant-a-forged"
	forged.Reason = "an account nobody gave"
	rehashed, err := NewRecord(forged)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}
	// Same partition, same sequence, same predecessor link, different content: every check
	// Restore makes against the records themselves passes, and only the anchored hash at
	// sequence 3 tells the two chains apart.
	rows := []dbgen.AuditRecord{
		applyDriverStorage(rowFor(records[0])),
		applyDriverStorage(rowFor(records[1])),
		applyDriverStorage(rowFor(rehashed)),
	}

	q := &fakeReaderQuerier{
		rows:        map[string][]dbgen.AuditRecord{"tenant-a": rows},
		checkpoints: map[string]dbgen.AuditCheckpoint{"tenant-a": checkpointRowFor(cp)},
	}
	chain := NewChain()
	if err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"}); err == nil {
		t.Fatal("an archive whose anchored head is a different record must be refused")
	}
}

// The restore-level unit behind the rehydration test, so the behaviour is pinned where it is
// implemented rather than only through the reader that reaches it.
func TestRestoreAnchoredRefusesAChainThatStopsShortOfItsCheckpoint(t *testing.T) {
	records, _, cp := archiveFor(t, "tenant-a", 4)
	anchors := map[string]Checkpoint{"tenant-a": cp}

	c := NewChain()
	if err := c.RestoreAnchored(records[:2], anchors); err == nil {
		t.Fatal("a two-record prefix of a four-record anchored partition must be refused")
	}
	if got := c.LastSequence("tenant-a"); got != 0 {
		t.Fatalf("a refused anchored restore applied %d record(s)", got)
	}

	full := NewChain()
	if err := full.RestoreAnchored(records, anchors); err != nil {
		t.Fatalf("the full anchored archive must restore: %v", err)
	}
	if got := full.LastSequence("tenant-a"); got != 4 {
		t.Fatalf("the anchored restore reached sequence %d, want 4", got)
	}
}

// What the anchor does not reach is stated here rather than left implied. Records written
// after the newest checkpoint are exactly the case the anchor must tolerate: they are not
// covered by any signature yet, so requiring the head to equal the checkpoint would refuse
// the ordinary state of a chain that has kept accepting work since it was last closed.
func TestRestoreAnchoredAcceptsRecordsWrittenAfterTheNewestCheckpoint(t *testing.T) {
	records, _, cp := archiveFor(t, "tenant-a", 2)
	anchors := map[string]Checkpoint{"tenant-a": cp}

	// Continued from the archive rather than from an empty chain, so the later records sit
	// at sequences 3 and 4 and link to sequence 2 exactly as the live chain would.
	live := NewChain()
	if err := live.Restore(records); err != nil {
		t.Fatalf("Restore: %v", err)
	}
	later, err := live.Append([]Record{
		stagedRecord("aud-"+cp.Partition+"-after", cp.Partition),
		stagedRecord("aud-"+cp.Partition+"-later", cp.Partition),
	})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}

	c := NewChain()
	if err := c.RestoreAnchored(append(append([]Record{}, records...), later...), anchors); err != nil {
		t.Fatalf("an archive that extends past its newest checkpoint must restore: %v", err)
	}
	if got := c.LastSequence(cp.Partition); got != 4 {
		t.Fatalf("rehydrated to sequence %d, want 4", got)
	}
}

// A partition nobody has checkpointed is the ordinary state of a fresh chain, and the anchor
// must not turn "no evidence yet" into a refusal to start.
func TestRehydrateLoadsAPartitionThatHasNoCheckpoint(t *testing.T) {
	_, rows, _ := archiveFor(t, "tenant-a", 3)
	q := &fakeReaderQuerier{rows: map[string][]dbgen.AuditRecord{"tenant-a": rows}}

	chain := NewChain()
	if err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"}); err != nil {
		t.Fatalf("an uncheckpointed partition must still rehydrate: %v", err)
	}
	if got := chain.LastSequence("tenant-a"); got != 3 {
		t.Fatalf("rehydrated to sequence %d, want 3", got)
	}
}

// The residual limitation, pinned so nobody has to infer it. Restore is given records and
// nothing else, so it has no way to know a partition used to be longer - and this test fails
// if that ever changes, which is the point: the limitation is a property of the operation,
// not an accident.
func TestRestoreWithoutAnAnchorCannotSeeADeletedTail(t *testing.T) {
	records, _, _ := archiveFor(t, "tenant-a", 4)
	c := NewChain()
	if err := c.Restore(records[:2]); err != nil {
		t.Fatalf("Restore without anchors is the unanchored path and must still load a "+
			"contiguous prefix: %v", err)
	}
	// This is why Rehydrate supplies anchors rather than relying on Restore: the prefix is
	// indistinguishable from a chain that was never written past sequence 2, and a reader
	// with no checkpoint to compare against would report this as a healthy chain.
	if got := c.LastSequence("tenant-a"); got != 2 {
		t.Fatalf("unexpected sequence %d", got)
	}
}

func TestSQLReaderMapsACheckpointRow(t *testing.T) {
	_, _, cp := archiveFor(t, "tenant-a", 3)
	q := &fakeReaderQuerier{checkpoints: map[string]dbgen.AuditCheckpoint{"tenant-a": checkpointRowFor(cp)}}

	got, found, err := newTestReader(t, q).LatestCheckpoint(context.Background(), "tenant-a")
	if err != nil {
		t.Fatalf("LatestCheckpoint: %v", err)
	}
	if !found {
		t.Fatal("a checkpoint exists for this partition")
	}
	if got.Partition != cp.Partition || got.FirstSequence != cp.FirstSequence ||
		got.LastSequence != cp.LastSequence || got.Count != cp.Count ||
		got.FirstHash != cp.FirstHash || got.LastHash != cp.LastHash ||
		got.SigningKeyID != cp.SigningKeyID {
		t.Fatalf("the checkpoint did not survive the round trip: %+v", got)
	}
	// The signature is copied rather than aliased, so a driver reusing its buffer cannot
	// mutate the anchor that a later comparison depends on.
	if string(got.Signature) != string(cp.Signature) {
		t.Fatal("the signature did not survive the round trip")
	}
}

func TestSQLReaderReportsNoCheckpointForAnUnwrittenPartition(t *testing.T) {
	// sql.ErrNoRows is the generated query's answer for a partition with no checkpoint, and
	// it is a state rather than a failure: reporting it as one would make a fresh deployment
	// refuse to start.
	_, found, err := newTestReader(t, &fakeReaderQuerier{}).LatestCheckpoint(context.Background(), "tenant-a")
	if err != nil {
		t.Fatalf("a partition with no checkpoint must not be an error: %v", err)
	}
	if found {
		t.Fatal("a partition with no rows in audit_checkpoints must not report an anchor")
	}
}

func TestSQLReaderRefusesACheckpointItCannotReDerive(t *testing.T) {
	_, _, cp := archiveFor(t, "tenant-a", 2)
	for name, apply := range map[string]func(*dbgen.AuditCheckpoint){
		"foreign schema version": func(c *dbgen.AuditCheckpoint) { c.SchemaVersion = CheckpointSchemaVersion + 1 },
		"short last hash":        func(c *dbgen.AuditCheckpoint) { c.LastHash = c.LastHash[:8] },
	} {
		t.Run(name, func(t *testing.T) {
			row := checkpointRowFor(cp)
			apply(&row)
			q := &fakeReaderQuerier{checkpoints: map[string]dbgen.AuditCheckpoint{cp.Partition: row}}
			if _, _, err := newTestReader(t, q).LatestCheckpoint(context.Background(), cp.Partition); err == nil {
				t.Fatal("a checkpoint this build cannot re-derive must be refused, not adopted")
			}
		})
	}
}

func TestRehydrateRefusesAnAnchorFiledUnderTheWrongPartition(t *testing.T) {
	// The query filters on partition, so this cannot happen against PostgreSQL. It is
	// checked anyway because the consequence is a sequence number compared against the wrong
	// chain, and that is the kind of mistake a reader substitution makes quietly.
	_, rows, cp := archiveFor(t, "tenant-a", 2)
	row := checkpointRowFor(cp)
	row.Partition = "tenant-b"
	q := &fakeReaderQuerier{
		rows:        map[string][]dbgen.AuditRecord{"tenant-a": rows},
		checkpoints: map[string]dbgen.AuditCheckpoint{"tenant-a": row},
	}
	if err := Rehydrate(context.Background(), NewChain(), newTestReader(t, q), []string{"tenant-a"}); err == nil {
		t.Fatal("a checkpoint naming a different partition must be refused as an anchor")
	}
}

func TestRehydratePropagatesAnAnchorReadFailure(t *testing.T) {
	// A swallowed anchor error would rehydrate the archive unanchored - the exact state this
	// check exists to prevent - and report success while doing it.
	_, rows, _ := archiveFor(t, "tenant-a", 2)
	q := &fakeReaderQuerier{
		rows:  map[string][]dbgen.AuditRecord{"tenant-a": rows},
		cpErr: sql.ErrConnDone,
	}
	chain := NewChain()
	if err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"}); err == nil {
		t.Fatal("a checkpoint that could not be read must be reported, not treated as absent")
	}
	if got := chain.LastSequence("tenant-a"); got != 0 {
		t.Fatalf("a refused rehydrate left sequence %d behind", got)
	}
}

// TestEveryAnchorColumnReachesTheComparison guards the mapping in both directions: a column
// the reader drops would either be compared against a zero value or not compared at all, and
// the second failure is invisible. A presence check alone cannot see that a field is carried
// but never consulted, so each case also asserts that changing the column changes what the
// restore compares.
//
// first_sequence is absent from the table deliberately. Contiguity from sequence 1 already
// proves that every record before it is present, so comparing it could not fail for a reason
// the restore has not already caught; restore.go says so where the anchor is used.
func TestEveryAnchorColumnReachesTheComparison(t *testing.T) {
	records, _, cp := archiveFor(t, "tenant-a", 2)

	for name, mutate := range map[string]func(*dbgen.AuditCheckpoint){
		"last_sequence": func(c *dbgen.AuditCheckpoint) { c.LastSequence = cp.LastSequence + 1 },
		"last_hash":     func(c *dbgen.AuditCheckpoint) { c.LastHash = make([]byte, 32) },
	} {
		t.Run(name, func(t *testing.T) {
			row := checkpointRowFor(cp)
			mutate(&row)
			if _, err := RehydrateAnchoredArchive(t, records, row); err == nil {
				t.Fatalf("a checkpoint whose %s disagrees with the archive must be refused; "+
					"the column is not reaching the comparison", name)
			}
		})
	}
}

// RehydrateAnchoredArchive runs the reader path over one archive and one anchor row, which is
// the same shape as a startup rehydration and keeps the column cases above honest about what
// they are exercising.
func RehydrateAnchoredArchive(t *testing.T, records []Record, row dbgen.AuditCheckpoint) (*Chain, error) {
	t.Helper()
	rows := make([]dbgen.AuditRecord, 0, len(records))
	for _, r := range records {
		rows = append(rows, applyDriverStorage(rowFor(r)))
	}
	q := &fakeReaderQuerier{
		rows:        map[string][]dbgen.AuditRecord{row.Partition: rows},
		checkpoints: map[string]dbgen.AuditCheckpoint{row.Partition: row},
	}
	chain := NewChain()
	return chain, Rehydrate(context.Background(), chain, newTestReader(t, q), []string{row.Partition})
}
