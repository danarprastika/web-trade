package oms

import (
	"fmt"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Outcome is the result of an applied transition.
//
// It carries everything docs/01 section 8 requires a transition to declare, so the caller
// persists the audit record and the event in the same transaction as the state change without
// having to re-derive them.
type Outcome struct {
	// Order is the order after the transition, at Version+1.
	Order Order
	// Transition is the declared edge that was applied.
	Transition Transition
	// EventType is the audit event to persist.
	EventType string
	// AuditRecord is the human-readable audit description.
	AuditRecord string
	// IdempotencyScope is the scope the caller's key is unique within.
	IdempotencyScope string
	// FailureBehavior is the declared behaviour if this transition later proves ambiguous.
	FailureBehavior FailureBehavior
	// FromVersion is the version the caller expected, which is also the version the
	// transition advanced from. Recording both makes a replay checkable.
	FromVersion uint64
	// RiskReference is the risk approval or rejection reference this transition recorded, if
	// any. It is what ties an order's lifecycle to the exact Risk Engine decision.
	RiskReference string
	// RequiresReconciliation mirrors the transition's FailureBehavior for a caller that
	// wants to know whether it must open a reconciliation case rather than inspect the enum.
	RequiresReconciliation bool
}

// Request is a proposed transition.
type Request struct {
	// OrderID is the canonical order the transition applies to. It must match the stored
	// order's identity; there is no path that retargets a transition at a different order.
	OrderID contracts.Identifier
	// ExpectedVersion is the version the caller believes the order is at. docs/01 section 8
	// prohibits last-write-wins, so a mismatch is a conflict rather than an overwrite.
	ExpectedVersion uint64
	// Command is the transition requested.
	Command Command
	// Actor is who is requesting it.
	Actor Actor
	// PreconditionsSatisfied lists the preconditions the caller asserts are met. Asserting
	// extra names is harmless; asserting a different one in place of a required one is refused.
	PreconditionsSatisfied []Precondition
	// RiskReference is the risk approval or rejection reference, required by the transitions
	// that record a risk decision.
	RiskReference string
	// HaltRef is the halt reference, required to clear a halt. It must equal the halt's own
	// reference, which is the exact-diff requirement.
	HaltRef string
	// HaltScope is the halt level, recorded when raising a halt.
	HaltScope string
	// ReconciliationCaseID is the case that resolved an UNKNOWN order.
	ReconciliationCaseID string
	// IdempotencyKey scopes this transition, so a retried command does not advance twice.
	IdempotencyKey string
	// At is when the command was issued. Supplied rather than read from a clock so the
	// outcome is a pure function of its inputs.
	At contracts.Timestamp
}

// Create mints a canonical order and returns it in StateCreated.
//
// The canonical identity is derived from the creating command id rather than generated, so a
// retried creation of the same command yields the same identity and the same order instead of
// a second one. Generation would need a source of uniqueness outside the request, and an
// order whose identity depends on a random draw cannot be reconciled against a command log.
func Create(req NewOrderRequest) (Order, error) {
	if err := req.validate(); err != nil {
		return Order{}, err
	}
	// The canonical order id is derived from the command id, not copied from it: the two are
	// different entities with different prefixes, and reusing the command's payload for an
	// order would make an order and the command that created it share an identity.
	orderID, err := deriveOrderID(req.CommandID)
	if err != nil {
		return Order{}, err
	}
	zero, err := contracts.NewQuantity(contracts.MustParseDecimal("0"), req.Quantity.Unit())
	if err != nil {
		return Order{}, reject(contracts.CodeValidation,
			"order quantity unit %q could not be used to zero the fill accumulator: %v",
			req.Quantity.Unit(), err)
	}
	return Order{
		OrderID:          orderID,
		CommandID:        req.CommandID,
		AccountID:        req.AccountID,
		StrategyID:       req.StrategyID,
		Instrument:       req.Instrument,
		Venue:            req.Venue,
		Market:           req.Market,
		Direction:        req.Direction,
		OrderType:        req.OrderType,
		Quantity:         req.Quantity,
		LimitPrice:       req.LimitPrice,
		IdempotencyKey:   req.IdempotencyKey,
		Environment:      req.Environment,
		State:            StateCreated,
		Version:          1,
		CumulativeFilled: zero,
		RequestedAt:      req.RequestedAt,
		UpdatedAt:        req.RequestedAt,
	}, nil
}

// deriveOrderID builds the canonical order identity from the creating command id.
func deriveOrderID(cmd contracts.Identifier) (contracts.Identifier, error) {
	// The payload is reused, which keeps the order id deterministic without a random source
	// and without inventing an unrelated identifier. The prefix distinguishes the entity.
	id, err := contracts.ParseIdentifier(contracts.PrefixOrder + strings.TrimPrefix(cmd.String(), contracts.PrefixCommand))
	if err != nil {
		return contracts.Identifier{}, reject(contracts.CodeValidation,
			"command %s does not yield a canonical order identity: %v", cmd, err)
	}
	return id, nil
}

// Apply validates a proposed transition and returns the resulting outcome.
//
// The order of the checks is deliberate and each step earns its place:
//
//  1. The order id is checked first, so a request naming no order is reported as such rather
//     than as a version conflict.
//  2. The expected version is checked before anything else that could succeed, because a
//     conflict means the caller's view of the world is stale and every later answer would be
//     computed against a state the caller did not see.
//  3. The state is validated before the command is looked up, so an unknown state is reported
//     as an unknown state rather than as a missing transition.
//  4. Authority is checked before preconditions, because an actor without permission has no
//     standing to assert that a precondition is met, and evaluating a precondition on their
//     behalf would leak whether the evidence exists.
//  5. Halt is checked before the transition's other preconditions, so a halted order is
//     reported as halted rather than as missing paperwork.
func Apply(order Order, req Request) (Outcome, error) {
	if req.OrderID.IsZero() {
		return Outcome{}, reject(contracts.CodeValidation, "order id is required")
	}
	if order.OrderID.IsZero() {
		return Outcome{}, reject(contracts.CodeValidation, "the order carries no canonical identity; "+
			"an order that cannot be identified cannot be advanced")
	}
	// The identity check is the structural half of "every accepted order has exactly one
	// canonical identity": a request is only ever applied to the order it names.
	if req.OrderID != order.OrderID {
		return Outcome{}, reject(contracts.CodeAuthorization,
			"request names order %s but the order being advanced is %s", req.OrderID, order.OrderID)
	}
	if err := req.Actor.valid(); err != nil {
		return Outcome{}, err
	}
	if req.At.IsZero() {
		return Outcome{}, reject(contracts.CodeValidation, "at is required; the engine does not read a clock")
	}

	// Optimistic concurrency. docs/01 section 8 requires version checks and prohibits
	// last-write-wins, so a mismatch is a conflict that goes to reconciliation rather than an
	// overwrite that would discard whatever advanced the order.
	if req.ExpectedVersion != order.Version {
		return Outcome{}, conflict(
			"order %s is at version %d but the request expected %d; a conflicting write is "+
				"reconciled, not applied, because overwriting would discard the state another "+
				"writer advanced to",
			order.OrderID, order.Version, req.ExpectedVersion)
	}

	if !order.State.Valid() {
		return Outcome{}, reject(contracts.CodeValidation,
			"order %s reports unknown state %q; an unknown state is not treated as a default",
			order.OrderID, order.State)
	}
	if !req.Command.Valid() {
		return Outcome{}, reject(contracts.CodeValidation,
			"%q is not a known order command; unknown commands are unsupported", req.Command)
	}
	if order.State.IsTerminal() {
		return Outcome{}, reject(contracts.CodeConflict,
			"order %s is in terminal state %s and cannot be advanced", order.OrderID, order.State)
	}

	declared, ok := transitionFor(order.State, req.Command)
	if !ok {
		return Outcome{}, reject(contracts.CodeValidation,
			"command %q is not declared for state %s; undeclared transitions are refused, "+
				"because a guessed edge in a financial lifecycle means an order the platform "+
				"never decided to create. Declared from %s: %v",
			req.Command, order.State, order.State, NextStates(order.State))
	}
	if !actorPermitted(declared, req.Actor.Type) {
		return Outcome{}, reject(contracts.CodeAuthorization,
			"actor type %s may not request %q on an order in %s; permitted: %v",
			req.Actor.Type, req.Command, order.State, declared.PermittedActors)
	}

	// A risk-increasing transition is refused while a halt is in force. The check is here and
	// not in the transition table so that adding a risk-increasing transition without this
	// check is a compile-time impossibility rather than a review question.
	if declared.RiskIncreasing && order.Halt.Active {
		return Outcome{}, reject(contracts.CodeAuthorization,
			"order %s is halted (ref %s, raised %s) and %q is risk-increasing; a halt stops "+
				"new exposure and may only be cleared by its owning authority",
			order.OrderID, order.Halt.Ref, order.Halt.Scope, req.Command)
	}

	if missing := missingPreconditions(declared, req.PreconditionsSatisfied); len(missing) > 0 {
		return Outcome{}, reject(contracts.CodeValidation,
			"transition %s requires precondition(s) %v which the request did not assert",
			declared, missing)
	}

	next := order
	next.Version = order.Version + 1
	next.UpdatedAt = req.At

	if err := applyCommandEffects(&next, declared, req, order); err != nil {
		return Outcome{}, err
	}
	next.State = declared.To

	return Outcome{
		Order:                  next,
		Transition:             declared,
		EventType:              declared.EventType,
		AuditRecord:            declared.AuditRecord,
		IdempotencyScope:       declared.IdempotencyScope,
		FailureBehavior:        declared.FailureBehavior,
		FromVersion:            order.Version,
		RiskReference:          req.RiskReference,
		RequiresReconciliation: declared.FailureBehavior == FailureUnresolved,
	}, nil
}

// applyCommandEffects mutates the fields a specific command owns, beyond the state itself.
func applyCommandEffects(next *Order, t Transition, req Request, current Order) error {
	switch req.Command {
	case CmdRecordRiskApproval, CmdRecordRiskRejection:
		if strings.TrimSpace(req.RiskReference) == "" {
			return reject(contracts.CodeValidation,
				"%s requires the risk engine's reference; an order approved or rejected "+
					"without a reference to the decision cannot be audited back to it",
				req.Command)
		}
		if req.Command == CmdRecordRiskApproval {
			next.RiskApprovalRef = req.RiskReference
		} else {
			next.RiskRejectionRef = req.RiskReference
		}
	case CmdSubmitToVenue:
		// A retry out of UNKNOWN is the duplicate-exposure hazard docs/04 warns about, so the
		// reconciling case is verified against the order rather than merely asserted by the
		// caller. Every other precondition in this machine is a claim the caller makes, but
		// this one would otherwise be a claim that could be made by typing a string, and the
		// claim is precisely what needs checking.
		if current.State == StateUnknown && current.ReconciliationCaseID == "" {
			return reject(contracts.CodeValidation,
				"order %s is UNKNOWN and no reconciliation case has been recorded against it; "+
					"docs/04 requires reconciliation before any retry that could duplicate "+
					"exposure, and asserting the precondition is not the same as reconciling",
				current.OrderID)
		}
		next.SubmissionAttempt++
		if req.ReconciliationCaseID != "" {
			next.ReconciliationCaseID = req.ReconciliationCaseID
		}
	case CmdRecordReconciliation:
		if strings.TrimSpace(req.ReconciliationCaseID) == "" {
			return reject(contracts.CodeValidation,
				"RECORD_RECONCILIATION requires the reconciliation case id; a resolution "+
					"without a case cannot be traced or reviewed")
		}
		next.ReconciliationCaseID = req.ReconciliationCaseID
	case CmdRaiseHalt:
		if strings.TrimSpace(req.HaltRef) == "" {
			return reject(contracts.CodeValidation,
				"RAISE_HALT requires a halt reference; a halt that cannot be named later "+
					"cannot be cleared by its owning authority")
		}
		if current.Halt.Active {
			return reject(contracts.CodeConflict,
				"order %s is already halted under ref %s", current.OrderID, current.Halt.Ref)
		}
		next.Halt = Halt{
			Active:   true,
			Ref:      req.HaltRef,
			Scope:    req.HaltScope,
			RaisedAt: req.At,
			RaisedBy: req.Actor.Type,
		}
	case CmdClearHalt:
		// Monotonicity's one exit. The actor is already known to be a human by the
		// transition's PermittedActors; the exact reference is checked here so that
		// clearance cannot be granted by citing a different halt.
		if !current.Halt.Active {
			return reject(contracts.CodeConflict,
				"order %s has no active halt to clear", current.OrderID)
		}
		if req.HaltRef != current.Halt.Ref {
			return reject(contracts.CodeAuthorization,
				"halt ref %q does not match the active halt %q; a halt may only be cleared by "+
					"its owning authority presenting its own reference",
				req.HaltRef, current.Halt.Ref)
		}
		next.Halt = Halt{}
	}
	return nil
}

// ObservationOutcome is the result of applying one or more observations.
//
// One observation can walk more than one edge: a venue that reports a complete fill without a
// prior acknowledgement takes the order through ACKNOWLEDGED to FILLED, and both edges are
// recorded. The chain in docs/04 is walked rather than short-circuited, so a reader never
// sees a fill from a submission with no acknowledgement in between.
type ObservationOutcome struct {
	// Order is the order after the observation.
	Order Order
	// Steps are the edges walked, in order. More than one is normal and expected.
	Steps []Transition
}

// Observe applies a venue adapter's report.
//
// There is no target state in the signature and no way to pass one. The adapter says what it
// saw; this function decides what that means. That is the whole of docs/25 section 3.2's
// "a venue adapter reports observations; it does not rewrite the OMS state machine".
func Observe(order Order, obs Observation) (ObservationOutcome, error) {
	if err := obs.validate(); err != nil {
		return ObservationOutcome{}, err
	}
	if order.OrderID.IsZero() {
		return ObservationOutcome{}, reject(contracts.CodeValidation,
			"the order carries no canonical identity")
	}
	if !order.State.Valid() {
		return ObservationOutcome{}, reject(contracts.CodeValidation,
			"order %s reports unknown state %q", order.OrderID, order.State)
	}
	if order.State.IsTerminal() {
		return ObservationOutcome{}, reject(contracts.CodeConflict,
			"order %s is in terminal state %s and cannot be advanced by an observation",
			order.OrderID, order.State)
	}
	// Observations are recorded against the expected version too. A venue report computed
	// against a different view of the order is exactly the stale write docs/01 prohibits.
	if obs.OccurredAt.Before(order.RequestedAt) {
		return ObservationOutcome{}, reject(contracts.CodeValidation,
			"observation is dated %s, before the order was requested at %s; an observation "+
				"that predates the order cannot be about it",
			obs.OccurredAt, order.RequestedAt)
	}

	current := order
	var steps []Transition
	for {
		t, ok := transitionForObservation(current.State, obs.Kind)
		if !ok {
			// A fill reported on an order the venue never separately acknowledged is normal
			// venue behaviour. The OMS accepts it, but it walks ACKNOWLEDGED first so the
			// chain in docs/04 is genuinely traversed and the audit record shows the order was
			// live before it traded. The intermediate edge is a real declared edge, not a
			// synthesised shortcut.
			if ack, synth := acknowledgementFor(current.State, obs.Kind); synth {
				t, ok = ack, true
			} else {
				break
			}
		}
		// An UNKNOWN order may only be resolved by an evidenced observation, and a
		// reconciliation case must have been recorded first. That is checked before the edge
		// is taken, so the order never moves at all on a refusal.
		if current.State == StateUnknown && current.ReconciliationCaseID == "" {
			return ObservationOutcome{}, reject(contracts.CodeValidation,
				"order %s is UNKNOWN and has no reconciliation case recorded; an unknown "+
					"outcome is resolved by reconciliation, not by the next adapter report "+
					"that happens to arrive (docs/25 section 3.3)",
				current.OrderID)
		}
		if missing := missingPreconditions(t, observedPreconditions(obs, order)); len(missing) > 0 {
			return ObservationOutcome{}, reject(contracts.CodeValidation,
				"observation edge %s requires %v, which this observation does not establish",
				t, missing)
		}

		next := current
		next.Version = current.Version + 1
		next.State = t.To
		next.UpdatedAt = obs.OccurredAt
		if obs.VenueOrderRef != "" {
			next.VenueOrderRef = obs.VenueOrderRef
		}
		if err := applyFillAccounting(&next, obs, current); err != nil {
			return ObservationOutcome{}, err
		}
		steps = append(steps, t)
		current = next

		// One observation consumes one kind. The only reason to loop is to walk the
		// synthesised acknowledgement, which is recognised by the order not yet being in the
		// state the kind produces.
		if current.State == obsTargetState(obs.Kind) || current.State.IsTerminal() {
			break
		}
		if current.State == StateAcknowledged && obs.Kind != ObsAcknowledged {
			// The acknowledgement step has been taken; the next pass takes the real edge.
			continue
		}
		break
	}
	if len(steps) == 0 {
		return ObservationOutcome{}, reject(contracts.CodeValidation,
			"observation %q is not a declared outcome for an order in %s; an adapter cannot "+
				"drive the state machine, and an observation the OMS cannot interpret is "+
				"refused rather than ignored", obs.Kind, order.State)
	}
	return ObservationOutcome{Order: current, Steps: steps}, nil
}

// acknowledgementFor returns the edge to walk before applying a fill that arrived on an order
// the venue never separately acknowledged.
//
// Only fills need it. A rejection, expiry, or cancellation is a terminal alternative to the
// chain rather than a step after it, so those are applied directly.
func acknowledgementFor(from State, kind ObservationKind) (Transition, bool) {
	if kind != ObsPartiallyFilled && kind != ObsFilled {
		return Transition{}, false
	}
	if from != StateSubmitting {
		return Transition{}, false
	}
	return transitionForObservation(from, ObsAcknowledged)
}

// observedPreconditions lists what an observation establishes.
//
// An observation is evidence from outside, so it establishes only what the venue could
// actually witness. It never establishes a risk decision, a halt clearance, or a
// reconciliation, all of which are internal facts an adapter has no standing to assert.
func observedPreconditions(obs Observation, order Order) []Precondition {
	var out []Precondition
	if obs.Kind == ObsPartiallyFilled || obs.Kind == ObsFilled {
		// Fills outstanding is a property of the order's own accounting, checked by
		// applyFillAccounting against the order quantity, so it is asserted here only when
		// the arithmetic actually leaves quantity outstanding.
		if remaining, err := order.RemainingQuantity(); err == nil {
			if positive, err := remaining.Value().Cmp(contracts.MustParseDecimal("0")); err == nil && positive > 0 {
				out = append(out, PreFillsOutstanding)
			}
		}
	}
	if order.State == StateUnknown && order.ReconciliationCaseID != "" {
		out = append(out, PreReconciled)
	}
	return out
}

// obsTargetState is the internal state an observation kind normally produces.
func obsTargetState(kind ObservationKind) State {
	if kind == ObsPartiallyFilled {
		return StatePartiallyFilled
	}
	for state, implied := range observationImpliedKind {
		if implied == kind {
			return state
		}
	}
	return ""
}

// applyFillAccounting enforces the financial invariants on a fill.
//
// The two that matter are that cumulative filled never decreases and never exceeds the order
// quantity. A venue reporting a smaller cumulative than it previously reported is a venue
// correction, not a fact, and accepting it would let an order's filled quantity move
// backwards; a venue reporting more than the order quantity means the platform mis-sized the
// order, and recording that as a fill would credit the account with exposure nobody authorised.
func applyFillAccounting(next *Order, obs Observation, current Order) error {
	if obs.Kind != ObsPartiallyFilled && obs.Kind != ObsFilled {
		return nil
	}
	if obs.CumulativeFilled.Unit() != current.Quantity.Unit() {
		return reject(contracts.CodeValidation,
			"observation reports fills in %s but the order is denominated in %s",
			obs.CumulativeFilled.Unit(), current.Quantity.Unit())
	}
	// The venue's running total must not be below what is already recorded. A venue that
	// reports a smaller cumulative is issuing a correction, not a fact, and accepting it
	// would let an order's filled quantity move backwards and quietly return position
	// limit headroom.
	regression, err := obs.CumulativeFilled.Value().Cmp(current.CumulativeFilled.Value())
	if err != nil {
		return err
	}
	if regression < 0 {
		return reject(contracts.CodeConflict,
			"venue reported cumulative filled %s, below the %s already recorded for order %s; "+
				"cumulative filled never decreases",
			obs.CumulativeFilled, current.CumulativeFilled, current.OrderID)
	}
	over, err := obs.CumulativeFilled.Value().Cmp(current.Quantity.Value())
	if err != nil {
		return err
	}
	if over > 0 {
		return reject(contracts.CodeRiskRejected,
			"venue reported cumulative filled %s against an order for %s; accepting an "+
				"overfill would credit exposure nobody authorised",
			obs.CumulativeFilled, current.Quantity)
	}
	next.CumulativeFilled = obs.CumulativeFilled
	return nil
}

// Remaining is a convenience for the audit record.
func (o Order) Remaining() string {
	remaining, err := o.RemainingQuantity()
	if err != nil {
		return "unknown"
	}
	return remaining.String()
}

// String renders an outcome for a log line.
func (o Outcome) String() string {
	return fmt.Sprintf("order %s v%d->%d %s", o.Order.OrderID, o.FromVersion,
		o.Order.Version, o.Transition)
}
