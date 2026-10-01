package model

import (
	"context"
	"errors"
	"sort"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// evaluationScope reads the idempotency scope the lifecycle declares for a transition.
//
// Read rather than hardcoded, because the scope is a property of the lifecycle rather than
// of the command name, and a test that repeats it would agree with the implementation
// without exercising it.
func evaluationScope(t *testing.T) string {
	t.Helper()
	tr, ok := lookup(StateRegistered, CommandRecordEvaluation)
	if !ok {
		t.Fatal("the lifecycle declares no evaluation edge")
	}
	return tr.IdempotencyScope
}

// journalWithStore builds a journal whose writes land in a store, over a chain the caller keeps.
//
// The chain is returned because a restart has to restore it too: Restore verifies the registry
// against audit records, so testing a restart means rebuilding both halves from what was
// written, not handing Restore a chain that is still warm in memory.
func journalWithStore(t *testing.T, store Store) (*Journal, *audit.Chain) {
	t.Helper()
	chain := audit.NewChain()
	j, err := NewJournalWithStore(chain, func() time.Time { return epoch }, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	return j, chain
}

// restart throws away everything in memory and rebuilds from the durable state alone.
func restart(t *testing.T, store SnapshotReader, stored []audit.Record) *Journal {
	t.Helper()
	chain := audit.NewChain()
	if err := chain.Restore(stored); err != nil {
		t.Fatalf("restoring the chain: %v", err)
	}
	ctx := context.Background()
	j, err := RehydratedJournal(ctx, chain, func() time.Time { return epoch }, "test", nil, store)
	if err != nil {
		t.Fatalf("RehydratedJournal: %v", err)
	}
	return j
}

func TestRestoreRecoversModelState(t *testing.T) {
	store := NewMemoryStore()
	j, chain := journalWithStore(t, store)
	id, _ := registeredModelN(t, j, 1)

	restored := restart(t, store, chain.AllRecords())

	if _, ok := restored.Record(id); !ok {
		t.Fatalf("model %s did not survive the restart", id)
	}
	if state, ok := restored.State(id); !ok || state != StateRegistered {
		t.Fatalf("restored state is %q (present=%t), want REGISTERED", state, ok)
	}
}

func TestRestoreRecoversTheIdempotencyLedger(t *testing.T) {
	// The severe one. Without the ledger a retried transition is not recognised as a retry,
	// so a caller retrying after a restart gets a second execution of an operation that
	// already committed - which for a promotion or an approval is not a duplicate, it is a
	// second unauthorised event.
	store := NewMemoryStore()
	j, chain := journalWithStore(t, store)
	id, _ := registeredModelN(t, j, 1)

	// The request is built once and replayed verbatim, because that is what a retry is: the
	// same intent under the same key. Note that From is REGISTERED, and that the model is
	// EVALUATED by the time of the replay - so the request no longer describes where the model
	// is. The journal returns the recorded outcome from the spent ledger before it ever
	// compares From against the current state, and that ordering is what is under test.
	retry := step(t, j, id, StateRegistered, CommandRecordEvaluation, "op-key-1")
	if _, err := j.Transact(retry); err != nil {
		t.Fatalf("Transact: %v", err)
	}

	restored := restart(t, store, chain.AllRecords())

	key := idempotencyKey(evaluationScope(t), "op-key-1")
	if _, ok := restored.applied[key]; !ok {
		t.Fatal("the idempotency ledger did not survive the restart")
	}
	// The restored state is the state the transition actually reached, not the state the model
	// was registered in. The durable store advances the model row as part of applying the
	// transition, so a snapshot read has to see that or a restart resurrects a REGISTERED model
	// whose own spent ledger says it was evaluated.
	state, _ := restored.State(id)
	if state != StateEvaluated {
		t.Fatalf("restored model is in %s, want EVALUATED; the stored state did not survive "+
			"the restart, so the registry disagrees with its own ledger", state)
	}
	// And the retry is actually recognised, which is the property the ledger exists for.
	again, err := restored.Transact(retry)
	if err != nil {
		t.Fatalf("replaying a spent key must return the recorded outcome, not an error: %v", err)
	}
	if again.AuditRecord == "" {
		t.Fatal("the replayed outcome carries no audit record; a retry must cite the evidence " +
			"of the original, not invent a new one")
	}
	if got := len(restored.Chain().AllRecords()); got != len(chain.AllRecords()) {
		t.Fatalf("the replay appended a new audit record: %d records, want %d", got, len(chain.AllRecords()))
	}
}

func TestRestoreRefusesARegistryTheChainDoesNotCorroborate(t *testing.T) {
	// The reason Restore checks the chain at all. The registry is mutable and the chain is
	// not, so where they disagree the chain is the one that is right.
	store := NewMemoryStore()
	j, chain := journalWithStore(t, store)
	id, _ := registeredModelN(t, j, 1)

	snapshot, err := store.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	snapshot.Models[0].State = StatePromoted // never established by any audit record

	fresh := audit.NewChain()
	if err := fresh.Restore(chain.AllRecords()); err != nil {
		t.Fatalf("restoring the chain: %v", err)
	}
	target, err := NewJournalWithStore(fresh, func() time.Time { return epoch }, "test", nil)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	err = target.Restore(snapshot)
	if err == nil {
		t.Fatal("a registry claiming a state its audit record does not support must be refused; " +
			"loading it would make the journal attest to something that never happened")
	}
	if !strings.Contains(err.Error(), "after-digest") {
		t.Fatalf("the refusal should name the digest mismatch, got: %v", err)
	}
	_ = id
}

func TestRestoreRefusesAModelWithNoAuditRecord(t *testing.T) {
	snapshot := Snapshot{Models: []ModelSnapshot{{
		Record:  setID(t, validRecord()),
		State:   StateRegistered,
		AuditID: "",
	}}}
	j, err := NewJournal(audit.NewChain(), func() time.Time { return epoch }, "test")
	if err != nil {
		t.Fatalf("NewJournal: %v", err)
	}
	if err := j.Restore(snapshot); err == nil {
		t.Fatal("a model with no audit record means the registry and the evidence disagree")
	}
}

func TestRestoreRefusesAnUnknownAuditRecord(t *testing.T) {
	snapshot := Snapshot{Models: []ModelSnapshot{{
		Record:  setID(t, validRecord()),
		State:   StateRegistered,
		AuditID: "aud-does-not-exist",
	}}}
	j, err := NewJournal(audit.NewChain(), func() time.Time { return epoch }, "test")
	if err != nil {
		t.Fatalf("NewJournal: %v", err)
	}
	err = j.Restore(snapshot)
	if err == nil {
		t.Fatal("a model citing an audit record the chain does not hold must be refused")
	}
	if !strings.Contains(err.Error(), "not in the chain") {
		t.Fatalf("the refusal should name the missing record, got: %v", err)
	}
}

func TestRestoreRefusesADuplicateModel(t *testing.T) {
	store := NewMemoryStore()
	j, chain := journalWithStore(t, store)
	id, rec := registeredModelN(t, j, 1)

	snapshot, err := store.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	snapshot.Models = append(snapshot.Models, ModelSnapshot{
		Record:  rec,
		State:   StateRegistered,
		AuditID: snapshot.Models[0].AuditID,
	})

	fresh := audit.NewChain()
	if err := fresh.Restore(chain.AllRecords()); err != nil {
		t.Fatalf("restoring the chain: %v", err)
	}
	target, _ := NewJournalWithStore(fresh, func() time.Time { return epoch }, "test", nil)
	if err := target.Restore(snapshot); err == nil {
		t.Fatal("a snapshot naming one model twice must be refused")
	}
	// "Unknown" and "never registered" are indistinguishable downstream, so a partial
	// restore is worse than none.
	if len(target.RegisteredModels()) != 0 {
		t.Fatal("a refused restore left models loaded")
	}
	_ = id
}

func TestARestoredJournalContinuesTheSameChain(t *testing.T) {
	store := NewMemoryStore()
	j, chain := journalWithStore(t, store)
	id, _ := registeredModelN(t, j, 1)
	before := len(chain.AllRecords())

	restored := restart(t, store, chain.AllRecords())

	if _, err := restored.Transact(step(t, restored, id, StateRegistered, CommandRecordEvaluation, "op-key-9")); err != nil {
		t.Fatalf("Transact after a restart: %v", err)
	}
	if got := len(restored.Chain().AllRecords()); got != before+1 {
		t.Fatalf("the post-restart transition produced %d records, want %d", got, before+1)
	}
}

func TestARestoredSnapshotPreservesTerminalStates(t *testing.T) {
	// Directly, so the property does not depend on a transition sequence. ListActiveModels
	// excludes RETIRED and QUARANTINED, and both are the rows that most have to survive: a
	// retired model that looks unregistered can be registered again.
	store := NewMemoryStore()
	for i, state := range []State{
		StateRegistered, StatePromoted, StateRetired, StateQuarantined,
	} {
		rec := setID(t, validRecord())
		rec.ModelID = modelIDN(t, i)
		if err := store.InsertModel(context.Background(), RegistryEntry{
			Record: rec, State: state, AuditID: "aud-" + string(state),
			At: epoch, RegisteredAt: epoch,
		}); err != nil {
			t.Fatalf("InsertModel %s: %v", state, err)
		}
	}
	snapshot, err := store.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	seen := map[State]bool{}
	for _, m := range snapshot.Models {
		seen[m.State] = true
	}
	for _, want := range []State{StateRegistered, StatePromoted, StateRetired, StateQuarantined} {
		if !seen[want] {
			t.Errorf("state %s is missing from the snapshot; a terminal state dropped here "+
				"makes a retired model look unregistered", want)
		}
	}
}

func TestLoadSnapshotIsStableAcrossRuns(t *testing.T) {
	// MemoryStore iterates maps, whose order Go randomises between runs. Two loads of the
	// same durable state must be identical, or nothing built on them can be compared.
	store := NewMemoryStore()
	for i := 0; i < 3; i++ {
		rec := setID(t, validRecord())
		rec.ModelID = modelIDN(t, 4+i)
		if err := store.InsertModel(context.Background(), RegistryEntry{
			Record: rec, State: StateRegistered, AuditID: "aud-" + string(rune('a'+i)),
			At: epoch, RegisteredAt: epoch,
		}); err != nil {
			t.Fatalf("InsertModel: %v", err)
		}
	}
	first, err := store.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	for i := 0; i < 8; i++ {
		again, err := store.LoadSnapshot(context.Background())
		if err != nil {
			t.Fatalf("LoadSnapshot: %v", err)
		}
		if len(again.Models) != len(first.Models) {
			t.Fatalf("load %d returned %d models, want %d", i, len(again.Models), len(first.Models))
		}
		for k := range first.Models {
			if again.Models[k].Record.ModelID != first.Models[k].Record.ModelID {
				t.Fatalf("load %d returned models in a different order", i)
			}
		}
	}
}

func TestLoadSnapshotPropagatesAReadFailure(t *testing.T) {
	store := NewMemoryStore()
	want := errors.New("registry unavailable")
	store.FailReads(want)
	if _, err := store.LoadSnapshot(context.Background()); !errors.Is(err, want) {
		t.Fatalf("a read failure must surface, got %v", err)
	}
}

func TestRehydratedJournalGuards(t *testing.T) {
	store := NewMemoryStore()
	ctx := context.Background()
	if _, err := RehydratedJournal(ctx, audit.NewChain(), func() time.Time { return epoch }, "test", store, nil); err == nil {
		t.Fatal("rehydrating without a reader would produce an empty journal, which is " +
			"indistinguishable from a registry that has never been written")
	}
	want := errors.New("registry unavailable")
	store.FailReads(want)
	if _, err := RehydratedJournal(ctx, audit.NewChain(), func() time.Time { return epoch }, "test", store, store); !errors.Is(err, want) {
		t.Fatalf("a failed load must be returned rather than producing an empty journal, got %v", err)
	}
	// A chain that was never restored fails corroboration rather than loading nothing, and
	// the refusal has to say so. This needs a registry that actually holds something: an
	// empty store against an empty chain is genuinely consistent, and returning nil there is
	// right rather than a hole.
	populated := NewMemoryStore()
	j, chain := journalWithStore(t, populated)
	registeredModelN(t, j, 3)
	if _, err := RehydratedJournal(ctx, audit.NewChain(), func() time.Time { return epoch }, "test",
		populated, populated); err == nil ||
		!strings.Contains(err.Error(), "not in the chain") {
		t.Fatalf("restoring against an unrestored chain should report missing evidence, got %v", err)
	}
	// And the same store restores cleanly once the chain is present, which is what makes the
	// refusal a statement about the chain rather than about the registry.
	if _, err := RehydratedJournal(ctx, chain, func() time.Time { return epoch }, "test",
		populated, populated); err != nil {
		t.Fatalf("restoring with the chain present must succeed: %v", err)
	}
}

func TestChainRecordByAuditID(t *testing.T) {
	// The lookup is exercised against a record the journal really wrote, rather than one
	// built by hand, so the identifier under test is the one the system derives.
	j := newJournal(t)
	id, _ := registeredModelN(t, j, 2)
	records := j.Chain().AllRecords()
	if len(records) == 0 {
		t.Fatal("registration wrote no audit record to look up")
	}
	want := records[len(records)-1]

	got, ok := j.Chain().RecordByAuditID(want.AuditID)
	if !ok {
		t.Fatalf("record %s was not found by its audit id", want.AuditID)
	}
	if got.RecordHash != want.RecordHash || got.Sequence != want.Sequence {
		t.Fatalf("the lookup returned a different record than was written:\n got %+v\nwant %+v", got, want)
	}
	if _, ok := j.Chain().RecordByAuditID("aud-does-not-exist"); ok {
		t.Fatal("an unknown audit id must report absence")
	}
	if _, ok := j.Chain().RecordByAuditID("   "); ok {
		t.Fatal("a blank audit id must report absence rather than matching something")
	}
	_ = id
}

func TestSQLSnapshotReaderMapsEveryRow(t *testing.T) {
	id := modelIDN(t, 9).String()
	q := &fakeSnapshotQuerier{
		models: []dbgen.ModelRegistry{{
			ModelID:                    id,
			Version:                    "1.0.0",
			Owner:                      "owner-1",
			Author:                     "pipeline-1",
			TrainingDatasetFingerprint: "sha256:abc",
			CodeRevision:               "deadbeef",
			FeatureSpecification:       "spec-1",
			EvaluationResults:          "sha256:def",
			Limitations:                "none known",
			ApprovalRecord:             "sha256:aaa",
			DeploymentScope:            "SIMULATION",
			MonitoringPolicy:           "policy-1",
			RollbackArtifact:           "sha256:bbb",
			State:                      string(StateRegistered),
			RegisteredAtUtc:            epoch,
			LastAuditID:                "aud-1",
			UpdatedBy:                  "auditor-1",
			UpdatedAtUtc:               epoch,
		}},
		ledger: map[string][]dbgen.ModelTransitionIdempotency{
			id: {{
				IdempotencyScope:   "model.evaluation.recorded",
				IdempotencyKey:     "op-key-1",
				RequestFingerprint: "fp-1",
				ModelID:            id,
				ToState:            string(StateEvaluated),
				AuditID:            "aud-1",
				AppliedAtUtc:       epoch,
			}},
		},
	}
	reader, err := NewSQLSnapshotReaderInTx(q)
	if err != nil {
		t.Fatalf("NewSQLSnapshotReaderInTx: %v", err)
	}
	snapshot, err := reader.LoadSnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadSnapshot: %v", err)
	}
	if len(snapshot.Models) != 1 {
		t.Fatalf("read %d models, want 1", len(snapshot.Models))
	}
	got := snapshot.Models[0]
	if got.Record.ModelID.String() != id {
		t.Fatalf("model id was not mapped: %s, want %s", got.Record.ModelID, id)
	}
	if got.Record.TrainingDatasetFingerprint != "sha256:abc" {
		t.Fatalf("the dataset fingerprint was not mapped: %q", got.Record.TrainingDatasetFingerprint)
	}
	if got.Record.CodeRevision != "deadbeef" || got.Record.MonitoringPolicy != "policy-1" {
		t.Fatalf("declaration fields were not mapped: %+v", got.Record)
	}
	if got.State != StateRegistered || got.AuditID != "aud-1" || got.UpdatedBy != "auditor-1" {
		t.Fatalf("state/audit/actor not mapped: %s / %s / %s", got.State, got.AuditID, got.UpdatedBy)
	}
	if len(snapshot.Idempotency) != 1 {
		t.Fatalf("read %d ledger entries, want 1", len(snapshot.Idempotency))
	}
	entry := snapshot.Idempotency[0]
	if entry.Fingerprint != "fp-1" || entry.To != StateEvaluated || entry.Key != "op-key-1" {
		t.Fatalf("the ledger entry was not mapped: %+v", entry)
	}
	if !entry.At.Equal(epoch) {
		t.Fatalf("the applied time was not mapped: %v", entry.At)
	}
}

func TestSQLSnapshotReaderRefusesARowThatIsNotAModel(t *testing.T) {
	reader, _ := NewSQLSnapshotReaderInTx(&fakeSnapshotQuerier{
		models: []dbgen.ModelRegistry{{ModelID: "not-an-identifier"}},
	})
	if _, err := reader.LoadSnapshot(context.Background()); err == nil {
		t.Fatal("a row whose model_id is not an identifier must be refused; it cannot be " +
			"placed in a partition or compared against a chain record")
	}
}

func TestSQLSnapshotReaderPropagatesAQueryError(t *testing.T) {
	want := errors.New("connection reset by peer")
	reader, _ := NewSQLSnapshotReaderInTx(&fakeSnapshotQuerier{err: want})
	if _, err := reader.LoadSnapshot(context.Background()); !errors.Is(err, want) {
		t.Fatalf("the underlying cause is lost: %v", err)
	}
}

func TestSnapshotReaderConstructionGuards(t *testing.T) {
	if _, err := NewSQLSnapshotReader(nil); err == nil {
		t.Fatal("a nil database handle must be refused")
	}
	if _, err := NewSQLSnapshotReaderInTx(nil); err == nil {
		t.Fatal("a nil querier must be refused")
	}
}

// fakeSnapshotQuerier serves registry rows without a database.
type fakeSnapshotQuerier struct {
	models []dbgen.ModelRegistry
	ledger map[string][]dbgen.ModelTransitionIdempotency
	err    error
	calls  int
}

func (q *fakeSnapshotQuerier) ListAllModels(context.Context) ([]dbgen.ModelRegistry, error) {
	q.calls++
	if q.err != nil {
		return nil, q.err
	}
	return q.models, nil
}

// ListAllIdempotency flattens the per-model map the fake was built with. The keys are walked in
// sorted order rather than map order so a failure in a test that inspects call order is not
// itself a coin toss; sortSnapshot normalises the snapshot regardless, so this is about the
// test's own legibility rather than about determinism the reader depends on.
func (q *fakeSnapshotQuerier) ListAllIdempotency(
	_ context.Context,
) ([]dbgen.ModelTransitionIdempotency, error) {
	q.calls++
	if q.err != nil {
		return nil, q.err
	}
	keys := make([]string, 0, len(q.ledger))
	for k := range q.ledger {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var all []dbgen.ModelTransitionIdempotency
	for _, k := range keys {
		all = append(all, q.ledger[k]...)
	}
	return all, nil
}

// These two cover the intersection EV-054 recorded as resting on a probe that was deleted:
// a restart taken between a refusal and its resolution. The suite had refusal-then-retry
// coherence without a restart, and restarts without a refusal, and never the composition.

// A refusal and its resolution are the only case where the chain holds a record saying a
// transition did not happen alongside one saying it did. Restarting in that window is where
// that contradiction would either survive or be resolved by the rehydration itself.
func TestARestartBetweenARefusalAndItsResolutionKeepsTheEvidenceCoherent(t *testing.T) {
	store := NewMemoryStore()
	at := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	chain := audit.NewChain()
	j, err := NewJournalWithStore(chain, func() time.Time {
		at = at.Add(time.Second)
		return at
	}, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	id, _ := registeredModelN(t, j, 0)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-mid-refusal")); err != nil {
		t.Fatalf("setup: %v", err)
	}
	store.FailNextWrite(context.DeadlineExceeded)
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-mid-refusal")); err == nil {
		t.Fatal("expected the durable store to refuse the transition")
	}
	outcome, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "key-mid-refusal"))
	if err != nil {
		t.Fatalf("the retry must succeed: %v", err)
	}

	restored := restart(t, store, chain.AllRecords())

	// The state survives the window. This is the part a resolution record exists to make true.
	if got, ok := restored.State(id); !ok || got != StateValidated {
		t.Fatalf("state after restart is %q (present=%t); the retry had already applied", got, ok)
	}

	// Both halves of the correction survive, not just the state they describe.
	refusals, resolutions := 0, 0
	for _, r := range restored.Chain().AllRecords() {
		switch r.Result {
		case audit.ResultRefused:
			refusals++
		case audit.ResultSucceeded:
			if r.CausationID != "" && strings.HasSuffix(r.CausationID, ".refused") {
				resolutions++
			}
		}
	}
	if refusals != 1 || resolutions != 1 {
		t.Fatalf("after restart the chain holds %d refusals and %d resolutions; a restart must "+
			"not drop the explanation of the failed write or the record that closes it",
			refusals, resolutions)
	}

	// The idempotency ledger has to have survived too, or a client that retries after the
	// restart gets a second record for a transition that already applied.
	before := len(restored.Chain().AllRecords())
	replayed, err := restored.Transact(step(t, restored, id, StateEvaluated, CommandRecordValidation, "key-mid-refusal"))
	if err != nil {
		t.Fatalf("replaying the request after a restart failed: %v", err)
	}
	if replayed.AuditRecord != outcome.AuditRecord {
		t.Fatalf("the replay after restart cited %s, the original cited %s; the idempotency "+
			"ledger did not survive the restart", replayed.AuditRecord, outcome.AuditRecord)
	}
	if after := len(restored.Chain().AllRecords()); after != before {
		t.Fatalf("the replay appended %d record(s); a retry of an applied transition must be "+
			"answered from the ledger, not by writing a second record", after-before)
	}
}

// Registration shares the commit path with a transition but not its digests, so it earns its
// own restart. A model whose first durable write failed and was retried must still be a
// registered model after the process that registered it is gone.
func TestARestartAfterARefusedRegistrationKeepsTheModel(t *testing.T) {
	store := NewMemoryStore()
	at := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	chain := audit.NewChain()
	j, err := NewJournalWithStore(chain, func() time.Time {
		at = at.Add(time.Second)
		return at
	}, "test", store)
	if err != nil {
		t.Fatalf("NewJournalWithStore: %v", err)
	}
	rec := setID(t, validRecord())
	rec.ModelID = modelIDN(t, 0)

	store.FailNextWrite(context.DeadlineExceeded)
	if _, err := j.Register(rec, contracts.ActorService, "control-plane-01"); err == nil {
		t.Fatal("expected the durable store to refuse the registration")
	}
	if _, err := j.Register(rec, contracts.ActorService, "control-plane-01"); err != nil {
		t.Fatalf("the registration retry must succeed: %v", err)
	}

	restored := restart(t, store, chain.AllRecords())
	if got, ok := restored.State(rec.ModelID); !ok || got != StateRegistered {
		t.Fatalf("state after restart is %q (present=%t); the retry had already registered it",
			got, ok)
	}
	if got, ok := restored.Record(rec.ModelID); !ok {
		t.Fatal("the registered record did not survive the restart; the owner, and therefore " +
			"the audit partition the model belongs to, would be lost")
	} else if got.Owner != rec.Owner {
		t.Fatalf("restored owner is %s, was %s; a restart must not move a model between "+
			"audit partitions", got, rec.Owner)
	}
}
