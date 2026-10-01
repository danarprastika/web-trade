package audit

import (
	"context"
	"errors"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// fakeSink records what it was asked to export and can be made to fail.
type fakeSink struct {
	exported [][]Record
	failWith error
	// commitsBeforeFailure is how many batches succeed before the sink starts failing.
	// Zero means it fails immediately.
	commitsBeforeFailure int
}

func (f *fakeSink) Export(_ context.Context, records []Record) error {
	if f.failWith != nil && len(f.exported) >= f.commitsBeforeFailure {
		return f.failWith
	}
	// Copy the slice header's contents, not the records: the point is to observe which
	// records arrived, and a later mutation of the caller's slice must not rewrite history.
	seen := make([]Record, len(records))
	copy(seen, records)
	f.exported = append(f.exported, seen)
	return nil
}

// recordingQuerier captures the parameters the sink hands to the generated accessor.
type recordingQuerier struct {
	calls  []dbgen.AppendAuditRecordParams
	failAt int
}

func (q *recordingQuerier) AppendAuditRecord(
	_ context.Context, arg dbgen.AppendAuditRecordParams,
) (dbgen.AuditRecord, error) {
	if q.failAt > 0 && len(q.calls)+1 == q.failAt {
		q.calls = append(q.calls, arg)
		return dbgen.AuditRecord{}, errors.New("sink: simulated write failure")
	}
	q.calls = append(q.calls, arg)
	return dbgen.AuditRecord{}, nil
}

func TestExportedIsReleasedOnlyAfterTheSinkCommits(t *testing.T) {
	g, err := NewGuard(10)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	if err := g.Accept(2); err != nil {
		t.Fatalf("Accept: %v", err)
	}

	sink := &fakeSink{failWith: errors.New("disk is on fire"), commitsBeforeFailure: 0}
	exp, err := NewExporter(g, sink)
	if err != nil {
		t.Fatalf("NewExporter: %v", err)
	}

	// The sink refuses. The records are still owed a durable place, so the backlog must be
	// untouched: releasing it here would let the guard resume while the evidence sits in a
	// buffer that a crash erases, which is the exact loss the guard exists to prevent.
	if err := exp.Export(context.Background(), []Record{
		stagedRecord("aud-1", "tenant-a"),
		stagedRecord("aud-2", "tenant-a"),
	}); err == nil {
		t.Fatal("a failing sink must be reported, not swallowed")
	}
	if got := g.Pending(); got != 2 {
		t.Fatalf("backlog after a refused export = %d, want 2; the records are still "+
			"unexported and the guard must still count them", got)
	}

	// The sink recovers and the same call succeeds.
	sink.failWith = nil
	if err := exp.Export(context.Background(), []Record{
		stagedRecord("aud-1", "tenant-a"),
		stagedRecord("aud-2", "tenant-a"),
	}); err != nil {
		t.Fatalf("Export after recovery: %v", err)
	}
	if got := g.Pending(); got != 0 {
		t.Fatalf("backlog after a committed export = %d, want 0", got)
	}
}

// TestABackloggedGuardCanBeDrainedAndCleared is the end-to-end property that the guard could
// not satisfy before this work. Until Exporter existed there was no producer for Exported,
// so a guard that reached its limit was an absorbing state.
func TestABackloggedGuardCanBeDrainedAndCleared(t *testing.T) {
	g, err := NewGuard(2)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	exp, err := NewExporter(g, &fakeSink{})
	if err != nil {
		t.Fatalf("NewExporter: %v", err)
	}

	// Fill the backlog and trip the halt exactly as a real outage would.
	if err := exp.Accept(1); err != nil {
		t.Fatalf("Accept 1: %v", err)
	}
	if err := exp.Accept(1); err != nil {
		t.Fatalf("Accept 2: %v", err)
	}
	if err := exp.Accept(1); err == nil {
		t.Fatal("exceeding the limit must be refused")
	}
	if !g.Halted() {
		t.Fatal("the refusal must latch the guard")
	}

	// The sink comes back and the backlog drains.
	if err := exp.Export(context.Background(), []Record{stagedRecord("aud-1", "tenant-a")}); err != nil {
		t.Fatalf("Export: %v", err)
	}
	if err := exp.Export(context.Background(), []Record{stagedRecord("aud-2", "tenant-a")}); err != nil {
		t.Fatalf("Export: %v", err)
	}
	if got := g.Pending(); got != 0 {
		t.Fatalf("backlog after draining = %d, want 0", got)
	}

	// Now the operator's escape hatch must actually work, which is the whole point.
	if err := g.Clear(); err != nil {
		t.Fatalf("Clear after draining must succeed: %v", err)
	}
	if err := g.Allow(OpRiskIncreasing); err != nil {
		t.Fatalf("after a drained backlog and an explicit clear, work must resume: %v", err)
	}
	// And accepting must work again, rather than re-tripping on the first record.
	if err := exp.Accept(1); err != nil {
		t.Fatalf("Accept after clearing: %v", err)
	}
}

func TestClearRefusesWhileTheBacklogIsOutstanding(t *testing.T) {
	g, err := NewGuard(1)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	if err := g.Accept(1); err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if err := g.Accept(1); err == nil {
		t.Fatal("exceeding the limit must be refused")
	}

	// The old unconditional Clear() set halted=false here, leaving pending at the limit, so
	// the very next Accept re-tripped the halt. The operator saw "cleared" and was halted
	// again on the next record, and could not even record that they had cleared.
	if err := g.Clear(); err == nil {
		t.Fatal("clearing with an outstanding backlog must be refused; the clear would be " +
			"undone by the next accepted record")
	}
	if !g.Halted() {
		t.Fatal("a refused clear must leave the guard halted")
	}
	if got := g.Pending(); got != 1 {
		t.Fatalf("a refused clear must not touch the backlog; got %d, want 1", got)
	}

	// Draining, then clearing, is the sequence that works.
	if err := g.Exported(1); err != nil {
		t.Fatalf("Exported: %v", err)
	}
	if err := g.Clear(); err != nil {
		t.Fatalf("Clear after draining: %v", err)
	}
}

func TestClearIsPermittedForAnIntegrityHaltWhileTheBacklogIsOutstanding(t *testing.T) {
	g, err := NewGuard(10)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	// A chain break is a different decision from an export backlog. An operator who has
	// reviewed the finding must not additionally be told to fix an unrelated backlog.
	g.Halt("SEV-1_AUDIT_INTEGRITY", "chain break at sequence 41")
	if err := g.Accept(3); err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if err := g.Clear(); err != nil {
		t.Fatalf("an integrity halt must be clearable regardless of the backlog: %v", err)
	}
	if g.Halted() {
		t.Fatal("the latch should be released")
	}
}

func TestClearOnAnUnhaltedGuardIsANoOp(t *testing.T) {
	g, err := NewGuard(5)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	if err := g.Clear(); err != nil {
		t.Fatalf("clearing a guard that was never halted must succeed: %v", err)
	}
	if g.Halted() {
		t.Fatal("the guard must not become halted by a clear")
	}
}

func TestAnExporterWithoutASinkOrGuardIsRefused(t *testing.T) {
	g, err := NewGuard(5)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	if _, err := NewExporter(nil, &fakeSink{}); err == nil {
		t.Fatal("an exporter with no guard has no backlog to drain and must be refused")
	}
	if _, err := NewExporter(g, nil); err == nil {
		t.Fatal("an exporter with no sink cannot write anything and must be refused")
	}
}

func TestExportingNoRecordsTouchesNothing(t *testing.T) {
	g, err := NewGuard(5)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	exp, err := NewExporter(g, &fakeSink{})
	if err != nil {
		t.Fatalf("NewExporter: %v", err)
	}
	if err := exp.Export(context.Background(), nil); err != nil {
		t.Fatalf("an empty export must succeed: %v", err)
	}
	if got := g.Pending(); got != 0 {
		t.Fatalf("an empty export changed the backlog to %d", got)
	}
}

func TestExportingMoreThanWasAcceptedIsReported(t *testing.T) {
	g, err := NewGuard(10)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	exp, err := NewExporter(g, &fakeSink{})
	if err != nil {
		t.Fatalf("NewExporter: %v", err)
	}
	if err := exp.Export(context.Background(), []Record{stagedRecord("aud-1", "tenant-a")}); err == nil {
		t.Fatal("releasing a backlog for records that were never accepted is a programming " +
			"error and must be reported, not absorbed")
	}
}

func TestTheSinkWritesEveryRecordInChainOrder(t *testing.T) {
	q := &recordingQuerier{}
	sink, err := NewSQLSinkInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}
	chain := NewChain()
	staged := []Record{
		stagedRecord("aud-1", "tenant-a"),
		stagedRecord("aud-2", "tenant-a"),
		stagedRecord("aud-3", "tenant-b"),
	}
	accepted, err := chain.Append(staged)
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	if err := sink.Export(context.Background(), accepted); err != nil {
		t.Fatalf("Export: %v", err)
	}
	if len(q.calls) != 3 {
		t.Fatalf("wrote %d records, want 3", len(q.calls))
	}
	// The durable order must be the chain's order. Re-sorting in the sink would mean the
	// stored order and the chained order could disagree, which is the comparison the
	// integrity verifier exists to make.
	for i, call := range q.calls {
		if call.AuditID != accepted[i].AuditID {
			t.Fatalf("record %d written as %s, want %s", i, call.AuditID, accepted[i].AuditID)
		}
		if call.Sequence != accepted[i].Sequence {
			t.Fatalf("record %d written at sequence %d, want %d",
				i, call.Sequence, accepted[i].Sequence)
		}
	}
}

func TestTheSinkRefusesToConstructWithoutADatabaseHandle(t *testing.T) {
	if _, err := NewSQLSink(nil); err == nil {
		t.Fatal("a sink with no database handle must be refused rather than built and " +
			"left to fail on first use")
	}
	if _, err := NewSQLSinkInTx(nil); err == nil {
		t.Fatal("a sink with no querier must be refused")
	}
}

// columnRenames maps a Record field to the insert parameter that carries it, where the two
// names differ. It is declared rather than inferred so that a genuine omission and a known
// rename stay distinguishable: every entry is a decision someone made, and anything not
// listed here must match by name.
var columnRenames = map[string]string{
	// The columns are named for their SQL type suffix because the schema is shared with
	// readers that do not know the Go type; the Go fields say which instant they mean.
	"OccurredAt": "OccurredAtUtc",
	"RecordedAt": "RecordedAtUtc",
}

// TestEveryRecordFieldReachesTheDatabase backs the claim in paramsFor's doc comment. The
// mapping is hand-written, so a field added to Record and forgotten here would be written
// as a zero value and the database would accept it, because every column in 0002 has either
// a default or only a NOT NULL check.
func TestEveryRecordFieldReachesTheDatabase(t *testing.T) {
	recordFields := fieldNames(reflect.TypeOf(Record{}))
	paramFields := fieldNames(reflect.TypeOf(dbgen.AppendAuditRecordParams{}))

	// SchemaVersion is a package constant rather than a field on Record, and the canonical
	// serialization includes it, so paramsFor supplies it without a source field.
	paramFields = removeOne(paramFields, "SchemaVersion")

	// Apply the declared renames, and require that each one names a column that exists -
	// a rename pointing at a typo would otherwise make its own field look unmapped while
	// also leaving a real column unexplained.
	targets := make([]string, 0, len(recordFields))
	for _, field := range recordFields {
		renamed, renamedOK := columnRenames[field]
		if !renamedOK {
			targets = append(targets, field)
			continue
		}
		if !contains(paramFields, renamed) {
			t.Fatalf("columnRenames maps %s to %s, which is not a column in the insert; "+
				"the rename is stale", field, renamed)
		}
		targets = append(targets, renamed)
	}

	missing := difference(targets, paramFields)
	if len(missing) > 0 {
		t.Fatalf("these Record fields have no column in the insert, so they would be "+
			"written as zero values: %s", strings.Join(missing, ", "))
	}
	extra := difference(paramFields, targets)
	if len(extra) > 0 {
		t.Fatalf("the insert has columns with no Record field, so paramsFor is filling "+
			"them with a constant: %s", strings.Join(extra, ", "))
	}
}

func contains(values []string, want string) bool {
	for _, v := range values {
		if v == want {
			return true
		}
	}
	return false
}

// TestParamsForTakesItsRecordByValue pins the signature that provides the isolation.
//
// The sink does not need to copy the hash arrays itself, and an earlier version of this
// file asserted that it did. That assertion could not fail: paramsFor takes a Record by
// value, so the language copies both fixed-size arrays before any []byte conversion runs,
// and deleting the explicit copy changed nothing observable. The mutation written to check
// it therefore "survived" while testing nothing. The copy is kept as a guard against a
// future pointer signature, and this test is what makes that guard real - it fails the day
// someone changes the parameter to *Record, at which point the explicit copies start to
// matter and the isolation silently depends on them.
func TestParamsForTakesItsRecordByValue(t *testing.T) {
	param := reflect.TypeOf(paramsFor)
	if got := param.In(0); got.Kind() == reflect.Ptr {
		t.Fatalf("paramsFor takes *%s; the hash arrays are then aliased rather than copied, "+
			"and the explicit copies in its body become load-bearing", got.Elem().Name())
	}
	// And the observable consequence, which holds for any implementation: writing to the
	// source record after the call must not change what the driver was handed.
	r := stagedRecord("aud-1", "tenant-a")
	accepted, err := NewChain().Append([]Record{r})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	params := paramsFor(accepted[0])
	accepted[0].RecordHash[0] ^= 0xff
	if params.RecordHash[0] == accepted[0].RecordHash[0] {
		t.Fatal("the parameters alias the caller's record; a later write to the record would " +
			"rewrite bytes the driver may not have flushed yet")
	}
}

func TestAnEmptyBatchIsNotOpenedAsATransaction(t *testing.T) {
	q := &recordingQuerier{}
	sink, err := NewSQLSinkInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}
	if err := sink.Export(context.Background(), nil); err != nil {
		t.Fatalf("Export: %v", err)
	}
	if len(q.calls) != 0 {
		t.Fatalf("an empty export issued %d writes, want 0", len(q.calls))
	}
}

func TestAQuerierFailureAbortsTheRestOfTheBatch(t *testing.T) {
	q := &recordingQuerier{failAt: 2}
	sink, err := NewSQLSinkInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSinkInTx: %v", err)
	}
	chain := NewChain()
	accepted, err := chain.Append([]Record{
		stagedRecord("aud-1", "tenant-a"),
		stagedRecord("aud-2", "tenant-a"),
		stagedRecord("aud-3", "tenant-a"),
	})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	// A partial batch must be reported as a failure, because the caller releases backlog
	// for the whole batch on success. Reporting nil here would let the guard resume while
	// the tail of the batch was never stored.
	if err := sink.Export(context.Background(), accepted); err == nil {
		t.Fatal("a batch whose second write failed must not report success")
	}
	if len(q.calls) != 2 {
		t.Fatalf("the sink continued past the failure: %d writes, want 2", len(q.calls))
	}
}

func TestTheSchemaVersionReachesTheDatabase(t *testing.T) {
	r := stagedRecord("aud-1", "tenant-a")
	accepted, err := NewChain().Append([]Record{r})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	// SchemaVersion has no Record field, so the field-mapping test cannot see it. It is
	// written from a package constant, and a reader of a stored record needs it to know
	// which canonical form produced the hash it is verifying.
	if got := paramsFor(accepted[0]).SchemaVersion; got != int32(SchemaVersion) {
		t.Fatalf("stored schema version = %d, want %d; a reader verifying this record's "+
			"hash would canonicalize it under the wrong rules", got, SchemaVersion)
	}
}

func fieldNames(t reflect.Type) []string {
	out := make([]string, 0, t.NumField())
	for i := 0; i < t.NumField(); i++ {
		out = append(out, t.Field(i).Name)
	}
	sort.Strings(out)
	return out
}

func difference(from, in []string) []string {
	set := make(map[string]bool, len(in))
	for _, v := range in {
		set[v] = true
	}
	var out []string
	for _, v := range from {
		if !set[v] {
			out = append(out, v)
		}
	}
	return out
}

func removeOne(values []string, name string) []string {
	out := make([]string, 0, len(values))
	removed := false
	for _, v := range values {
		if v == name && !removed {
			removed = true
			continue
		}
		out = append(out, v)
	}
	return out
}
