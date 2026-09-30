package oms

import (
	"fmt"
	"sort"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// docs/01 section 8 requires that "every state transition declares: actor, command,
// precondition, resulting state, event, idempotency key, audit record, and failure behavior".
// Every field below is populated for every transition, and a test asserts that, because a
// declaration with a blank field is a declaration that says nothing about the case the
// field exists to cover.

// Precondition is a named, checkable requirement on a transition.
//
// Preconditions are named rather than expressed as predicates so a caller can assert which
// ones it believes are met and the engine can refuse a request whose assertion does not
// match. That keeps the evidence in the request and therefore in the audit record, rather
// than in a boolean the engine computed and discarded.
type Precondition string

// The preconditions used by this machine.
const (
	// PreRiskEvaluated is asserted when the Risk Engine has returned a decision.
	PreRiskEvaluated Precondition = "RISK_EVALUATED"
	// PreRiskApproved is asserted when the Risk Engine approved, with a reference.
	PreRiskApproved Precondition = "RISK_APPROVED"
	// PreRiskRejected is asserted when the Risk Engine rejected, with a reference.
	PreRiskRejected Precondition = "RISK_REJECTED"
	// PreNoActiveHalt is asserted when no halt is in force for the order.
	PreNoActiveHalt Precondition = "NO_ACTIVE_HALT"
	// PreHaltAuthority is asserted by a human actor presenting the exact halt reference.
	PreHaltAuthority Precondition = "HALT_CLEARANCE_AUTHORITY"
	// PreFillsOutstanding is asserted when quantity remains to be filled.
	PreFillsOutstanding Precondition = "FILLS_OUTSTANDING"
	// PreReconciled is asserted when a reconciliation case has resolved an UNKNOWN order.
	PreReconciled Precondition = "RECONCILIATION_RESOLVED"
	// PreReconciledRequired is asserted by a retry from UNKNOWN, naming the case that
	// resolved it. docs/04 requires reconciliation before any retry that could duplicate
	// exposure.
	PreReconciledRequired Precondition = "RECONCILIATION_RESOLVED_BEFORE_RETRY"
)

// FailureBehavior is what happens when a transition later proves ambiguous.
//
// It is declared per transition rather than chosen by the caller, because the safe behaviour
// depends on where the order sits in its life and only the machine knows that. A submission
// that may have reached the venue is UNKNOWN; a cancellation that may not have reached the
// venue leaves the order live at the venue and is likewise UNKNOWN.
type FailureBehavior string

// The failure behaviours.
const (
	// FailureUnresolved means the order enters or stays UNKNOWN and requires reconciliation.
	FailureUnresolved FailureBehavior = "ENTER_UNKNOWN_REQUIRE_RECONCILIATION"
	// FailureTerminal means the order reaches a terminal state and no retry is possible.
	FailureTerminal FailureBehavior = "TERMINAL_NO_RETRY"
	// FailureHoldStops means the order stays in its current state and stops there.
	FailureHoldStops FailureBehavior = "HOLD_IN_CURRENT_STATE"
)

var failureBehaviors = map[FailureBehavior]struct{}{
	FailureUnresolved: {}, FailureTerminal: {}, FailureHoldStops: {},
}

func (f FailureBehavior) valid() bool {
	_, ok := failureBehaviors[f]
	return ok
}

// Transition is one fully declared edge of the order lifecycle.
type Transition struct {
	// From is the state the transition applies to.
	From State
	// To is the state the order reaches.
	To State
	// Command is the command that requests it.
	Command Command
	// PermittedActors are the actor types allowed to request it. An agent is never in any
	// of these sets: docs/25 is explicit that AI proposes and explains while a human or a
	// system acts, and a proposal from an agent is routed to an operator rather than applied.
	PermittedActors []contracts.ActorType
	// RequiresPreconditions must all be asserted by the request.
	RequiresPreconditions []Precondition
	// EventType is the audit event to persist, in the same transaction as the state change.
	EventType string
	// IdempotencyScope is the scope the caller's key is unique within.
	IdempotencyScope string
	// AuditRecord is the human-readable audit description.
	AuditRecord string
	// FailureBehavior is the declared behaviour if this transition later proves ambiguous.
	FailureBehavior FailureBehavior
	// RiskIncreasing marks transitions that create or grow exposure. A risk-increasing
	// transition requires PreNoActiveHalt, which is how the halt hierarchy reaches the OMS
	// without the OMS reimplementing the hierarchy itself.
	RiskIncreasing bool
	// Internal marks transitions only the OMS itself may request, never a caller. Entering
	// UNKNOWN is internal: no adapter observed anything, so no adapter may report it.
	Internal bool
}

// transitions is the declared order lifecycle, exactly the chain in docs/04 plus the
// reconciliation and halt edges this machine needs.
//
// The table is the whole of "adapters report observations and do not rewrite the state
// machine": an observation is resolved to a transition by its kind, and if no transition
// matches, the observation is refused. There is no way to ask for an arbitrary edge.
var transitions = []Transition{
	{
		From: StateCreated, To: StateRiskPending, Command: CmdSubmitForRisk,
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreRiskEvaluated},
		EventType:             "order.risk_pending",
		IdempotencyScope:      "order:" + "risk_pending",
		AuditRecord:           "order entered risk evaluation",
		FailureBehavior:       FailureHoldStops,
	},
	{
		From: StateRiskPending, To: StateRiskApproved, Command: CmdRecordRiskApproval,
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreRiskEvaluated, PreRiskApproved},
		EventType:             "order.risk_approved",
		IdempotencyScope:      "order:risk_approval",
		AuditRecord:           "risk engine approved the order",
		FailureBehavior:       FailureTerminal,
		// An approval is not itself risk-increasing: no exposure exists yet. The submission
		// transition is where a halt must stop the order, and putting the requirement there
		// keeps a halt from blocking the recording of a decision that already happened.
		RiskIncreasing: false,
	},
	{
		From: StateRiskPending, To: StateRejected, Command: CmdRecordRiskRejection,
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreRiskEvaluated, PreRiskRejected},
		EventType:             "order.risk_rejected",
		IdempotencyScope:      "order:risk_rejection",
		AuditRecord:           "risk engine rejected the order",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StateSubmitting, To: StateAcknowledged, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.acknowledged",
		IdempotencyScope:      "venue_order_ref",
		AuditRecord:           "venue acknowledged the order",
		FailureBehavior:       FailureHoldStops,
		// This edge is reached by observation, not by command. The Command field is empty
		// because there is no command that produces it, and a request naming one is refused.
	},
	{
		// There is deliberately no SUBMITTING -> FILLED or SUBMITTING -> PARTIALLY_FILLED edge
		// here. Venues do report a fill on an order they never separately acknowledged, and
		// the OMS accepts that, but it does so by walking ACKNOWLEDGED first (see
		// acknowledgementFor). A direct edge would let a fill land without the order ever
		// having been acknowledged, which contradicts the chain in docs/04 and would mean
		// the OMS recorded a state the order never passed through.
		From: StateSubmitting, To: StateRejected, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.rejected",
		IdempotencyScope:      "venue_order_ref",
		AuditRecord:           "venue rejected the order",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StateSubmitting, To: StateExpired, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.expired",
		IdempotencyScope:      "venue_order_ref",
		AuditRecord:           "venue reported the order expired unfilled",
		FailureBehavior:       FailureTerminal,
	},
	{
		// The edge docs/25 section 3.3 exists to protect. Entering UNKNOWN is internal: it
		// is reached because a submission timed out, which is the absence of a response, not
		// an observation. No adapter can produce it, and no command can request it, so the
		// only way into the ambiguous state is the timeout itself.
		From: StateSubmitting, To: StateUnknown, Command: CmdRecordSubmissionTimeout,
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.unknown",
		IdempotencyScope:      "submission_attempt",
		AuditRecord:           "submission timed out; outcome undetermined and requiring reconciliation",
		FailureBehavior:       FailureUnresolved,
		Internal:              true,
	},
	{
		From: StateAcknowledged, To: StatePartiallyFilled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreFillsOutstanding},
		EventType:             "order.partially_filled",
		IdempotencyScope:      "venue_fill_sequence",
		AuditRecord:           "venue reported a partial fill",
		FailureBehavior:       FailureHoldStops,
	},
	{
		From: StateAcknowledged, To: StateFilled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.filled",
		IdempotencyScope:      "venue_fill_sequence",
		AuditRecord:           "venue reported the order filled",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StatePartiallyFilled, To: StatePartiallyFilled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreFillsOutstanding},
		EventType:             "order.partially_filled",
		IdempotencyScope:      "venue_fill_sequence",
		AuditRecord:           "venue reported a further partial fill",
		FailureBehavior:       FailureHoldStops,
	},
	{
		From: StatePartiallyFilled, To: StateFilled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.filled",
		IdempotencyScope:      "venue_fill_sequence",
		AuditRecord:           "venue reported the remaining quantity filled",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StatePartiallyFilled, To: StateCancelled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreFillsOutstanding},
		EventType:             "order.cancelled",
		IdempotencyScope:      "venue_order_ref",
		AuditRecord:           "venue cancelled the remaining quantity",
		FailureBehavior:       FailureTerminal,
	},
	{
		// A cancellation is risk-reducing, so it is permitted while halted. Blocking it would
		// mean a kill switch stopped the operator from reducing exposure, which is the
		// opposite of what an emergency control is for.
		From: StateRiskPending, To: StateCancelled, Command: CmdCancel,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman, contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.cancelled",
		IdempotencyScope:      "order:cancel",
		AuditRecord:           "order cancelled before submission",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StateRiskApproved, To: StateCancelled, Command: CmdCancel,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman, contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.cancelled",
		IdempotencyScope:      "order:cancel",
		AuditRecord:           "order cancelled after risk approval and before submission",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StateSubmitting, To: StateCancelled, Command: CmdCancel,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman, contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.cancel_requested",
		IdempotencyScope:      "order:cancel",
		AuditRecord:           "cancel requested; the venue outcome is not yet known",
		// A cancel sent to a venue that does not answer leaves the order live at the venue.
		// The honest state for that is UNKNOWN, not CANCELLED, and the timeout edge is what
		// gets the order there.
		FailureBehavior: FailureUnresolved,
	},
	{
		From: StateAcknowledged, To: StateCancelled, Command: CmdCancel,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman, contracts.ActorService},
		RequiresPreconditions: []Precondition{},
		EventType:             "order.cancelled",
		IdempotencyScope:      "order:cancel",
		AuditRecord:           "order cancelled after venue acknowledgement",
		FailureBehavior:       FailureUnresolved,
	},
	{
		// The retry edge, and the reason docs/04 says reconciliation precedes it. The
		// precondition is not a note: a resubmission without a reconciliation case that
		// resolved the order is refused, so the duplicate-exposure hazard is closed by
		// construction.
		From: StateUnknown, To: StateSubmitting, Command: CmdSubmitToVenue,
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreReconciledRequired, PreNoActiveHalt},
		EventType:             "order.resubmitted",
		IdempotencyScope:      "submission_attempt",
		AuditRecord:           "order resubmitted after reconciliation resolved its prior outcome",
		FailureBehavior:       FailureUnresolved,
		RiskIncreasing:        true,
	},
	{
		// Recording the reconciliation result is what lets the edges above fire. It does not
		// itself move the order, because what the evidence showed is not known here; the
		// adapter's subsequent observation does that.
		From: StateUnknown, To: StateUnknown, Command: CmdRecordReconciliation,
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreReconciled},
		EventType:             "order.reconciled",
		IdempotencyScope:      "reconciliation_case",
		AuditRecord:           "reconciliation case recorded against the unknown order",
		FailureBehavior:       FailureUnresolved,
	},
	{
		From: StateUnknown, To: StateFilled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreReconciled},
		EventType:             "order.filled",
		IdempotencyScope:      "venue_fill_sequence",
		AuditRecord:           "venue reported the order filled while outcome was unknown",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StateUnknown, To: StatePartiallyFilled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreReconciled, PreFillsOutstanding},
		EventType:             "order.partially_filled",
		IdempotencyScope:      "venue_fill_sequence",
		AuditRecord:           "venue reported a fill while outcome was unknown",
		FailureBehavior:       FailureHoldStops,
	},
	{
		From: StateUnknown, To: StateRejected, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreReconciled},
		EventType:             "order.rejected",
		IdempotencyScope:      "venue_order_ref",
		AuditRecord:           "venue reported rejection while outcome was unknown",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StateUnknown, To: StateCancelled, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreReconciled},
		EventType:             "order.cancelled",
		IdempotencyScope:      "venue_order_ref",
		AuditRecord:           "venue reported the order cancelled while outcome was unknown",
		FailureBehavior:       FailureTerminal,
	},
	{
		From: StateUnknown, To: StateExpired, Command: "",
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreReconciled},
		EventType:             "order.expired",
		IdempotencyScope:      "venue_order_ref",
		AuditRecord:           "venue reported the order expired while outcome was unknown",
		FailureBehavior:       FailureTerminal,
	},
	{
		// Halting. A halt is risk-reducing, so it is explicitly NOT marked RiskIncreasing:
		// the generic halt check in Apply refuses risk-increasing transitions while a halt is
		// in force, and marking this one would make it impossible to halt an already-halted
		// order, which is the opposite of what an emergency control should do. Re-raising over
		// an active halt is refused separately, by the already-halted check, because
		// overwriting the reference would lock the authority out of clearing it.
		From: StateRiskApproved, To: StateRiskApproved, Command: CmdRaiseHalt,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman},
		RequiresPreconditions: []Precondition{PreNoActiveHalt},
		EventType:             "order.halted",
		IdempotencyScope:      "order:halt",
		AuditRecord:           "order halted",
		FailureBehavior:       FailureHoldStops,
	},
	{
		// Clearing. The only edge in the table that sets a halt inactive, and it is
		// human-only and requires the exact halt reference. There is no system or service
		// actor in PermittedActors, which is what makes the halt monotonic against recovery
		// automation: the automation has no edge to take.
		From: StateRiskApproved, To: StateRiskApproved, Command: CmdClearHalt,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman},
		RequiresPreconditions: []Precondition{PreHaltAuthority},
		EventType:             "order.halt_cleared",
		IdempotencyScope:      "order:halt_clearance",
		AuditRecord:           "order halt cleared by the owning authority",
		FailureBehavior:       FailureHoldStops,
	},
	{
		From: StateSubmitting, To: StateSubmitting, Command: CmdRaiseHalt,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman},
		RequiresPreconditions: []Precondition{PreNoActiveHalt},
		EventType:             "order.halted",
		IdempotencyScope:      "order:halt",
		AuditRecord:           "order halted",
		FailureBehavior:       FailureHoldStops,
		// Risk-reducing for the same reason as the RISK_APPROVED halt edge: an emergency
		// control that could not be applied to a live order would be useless.
	},
	{
		From: StateSubmitting, To: StateSubmitting, Command: CmdClearHalt,
		PermittedActors:       []contracts.ActorType{contracts.ActorHuman},
		RequiresPreconditions: []Precondition{PreHaltAuthority},
		EventType:             "order.halt_cleared",
		IdempotencyScope:      "order:halt_clearance",
		AuditRecord:           "order halt cleared by the owning authority",
		FailureBehavior:       FailureHoldStops,
	},
	{
		// The one risk-increasing edge in the normal chain. PreNoActiveHalt is required here
		// and nowhere else, so a halt stops new exposure and nothing else.
		From: StateRiskApproved, To: StateSubmitting, Command: CmdSubmitToVenue,
		PermittedActors:       []contracts.ActorType{contracts.ActorService},
		RequiresPreconditions: []Precondition{PreRiskApproved, PreNoActiveHalt},
		EventType:             "order.submitting",
		IdempotencyScope:      "submission_attempt",
		AuditRecord:           "order submitted to the venue",
		FailureBehavior:       FailureUnresolved,
		RiskIncreasing:        true,
	},
}

var (
	// byCommand is keyed by "from|command", so a request is matched on both the state it
	// claims and the command it carries. Matching on the state alone would let a caller name
	// a real command that belongs to a different edge, which is a confused-deputy shape
	// rather than a typo.
	byCommand = map[string]Transition{}
	// byObservation is keyed by "from|observation", and is how an adapter report is resolved
	// to an internal state without the adapter naming a state.
	byObservation = map[string]Transition{}
)

// observationImpliedKind maps a destination state to the observation kind that produces it.
//
// It is the inverse of the observation lookup and is what keeps an adapter from naming a
// state: the adapter chooses a kind, and only this map decides what that means internally.
var observationImpliedKind = map[State]ObservationKind{
	StateAcknowledged:    ObsAcknowledged,
	StatePartiallyFilled: ObsPartiallyFilled,
	StateFilled:          ObsFilled,
	StateRejected:        ObsRejected,
	StateExpired:         ObsExpired,
	StateCancelled:       ObsCancelled,
}

func init() {
	// A commandless edge is reached by observation. Its destination determines which
	// observation kind reaches it, so an adapter picks a kind and never a state.
	for _, t := range transitions {
		if t.Command != "" {
			byCommand[t.From.String()+"|"+string(t.Command)] = t
			continue
		}
		kind, ok := observationImpliedKind[t.To]
		if !ok {
			// A commandless edge whose destination is not observation-implied would be
			// unreachable. TestTransitionsAreAllReachable fails on this rather than trusting
			// the table to be well formed.
			continue
		}
		byObservation[t.From.String()+"|"+string(kind)] = t
	}
}

func (t Transition) String() string {
	if t.Command != "" {
		return fmt.Sprintf("%s --%s--> %s", t.From, t.Command, t.To)
	}
	return fmt.Sprintf("%s --observation--> %s", t.From, t.To)
}

// transitionFor returns the declared edge for a state and command.
func transitionFor(from State, cmd Command) (Transition, bool) {
	t, ok := byCommand[from.String()+"|"+string(cmd)]
	return t, ok
}

// transitionForObservation returns the declared edge an observation implies.
func transitionForObservation(from State, kind ObservationKind) (Transition, bool) {
	t, ok := byObservation[from.String()+"|"+string(kind)]
	return t, ok
}

// NextStates returns the states reachable from a state, in a stable order.
//
// It is a hint for a UI or a planner, not a permission: reachability here says nothing about
// authority or preconditions, and the engine still refuses anything undeclared.
func NextStates(from State) []State {
	seen := map[State]bool{}
	for _, t := range transitions {
		if t.From == from {
			seen[t.To] = true
		}
	}
	out := make([]State, 0, len(seen))
	for s := range seen {
		out = append(out, s)
	}
	// Sorted by the documented state order rather than alphabetically, so the list reads in
	// lifecycle order and two runs produce the same list.
	sort.Slice(out, func(i, j int) bool {
		return stateRank(out[i]) < stateRank(out[j])
	})
	return out
}

func stateRank(s State) int {
	for i, v := range allStates {
		if v == s {
			return i
		}
	}
	return len(allStates)
}

func actorPermitted(t Transition, a contracts.ActorType) bool {
	for _, permitted := range t.PermittedActors {
		if permitted == a {
			return true
		}
	}
	return false
}

// missingPreconditions returns the preconditions the transition requires that the request did
// not assert.
func missingPreconditions(t Transition, asserted []Precondition) []Precondition {
	have := make(map[Precondition]bool, len(asserted))
	for _, p := range asserted {
		have[p] = true
	}
	var missing []Precondition
	for _, p := range t.RequiresPreconditions {
		if !have[p] {
			missing = append(missing, p)
		}
	}
	return missing
}
