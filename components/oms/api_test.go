package oms

import (
	"errors"
	"fmt"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The rejection type carries two things on purpose: a canonical ErrorCode for callers on
// another service, and a local sentinel so errors.Is keeps working in process. Formatting an
// ErrorCode with %w is not valid Go, and formatting it with %s would discard the part that
// must survive, so both are carried explicitly and both are tested here.

func TestARejectionIsAttributableToOrderHandling(t *testing.T) {
	order := toRiskPending(t)
	req := request(t, order, CmdSubmitToVenue)
	_, err := Apply(order, req)
	if err == nil {
		t.Fatal("submitting from RISK_PENDING is undeclared and must be refused")
	}

	// The sentinel survives wrapping by a caller, which is the whole point of Unwrap.
	wrapped := fmt.Errorf("submitting order: %w", err)
	if !errors.Is(wrapped, ErrInvalidOrderInput) {
		t.Error("a wrapped rejection must still match the local sentinel")
	}
	if !errors.Is(wrapped, contracts.ErrInvalidContractValue) {
		t.Error("a wrapped rejection must still match the canonical contract sentinel")
	}

	var r Rejection
	if !errors.As(wrapped, &r) {
		t.Fatal("a wrapped rejection must still be extractable as a Rejection")
	}
	if r.Code == "" {
		t.Error("a rejection must carry a canonical code")
	}
	// The code is the first thing in the message so a log consumer pattern-matching on the
	// stable prefix stays correct if the wording changes.
	if got := r.Error(); len(got) < len(string(r.Code)) || got[:len(r.Code)] != string(r.Code) {
		t.Errorf("the message should lead with the code %q, got %q", r.Code, got)
	}
}

func TestAnUnattributedTransitionIsRefused(t *testing.T) {
	// An unattributed order lifecycle change is not auditable, so a missing actor id and an
	// unknown actor type are each a refusal rather than a default.
	order := toRiskPending(t)

	for name, actor := range map[string]Actor{
		"no actor id":        {ID: "  ", Type: contracts.ActorService},
		"no actor type":      {ID: "svc-1"},
		"unknown actor type": {ID: "svc-1", Type: contracts.ActorType("ROBOT")},
	} {
		t.Run(name, func(t *testing.T) {
			req := request(t, order, CmdSubmitForRisk)
			req.Actor = actor
			_, err := Apply(order, req)
			if err == nil {
				t.Fatalf("a transition with %s must be refused", name)
			}
		})
	}
}

func TestAMissingOrderIdIsRefused(t *testing.T) {
	order := toRiskPending(t)
	req := request(t, order, CmdCancel)
	req.OrderID = contracts.Identifier{}
	if _, err := Apply(order, req); err == nil {
		t.Fatal("a request naming no order must be refused")
	}
}

func TestAnOrderWithNoIdentityCannotBeAdvanced(t *testing.T) {
	// The structural half of one-canonical-identity. An order that cannot be identified
	// cannot be advanced, so this cannot be reached by normal use and is refused anyway.
	order := Order{State: StateCreated, Version: 1}
	req := Request{
		OrderID:         id(t, contracts.PrefixOrder),
		ExpectedVersion: 1,
		Command:         CmdSubmitForRisk,
		Actor:           serviceActor(),
		At:              ts(t, issuedAt),
	}
	if _, err := Apply(order, req); err == nil {
		t.Fatal("an order with no canonical identity must be refused")
	}
}

func TestAMissingTransitionTimeIsRefused(t *testing.T) {
	// The engine does not read a clock, so the time is an input and an absent one is a
	// refusal rather than a zero time.
	order := toRiskPending(t)
	req := request(t, order, CmdCancel)
	req.At = contracts.Timestamp{}
	if _, err := Apply(order, req); err == nil {
		t.Fatal("a transition with no time must be refused")
	}
}

func TestATerminalOrderCannotBeAdvanced(t *testing.T) {
	order := toSubmitting(t)
	req := request(t, order, CmdCancel)
	cancelled, err := Apply(order, req)
	if err != nil {
		t.Fatalf("cancel should apply: %v", err)
	}

	req = request(t, cancelled.Order, CmdCancel)
	if _, err := Apply(cancelled.Order, req); err == nil {
		t.Fatal("a terminal order must not be advanced further")
	}
	if _, err := Observe(cancelled.Order, observation(t, ObsFilled)); err == nil {
		t.Fatal("a terminal order must not be advanced by an observation")
	}
}

func TestAnUnknownOrderStateIsRefused(t *testing.T) {
	// A lost or unrecognised state is not a default. Treating it as anything in particular
	// would guess, and a guess in an order lifecycle means an order nobody decided to place.
	order := toRiskPending(t)
	order.State = State("SOMETHING_ELSE")
	if _, err := Apply(order, request(t, order, CmdCancel)); err == nil {
		t.Error("an unknown order state must be refused by Apply")
	}
	if _, err := Observe(order, observation(t, ObsFilled)); err == nil {
		t.Error("an unknown order state must be refused by Observe")
	}
}

func TestTheClosedSetsAreExposedAndComplete(t *testing.T) {
	// The exported accessors are part of the API a UI or planner uses, and a copy that let a
	// caller mutate the package's own table would be a real hazard.
	states := AllStates()
	if len(states) != len(allStates) {
		t.Errorf("AllStates returned %d states, want %d", len(states), len(allStates))
	}
	states[0] = State("MUTATED")
	if AllStates()[0] == State("MUTATED") {
		t.Error("AllStates must return a copy, not the package's own slice")
	}

	commands := AllCommands()
	commands[0] = Command("MUTATED")
	if AllCommands()[0] == Command("MUTATED") {
		t.Error("AllCommands must return a copy, not the package's own slice")
	}

	kinds := AllObservationKinds()
	kinds[0] = ObservationKind("MUTATED")
	if AllObservationKinds()[0] == ObservationKind("MUTATED") {
		t.Error("AllObservationKinds must return a copy, not the package's own slice")
	}
}

func TestEveryCommandIsReachableFromSomeState(t *testing.T) {
	// A command nobody can invoke is either a mistake or a hazard waiting for the state it
	// was meant for. Either way it should be visible now.
	declared := map[Command]bool{}
	for _, tr := range transitions {
		if tr.Command != "" {
			declared[tr.Command] = true
		}
	}
	for _, cmd := range AllCommands() {
		if !declared[cmd] {
			t.Errorf("command %s is in the closed set but no transition declares it", cmd)
		}
	}
}

func TestTheUndocumentedStateSetIsNotInTheMachine(t *testing.T) {
	// docs/04 names eleven order states. An extra one would mean the OMS and the
	// specification disagree, and the specification is the authority.
	documented := map[State]bool{
		StateCreated: true, StateRiskPending: true, StateRiskApproved: true,
		StateSubmitting: true, StateAcknowledged: true, StatePartiallyFilled: true,
		StateFilled: true, StateCancelled: true, StateRejected: true,
		StateExpired: true, StateUnknown: true,
	}
	for _, s := range AllStates() {
		if !documented[s] {
			t.Errorf("state %s is not one of the states docs/04 names", s)
		}
	}
	if len(AllStates()) != len(documented) {
		t.Errorf("the machine has %d states, docs/04 names %d",
			len(AllStates()), len(documented))
	}
}

func TestDirectionSignMatchesTheSide(t *testing.T) {
	// Used for anything that needs a signed multiplier. Getting it wrong would flip a
	// position calculation rather than fail loudly.
	if DirBuy.Sign() != 1 {
		t.Errorf("a buy has sign %d, want 1", DirBuy.Sign())
	}
	if DirSell.Sign() != -1 {
		t.Errorf("a sell has sign %d, want -1", DirSell.Sign())
	}
}

func TestTheHaltAccessorsReportTheOrderState(t *testing.T) {
	order := newOrder(t)
	if order.Halted() {
		t.Error("a newly created order is not halted")
	}
	halted := haltedOrder(t)
	if !halted.Halted() {
		t.Error("a halted order should report Halted")
	}
	if halted.Halt.Ref != fixtureHaltRef {
		t.Errorf("halt ref is %q, want %q", halted.Halt.Ref, fixtureHaltRef)
	}
	if halted.Halt.RaisedBy != contracts.ActorHuman {
		t.Errorf("halt was raised by %s, want HUMAN", halted.Halt.RaisedBy)
	}
	if !halted.Halt.RaisedAt.Equal(ts(t, issuedAt)) {
		t.Errorf("halt raised at %s, want the transition time", halted.Halt.RaisedAt)
	}
}

func TestTheStringRenderingsAreForLogsNotParsers(t *testing.T) {
	// These exist to be read by a person in a log. Nothing may parse them, so they carry no
	// stability guarantee, but they must not panic and must carry the identifying fields.
	order := toSubmitting(t)
	got := order.String()
	for _, want := range []string{order.OrderID.String(), "SUBMITTING", fixtureInstrument} {
		if !contains(got, want) {
			t.Errorf("order rendering %q should contain %q", got, want)
		}
	}

	outcome, err := Apply(order, request(t, order, CmdCancel))
	if err != nil {
		t.Fatalf("cancel should apply: %v", err)
	}
	if !contains(outcome.String(), order.OrderID.String()) {
		t.Errorf("outcome rendering %q should contain the order id", outcome.String())
	}
	if serviceActor().String() != "SERVICE:svc-order-gateway" {
		t.Errorf("actor rendering is %q", serviceActor().String())
	}
}

func TestAHaltReferenceIsRequiredToRaiseAHalt(t *testing.T) {
	// A halt that cannot be named later cannot be cleared by its owning authority, which
	// would make it permanent. So the reference is required at the moment it is raised.
	order := toRiskApproved(t)
	req := request(t, order, CmdRaiseHalt)
	req.Actor = humanActor()
	req.PreconditionsSatisfied = []Precondition{PreNoActiveHalt}
	if _, err := Apply(order, req); err == nil {
		t.Fatal("raising a halt with no reference must be refused")
	}
}

func TestARiskDecisionWithoutItsReferenceIsRefused(t *testing.T) {
	// An order approved or rejected with nothing to trace back to the Risk Engine's decision
	// cannot be audited back to it, and the audit chain is what makes the decision
	// reviewable after the fact.
	order := toRiskPending(t)
	req := request(t, order, CmdRecordRiskApproval)
	req.PreconditionsSatisfied = []Precondition{PreRiskEvaluated, PreRiskApproved}
	if _, err := Apply(order, req); err == nil {
		t.Fatal("a risk approval with no reference must be refused")
	}

	order = toRiskPending(t)
	req = request(t, order, CmdRecordRiskRejection)
	req.PreconditionsSatisfied = []Precondition{PreRiskEvaluated, PreRiskRejected}
	if _, err := Apply(order, req); err == nil {
		t.Fatal("a risk rejection with no reference must be refused")
	}
}

func TestAReconciliationWithNoCaseIsRefused(t *testing.T) {
	order := toSubmitting(t)
	timeout := request(t, order, CmdRecordSubmissionTimeout)
	step, err := Apply(order, timeout)
	if err != nil {
		t.Fatalf("timeout should apply: %v", err)
	}
	req := request(t, step.Order, CmdRecordReconciliation)
	req.PreconditionsSatisfied = []Precondition{PreReconciled}
	if _, err := Apply(step.Order, req); err == nil {
		t.Fatal("recording a reconciliation with no case id must be refused")
	}
}

func TestAHaltClearanceWithNoHaltInForceIsRefused(t *testing.T) {
	order := toRiskApproved(t)
	req := request(t, order, CmdClearHalt)
	req.Actor = humanActor()
	req.PreconditionsSatisfied = []Precondition{PreHaltAuthority}
	req.HaltRef = fixtureHaltRef
	if _, err := Apply(order, req); err == nil {
		t.Fatal("clearing a halt on an un-halted order must be refused")
	}
}

func TestTheOutcomeCarriesEverythingTheAuditRecordNeeds(t *testing.T) {
	// docs/01 section 8 requires the transition's declarations to be persisted alongside the
	// state change. The outcome is what the caller persists, so it must carry them rather
	// than making the caller re-derive them.
	order := toSubmitting(t)
	outcome, err := Apply(order, request(t, order, CmdCancel))
	if err != nil {
		t.Fatalf("cancel should apply: %v", err)
	}
	if outcome.EventType == "" || outcome.AuditRecord == "" || outcome.IdempotencyScope == "" {
		t.Error("the outcome must carry the event, audit record, and idempotency scope")
	}
	if outcome.FailureBehavior != FailureUnresolved {
		t.Errorf("a cancel at SUBMITTING has failure behavior %s, want %s because the venue "+
			"outcome is not yet known", outcome.FailureBehavior, FailureUnresolved)
	}
	if !outcome.RequiresReconciliation {
		t.Error("a cancel whose venue outcome is unknown must require reconciliation")
	}
	if outcome.Order.RiskApprovalRef == "" {
		t.Error("the carried order should still reference the risk approval it was made under")
	}
}

func contains(haystack, needle string) bool {
	return len(needle) == 0 || len(haystack) >= len(needle) &&
		indexOf(haystack, needle) >= 0
}

func indexOf(haystack, needle string) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return i
		}
	}
	return -1
}
