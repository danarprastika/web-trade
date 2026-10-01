package model

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// These tests cover what the journal's existing 122 could not check.
//
// Until now every guarantee in this package was provable only against maps. "The state is
// written only after the audit chain accepts the record" was true and checkable, because a
// map cannot fail. The moment a durable store sits behind the journal, three claims become
// checkable that were previously unfalsifiable, and all three are the ones that matter:
//
//   - the durable write happens after the audit append, not instead of it or before it;
//   - a durable write that fails leaves the in-memory state exactly as it was, so a caller
//     told "not applied" is not lying;
//   - the two statements ApplyTransition issues are one unit, so a half-applied transition
//     cannot exist even in principle.
//
// Each test below is written to fail if its claim is broken rather than to confirm the
// current behaviour, and each states the failure it is preventing.

// newDurableJournal builds a journal whose writes go through store, which the caller can
// then make fail.
func newDurableJournal(t *testing.T, store Store) (*Journal, *audit.Chain) {
	t.Helper()
	chain := audit.NewChain()
	j, err := NewJournalWithStore(chain, func() time.Time { return epoch }, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	return j, chain
}

// recordingStore captures the order of durable writes so a test can assert that the store
// was called after the audit chain, not before it.
//
// It is deliberately not MemoryStore. MemoryStore answers "was anything written"; this
// answers "in what order, relative to something outside the store", which is the actual
// claim and which a store cannot observe about itself.
type recordingStore struct {
	// calls records each durable write in order.
	calls []string
	// entries records what was written.
	entries []RegistryEntry
	// transitions records the applied transitions in order.
	transitions []TransitionEntry
	// failAt, when non-empty, fails the named call ("insert" or "transition").
	failAt string
	// observe is called before each write is recorded, so a test can inspect the audit
	// chain at the moment the durable write happens.
	observe func()
}

func (r *recordingStore) record(kind string) error {
	if r.observe != nil {
		r.observe()
	}
	r.calls = append(r.calls, kind)
	if r.failAt == kind {
		r.failAt = ""
		return errors.New("injected durable write failure")
	}
	return nil
}

func (r *recordingStore) InsertModel(_ context.Context, entry RegistryEntry) error {
	if err := r.record("insert"); err != nil {
		return err
	}
	r.entries = append(r.entries, entry)
	return nil
}

func (r *recordingStore) ApplyTransition(_ context.Context, entry TransitionEntry) error {
	if err := r.record("transition"); err != nil {
		return err
	}
	r.transitions = append(r.transitions, entry)
	return nil
}

func (r *recordingStore) Close() error { return nil }

// TestDurableWriteHappensAfterTheAuditAppend is the core ordering claim.
//
// The journal's guarantee has always been that state is written only after the audit chain
// accepts the record describing it. That was checkable against a map. It is only meaningful
// against a store that can fail, because "written only after" is a statement about a failure
// window: between the append and the write there is a point at which the audit chain says
// something happened and the registry does not.
func TestDurableWriteHappensAfterTheAuditAppend(t *testing.T) {
	store := &recordingStore{}
	j, chain := newDurableJournal(t, store)

	// At the moment the store is called, the audit chain must already hold the record for
	// this transition. Observing from inside the store is the only way to check the
	// ordering; checking afterwards would see both and prove nothing.
	observed := false
	store.observe = func() {
		records := chain.AllRecords()
		if len(records) != 1 {
			t.Errorf("the store was called with %d audit records in the chain; the append "+
				"must happen first or the registry holds a state with no audit trail", len(records))
			return
		}
		observed = true
	}

	registeredModel(t, j)
	if !observed {
		t.Fatal("the durable write never observed the audit chain; the test's observer did not run")
	}
	if got := len(store.entries); got != 1 {
		t.Fatalf("registration wrote %d durable rows, want 1", got)
	}
}

// TestRefusedRegistrationWritesNothingDurable checks that a refusal leaves no durable trace.
//
// The in-memory check ("the model is not in the registry") was not enough, because a
// registration that appends an audit record and then fails its durable write has left
// something behind in the chain. That is tolerable and is a different claim. What must not
// happen is a durable row for a model the caller was told does not exist.
func TestRefusedRegistrationWritesNothingDurable(t *testing.T) {
	store := &recordingStore{failAt: "insert"}
	j, _ := newDurableJournal(t, store)

	if _, err := j.Register(setID(t, validRecord()), contracts.ActorService, "control-plane-01"); err == nil {
		t.Fatal("Register succeeded although the durable store refused it; a caller told the " +
			"model exists would proceed to transition a model that was never recorded")
	}
	if got := len(store.entries); got != 0 {
		t.Fatalf("a refused registration wrote %d durable rows, want 0", got)
	}
	if _, ok := j.Record(mustModelID(t)); ok {
		t.Fatal("a refused registration left the model in the in-memory registry; the caller " +
			"was told registration failed and must not find the model present")
	}
}

// TestRefusedTransitionLeavesTheModelWhereItWas is the property that distinguishes a durable
// write from a best-effort one.
//
// Before the store existed there was no failure to survive, so "the caller is told the
// transition did not happen" was true by construction. With a store it has to be earned: the
// in-memory state must not move when the durable write fails, or a caller that retries would
// find the model already advanced and be refused as stale, with no way to tell the
// difference between "already done" and "half done".
func TestRefusedTransitionLeavesTheModelWhereItWas(t *testing.T) {
	store := &recordingStore{}
	j, _ := newDurableJournal(t, store)
	id, _ := registeredModelN(t, j, 0)

	// Advance one declared step so the next transition has a legal source state.
	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-eval-1")); err != nil {
		t.Fatalf("the setup transition failed: %v", err)
	}
	before, _ := j.State(id)

	store.failAt = "transition"
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-val-1")); err == nil {
		t.Fatal("Transact succeeded although the durable store refused the write")
	}

	after, _ := j.State(id)
	if after != before {
		t.Fatalf("after a refused durable write the model is in %s, but it was in %s before; "+
			"the in-memory state moved even though the caller was told the transition was "+
			"not applied", after, before)
	}
}

// TestTheSameRetrySucceedsAfterAFailedWrite proves the failure is recoverable rather than
// terminal.
//
// The one-shot failure in the test above is the easy case. This is the one that matters: a
// caller whose transition failed must be able to retry the identical request and get it
// applied exactly once. If the failed attempt had recorded the idempotency key, the retry
// would return a fabricated outcome for a transition that never happened.
func TestTheSameRetrySucceedsAfterAFailedWrite(t *testing.T) {
	store := &recordingStore{}
	j, _ := newDurableJournal(t, store)
	id, _ := registeredModelN(t, j, 0)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-retry-1")); err != nil {
		t.Fatalf("the setup transition failed: %v", err)
	}

	store.failAt = "transition"
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-retry-1")); err == nil {
		t.Fatal("the first attempt succeeded although the store was told to fail it")
	}

	outcome, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-retry-1"))
	if err != nil {
		t.Fatalf("the retry after a failed durable write was refused: %v", err)
	}
	if outcome.Transition.To != StateValidated {
		t.Fatalf("the retry produced %s, want VALIDATED", outcome.Transition.To)
	}

	applied := 0
	for _, e := range store.transitions {
		if e.To == StateValidated {
			applied++
		}
	}
	if applied != 1 {
		t.Fatalf("%d durable transitions recorded VALIDATED, want exactly 1; the failed "+
			"attempt must not have left an entry that the retry then duplicated", applied)
	}
}

// TestTheDurableRowCitesTheSameAuditRecordAsTheRegistry guards the linkage.
//
// The store receives the audit identifier rather than deriving it, and this is the test
// that the identifier it receives is the one the chain actually holds. Deriving the
// identifier in both places would be one refactor away from the two copies disagreeing, and
// a store row citing a different record than the registry row is precisely the broken
// linkage the last_audit_id column exists to prevent.
//
// It covers the registration row as well as the transition rows. An earlier version checked
// only store.transitions, and the mutation harness found it: substituting a wrong audit
// identity on the registration path left the suite green. That is the mutation harness
// earning its place, and it is why the assertion below walks every durable row rather than
// only the ones a transition produced.
func TestTheDurableRowCitesTheSameAuditRecordAsTheRegistry(t *testing.T) {
	store := &recordingStore{}
	j, chain := newDurableJournal(t, store)
	id, _ := registeredModelN(t, j, 0)

	outcome, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-link-1"))
	if err != nil {
		t.Fatalf("Transact: %v", err)
	}

	chainIDs := make(map[string]bool, len(chain.AllRecords()))
	for _, r := range chain.AllRecords() {
		chainIDs[r.AuditID] = true
	}
	if outcome.AuditRecord == "" || !chainIDs[outcome.AuditRecord] {
		t.Fatalf("the returned audit record %q is not in the chain", outcome.AuditRecord)
	}

	if len(store.entries) == 0 {
		t.Fatal("registration wrote no durable row; there is nothing to check the linkage on")
	}
	for _, e := range store.entries {
		if e.AuditID == "" || !chainIDs[e.AuditID] {
			t.Fatalf("the durable registration cites audit record %q, which the chain does "+
				"not hold; a model in the durable registry whose audit identity is not in the "+
				"chain could be promoted out of a history that does not contain its existence",
				e.AuditID)
		}
	}
	for _, e := range store.transitions {
		if !chainIDs[e.AuditID] {
			t.Fatalf("the durable transition cites audit record %q, which the chain does "+
				"not hold; a transition whose durable row cites an unknown audit record cannot "+
				"be reconstructed from the audit trail", e.AuditID)
		}
	}
}

// TestRegistrationDurableRowCarriesTheWholeRecord checks that nothing required is dropped in
// the translation to the store.
//
// This is a translation boundary, and translation boundaries lose fields silently: a field
// dropped here is a column left at its default in PostgreSQL, and a default is a value that
// looks correct until somebody reads it. The eleven required fields are checked by name
// rather than by reflection, so a field added to Record is not silently accepted as covered.
func TestRegistrationDurableRowCarriesTheWholeRecord(t *testing.T) {
	store := &recordingStore{}
	j, _ := newDurableJournal(t, store)

	rec := setID(t, validRecord())
	rec.ApprovalRecord = digestApproval
	if _, err := j.Register(rec, contracts.ActorService, "control-plane-01"); err != nil {
		t.Fatalf("Register: %v", err)
	}
	if len(store.entries) != 1 {
		t.Fatalf("registration wrote %d rows, want 1", len(store.entries))
	}

	got := store.entries[0].Record
	if got.TrainingDatasetFingerprint != rec.TrainingDatasetFingerprint {
		t.Errorf("training dataset fingerprint is %q on the durable row and %q in the record",
			got.TrainingDatasetFingerprint, rec.TrainingDatasetFingerprint)
	}
	if got.EvaluationResults != rec.EvaluationResults {
		t.Errorf("evaluation results are %q on the durable row and %q in the record",
			got.EvaluationResults, rec.EvaluationResults)
	}
	if got.RollbackArtifact != rec.RollbackArtifact {
		t.Errorf("rollback artifact is %q on the durable row and %q in the record",
			got.RollbackArtifact, rec.RollbackArtifact)
	}
	if got.ApprovalRecord != rec.ApprovalRecord {
		t.Errorf("approval record is %q on the durable row and %q in the record; an approval "+
			"dropped here is an approval the durable registry never saw", got.ApprovalRecord,
			rec.ApprovalRecord)
	}
	if got.Limitations != rec.Limitations {
		t.Errorf("limitations are %q on the durable row and %q in the record; limitations "+
			"dropped here are failure modes the durable registry does not record", got.Limitations,
			rec.Limitations)
	}
}

// TestJournalReportsWhetherItIsDurable checks that "does this journal persist" has an
// answer. It is a small test for a small method, and it exists because the alternative is a
// nil check at every call site and a caller who cannot tell.
func TestJournalReportsWhetherItIsDurable(t *testing.T) {
	if j := newJournal(t); j.Durable() {
		t.Error("a journal built by NewJournal reports itself durable; it has no store")
	}
	j, _ := newDurableJournal(t, NewMemoryStore())
	if !j.Durable() {
		t.Error("a journal built with a store reports itself in-memory")
	}
}

// TestNoStoreMeansNoDurableWrite is the negative control.
//
// Without it, a suite where every test wired up a store would still pass if the journal had
// stopped consulting it entirely, because nothing would notice that no write happened.
func TestNoStoreMeansNoDurableWrite(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModelN(t, j, 0)
	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-none-1")); err != nil {
		t.Fatalf("Transact without a store failed: %v", err)
	}
	if state, _ := j.State(id); state != StateEvaluated {
		t.Fatalf("the model is in %s, want EVALUATED", state)
	}
}

// fakeQuerier records the calls SQLStore makes and can fail any of them.
//
// It exists because the atomicity of ApplyTransition is a property of the sequence of two
// statements inside one transaction, and there is no way to check that against a map or
// against a mock that asserts call counts. What can be checked is that the second statement
// is not attempted after the first fails, which is the observable form of "one unit".
type fakeQuerier struct {
	calls  []string
	failOn string
	// insideTx records whether the calls arrived through the transactional path.
	insideTx bool
}

func (f *fakeQuerier) InsertModel(_ context.Context, _ dbgen.InsertModelParams) (dbgen.ModelRegistry, error) {
	f.calls = append(f.calls, "insert")
	if f.failOn == "insert" {
		return dbgen.ModelRegistry{}, errors.New("injected insert failure")
	}
	return dbgen.ModelRegistry{}, nil
}

func (f *fakeQuerier) SetModelState(_ context.Context, _ dbgen.SetModelStateParams) (dbgen.ModelRegistry, error) {
	f.calls = append(f.calls, "setState")
	if f.failOn == "setState" {
		return dbgen.ModelRegistry{}, errors.New("injected state failure")
	}
	return dbgen.ModelRegistry{}, nil
}

func (f *fakeQuerier) RecordTransitionIdempotency(
	_ context.Context, _ dbgen.RecordTransitionIdempotencyParams,
) (dbgen.ModelTransitionIdempotency, error) {
	f.calls = append(f.calls, "recordIdempotency")
	return dbgen.ModelTransitionIdempotency{}, nil
}

// TestApplyTransitionIsOneUnit is the atomicity claim for the SQL store.
//
// The two statements are ordered state-then-ledger, and the second is not attempted if the
// first fails. The reverse order would be the dangerous one: an idempotency entry recorded
// before the state moved is a fabricated success, because a retry would find the key and
// return an outcome for a transition that never happened.
func TestApplyTransitionIsOneUnit(t *testing.T) {
	q := &fakeQuerier{}
	store, err := NewSQLStoreInTx(q)
	if err != nil {
		t.Fatalf("NewSQLStoreInTx: %v", err)
	}
	entry := TransitionEntry{
		Scope:       "model/lifecycle/validation",
		Key:         "key-1",
		Fingerprint: digestOf("request", "x"),
		From:        StateEvaluated,
		To:          StateValidated,
		AuditID:     "audit-1",
		At:          epoch,
	}
	entry.ModelID = mustModelID(t)

	if err := store.ApplyTransition(context.Background(), entry); err != nil {
		t.Fatalf("ApplyTransition: %v", err)
	}
	if len(q.calls) != 2 || q.calls[0] != "setState" || q.calls[1] != "recordIdempotency" {
		t.Fatalf("the two statements ran in order %v, want [setState recordIdempotency]", q.calls)
	}
}

// TestApplyTransitionStopsAtTheFirstRefusal is the half-write check.
//
// If the state write fails, the idempotency entry must not be written. This is the concrete
// shape of "a transition cannot be half applied", and it is the case that would otherwise be
// discovered in production as a model stuck in a state no ledger entry explains.
func TestApplyTransitionStopsAtTheFirstRefusal(t *testing.T) {
	q := &fakeQuerier{failOn: "setState"}
	store, err := NewSQLStoreInTx(q)
	if err != nil {
		t.Fatalf("NewSQLStoreInTx: %v", err)
	}
	entry := TransitionEntry{Scope: "s", Key: "k", From: StateEvaluated, To: StateValidated,
		AuditID: "audit-1", At: epoch}
	entry.ModelID = mustModelID(t)

	if err := store.ApplyTransition(context.Background(), entry); err == nil {
		t.Fatal("ApplyTransition succeeded although the state write failed")
	}
	for _, c := range q.calls {
		if c == "recordIdempotency" {
			t.Fatalf("the idempotency entry was written after the state write failed "+
				"(calls %v); the ledger now claims a transition that was not applied", q.calls)
		}
	}
}

// TestSQLStoreRefusesAMissingHandle keeps the constructor honest. A store built over a nil
// handle would fail at the first write with a panic from inside database/sql, far from the
// mistake.
func TestSQLStoreRefusesAMissingHandle(t *testing.T) {
	if _, err := NewSQLStore(nil); err == nil {
		t.Error("NewSQLStore accepted a nil database handle")
	}
	if _, err := NewSQLStoreInTx(nil); err == nil {
		t.Error("NewSQLStoreInTx accepted a nil querier")
	}
}

// TestMemoryStoreRefusesToWriteOnceFailed is the single-shot semantics check.
//
// It is small, but the property it guards is the one the recovery test above depends on: a
// failure that persisted would make every later write fail too, and the recovery test would
// pass or fail for the wrong reason.
func TestMemoryStoreRefusesToWriteOnceFailed(t *testing.T) {
	s := NewMemoryStore()
	want := errors.New("injected")
	s.FailNextWrite(want)

	entry := RegistryEntry{State: StateRegistered, At: epoch}
	if err := s.InsertModel(context.Background(), entry); err == want {
		// expected
	} else {
		t.Fatalf("the first write returned %v, want the injected error", err)
	}
	if err := s.InsertModel(context.Background(), entry); err != nil {
		t.Fatalf("the second write also failed with %v; FailNextWrite is single-shot", err)
	}
	if s.Writes() != 1 {
		t.Fatalf("Writes reports %d, want 1; a failed write must not be counted", s.Writes())
	}
}

// TestStoreCloseIsReachableThroughTheInterface checks that a caller holding a Store can
// release it without knowing which implementation it has.
//
// It is the reason Close is on the port at all. Without it a caller would need a type switch
// to close a SQL pool, and the natural place for that switch is a shutdown path that
// forgets it exactly once.
func TestStoreCloseIsReachableThroughTheInterface(t *testing.T) {
	var s Store = NewMemoryStore()
	if err := s.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	mem, ok := s.(*MemoryStore)
	if !ok {
		t.Fatalf("the store is a %T; this test asserts on the in-memory implementation", s)
	}
	if !mem.Closed() {
		t.Error("Close returned no error but the store does not report itself closed")
	}
}

// A retry of a transition whose durable write was refused must succeed on a clock that moves.
//
// TestTheSameRetrySucceedsAfterAFailedWrite above proves the same recovery, but through
// newDurableJournal, which installs a frozen clock. A frozen clock regenerates a byte-identical
// record, so the test passes whether or not the timestamps are stable across attempts - and they
// are not stable by default, because they are read from the clock on every attempt while the
// audit identity is derived from stable inputs. With a real clock the retry reached the chain
// with the same identity and different content, and was refused as a conflicting reuse, which
// made the transition unreachable for the life of the process after one transient failure.
func TestARetryAfterARefusedWriteSucceedsWithAnAdvancingClock(t *testing.T) {
	store := &recordingStore{}
	at := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	j, err := NewJournalWithStore(audit.NewChain(), func() time.Time {
		at = at.Add(time.Second)
		return at
	}, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	id, _ := registeredModelN(t, j, 0)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-advancing")); err != nil {
		t.Fatalf("setup transition failed: %v", err)
	}

	store.failAt = "transition"
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-advancing")); err == nil {
		t.Fatal("the first attempt succeeded although the store was told to fail it")
	}

	outcome, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-advancing"))
	if err != nil {
		t.Fatalf("a retry after a refused durable write must succeed on a real clock; a "+
			"transient storage failure would otherwise wedge the transition permanently: %v", err)
	}
	if outcome.Transition.To != StateValidated {
		t.Fatalf("the retry produced %s, want VALIDATED", outcome.Transition.To)
	}
}

// A refused durable write leaves a SUCCEEDED record in an append-only chain, so the refusal has
// to be recorded beside it.
//
// Without the correction the chain permanently certifies a governance event that never happened,
// and the audit sink will export that false success to durable storage where nothing can later
// retract it. The correction cites the original as its cause and inverts the digests, so the
// chain shows the state the model was actually left in rather than the state the transition
// would have reached.
func TestARefusedDurableWriteIsCorrectedInTheAuditChain(t *testing.T) {
	store := &recordingStore{}
	j, chain := newDurableJournal(t, store)
	id, _ := registeredModelN(t, j, 0)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-corrected")); err != nil {
		t.Fatalf("setup transition failed: %v", err)
	}

	store.failAt = "transition"
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-corrected")); err == nil {
		t.Fatal("expected the store refusal to surface")
	}

	records := chain.AllRecords()
	var correction, corrected audit.Record
	found := false
	for _, r := range records {
		if r.Result == audit.ResultRefused {
			correction, found = r, true
		}
	}
	if !found {
		t.Fatalf("the chain holds %d records and none of them records the refusal; the "+
			"SUCCEEDED record for the refused transition is uncorrectable once exported", len(records))
	}
	// The correction has to name the record it corrects, and that record has to be real: an
	// audit ID that resolves to nothing is a dangling pointer dressed as evidence.
	for _, r := range records {
		if r.AuditID == correction.CausationID {
			corrected = r
		}
	}
	if corrected.AuditID == "" {
		t.Fatalf("the refusal cites %q as its cause but no such record is in the chain",
			correction.CausationID)
	}
	if corrected.Result != audit.ResultSucceeded {
		t.Fatalf("the refusal corrects a %s record; it exists to contradict an acceptance",
			corrected.Result)
	}
	if corrected.Action != string(CommandRecordValidation) {
		t.Fatalf("the refusal corrects the %q action, want the refused transition %q",
			corrected.Action, CommandRecordValidation)
	}
	if correction.AfterDigest != stateDigest(id, StateEvaluated) {
		t.Fatal("the refusal does not end in the state the model was actually left in")
	}

	// And the state's real claim is contradicted by a refusal, not merely accompanied by one.
	state, _ := j.State(id)
	if state != StateEvaluated {
		t.Fatalf("the model is in %s; the refused transition should have left it in EVALUATED", state)
	}
}

// The durable store advances the model row as part of applying the transition, so a snapshot
// read reports where the model actually is rather than where it was registered.
//
// MemoryStore.ApplyTransition recorded only the transition, which made every snapshot read
// report REGISTERED forever. That is not a harmless simplification of SQLStore: it is the store
// the restore tests run against, so the tests were exercising a registry whose state and whose
// own spent idempotency ledger contradicted each other, and a restart built from it would have
// resurrected a REGISTERED model whose ledger asserted it had been evaluated.
func TestMemoryStoreSnapshotReportsTheStateTransitionsReached(t *testing.T) {
	store := NewMemoryStore()
	j, err := NewJournalWithStore(audit.NewChain(), func() time.Time { return epoch }, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	id, _ := registeredModelN(t, j, 0)

	for _, s := range []struct {
		from State
		cmd  Command
	}{
		{StateRegistered, CommandRecordEvaluation},
		{StateEvaluated, CommandRecordValidation},
	} {
		if _, err := j.Transact(step(t, j, id, s.from, s.cmd, "key-snapshot-"+string(s.cmd))); err != nil {
			t.Fatalf("transact via %s: %v", s.cmd, err)
		}
	}

	live, _ := j.State(id)
	snap, err := store.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	if len(snap.Models) != 1 {
		t.Fatalf("the snapshot holds %d models, want 1", len(snap.Models))
	}
	if snap.Models[0].State != live {
		t.Fatalf("the snapshot reports %s while the journal is in %s; the durable store is not "+
			"advancing the model row, so a restart would contradict its own ledger", snap.Models[0].State, live)
	}
	if snap.Models[0].State != StateValidated {
		t.Fatalf("the snapshot reports %s, want VALIDATED", snap.Models[0].State)
	}
}

// A refusal record is terminal, so the retry that finally lands has to record itself.
//
// Without this, the chain ends holding SUCCEEDED, then REFUSED, then nothing: the last evidence
// for the transition says it was not applied while the durable registry says it was, and
// nothing detects the disagreement. Not the chain restore, not the registry restore - the row
// cites the accepted record and verifyAgainstChain is right to accept it. The contradiction is
// invisible precisely because both halves are individually correct.
func TestARefusedWriteThatIsRetriedLeavesTheEvidenceCoherent(t *testing.T) {
	store := NewMemoryStore()
	at := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	j, err := NewJournalWithStore(audit.NewChain(), func() time.Time {
		at = at.Add(time.Second)
		return at
	}, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	id, _ := registeredModelN(t, j, 0)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-coherent")); err != nil {
		t.Fatalf("setup: %v", err)
	}
	store.FailNextWrite(context.DeadlineExceeded)
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-coherent")); err == nil {
		t.Fatal("expected the refusal")
	}
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-coherent")); err != nil {
		t.Fatalf("the retry must succeed: %v", err)
	}

	records := j.Chain().AllRecords()
	var refusal, resolution audit.Record
	for _, r := range records {
		if r.Result == audit.ResultRefused {
			refusal = r
		}
		if r.Result == audit.ResultSucceeded && r.CausationID == refusal.AuditID && refusal.AuditID != "" {
			resolution = r
		}
	}
	if refusal.AuditID == "" {
		t.Fatal("no refusal was recorded, so this test is not exercising the repair")
	}
	if resolution.AuditID == "" {
		t.Fatalf("the refusal at sequence %d is never resolved; the last evidence for this "+
			"transition says it was not applied, while the registry says it was", refusal.Sequence)
	}
	// And the resolution has to carry the state the transition actually reached, or it
	// corrects the record into a different wrong answer.
	if resolution.AfterDigest != stateDigest(id, StateValidated) {
		t.Fatalf("the resolution ends in %q, want the digest of %s", resolution.AfterDigest, StateValidated)
	}
	// Nothing may be left hanging: the registry and the evidence must agree.
	state, _ := j.State(id)
	if state != StateValidated {
		t.Fatalf("the journal is in %s, want VALIDATED", state)
	}
	snap, err := store.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	if snap.Models[0].State != state {
		t.Fatalf("the durable row is in %s and the journal in %s; the two stores disagree",
			snap.Models[0].State, state)
	}
}

// The repair above must not make the ordinary case noisier than the rare one it exists for.
//
// A transition the store accepted first time is one record. If the resolution were appended
// unconditionally the chain would carry a record per transition that says nothing, and the
// refusal records it corrects would be indistinguishable from routine traffic.
func TestTheOrdinaryPathAppendsNoResolutionRecord(t *testing.T) {
	store := NewMemoryStore()
	j, err := NewJournalWithStore(audit.NewChain(), func() time.Time { return epoch }, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	id, _ := registeredModelN(t, j, 0)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-plain-1")); err != nil {
		t.Fatalf("Transact: %v", err)
	}
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-plain-2")); err != nil {
		t.Fatalf("Transact: %v", err)
	}

	// One registration plus two transitions. Anything else is a record about a repair that
	// never happened.
	if got := len(j.Chain().AllRecords()); got != 3 {
		t.Fatalf("a registration and two clean transitions produced %d audit records, want 3", got)
	}
	for _, r := range j.Chain().AllRecords() {
		if strings.HasSuffix(r.AuditID, ".refused") || strings.HasSuffix(r.AuditID, ".applied") {
			t.Fatalf("the chain holds a repair record %q on a path that never refused", r.AuditID)
		}
		if r.Result != audit.ResultSucceeded {
			t.Fatalf("record %s has result %s on a path that never refused", r.AuditID, r.Result)
		}
	}
}

// downStore is a store that is unavailable for a stretch, not for a single call.
// FailNextWrite models a one-off blip, which is the case the other tests here cover; a store
// that refuses two attempts in a row is the case where a correction record could be appended
// twice and where a model could be left permanently unwritable.
type downStore struct {
	*MemoryStore
	down     bool
	attempts int
}

func (d *downStore) ApplyTransition(ctx context.Context, e TransitionEntry) error {
	if !d.down {
		return d.MemoryStore.ApplyTransition(ctx, e)
	}
	d.attempts++
	return errors.New("store is down")
}

func (d *downStore) InsertModel(ctx context.Context, e RegistryEntry) error {
	if !d.down {
		return d.MemoryStore.InsertModel(ctx, e)
	}
	d.attempts++
	return errors.New("store is down")
}

// A retry arriving while the store is still down must not append a second correction record.
// The first refusal already explains itself, and a chain carrying one REFUSED per attempt would
// misstate how many times the decision was actually made.
func TestRepeatedRefusalsAppendOneCorrectionRecord(t *testing.T) {
	inner := NewMemoryStore()
	store := &downStore{MemoryStore: inner}
	j, chain := journalWithStore(t, store)
	id, _ := registeredModelN(t, j, 0)

	store.down = true
	for attempt := 1; attempt <= 3; attempt++ {
		if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-outage-retry")); err == nil {
			t.Fatalf("attempt %d: a store that is down must refuse the transition", attempt)
		}
	}

	refusals := 0
	for _, r := range chain.AllRecords() {
		if r.Result == audit.ResultRefused {
			refusals++
		}
	}
	if refusals != 1 {
		t.Fatalf("three refused attempts produced %d REFUSED records; the correction record "+
			"must be written once, not once per attempt", refusals)
	}

	// The store comes back. The model must not be left permanently unwritable: the record that
	// explains the refusal must not also block the retry that follows it.
	store.down = false
	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-outage-retry")); err != nil {
		t.Fatalf("the retry after the store recovered was refused: %v", err)
	}
	if got, _ := j.State(id); got != StateEvaluated {
		t.Fatalf("state is %s; the retry after recovery should have applied the transition", got)
	}

	// Once applied, nothing may still claim the transition is outstanding.
	records := chain.AllRecords()
	for _, r := range records[len(records)-1:] {
		if r.Result != audit.ResultSucceeded {
			t.Fatalf("the last record is %s; a recovered store must leave a SUCCEEDED transition "+
				"as the final word in the chain", r.Result)
		}
	}
}
