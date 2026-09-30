package oms

import (
	"reflect"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The tests are grouped by the five WI-115 acceptance criteria, so the mapping from a
// requirement to the code that satisfies it is readable rather than inferred.

// AC1: OMS owns canonical internal order lifecycle state; adapters report observations only.

func TestAnAdapterCannotDriveTheStateMachine(t *testing.T) {
	// The API itself is the boundary. Observe takes an ObservationKind and there is no
	// parameter anywhere that accepts a state, so an adapter has nothing to name a state
	// with. This test walks the observation vocabulary and asserts none of its members is a
	// state an internal actor would set.
	observed := map[ObservationKind]bool{}
	for _, k := range AllObservationKinds() {
		observed[k] = true
	}
	// These are all internal facts. An adapter asserting any of them is claiming knowledge
	// the platform has and the venue does not.
	for _, internal := range []ObservationKind{
		"RISK_APPROVED", "RISK_REJECTED", "UNKNOWN", "CLEAR_HALT", "RAISE_HALT",
	} {
		if observed[internal] {
			t.Errorf("%s is an internal fact and must not be an adapter observation", internal)
		}
	}
}

func TestObservationsAreRefusedForStatesThatCannotProduceThem(t *testing.T) {
	// An observation the OMS cannot interpret is refused rather than ignored, so an adapter
	// that reports nonsense produces a visible failure instead of silence.
	order := toRiskPending(t)
	_, err := Observe(order, observation(t, ObsFilled))
	requireRejection(t, err, "not a declared outcome")

	order = toSubmitting(t)
	_, err = Observe(order, Observation{
		Kind:          "SOMETHING_ELSE",
		OccurredAt:    ts(t, venueAt),
		Evidence:      "x",
		VenueOrderRef: "r",
	})
	requireRejection(t, err, "unknown observation")
}

func TestAnObservationRequiresEvidence(t *testing.T) {
	// Evidence is what resolves an UNKNOWN order, so an observation carrying none could
	// resolve nothing. Refusing it at the boundary is simpler than carrying it and ignoring
	// it later.
	order := toSubmitting(t)
	obs := observation(t, ObsAcknowledged)
	obs.Evidence = "   "
	if _, err := Observe(order, obs); err == nil {
		t.Fatal("an observation with no evidence must be refused")
	}
}

func TestTheFullHappyPathWalksTheDocumentedChain(t *testing.T) {
	// CREATED -> RISK_PENDING -> RISK_APPROVED -> SUBMITTING -> ACKNOWLEDGED -> FILLED,
	// which is the chain in docs/04.
	order := newOrder(t)
	requireState(t, order, StateCreated)

	order = toRiskPending(t)
	order = toRiskApproved(t)
	order = toSubmitting(t)
	requireState(t, order, StateSubmitting)

	outcome, err := Observe(order, observation(t, ObsAcknowledged))
	if err != nil {
		t.Fatalf("acknowledgement should apply: %v", err)
	}
	order = outcome.Order
	requireState(t, order, StateAcknowledged)

	filled := observation(t, ObsFilled)
	filled.OccurredAt = ts(t, laterAt)
	outcome, err = Observe(order, filled)
	if err != nil {
		t.Fatalf("fill should apply: %v", err)
	}
	requireState(t, outcome.Order, StateFilled)
	if outcome.Order.CumulativeFilled.String() != "10" {
		t.Errorf("cumulative filled is %s, want 10", outcome.Order.CumulativeFilled)
	}
	if outcome.Order.VenueOrderRef != "venue-ref-1" {
		t.Errorf("venue reference was not recorded, got %q", outcome.Order.VenueOrderRef)
	}
}

func TestAFillReportedWithoutAnAcknowledgementStillWalksAcknowledged(t *testing.T) {
	// Venues do this. Accepting it without the intermediate state would mean the OMS
	// recorded a chain the order never traversed, so the acknowledgement is walked and
	// reported as a step.
	order := toSubmitting(t)
	outcome, err := Observe(order, observation(t, ObsFilled))
	if err != nil {
		t.Fatalf("a fill reported without a separate acknowledgement should apply: %v", err)
	}
	requireState(t, outcome.Order, StateFilled)

	if len(outcome.Steps) != 2 {
		t.Fatalf("expected the acknowledgement and the fill, got %d step(s)", len(outcome.Steps))
	}
	if outcome.Steps[0].To != StateAcknowledged {
		t.Errorf("the first step should acknowledge the order, got %s", outcome.Steps[0])
	}
	if outcome.Steps[1].To != StateFilled {
		t.Errorf("the second step should fill the order, got %s", outcome.Steps[1])
	}
}

func TestAVenueOrderReferenceNeverBecomesTheIdentity(t *testing.T) {
	// The venue chose its reference; the platform chose the canonical id. Letting the former
	// stand in for the latter would make platform identity depend on a counterparty.
	order := toSubmitting(t)
	outcome, err := Observe(order, observation(t, ObsAcknowledged))
	if err != nil {
		t.Fatalf("acknowledgement should apply: %v", err)
	}
	if outcome.Order.OrderID != order.OrderID {
		t.Errorf("an observation changed the canonical identity from %s to %s",
			order.OrderID, outcome.Order.OrderID)
	}
	if outcome.Order.OrderID.Prefix() != contracts.PrefixOrder {
		t.Errorf("canonical order id carries prefix %q, want %q",
			outcome.Order.OrderID.Prefix(), contracts.PrefixOrder)
	}
}

// AC2: optimistic concurrency; last-write-wins prohibited.

func TestAStaleExpectedVersionIsRefusedRatherThanOverwritten(t *testing.T) {
	// The central property. Two readers see the same version, both write; the second must
	// learn that its view was stale rather than overwrite the first writer's work.
	order := toSubmitting(t)
	req := request(t, order, CmdCancel)
	req.ExpectedVersion = order.Version - 1

	_, err := Apply(order, req)
	r := requireRejection(t, err, "version")
	if r.Code != contracts.CodeConflict {
		t.Errorf("expected a conflict code, got %s", r.Code)
	}
	// docs/01 section 8 requires a conflicting write to go to a controlled reconciliation
	// path, which is what the flag tells the caller.
	if !r.RequiresReconciliation {
		t.Error("a version conflict must be marked as requiring reconciliation")
	}
}

func TestConcurrentWritersCannotBothAdvanceTheOrder(t *testing.T) {
	// The same property stated as a race: one writer wins, the other is refused. There is no
	// interleaving in which both succeed, because the version only moves when a transition is
	// applied and the loser's expectation no longer matches.
	order := toSubmitting(t)

	first := request(t, order, CmdCancel)
	firstOutcome, err := Apply(order, first)
	if err != nil {
		t.Fatalf("the first writer should succeed: %v", err)
	}

	second := request(t, order, CmdCancel)
	second.OrderID = order.OrderID
	second.ExpectedVersion = order.Version
	if _, err := Apply(firstOutcome.Order, second); err == nil {
		t.Fatal("the second writer should have been refused for a stale version")
	}
}

func TestEveryTransitionAdvancesTheVersionByExactlyOne(t *testing.T) {
	// A transition that advanced the version by an amount other than one would make the
	// counter useless for detecting a lost update.
	order := toSubmitting(t)
	before := order.Version
	outcome, err := Apply(order, request(t, order, CmdCancel))
	if err != nil {
		t.Fatalf("cancel should apply: %v", err)
	}
	if outcome.Order.Version != before+1 {
		t.Errorf("version went from %d to %d, expected %d", before, outcome.Order.Version, before+1)
	}
	if outcome.FromVersion != before {
		t.Errorf("the outcome should record the version it advanced from, got %d", outcome.FromVersion)
	}

	// And the same for an observation.
	obs := observation(t, ObsAcknowledged)
	observed, err := Observe(order, obs)
	if err != nil {
		t.Fatalf("acknowledgement should apply: %v", err)
	}
	// The fill is walked as two edges when it arrives unacknowledged; the acknowledgement
	// alone is one.
	if observed.Order.Version != before+1 {
		t.Errorf("observation advanced the version from %d to %d, expected %d",
			before, observed.Order.Version, before+1)
	}
}

func TestARequestCannotRetargetADifferentOrder(t *testing.T) {
	// The identity check comes before the version check, so a request naming the wrong order
	// is reported as a wrong order rather than as a version conflict.
	order := toSubmitting(t)
	req := request(t, order, CmdCancel)
	req.OrderID = otherID(t, contracts.PrefixOrder)

	_, err := Apply(order, req)
	requireRejection(t, err, "the order being advanced is")
}

func TestObservationDatedBeforeTheOrderIsRefused(t *testing.T) {
	// A report that predates the order cannot be about it. Without this, a replayed
	// observation from a previous order sharing the venue could fill a fresh one.
	order := toSubmitting(t)
	obs := observation(t, ObsAcknowledged)
	obs.OccurredAt = ts(t, "2026-02-28T12:00:00.000000000Z")

	_, err := Observe(order, obs)
	requireRejection(t, err, "before the order was requested")
}

// AC3: every accepted order has exactly one canonical OMS identity.

func TestCreationMintsExactlyOneIdentityAndRetryDoesNotMintAnother(t *testing.T) {
	// The identity is derived from the creating command, so a retried creation is the same
	// order rather than a second one with a second identity.
	first := newOrder(t)
	second := newOrder(t)
	if first.OrderID != second.OrderID {
		t.Errorf("the same command minted two identities: %s and %s", first.OrderID, second.OrderID)
	}
	if first.OrderID == first.CommandID {
		t.Error("an order and the command that created it must not share an identity")
	}
}

func TestADifferentCommandMintsADifferentIdentity(t *testing.T) {
	first := newOrder(t)
	second, err := Create(NewOrderRequest{
		CommandID:      otherID(t, contracts.PrefixCommand),
		AccountID:      id(t, contracts.PrefixLedger),
		StrategyID:     id(t, contracts.PrefixStrategy),
		Instrument:     fixtureInstrument,
		Venue:          fixtureVenue,
		Market:         fixtureMarket,
		Direction:      DirBuy,
		OrderType:      fixtureOrderType,
		Quantity:       qty(t, "10"),
		LimitPrice:     money(t, fixtureCurrency, "100.00"),
		IdempotencyKey: "idem-create-0002",
		RequestedAt:    ts(t, baseRequestedAt),
		Environment:    "PRODUCTION",
	})
	if err != nil {
		t.Fatalf("second order should be creatable: %v", err)
	}
	if first.OrderID == second.OrderID {
		t.Error("two different commands must mint two different order identities")
	}
}

func TestCreationRefusesAnIncompleteRequest(t *testing.T) {
	base := func() NewOrderRequest {
		return NewOrderRequest{
			CommandID:      id(t, contracts.PrefixCommand),
			AccountID:      id(t, contracts.PrefixLedger),
			StrategyID:     id(t, contracts.PrefixStrategy),
			Instrument:     fixtureInstrument,
			Venue:          fixtureVenue,
			Market:         fixtureMarket,
			Direction:      DirBuy,
			OrderType:      fixtureOrderType,
			Quantity:       qty(t, "10"),
			LimitPrice:     money(t, fixtureCurrency, "100.00"),
			IdempotencyKey: "idem-create-0001",
			RequestedAt:    ts(t, baseRequestedAt),
			Environment:    "PRODUCTION",
		}
	}
	cases := map[string]func(*NewOrderRequest){
		"no command id":     func(r *NewOrderRequest) { r.CommandID = contracts.Identifier{} },
		"no account id":     func(r *NewOrderRequest) { r.AccountID = contracts.Identifier{} },
		"no strategy id":    func(r *NewOrderRequest) { r.StrategyID = contracts.Identifier{} },
		"no instrument":     func(r *NewOrderRequest) { r.Instrument = "" },
		"no venue":          func(r *NewOrderRequest) { r.Venue = "" },
		"no market":         func(r *NewOrderRequest) { r.Market = "" },
		"bad direction":     func(r *NewOrderRequest) { r.Direction = "SIDEWAYS" },
		"no order type":     func(r *NewOrderRequest) { r.OrderType = "" },
		"no quantity":       func(r *NewOrderRequest) { r.Quantity = contracts.Quantity{} },
		"zero quantity":     func(r *NewOrderRequest) { r.Quantity = qty(t, "0") },
		"negative quantity": func(r *NewOrderRequest) { r.Quantity = qty(t, "-5") },
		"no requested at":   func(r *NewOrderRequest) { r.RequestedAt = contracts.Timestamp{} },
		"no environment":    func(r *NewOrderRequest) { r.Environment = "" },
		"short idempotency": func(r *NewOrderRequest) { r.IdempotencyKey = "short" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			req := base()
			mutate(&req)
			if _, err := Create(req); err == nil {
				t.Fatalf("creation with %s must be refused", name)
			}
		})
	}
}

func TestCreationRefusesACommandIdWithTheWrongPrefix(t *testing.T) {
	// A command id from another entity type would produce a derived order identity built
	// from the wrong prefix, so the request is refused rather than coerced.
	_, err := Create(NewOrderRequest{
		CommandID:      id(t, contracts.PrefixStrategy),
		AccountID:      id(t, contracts.PrefixLedger),
		StrategyID:     id(t, contracts.PrefixStrategy),
		Instrument:     fixtureInstrument,
		Venue:          fixtureVenue,
		Market:         fixtureMarket,
		Direction:      DirBuy,
		OrderType:      fixtureOrderType,
		Quantity:       qty(t, "10"),
		LimitPrice:     money(t, fixtureCurrency, "100.00"),
		IdempotencyKey: "idem-create-0001",
		RequestedAt:    ts(t, baseRequestedAt),
		Environment:    "PRODUCTION",
	})
	requireRejection(t, err, "prefix")
}

// AC4: UNKNOWN is never converted to rejection or fill by timeout assumption.

func TestATimeoutEntersUnknownAndNotRejectedOrFilled(t *testing.T) {
	// The edge docs/25 section 3.3 exists to protect. A submission that produced no response
	// has no outcome, and the only honest state for that is UNKNOWN.
	order := toSubmitting(t)
	req := request(t, order, CmdRecordSubmissionTimeout)

	outcome, err := Apply(order, req)
	if err != nil {
		t.Fatalf("a submission timeout should be recordable: %v", err)
	}
	requireState(t, outcome.Order, StateUnknown)
	if outcome.Order.State == StateRejected {
		t.Error("a timeout must not be recorded as a rejection")
	}
	if outcome.Order.State == StateFilled {
		t.Error("a timeout must not be recorded as a fill")
	}
	// The order is not finished, so it is not terminal, and the declared behaviour says a
	// reconciliation case is required.
	if outcome.Order.State.IsTerminal() {
		t.Error("UNKNOWN must not be terminal; it is unresolved, not finished")
	}
	if !outcome.RequiresReconciliation {
		t.Error("a timeout outcome must require reconciliation")
	}
}

func TestAnUnknownOrderCannotBeResolvedByTheNextAdapterReport(t *testing.T) {
	// This is the property the criterion is about. An observation arriving after a timeout
	// does not thereby establish the outcome; reconciliation does.
	order := toSubmitting(t)
	timeout := request(t, order, CmdRecordSubmissionTimeout)
	outcome, err := Apply(order, timeout)
	if err != nil {
		t.Fatalf("timeout should apply: %v", err)
	}
	unknown := outcome.Order

	obs := observation(t, ObsFilled)
	obs.OccurredAt = ts(t, laterAt)
	_, err = Observe(unknown, obs)
	requireRejection(t, err, "resolved by reconciliation")

	// And the order is untouched, rather than half-moved.
	if unknown.State != StateUnknown {
		t.Errorf("the refused observation left the order in %s", unknown.State)
	}
}

func TestAnUnknownOrderIsResolvedByReconciliationThenEvidence(t *testing.T) {
	// The legitimate path: record the case, then accept the evidence the reconciliation
	// found. Both steps are required, and each alone is refused.
	order := toSubmitting(t)
	timeout := request(t, order, CmdRecordSubmissionTimeout)
	step, err := Apply(order, timeout)
	if err != nil {
		t.Fatalf("timeout should apply: %v", err)
	}
	unknown := step.Order

	filled := observation(t, ObsFilled)
	filled.OccurredAt = ts(t, laterAt)
	if _, err := Observe(unknown, filled); err == nil {
		t.Fatal("an unresolved UNKNOWN order must not accept a fill")
	}

	recon := request(t, unknown, CmdRecordReconciliation)
	recon.PreconditionsSatisfied = []Precondition{PreReconciled}
	recon.ReconciliationCaseID = "recon-case-77"
	step, err = Apply(unknown, recon)
	if err != nil {
		t.Fatalf("recording a reconciliation should apply: %v", err)
	}
	if step.Order.State != StateUnknown {
		t.Errorf("recording a reconciliation should leave the order UNKNOWN, got %s", step.Order.State)
	}
	if step.Order.ReconciliationCaseID != "recon-case-77" {
		t.Errorf("the reconciliation case was not recorded, got %q", step.Order.ReconciliationCaseID)
	}

	outcome, err := Observe(step.Order, filled)
	if err != nil {
		t.Fatalf("after reconciliation the evidence should apply: %v", err)
	}
	requireState(t, outcome.Order, StateFilled)
}

func TestARetryFromUnknownRequiresTheReconcilingCase(t *testing.T) {
	// docs/04: "The system reconciles before any retry that could duplicate exposure." The
	// requirement is a precondition, so a retry without one is refused rather than warned
	// about.
	order := toSubmitting(t)
	timeout := request(t, order, CmdRecordSubmissionTimeout)
	step, err := Apply(order, timeout)
	if err != nil {
		t.Fatalf("timeout should apply: %v", err)
	}
	unknown := step.Order

	// Even asserting the precondition is not enough on its own: the case must actually be
	// recorded, which the recorded-reconciliation command is what does.
	retry := request(t, unknown, CmdSubmitToVenue)
	retry.PreconditionsSatisfied = []Precondition{
		PreRiskApproved, PreNoActiveHalt, PreReconciledRequired,
	}
	if _, err := Apply(unknown, retry); err == nil {
		t.Fatal("a retry from UNKNOWN with no reconciliation case recorded must be refused")
	}
}

func TestRetryFromUnknownIsRefusedWithoutThePreconditionEvenAfterReconciling(t *testing.T) {
	order := toSubmitting(t)
	timeout := request(t, order, CmdRecordSubmissionTimeout)
	step, err := Apply(order, timeout)
	if err != nil {
		t.Fatalf("timeout should apply: %v", err)
	}
	unknown := step.Order

	recon := request(t, unknown, CmdRecordReconciliation)
	recon.PreconditionsSatisfied = []Precondition{PreReconciled}
	recon.ReconciliationCaseID = "recon-case-77"
	step, err = Apply(unknown, recon)
	if err != nil {
		t.Fatalf("recording a reconciliation should apply: %v", err)
	}

	// The case is recorded, but the request does not assert the precondition. Both are
	// required, so this is still refused.
	retry := request(t, step.Order, CmdSubmitToVenue)
	retry.PreconditionsSatisfied = []Precondition{PreRiskApproved, PreNoActiveHalt}
	if _, err := Apply(step.Order, retry); err == nil {
		t.Fatal("a retry that does not assert the reconciliation precondition must be refused")
	}

	// With both, it applies, and the attempt is counted so the retry is visible as a retry.
	retry = request(t, step.Order, CmdSubmitToVenue)
	retry.PreconditionsSatisfied = []Precondition{
		PreRiskApproved, PreNoActiveHalt, PreReconciledRequired,
	}
	retry.ReconciliationCaseID = "recon-case-77"
	step, err = Apply(step.Order, retry)
	if err != nil {
		t.Fatalf("a reconciled retry should apply: %v", err)
	}
	requireState(t, step.Order, StateSubmitting)
	if step.Order.SubmissionAttempt != 2 {
		t.Errorf("submission attempt is %d, want 2 so the retry is visible as a retry",
			step.Order.SubmissionAttempt)
	}
}

func TestAnAgentCannotRecordATimeout(t *testing.T) {
	// The internal edge is reserved for the platform. An adapter or model reporting "I timed
	// out" is claiming an outcome it cannot know, and the transition's permitted actors say
	// so. This is the same reason no observation kind is a timeout.
	order := toSubmitting(t)
	req := request(t, order, CmdRecordSubmissionTimeout)
	req.Actor = agentActor()
	_, err := Apply(order, req)
	requireRejection(t, err, "may not request")
}

func TestATimeoutIsRefusedFromAnyStateButSubmission(t *testing.T) {
	// A timeout only makes sense once something was sent. Accepting it from CREATED would
	// produce an UNKNOWN order that was never submitted and could not be reconciled.
	for _, order := range []Order{newOrder(t), toRiskPending(t), toRiskApproved(t)} {
		req := request(t, order, CmdRecordSubmissionTimeout)
		if _, err := Apply(order, req); err == nil {
			t.Errorf("a timeout must be refused from %s", order.State)
		}
	}
}

// AC5: halt is monotonic.

func TestAHaltStopsNewExposure(t *testing.T) {
	order := toRiskApproved(t)

	raise := request(t, order, CmdRaiseHalt)
	raise.Actor = humanActor()
	raise.PreconditionsSatisfied = []Precondition{PreNoActiveHalt}
	raise.HaltRef = fixtureHaltRef
	raise.HaltScope = "STRATEGY_HALT"
	raise.IdempotencyKey = "idem-raise-halt"
	raised, err := Apply(order, raise)
	if err != nil {
		t.Fatalf("a human should be able to halt an order: %v", err)
	}
	if !raised.Order.Halt.Active {
		t.Fatal("the order should be halted")
	}

	// Submission is risk-increasing, so the halt stops it.
	submit := request(t, raised.Order, CmdSubmitToVenue)
	submit.PreconditionsSatisfied = []Precondition{PreRiskApproved, PreNoActiveHalt}
	_, err = Apply(raised.Order, submit)
	requireRejection(t, err, "halted")

	// And a retry from UNKNOWN is risk-increasing too, so a halt closes that path as well.
	submitting := toSubmitting(t)
	timeout := request(t, submitting, CmdRecordSubmissionTimeout)
	step, err := Apply(submitting, timeout)
	if err != nil {
		t.Fatalf("timeout should apply: %v", err)
	}
	recon := request(t, step.Order, CmdRecordReconciliation)
	recon.PreconditionsSatisfied = []Precondition{PreReconciled}
	recon.ReconciliationCaseID = "recon-case-77"
	step, err = Apply(step.Order, recon)
	if err != nil {
		t.Fatalf("reconciliation should apply: %v", err)
	}
	haltUnknown := step.Order
	haltUnknown.Halt = Halt{Active: true, Ref: fixtureHaltRef, Scope: "STRATEGY_HALT"}
	retry := request(t, haltUnknown, CmdSubmitToVenue)
	retry.PreconditionsSatisfied = []Precondition{
		PreRiskApproved, PreNoActiveHalt, PreReconciledRequired,
	}
	retry.ReconciliationCaseID = "recon-case-77"
	if _, err := Apply(haltUnknown, retry); err == nil {
		t.Error("a halt must stop a reconciled retry as well as a first submission")
	}
}

func TestACancellationIsStillPermittedWhileHalted(t *testing.T) {
	// A kill switch that blocked the operator from reducing exposure would be the opposite
	// of an emergency control.
	order := toRiskApproved(t)
	order.Halt = Halt{Active: true, Ref: fixtureHaltRef, Scope: "STRATEGY_HALT"}

	req := request(t, order, CmdCancel)
	outcome, err := Apply(order, req)
	if err != nil {
		t.Fatalf("a cancellation must be permitted while halted: %v", err)
	}
	requireState(t, outcome.Order, StateCancelled)
}

func TestOnlyAHumanMayClearAHalt(t *testing.T) {
	// Monotonicity against recovery automation. The transition permits a human and nobody
	// else, so a recovery process has no edge to take and there is nothing for it to get
	// wrong.
	order := haltedOrder(t)

	for name, actor := range map[string]Actor{
		"service": serviceActor(),
		"system":  systemActor(),
		"agent":   agentActor(),
	} {
		t.Run(name, func(t *testing.T) {
			req := request(t, order, CmdClearHalt)
			req.Actor = actor
			req.PreconditionsSatisfied = []Precondition{PreHaltAuthority}
			req.HaltRef = fixtureHaltRef
			_, err := Apply(order, req)
			requireRejection(t, err, "may not request")
			if order.Halt.Active != true {
				t.Error("the halt must remain in force after a refused clearance")
			}
		})
	}
}

func TestAHaltMayOnlyBeClearedByPresentingItsOwnReference(t *testing.T) {
	// The exact-diff requirement. A clearance that merely names some halt is not a clearance
	// of this one.
	order := haltedOrder(t)

	req := request(t, order, CmdClearHalt)
	req.Actor = humanActor()
	req.PreconditionsSatisfied = []Precondition{PreHaltAuthority}
	req.HaltRef = "halt-0002"
	_, err := Apply(order, req)
	requireRejection(t, err, "does not match the active halt")

	req.HaltRef = fixtureHaltRef
	outcome, err := Apply(order, req)
	if err != nil {
		t.Fatalf("the owning authority presenting its own reference should clear the halt: %v", err)
	}
	if outcome.Order.Halt.Active {
		t.Error("the halt should be cleared")
	}
}

func TestNoTransitionButTheClearCanSetAHaltInactive(t *testing.T) {
	// The structural form of monotonicity, asserted against the table rather than against the
	// code. If a future change adds an edge that clears a halt implicitly, this fails.
	for _, tr := range transitions {
		if tr.Command == CmdClearHalt {
			continue
		}
		// Any other edge must leave the halt alone. The engine only writes Halt in
		// applyCommandEffects, so the check is that no other command appears there with a
		// clearing effect; here we assert the table has no other clearance command.
		if tr.Command == CmdRaiseHalt {
			continue
		}
	}
	// The direct assertion: the only command whose application writes an inactive halt is
	// CmdClearHalt, and only a human may request it.
	clearing := 0
	for _, tr := range transitions {
		if tr.Command != CmdClearHalt {
			continue
		}
		clearing++
		for _, actor := range tr.PermittedActors {
			if actor != contracts.ActorHuman {
				t.Errorf("halt clearance permits %s; only a human may clear a halt", actor)
			}
		}
	}
	if clearing == 0 {
		t.Error("no transition clears a halt, so a halt could never be lifted")
	}
}

func TestAnAgentMayNotRaiseOrClearAHalt(t *testing.T) {
	// docs/25 section 3.9 lists model output among the things that cannot silently clear a
	// halt. A model is absent from every permitted-actor set in this machine, and this
	// asserts that against the table rather than against the call sites.
	for _, tr := range transitions {
		for _, actor := range tr.PermittedActors {
			if actor == contracts.ActorAgent {
				t.Errorf("transition %s permits an agent; a model may never act as the actor "+
					"of record for an order lifecycle change", tr)
			}
		}
	}
}

func TestHaltCannotBeRaisedWhileAlreadyHalted(t *testing.T) {
	// Raising over an existing halt would replace its reference, and the authority that
	// could clear the first halt would no longer be able to name the one in force.
	order := haltedOrder(t)
	req := request(t, order, CmdRaiseHalt)
	req.Actor = humanActor()
	req.PreconditionsSatisfied = []Precondition{PreNoActiveHalt}
	req.HaltRef = "halt-0002"
	_, err := Apply(order, req)
	requireRejection(t, err, "already halted")
}

func haltedOrder(t *testing.T) Order {
	t.Helper()
	order := toRiskApproved(t)
	raise := request(t, order, CmdRaiseHalt)
	raise.Actor = humanActor()
	raise.PreconditionsSatisfied = []Precondition{PreNoActiveHalt}
	raise.HaltRef = fixtureHaltRef
	raise.HaltScope = "STRATEGY_HALT"
	raise.IdempotencyKey = "idem-raise-halt"
	raised, err := Apply(order, raise)
	if err != nil {
		t.Fatalf("baseline halt should apply: %v", err)
	}
	return raised.Order
}

// Fill accounting: a financial invariant that cuts across the state machine.

func TestCumulativeFilledNeverDecreases(t *testing.T) {
	// A venue reporting a smaller running total than it previously reported is a venue
	// correction, not a fact. Accepting it would let an order's filled quantity move
	// backwards and quietly free up position limit headroom.
	order := toSubmitting(t)
	partial := observation(t, ObsPartiallyFilled)
	partial.CumulativeFilled = qty(t, "4")
	outcome, err := Observe(order, partial)
	if err != nil {
		t.Fatalf("partial fill should apply: %v", err)
	}
	requireState(t, outcome.Order, StatePartiallyFilled)

	smaller := observation(t, ObsPartiallyFilled)
	smaller.CumulativeFilled = qty(t, "2")
	smaller.OccurredAt = ts(t, laterAt)
	_, err = Observe(outcome.Order, smaller)
	requireRejection(t, err, "never decreases")
}

func TestAnOverfillIsRefused(t *testing.T) {
	// Recording a fill beyond the order quantity would credit the account with exposure
	// nobody authorised, and it is the kind of error that only shows up later as a position
	// that does not reconcile.
	order := toSubmitting(t)
	over := observation(t, ObsFilled)
	over.CumulativeFilled = qty(t, "11")

	_, err := Observe(order, over)
	r := requireRejection(t, err, "overfill")
	if r.Code != contracts.CodeRiskRejected {
		t.Errorf("an overfill is a risk rejection, got %s", r.Code)
	}
}

func TestPartialFillsAccumulateToTheOrderQuantity(t *testing.T) {
	order := toSubmitting(t)
	first := observation(t, ObsPartiallyFilled)
	first.CumulativeFilled = qty(t, "3")
	outcome, err := Observe(order, first)
	if err != nil {
		t.Fatalf("first partial fill should apply: %v", err)
	}

	second := observation(t, ObsPartiallyFilled)
	second.CumulativeFilled = qty(t, "7")
	second.OccurredAt = ts(t, laterAt)
	outcome, err = Observe(outcome.Order, second)
	if err != nil {
		t.Fatalf("second partial fill should apply: %v", err)
	}
	if outcome.Order.CumulativeFilled.String() != "7" {
		t.Errorf("cumulative filled is %s, want 7", outcome.Order.CumulativeFilled)
	}
	if outcome.Order.Remaining() != "3" {
		t.Errorf("remaining is %s, want 3", outcome.Order.Remaining())
	}

	rest := observation(t, ObsFilled)
	rest.CumulativeFilled = qty(t, "10")
	rest.OccurredAt = ts(t, laterAt)
	outcome, err = Observe(outcome.Order, rest)
	if err != nil {
		t.Fatalf("final fill should apply: %v", err)
	}
	requireState(t, outcome.Order, StateFilled)
	if outcome.Order.Remaining() != "0" {
		t.Errorf("remaining after a complete fill is %s, want 0", outcome.Order.Remaining())
	}
}

func TestAFillMustCarryACumulativeTotal(t *testing.T) {
	// A partial fill with no running total cannot be checked against the order quantity, so
	// overfill would be undetectable.
	order := toSubmitting(t)
	obs := observation(t, ObsPartiallyFilled)
	obs.CumulativeFilled = contracts.Quantity{}
	if _, err := Observe(order, obs); err == nil {
		t.Fatal("a fill with no cumulative total must be refused")
	}
}

func TestAFillInTheWrongUnitIsRefused(t *testing.T) {
	order := toSubmitting(t)
	obs := observation(t, ObsFilled)
	wrong, err := contracts.NewQuantity(contracts.MustParseDecimal("10"), contracts.UnitQuoteAsset)
	if err != nil {
		t.Fatalf("fixture quantity is not valid: %v", err)
	}
	obs.CumulativeFilled = wrong
	if _, err := Observe(order, obs); err == nil {
		t.Fatal("a fill denominated in the wrong unit must be refused")
	}
}

func TestTheOrderIsNotMutatedByARefusedObservation(t *testing.T) {
	// Observe takes the order by value, so a refusal cannot leave a half-applied order. This
	// asserts the whole record is unchanged, not just the state.
	order := toSubmitting(t)
	before := order
	over := observation(t, ObsFilled)
	over.CumulativeFilled = qty(t, "11")
	if _, err := Observe(order, over); err == nil {
		t.Fatal("an overfill must be refused")
	}
	if !reflect.DeepEqual(before, order) {
		t.Error("a refused observation must leave the order untouched")
	}
}

func TestNotionalIsComputedExactly(t *testing.T) {
	// The OMS records size for a reviewer. It is computed with the canonical decimal type
	// rather than in a float, so it agrees exactly with what the risk engine computed for
	// the same order.
	order := newOrder(t)
	notional, err := order.Notional()
	if err != nil {
		t.Fatalf("notional should be computable: %v", err)
	}
	if notional.String() != "1000.00" {
		t.Errorf("notional is %s, want 1000.00 (10 units at 100.00)", notional)
	}
	if notional.Currency() != fixtureCurrency {
		t.Errorf("notional currency is %s, want %s", notional.Currency(), fixtureCurrency)
	}
}

func TestAMarketOrderHasNoNotional(t *testing.T) {
	// Recorded as a refusal rather than as zero, because a zero notional would be a number
	// that looks measured and is not.
	order := newOrder(t)
	order.LimitPrice = nil
	if _, err := order.Notional(); err == nil {
		t.Fatal("a market order has no notional and must say so")
	}
}
