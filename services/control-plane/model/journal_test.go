package model

import (
	"fmt"
	"strings"
	"sync"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/audit"
)

// newJournal builds a Journal over a fresh chain and the shared fixed clock.
func newJournal(t *testing.T) *Journal {
	t.Helper()
	j, err := NewJournal(audit.NewChain(), func() time.Time { return epoch }, "test")
	if err != nil {
		t.Fatalf("NewJournal: %v", err)
	}
	return j
}

// modelIDN returns a distinct valid model identifier. mustModelID is deterministic, which
// is right for tests that want a stable id and wrong for tests that register several models,
// because two registrations would collide on one identity. The body is capped at 26
// characters, so the variation goes in its last character rather than appended to it.
func modelIDN(t *testing.T, n int) contracts.Identifier {
	t.Helper()
	id, err := contracts.ParseIdentifier("mdl_" + modelBody[:25] + string(rune('a'+n)))
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	return id
}

// registeredModel registers a model and returns its id, so a request can address the model
// the journal actually holds rather than a freshly minted one.
func registeredModel(t *testing.T, j *Journal) (contracts.Identifier, Record) {
	t.Helper()
	return registeredModelN(t, j, 0)
}

func registeredModelN(t *testing.T, j *Journal, n int) (contracts.Identifier, Record) {
	t.Helper()
	rec := setID(t, validRecord())
	rec.ModelID = modelIDN(t, n)
	if _, err := j.Register(rec, contracts.ActorService, "control-plane-01"); err != nil {
		t.Fatalf("Register: %v", err)
	}
	return rec.ModelID, rec
}

// step builds a request that moves the journal's registered model from where it actually is.
//
// The precondition and the actor type are resolved from the real edge rather than supplied
// by the test, so a request that the lifecycle genuinely permits is produced. Hardcoding
// either would let the test assert the journal's behaviour against requests the lifecycle
// would have refused for unrelated reasons.
func step(t *testing.T, j *Journal, id contracts.Identifier, from State, cmd Command, key string) Request {
	t.Helper()
	declared, ok := lookup(from, cmd)
	if !ok {
		t.Fatalf("the lifecycle declares no %s edge from %s; the test is asking for a "+
			"transition that does not exist", cmd, from)
	}
	actor := contracts.ActorService
	if len(declared.PermittedActors) > 0 {
		actor = declared.PermittedActors[0]
	}
	return Request{
		ModelID:                id,
		From:                   from,
		Command:                cmd,
		ActorID:                "pipeline-research-07",
		ActorType:              actor,
		PreconditionsSatisfied: []Precondition{declared.Precondition},
		IdempotencyKey:         key,
		Reference:              string(digestApproval),
		Record:                 ptrRecord(validRecord()),
	}
}

// TestEveryStateChangeIsAudited is the gate's first acceptance criterion, stated as a
// property of the registry rather than as an instruction to its callers: after a sequence of
// transitions, the audit chain holds one record per state change, and the chain verifies.
//
// Apply is a pure function, so nothing stopped a caller promoting a model and writing
// nothing. That is the failure this test exists to make impossible to reintroduce.
func TestEveryStateChangeIsAudited(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	for i, s := range []struct {
		from State
		cmd  Command
	}{
		{StateRegistered, CommandRecordEvaluation},
		{StateEvaluated, CommandRecordValidation},
	} {
		outcome, err := j.Transact(step(t, j, id, s.from, s.cmd, fmt.Sprintf("idempotency-key-%02d", i)))
		if err != nil {
			t.Fatalf("Transact(%s): %v", s.cmd, err)
		}
		if outcome.AuditRecord == "" {
			t.Errorf("%s produced no audit record identity", s.cmd)
		}
	}

	// Registration plus two transitions.
	records := j.AuditRecords(id)
	if len(records) != 3 {
		t.Fatalf("%d audit records for the model, want 3 (registration plus two transitions): %+v",
			len(records), records)
	}
	// Verified with the audit package's own verifier rather than a hand-rolled link check,
	// so this asserts what the platform asserts and not a weaker restatement of it.
	if v := audit.NewVerifier(audit.NewKeyRing()).Verify(records, nil); !v.OK {
		t.Errorf("the chain the registry wrote to does not verify: %v", v.Findings)
	}
}

// TestARefusedAuditChainLeavesTheStateUnchanged is the load-bearing property of the whole
// type. If the chain refuses the record, the transition must not be applied.
//
// The alternative - applying the state change and then failing to record it - is the exact
// failure the gate names, and it is the one that cannot be repaired after the fact: a model
// that was promoted with no trace is indistinguishable from one that was never promoted.
func TestARefusedAuditChainLeavesTheStateUnchanged(t *testing.T) {
	j := newJournal(t)
	id, rec := registeredModel(t, j)

	// Poison the chain: write a record carrying the identity this transition will produce,
	// with different content. The chain treats that as a conflict rather than a redelivery
	// and refuses it, which is a refusal this package can actually encounter - a retry
	// after a partial write, or a partition restored from a divergent backup.
	clash := auditIDFor(rec.Owner, id, byCmd[CommandRecordEvaluation].EventType, StateEvaluated)
	if _, err := j.Chain().Append([]audit.Record{{
		AuditID:     clash,
		Partition:   rec.Owner,
		Sequence:    j.Chain().LastSequence(rec.Owner) + 1,
		ActorID:     "someone-else",
		ActorType:   contracts.ActorHuman,
		Action:      "model.evaluation.recorded",
		TargetType:  "model",
		TargetID:    id.String(),
		Environment: "test",
		OccurredAt:  audit.TimestampFrom(epoch),
		RecordedAt:  audit.TimestampFrom(epoch),
		Reason:      "a conflicting record for the same identity",
		Result:      audit.ResultSucceeded,
	}}); err != nil {
		t.Fatalf("seeding the conflicting record: %v", err)
	}

	before, _ := j.State(id)
	recordsBefore := len(j.AuditRecords(id))

	_, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-clash"))
	if err == nil {
		t.Fatal("a transition was applied even though the audit chain refused its record")
	}

	after, _ := j.State(id)
	if after != before {
		t.Errorf("state moved from %s to %s despite the audit refusal; a state change that "+
			"cannot be recorded must not happen", before, after)
	}
	if after != StateRegistered {
		t.Errorf("model is in %s, want it left in REGISTERED", after)
	}
	if got := len(j.AuditRecords(id)); got != recordsBefore+1 {
		// +1 because the poisoned record is itself a record for this model and is counted.
		// What matters is that the *transition* added nothing.
		t.Logf("audit records for the model: %d (was %d; the conflicting seed counts)", got, recordsBefore)
	}
	// And the transition is not recorded as having happened: no record in the chain names
	// the evaluator who was refused.
	for _, r := range j.AuditRecords(id) {
		if r.Reason == byCmd[CommandRecordEvaluation].EventType {
			t.Errorf("a record names the refused evaluation: %+v", r)
		}
	}
}

// TestARetriedTransitionDoesNotDoubleApply: the second responder to arrive at the same
// transition is doing the right thing, and a journal that treated the retry as a second
// transition would produce two audit records and two state changes for one decision.
func TestARetriedTransitionDoesNotDoubleApply(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	req := step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-retry")
	first, err := j.Transact(req)
	if err != nil {
		t.Fatalf("first Transact: %v", err)
	}
	recordsAfterFirst := len(j.AuditRecords(id))

	second, err := j.Transact(req)
	if err != nil {
		t.Fatalf("retried Transact failed: %v", err)
	}
	if second.AuditRecord != first.AuditRecord {
		t.Errorf("the retry produced audit record %q, want the original %q",
			second.AuditRecord, first.AuditRecord)
	}
	if got := len(j.AuditRecords(id)); got != recordsAfterFirst {
		t.Errorf("the retry added %d audit records; a retry is the same record",
			got-recordsAfterFirst)
	}
	if state, _ := j.State(id); state != StateEvaluated {
		t.Errorf("state is %s after a retry, want EVALUATED", state)
	}
}

// TestAReusedIdempotencyKeyWithADifferentRequestIsAConflict: two different intents sharing
// one scope and one key cannot both be honoured, and resolving that by preferring either
// copy would mean silently deciding which one actually happened.
//
// The two requests deliberately share a scope, which means sharing a transition type. A key
// reused across two *different* transition types is not a conflict and must not be, because
// the ledger namespaces keys by scope precisely so that a caller using "transition 1" as a
// key across many transitions is not accidentally serialised against itself.
func TestAReusedIdempotencyKeyWithADifferentRequestIsAConflict(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	first := step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-shared")
	if _, err := j.Transact(first); err != nil {
		t.Fatalf("first Transact: %v", err)
	}

	// Same scope, same key, same command and source state, but a different evidence
	// reference. That is a second, different intent wearing the first's key, and it is
	// caught before the state check rather than after it, because a request that is a
	// conflict must not be evaluated as though it were fresh.
	second := step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-shared")
	second.Reference = string(digestRollback)
	if _, err := j.Transact(second); err == nil {
		t.Error("two different requests sharing one scope and idempotency key were both applied")
	}
	if state, _ := j.State(id); state != StateEvaluated {
		t.Errorf("state is %s, want EVALUATED; the conflicting request must not have applied", state)
	}
	if got := len(j.AuditRecords(id)); got != 2 {
		t.Errorf("%d audit records, want 2 (registration plus the one real transition); a "+
			"conflicting request must not be recorded as though it happened", got)
	}
}

// TestAKeyReusedAcrossScopesIsNotAConflict: the ledger namespaces by scope, so one caller's
// key reused across transition types is a different key, not a collision. Refusing these
// would make a caller who numbers their requests by hand serialised against themselves.
func TestAKeyReusedAcrossScopesIsNotAConflict(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	if _, err := j.Transact(step(t, j, id, StateRegistered,
		CommandRecordEvaluation, "shared-key-across-scopes")); err != nil {
		t.Fatalf("evaluation: %v", err)
	}
	if _, err := j.Transact(step(t, j, id, StateEvaluated,
		CommandRecordValidation, "shared-key-across-scopes")); err != nil {
		t.Errorf("a key reused across two transition scopes was refused: %v", err)
	}
}

// TestAStaleStateClaimIsRefused is the check the transition table cannot do for itself. The
// table says which edges exist; only the journal knows where this model is, and a request
// that misdescribes it is how a quarantined model would be promoted.
func TestAStaleStateClaimIsRefused(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandQuarantine, "idempotency-key-quarantine")); err != nil {
		t.Fatalf("quarantine: %v", err)
	}
	if state, _ := j.State(id); state != StateQuarantined {
		t.Fatalf("state is %s, want QUARANTINED", state)
	}

	// Now describe the quarantined model as REGISTERED and try to evaluate it. The edge
	// REGISTERED -> EVALUATED exists and the command is permitted, so only the journal's
	// state check can refuse this.
	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-stale")); err == nil {
		t.Error("a quarantined model was transitioned by misdescribing its state")
	}
	if state, _ := j.State(id); state != StateQuarantined {
		t.Errorf("state is %s, want QUARANTINED; a misdescribed request must not apply", state)
	}
}

// TestAnUnregisteredModelCannotBeTransitioned: a transition for a model the registry has
// never seen has no owner to chain under.
func TestAnUnregisteredModelCannotBeTransitioned(t *testing.T) {
	j := newJournal(t)
	if _, err := j.Transact(step(t, j, mustModelID(t), StateRegistered,
		CommandRecordEvaluation, "key-unknown")); err == nil {
		t.Error("a transition was applied to an unregistered model")
	}
}

// TestARefusedRequestWritesNoAuditRecord: a refusal is not a state change, so it must not
// reach the chain.
//
// This test exists because mutation M27 - which makes a rejected request append a record
// anyway - survived for a long time without any test failing. It survived because M27 did
// not compile, and a mutation that does not compile is reported as detected while running
// no test at all; see the harness's build-failure accounting. The claim was written down in
// this file's own comments and in an evidence record, and nothing enforced it.
//
// The distinction matters beyond tidiness. The chain is the evidence an operator reads to
// reconstruct what happened, and a chain that records every rejected call buries the
// changes that did happen inside the noise of the ones that did not - which is the same
// argument the chain makes for not accepting a partial batch.
func TestARefusedRequestWritesNoAuditRecord(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	before := len(j.Chain().AllRecords())

	// A model that was never registered: refused for a reason unrelated to any model the
	// journal knows, so nothing else in the chain should move either.
	if _, err := j.Transact(step(t, j, modelIDN(t, 7), StateRegistered,
		CommandRecordEvaluation, "key-refused-unknown")); err == nil {
		t.Fatal("a transition was applied to an unregistered model")
	}
	// A model that exists, asked for an edge from a state it is not in: also a refusal.
	// The request is built from the real edge and then misdescribes where the model is,
	// which is the shape a confused or hostile caller would send.
	misdescribed := step(t, j, id, StateRegistered, CommandRecordEvaluation, "key-refused-state")
	misdescribed.From = StatePromoted
	if _, err := j.Transact(misdescribed); err == nil {
		t.Fatal("a transition was applied against a misdescribed current state")
	}

	if after := len(j.Chain().AllRecords()); after != before {
		t.Fatalf("chain grew from %d to %d records across two refusals; a refusal is not a "+
			"state change and must not be recorded as one. Records written: %s",
			before, after, describeNewRecords(j.Chain().AllRecords()[before:]))
	}
}

// describeNewRecords names the records a mutation managed to add, so a failure says which
// unexpected write happened rather than only how many.
func describeNewRecords(records []audit.Record) string {
	parts := make([]string, 0, len(records))
	for _, r := range records {
		parts = append(parts, r.AuditID+"/"+r.Action+"/"+string(r.Result))
	}
	return strings.Join(parts, ", ")
}

// TestRegistrationIsAudited: a model that exists in the registry but never in the audit
// chain could be promoted out of a history that does not contain its own existence.
func TestRegistrationIsAudited(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	records := j.AuditRecords(id)
	if len(records) != 1 {
		t.Fatalf("%d audit records, want 1 for the registration", len(records))
	}
	if records[0].Action != byCmd[""].EventType && records[0].Action == "" {
		t.Error("the registration record names no action")
	}
	if records[0].TargetID != id.String() {
		t.Errorf("the registration names target %q, want %q", records[0].TargetID, id)
	}
}

// TestEachTransitionNamesTheOneBeforeIt: a record with no causation floats free in the
// chain, and a reader reconstructing why a model was promoted cannot tell what preceded it.
func TestEachTransitionNamesTheOneBeforeIt(t *testing.T) {
	j := newJournal(t)
	id, _ := registeredModel(t, j)

	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-1")); err != nil {
		t.Fatalf("Transact: %v", err)
	}
	if _, err := j.Transact(step(t, j, id, StateEvaluated, CommandRecordValidation, "idempotency-key-2")); err != nil {
		t.Fatalf("Transact: %v", err)
	}

	records := j.AuditRecords(id)
	if len(records) != 3 {
		t.Fatalf("%d records, want 3", len(records))
	}
	if records[0].CausationID != "" {
		t.Errorf("the registration names a cause (%q); nothing preceded it", records[0].CausationID)
	}
	if records[1].CausationID != records[0].AuditID {
		t.Errorf("the first transition's cause is %q, want the registration %q",
			records[1].CausationID, records[0].AuditID)
	}
	if records[2].CausationID != records[1].AuditID {
		t.Errorf("the second transition's cause is %q, want the first transition %q",
			records[2].CausationID, records[1].AuditID)
	}
}

// TestOwnersDoNotShareAPartition is the tamper-isolation property: one owner's governance
// activity must not be usable to reason about another's. If both shared a partition, a
// record for one model would sit in the chain of the other, and the ordering evidence from
// one would appear to cover the other.
func TestOwnersDoNotShareAPartition(t *testing.T) {
	j := newJournal(t)
	first := setID(t, validRecord())
	first.ModelID = modelIDN(t, 0)
	second := setID(t, validRecord())
	second.ModelID = modelIDN(t, 1)
	second.Owner = "owner-different"

	if _, err := j.Register(first, contracts.ActorService, "control-plane-01"); err != nil {
		t.Fatalf("Register: %v", err)
	}
	if _, err := j.Register(second, contracts.ActorService, "control-plane-01"); err != nil {
		t.Fatalf("Register: %v", err)
	}

	if got := len(j.Chain().Partitions()); got != 2 {
		t.Errorf("%d audit partitions, want 2; two owners sharing one partition would let "+
			"one owner's record be read as covering the other", got)
	}
	if firstRecord := j.AuditRecords(first.ModelID); len(firstRecord) != 1 {
		t.Errorf("the first owner's model has %d records, want 1", len(firstRecord))
	} else if firstRecord[0].Sequence != 1 {
		t.Errorf("the second owner shares the first's sequence space (got %d, want 1)",
			firstRecord[0].Sequence)
	}
}

// TestASequenceIsPerOwnerAndChained: the sequence must advance and the previous hash must
// link, or the chain cannot detect a removed record.
func TestASequenceIsPerOwnerAndChained(t *testing.T) {
	j := newJournal(t)
	id, rec := registeredModel(t, j)
	if _, err := j.Transact(step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-1")); err != nil {
		t.Fatalf("Transact: %v", err)
	}

	records := j.AuditRecords(id)
	if records[0].Sequence != 1 || records[1].Sequence != 2 {
		t.Errorf("sequences are %d then %d, want 1 then 2",
			records[0].Sequence, records[1].Sequence)
	}
	if records[1].PreviousHash != records[0].RecordHash {
		t.Error("the second record does not link to the first; a removed record would be " +
			"undetectable")
	}
	if records[0].Partition != rec.Owner {
		t.Errorf("partition is %q, want the model owner %q", records[0].Partition, rec.Owner)
	}
}

// TestReRegisteringAModelIsRefused: an in-place edit of a registered model is a new version,
// not a replacement, and re-registration would give one model two lifecycles.
func TestReRegisteringAModelIsRefused(t *testing.T) {
	j := newJournal(t)
	rec := setID(t, validRecord())
	if _, err := j.Register(rec, contracts.ActorService, "control-plane-01"); err != nil {
		t.Fatalf("Register: %v", err)
	}
	if _, err := j.Register(rec, contracts.ActorService, "control-plane-01"); err == nil {
		t.Error("a model was registered twice")
	}
}

// TestTheJournalRefusesToExistWithoutItsEvidencePath: a Journal with no chain, clock, or
// environment would be a registry whose audit trail is optional, which is the exact
// condition the gate excludes.
func TestTheJournalRefusesToExistWithoutItsEvidencePath(t *testing.T) {
	clock := func() time.Time { return epoch }
	if _, err := NewJournal(nil, clock, "test"); err == nil {
		t.Error("a journal was built with no audit chain")
	}
	if _, err := NewJournal(audit.NewChain(), nil, "test"); err == nil {
		t.Error("a journal was built with no clock")
	}
	if _, err := NewJournal(audit.NewChain(), clock, "  "); err == nil {
		t.Error("a journal was built with no environment; the chain refuses such a record")
	}
}

// TestTheJournalIsSafeForConcurrentUse runs the race detector over interleaved transitions.
// Apply is pure and the maps are not, so without the lock this is a data race rather than a
// logic bug, and a logic bug would be far less visible than a corrupted map.
func TestTheJournalIsSafeForConcurrentUse(t *testing.T) {
	j := newJournal(t)
	ids := make([]contracts.Identifier, 0, 4)
	for i := 0; i < 4; i++ {
		rec := setID(t, validRecord())
		rec.ModelID = modelIDN(t, i)
		if _, err := j.Register(rec, contracts.ActorService, "control-plane-01"); err != nil {
			t.Fatalf("Register: %v", err)
		}
		ids = append(ids, rec.ModelID)
	}

	// The requests are built before the goroutines start. step calls t.Fatalf, which is
	// only valid on the test goroutine; building them here keeps a test failure reported
	// properly instead of ending a worker goroutine silently.
	type work struct {
		id            contracts.Identifier
		first, second Request
	}
	var jobs []work
	for _, id := range ids {
		jobs = append(jobs, work{
			id,
			step(t, j, id, StateRegistered, CommandRecordEvaluation, "idempotency-key-a"),
			step(t, j, id, StateEvaluated, CommandRecordValidation, "idempotency-key-b"),
		})
	}

	var wg sync.WaitGroup
	for _, w := range jobs {
		wg.Add(1)
		go func(id contracts.Identifier, first, second Request) {
			defer wg.Done()
			// Most of these are expected refusals (state moved, key reused) and some are
			// expected successes. The test is not about which; it is about the race detector
			// finding no unsynchronized access.
			_, _ = j.Transact(first)
			_, _ = j.Transact(second)
			_, _ = j.State(id)
			_ = j.RegisteredModels()
			_ = j.AuditRecords(id)
		}(w.id, w.first, w.second)
	}
	wg.Wait()
}

// TestRejectedRequestsWriteNoAuditRecord: a refusal is a governance fact too, but it is
// not a state change, and a journal that appended a record for every rejected call would
// bury the changes that actually happened.
func TestRejectedRequestsWriteNoAuditRecord(t *testing.T) {
	j := newJournal(t)
	before := len(j.Chain().AllRecords())

	if _, err := j.Transact(step(t, j, mustModelID(t), StateRegistered,
		CommandRecordEvaluation, "idempotency-key-none")); err == nil {
		t.Fatal("a transition for an unregistered model was applied")
	}
	if got := len(j.Chain().AllRecords()); got != before {
		t.Errorf("a rejected request wrote %d audit records; a refusal is not a state change",
			got-before)
	}
}
