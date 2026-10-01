package audit

import (
	"context"
	"database/sql"
	"errors"
	"testing"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// fakeReaderQuerier serves rows for ListAuditRecordsInPartitionRange without a database.
//
// The rows are pre-built with rowFor rather than assembled field by field, so these tests
// exercise the reader's own behaviour - paging, ordering, error propagation - rather than
// re-implementing the mapping they are meant to be checking.
type fakeReaderQuerier struct {
	rows    map[string][]dbgen.AuditRecord // keyed by partition, pre-ordered
	err     error
	calls   []dbgen.ListAuditRecordsInPartitionRangeParams
	canned  [][]dbgen.AuditRecord // when set, returned in order, ignoring the range
	respond func(dbgen.ListAuditRecordsInPartitionRangeParams) ([]dbgen.AuditRecord, error)
	// checkpoints holds at most one row per partition: the query this stands in for returns
	// the newest, so a second row for one partition could never be observed.
	checkpoints map[string]dbgen.AuditCheckpoint
	cpErr       error
}

func (q *fakeReaderQuerier) GetLatestAuditCheckpoint(
	_ context.Context, partition string,
) (dbgen.AuditCheckpoint, error) {
	if q.cpErr != nil {
		return dbgen.AuditCheckpoint{}, q.cpErr
	}
	cp, ok := q.checkpoints[partition]
	if !ok {
		// The generated query is :one, so a partition with no checkpoint is sql.ErrNoRows.
		return dbgen.AuditCheckpoint{}, sql.ErrNoRows
	}
	return cp, nil
}

func (q *fakeReaderQuerier) ListAuditRecordsInPartitionRange(
	_ context.Context, arg dbgen.ListAuditRecordsInPartitionRangeParams,
) ([]dbgen.AuditRecord, error) {
	q.calls = append(q.calls, arg)
	if q.err != nil {
		return nil, q.err
	}
	if q.respond != nil {
		return q.respond(arg)
	}
	if q.canned != nil {
		idx := int(arg.Sequence-1) / rehydratePageSize
		if idx >= len(q.canned) {
			return nil, nil
		}
		return q.canned[idx], nil
	}
	var out []dbgen.AuditRecord
	for _, r := range q.rows[arg.Partition] {
		if r.Sequence >= arg.Sequence && r.Sequence <= arg.Sequence_2 {
			out = append(out, r)
		}
	}
	return out, nil
}

func rowsFor(t *testing.T, partition string, n int) []dbgen.AuditRecord {
	t.Helper()
	c := NewChain()
	staged := make([]Record, 0, n)
	for i := 0; i < n; i++ {
		// audit_id is the table's primary key, so it is unique across partitions rather
		// than within one. A fixture that reused ids across partitions would be refused by
		// Restore, correctly, and for a reason that has nothing to do with paging.
		r := stagedRecord(auditIDFor(i), partition)
		r.AuditID = partition + "-" + r.AuditID
		staged = append(staged, r)
	}
	out, err := c.Append(staged)
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	rows := make([]dbgen.AuditRecord, 0, len(out))
	for _, r := range out {
		rows = append(rows, rowFor(r))
	}
	return rows
}

func newTestReader(t *testing.T, q SQLChainReaderQuerier) *SQLChainReader {
	t.Helper()
	r, err := NewSQLChainReaderInTx(q)
	if err != nil {
		t.Fatalf("NewSQLChainReaderInTx: %v", err)
	}
	return r
}

func TestSQLReaderMapsEveryRow(t *testing.T) {
	q := &fakeReaderQuerier{rows: map[string][]dbgen.AuditRecord{"tenant-a": rowsFor(t, "tenant-a", 3)}}
	records, err := newTestReader(t, q).ReadPartition(context.Background(), "tenant-a", 1, 500)
	if err != nil {
		t.Fatalf("ReadPartition: %v", err)
	}
	if len(records) != 3 {
		t.Fatalf("read %d records, want 3", len(records))
	}
	for i, r := range records {
		if r.Sequence != int64(i+1) {
			t.Fatalf("record %d has sequence %d, want %d", i, r.Sequence, i+1)
		}
	}
}

func TestSQLReaderPropagatesAQueryError(t *testing.T) {
	// A swallowed read error would let Rehydrate proceed with a partial archive, and Restore
	// would report it as a gap in the sequence - an accurate statement about a cause it
	// cannot see. The reader's error has to survive as itself.
	want := errors.New("connection reset by peer")
	q := &fakeReaderQuerier{err: want}
	_, err := newTestReader(t, q).ReadPartition(context.Background(), "tenant-a", 1, 500)
	if err == nil {
		t.Fatal("a query error must not be reported as a successful read")
	}
	if !errors.Is(err, want) {
		t.Fatalf("the underlying cause is lost: %v", err)
	}
}

func TestSQLReaderRefusesRatherThanDropsARowThatFailsToMap(t *testing.T) {
	// The row that will not map is in the middle, so dropping it leaves a hole and the
	// archive looks like tampering. Refusing at the row names the actual problem.
	rows := rowsFor(t, "tenant-a", 3)
	rows[1].RecordHash = rows[1].RecordHash[:10]
	q := &fakeReaderQuerier{rows: map[string][]dbgen.AuditRecord{"tenant-a": rows}}

	records, err := newTestReader(t, q).ReadPartition(context.Background(), "tenant-a", 1, 500)
	if err == nil {
		t.Fatalf("an unmappable row must be refused, got %d records", len(records))
	}
	if records != nil {
		t.Fatal("a refused read must not return a partial slice; a caller that ignored the " +
			"error would otherwise store a truncated archive as if it were complete")
	}
}

func TestRehydratePagesAndTerminates(t *testing.T) {
	total := rehydratePageSize*2 + 7 // more than two full pages, so the loop must stop on a short page
	rows := rowsFor(t, "tenant-a", total)
	pages := make([][]dbgen.AuditRecord, 0, 3)
	for start := 0; start < len(rows); start += rehydratePageSize {
		end := start + rehydratePageSize
		if end > len(rows) {
			end = len(rows)
		}
		pages = append(pages, rows[start:end])
	}
	q := &fakeReaderQuerier{canned: pages}

	chain := NewChain()
	if err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"}); err != nil {
		t.Fatalf("Rehydrate: %v", err)
	}
	if got := chain.LastSequence("tenant-a"); got != int64(total) {
		t.Fatalf("rehydrated to sequence %d, want %d", got, total)
	}
	// One page short of full would have read past the end; a full final page would loop
	// forever, so the count of calls is the guarantee that paging terminates.
	if len(q.calls) != 3 {
		t.Fatalf("made %d queries, want 3 (two full pages plus one short page)", len(q.calls))
	}
	for i, call := range q.calls {
		if call.Sequence != int64(1+i*rehydratePageSize) {
			t.Fatalf("query %d started at sequence %d, want %d", i, call.Sequence, 1+i*rehydratePageSize)
		}
	}
}

func TestRehydrateOfSeveralPartitionsRestoresOnce(t *testing.T) {
	// Restore refuses a chain that already holds records, so a per-partition implementation
	// fails on the second partition. This is the test that distinguishes the two.
	q := &fakeReaderQuerier{rows: map[string][]dbgen.AuditRecord{
		"tenant-a": rowsFor(t, "tenant-a", 2),
		"tenant-b": rowsFor(t, "tenant-b", 3),
	}}

	chain := NewChain()
	if err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a", "tenant-b"}); err != nil {
		t.Fatalf("Rehydrate across partitions: %v", err)
	}
	if got := chain.LastSequence("tenant-a"); got != 2 {
		t.Fatalf("tenant-a rehydrated to %d, want 2", got)
	}
	if got := chain.LastSequence("tenant-b"); got != 3 {
		t.Fatalf("tenant-b rehydrated to %d, want 3", got)
	}
}

func TestRehydrateOfAnEmptyPartitionIsNotAnError(t *testing.T) {
	chain := NewChain()
	q := &fakeReaderQuerier{}
	if err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"}); err != nil {
		t.Fatalf("rehydrating an unwritten partition must succeed: %v", err)
	}
	if chain.LastSequence("tenant-a") != 0 {
		t.Fatal("an empty partition changed the chain")
	}
}

func TestRehydrateSurfacesARestoreRefusal(t *testing.T) {
	// The archive is intact per row but has a hole, which is what a tampered store produces.
	rows := rowsFor(t, "tenant-a", 3)
	rows = append(rows[:1], rows[2:]...)
	q := &fakeReaderQuerier{rows: map[string][]dbgen.AuditRecord{"tenant-a": rows}}

	chain := NewChain()
	err := Rehydrate(context.Background(), chain, newTestReader(t, q), []string{"tenant-a"})
	if err == nil {
		t.Fatal("an archive with a deleted record must be refused by Rehydrate")
	}
	if chain.LastSequence("tenant-a") != 0 {
		t.Fatal("a refused rehydrate left a partially loaded chain")
	}
}

func TestSQLReaderConstructionGuards(t *testing.T) {
	if _, err := NewSQLChainReader(nil); err == nil {
		t.Fatal("a nil database handle must be refused")
	}
	if _, err := NewSQLChainReaderInTx(nil); err == nil {
		t.Fatal("a nil querier must be refused")
	}
}

func TestSQLReaderCloseIsSafeWhenItOwnsNothing(t *testing.T) {
	if err := newTestReader(t, &fakeReaderQuerier{}).Close(); err != nil {
		t.Fatalf("closing an in-transaction reader must be a no-op, got %v", err)
	}
}
