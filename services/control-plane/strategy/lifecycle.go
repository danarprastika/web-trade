// Package strategy implements the strategy lifecycle state machine.
//
// The lifecycle is authoritative domain state owned by the control plane, not by the
// strategy component itself. docs/01 section 5 and docs/25 section 3.6 keep the authority
// boundary here; a strategy may propose that it be advanced, and this package decides
// whether the proposal is well-formed.
//
// Two properties are load-bearing and are what make the rest of the system auditable:
//
//  1. The state set is closed and every transition is declared. An unknown state or an
//     undeclared transition is a controlled rejection, never a guess. docs/03 requires
//     unknown enum values to be treated as unsupported rather than silently mapped, and a
//     guessed transition in a deployment lifecycle means deploying something nobody
//     approved.
//  2. A strategy holds zero financial authority. The DEPLOYED state makes a strategy
//     *eligible* for risk evaluation; it does not authorize a trade. Every risk-increasing
//     order still passes the deterministic Risk Engine veto, which is final
//     (docs/25 section 3.1). Nothing in this package can place, amend, or cancel an order,
//     and the import test in lifecycle_test.go enforces that boundary mechanically.
package strategy

import (
	"fmt"
	"sort"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// State is a strategy lifecycle state. The set is closed and taken verbatim from
// docs/04_TRADING_DOMAIN_AND_RISK.md: "DRAFT -> REVIEW -> BACKTESTED -> SIMULATION ->
// PAPER -> SHADOW -> APPROVED -> DEPLOYED -> PAUSED -> RETIRED".
type State string

// The closed set of lifecycle states.
const (
	StateDraft      State = "DRAFT"
	StateReview     State = "REVIEW"
	StateBacktested State = "BACKTESTED"
	StateSimulation State = "SIMULATION"
	StatePaper      State = "PAPER"
	StateShadow     State = "SHADOW"
	StateApproved   State = "APPROVED"
	StateDeployed   State = "DEPLOYED"
	StatePaused     State = "PAUSED"
	StateRetired    State = "RETIRED"
)

var allStates = []State{
	StateDraft, StateReview, StateBacktested, StateSimulation, StatePaper,
	StateShadow, StateApproved, StateDeployed, StatePaused, StateRetired,
}

// Valid reports whether the state is in the closed set.
func (s State) Valid() bool {
	_, ok := stateIndex[s]
	return ok
}

var stateIndex = func() map[State]struct{} {
	m := make(map[State]struct{}, len(allStates))
	for _, s := range allStates {
		m[s] = struct{}{}
	}
	return m
}()

// AllStates returns every lifecycle state in progression order.
//
// The order is the documented order, not alphabetical. It is used to present a next-state
// hint to an operator, so a stable and meaningful order matters more than a total one.
func AllStates() []State {
	out := make([]State, len(allStates))
	copy(out, allStates)
	return out
}

// ParseState resolves a state name, rejecting anything outside the closed set.
func ParseState(s string) (State, error) {
	st := State(s)
	if !st.Valid() {
		return "", fmt.Errorf("%w: %q is not a known strategy state; unknown states are "+
			"unsupported, not mapped to a default", contracts.ErrInvalidContractValue, s)
	}
	return st, nil
}

// IsTerminal reports whether the state has no onward transition.
func (s State) IsTerminal() bool { return s == StateRetired }

// Command is a lifecycle transition request. Commands are explicit: docs/04 states that
// "transitions are explicit commands and produce immutable audit events".
type Command string

// The command types, one per declared transition.
const (
	CommandSubmitForReview Command = "strategy.review.requested"
	CommandRecordBacktest  Command = "strategy.backtest.recorded"
	CommandBeginSimulation Command = "strategy.simulation.started"
	CommandPromoteToPaper  Command = "strategy.paper.promoted"
	CommandPromoteToShadow Command = "strategy.shadow.promoted"
	CommandApprove         Command = "strategy.approved"
	CommandDeploy          Command = "strategy.deployed"
	CommandPause           Command = "strategy.paused"
	CommandRetire          Command = "strategy.retired"
)

// FailureBehavior is what happens when a transition cannot be applied cleanly.
//
// It is declared per transition rather than chosen by the caller, because the safe
// response to an ambiguous outcome differs by transition: refusing to leave a known state
// is correct for most transitions, while a partially applied deployment has to be halted
// and reconciled instead.
type FailureBehavior string

// The failure behaviours.
const (
	// FailureDenyRemain means the state is unchanged and the request is refused.
	FailureDenyRemain FailureBehavior = "DENY_REMAIN_IN_STATE"
	// FailureHaltAndReconcile means the strategy is halted and a reconciliation case is
	// required before it can move again. Used where a partially applied transition would
	// leave the platform unable to establish the true state.
	FailureHaltAndReconcile FailureBehavior = "HALT_AND_RECONCILE"
)

// Transition is one fully declared edge of the lifecycle graph.
//
// Every field is populated for every transition, because the acceptance criteria require
// that each transition declare its actor, command, precondition, resulting state, event,
// idempotency scope, audit record, and failure behaviour. A transition with a blank field
// is a defect the constructor rejects, rather than a gap left for a caller to interpret.
type Transition struct {
	From State
	To   State
	// Command is the request type that attempts this transition.
	Command Command
	// PermittedActors is the closed set of actor types allowed to invoke it. An actor
	// outside this set is denied; it is never downgraded to a warning.
	PermittedActors []contracts.ActorType
	// Precondition is the named evidence this transition requires. It is a name rather
	// than prose so it can be referenced by a test and by the audit record.
	Precondition Precondition
	// EventType is the immutable audit event the successful transition emits.
	EventType string
	// IdempotencyScope names the scope a caller must key its retry within.
	IdempotencyScope string
	// AuditRecord describes what is written to the audit chain on success.
	AuditRecord string
	// FailureBehavior is what a refusal or ambiguity does to the strategy.
	FailureBehavior FailureBehavior
}

// Precondition is a named, checkable requirement. The engine evaluates the name the caller
// supplies against the name the transition requires, and refuses a mismatch.
type Precondition string

// The named preconditions.
const (
	// PreconditionReviewSubmission means a review request exists with a named reviewer.
	PreconditionReviewSubmission Precondition = "review_submission_recorded"
	// PreconditionReproducibleBacktest means a reproducible backtest artifact exists.
	PreconditionReproducibleBacktest Precondition = "reproducible_backtest_artifact"
	// PreconditionSimulationGate means the simulation gate evidence is current.
	PreconditionSimulationGate Precondition = "simulation_gate_evidence_current"
	// PreconditionPaperEvidence means paper-trading evidence is recorded.
	PreconditionPaperEvidence Precondition = "paper_trading_evidence_recorded"
	// PreconditionShadowEvidence means shadow-trading evidence and reconciliation passed.
	PreconditionShadowEvidence Precondition = "shadow_reconciliation_passed"
	// PreconditionOwnerApproval means an explicit, non-delegable owner approval exists.
	PreconditionOwnerApproval Precondition = "explicit_owner_approval"
	// PreconditionNoActiveHalt means no halt is active at this or any higher level.
	PreconditionNoActiveHalt Precondition = "no_active_halt"
	// PreconditionFlatPosition means the strategy holds no exposure, so it can be retired
	// without stranding a position.
	PreconditionFlatPosition Precondition = "no_open_exposure"
)

// humanActor is the set permitted to grant or revoke authority. Grounded in docs/25 section
// 3.6, where human approval governs sensitive transitions, and docs/01 section 5, where AI
// and strategy components propose only.
//
// An agent is deliberately absent. docs/25 is explicit that AI proposes and explains while
// deterministic policy and human approval govern sensitive transitions, so an AI actor may
// never be the actor of record for a lifecycle change. A proposal from an agent is routed to
// a permitted actor and recorded as such.
var humanActor = []contracts.ActorType{contracts.ActorHuman}

// machineActors are the actors permitted to advance a state whose evidence is produced by a
// pipeline rather than by a person. The proposal is still recorded and the evidence is
// still checked; what changes is who supplies the attestation.
var machineActors = []contracts.ActorType{contracts.ActorService, contracts.ActorSystem}

// humanAndMachine is the set permitted where a person may act and a pipeline may also
// supply the evidence, such as an owner-initiated retirement and an automated one.
//
// The slices are spelled out rather than composed with append because a shared backing
// array is a real hazard here: appending to one set could otherwise overwrite the elements
// of another if a capacity were ever reused.
var (
	humanAndService = []contracts.ActorType{contracts.ActorHuman, contracts.ActorService}
	humanAndSystem  = []contracts.ActorType{contracts.ActorHuman, contracts.ActorSystem}
	anyNonAgent     = []contracts.ActorType{
		contracts.ActorHuman, contracts.ActorService, contracts.ActorSystem,
	}
)

// transitions is the declared lifecycle graph, exactly the chain in docs/04.
var transitions = []Transition{
	{
		From: StateDraft, To: StateReview, Command: CommandSubmitForReview,
		PermittedActors:  humanAndService,
		Precondition:     PreconditionReviewSubmission,
		EventType:        "strategy.review.requested",
		IdempotencyScope: "strategy/lifecycle/review",
		AuditRecord:      "strategy entered REVIEW with the requesting actor and review request id",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateReview, To: StateBacktested, Command: CommandRecordBacktest,
		PermittedActors:  machineActors,
		Precondition:     PreconditionReproducibleBacktest,
		EventType:        "strategy.backtest.recorded",
		IdempotencyScope: "strategy/lifecycle/backtest",
		AuditRecord:      "strategy entered BACKTESTED with the backtest artifact digest",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateBacktested, To: StateSimulation, Command: CommandBeginSimulation,
		PermittedActors:  machineActors,
		Precondition:     PreconditionSimulationGate,
		EventType:        "strategy.simulation.started",
		IdempotencyScope: "strategy/lifecycle/simulation",
		AuditRecord:      "strategy entered SIMULATION with the gate evidence reference",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateSimulation, To: StatePaper, Command: CommandPromoteToPaper,
		PermittedActors:  machineActors,
		Precondition:     PreconditionPaperEvidence,
		EventType:        "strategy.paper.promoted",
		IdempotencyScope: "strategy/lifecycle/paper",
		AuditRecord:      "strategy entered PAPER with the simulation outcome summary",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StatePaper, To: StateShadow, Command: CommandPromoteToShadow,
		PermittedActors:  machineActors,
		Precondition:     PreconditionShadowEvidence,
		EventType:        "strategy.paper.to_shadow.promoted",
		IdempotencyScope: "strategy/lifecycle/shadow",
		AuditRecord:      "strategy entered SHADOW with the paper-trading evidence reference",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateShadow, To: StateApproved, Command: CommandApprove,
		// Approval is the first state that carries authority, so it is human-gated.
		PermittedActors:  humanActor,
		Precondition:     PreconditionOwnerApproval,
		EventType:        "strategy.approved",
		IdempotencyScope: "strategy/lifecycle/approve",
		AuditRecord:      "strategy APPROVED by a named owner, recording the approval reference",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateApproved, To: StateDeployed, Command: CommandDeploy,
		// Deployment is authority-bearing, so it stays human-gated even though the
		// preceding states may be advanced by a pipeline.
		PermittedActors:  humanActor,
		Precondition:     PreconditionNoActiveHalt,
		EventType:        "strategy.deployed",
		IdempotencyScope: "strategy/lifecycle/deploy",
		AuditRecord:      "strategy DEPLOYED with the release artifact digest and configuration snapshot id",
		FailureBehavior:  FailureHaltAndReconcile,
	},
	{
		From: StateDeployed, To: StatePaused, Command: CommandPause,
		PermittedActors:  humanAndSystem,
		Precondition:     PreconditionNoActiveHalt,
		EventType:        "strategy.paused",
		IdempotencyScope: "strategy/lifecycle/pause",
		AuditRecord:      "strategy PAUSED with the reason and the requesting actor",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StatePaused, To: StateRetired, Command: CommandRetire,
		PermittedActors:  anyNonAgent,
		Precondition:     PreconditionFlatPosition,
		EventType:        "strategy.retired",
		IdempotencyScope: "strategy/lifecycle/retire",
		AuditRecord:      "strategy RETIRED with the disposition of any residual position",
		FailureBehavior:  FailureDenyRemain,
	},
}

// transitionIndex is keyed by "from" then "to", and separately by "from" then command, so a
// request is matched on both the state it claims and the command it carries.
var (
	byFromTo = map[[2]State]Transition{}
	byCmd    = map[Command]Transition{}
)

func init() {
	for _, t := range transitions {
		byFromTo[[2]State{t.From, t.To}] = t
		byCmd[t.Command] = t
	}
}

// transitionsFrom returns the declared onward transitions from a state, in progression
// order. It is the machine-readable answer to "what could happen next from here", which an
// operator needs in order to understand a rejection.
func transitionsFrom(s State) []Transition {
	var out []Transition
	for _, t := range transitions {
		if t.From == s {
			out = append(out, t)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].To < out[j].To })
	return out
}

// NextStates returns the states reachable from s in one declared transition.
func NextStates(s State) []State {
	var out []State
	for _, t := range transitionsFrom(s) {
		out = append(out, t.To)
	}
	return out
}

// TransitionFor returns the declared transition from one state to another.
func TransitionFor(from, to State) (Transition, bool) {
	t, ok := byFromTo[[2]State{from, to}]
	return t, ok
}

// Request is a proposed lifecycle transition.
type Request struct {
	StrategyID contracts.Identifier
	From       State
	Command    Command
	ActorID    string
	ActorType  contracts.ActorType
	// PreconditionsSatisfied lists the preconditions the caller asserts are met. The
	// engine requires the transition's own precondition to appear here; asserting extra
	// names is harmless, and asserting a different one is refused.
	PreconditionsSatisfied []Precondition
	// IdempotencyKey is the caller's key for this logical transition. It is required
	// because a retried transition must not advance a strategy twice.
	IdempotencyKey string
	// Reference is a pointer to the evidence the precondition names, such as an approval
	// reference or an artifact digest. It is recorded in the audit event.
	Reference string
}

// Outcome is the result of a successful transition.
type Outcome struct {
	StrategyID contracts.Identifier
	Transition Transition
	// EventType is the audit event to persist, in the same transaction as the state change.
	EventType string
	// AuditRecord is the human-readable audit description.
	AuditRecord string
	// IdempotencyScope is the scope the caller's key is unique within.
	IdempotencyScope string
	// FailureBehavior is the declared behaviour if this transition later proves ambiguous.
	FailureBehavior FailureBehavior
}

// Apply validates a proposed transition and returns the resulting outcome.
//
// The order of checks matters and is deliberate: the state is validated before the command
// is looked up, so an unknown state is reported as an unknown state rather than as a
// missing transition. Authority is checked before preconditions, because an actor without
// permission has no standing to assert that a precondition is met, and evaluating a
// precondition on behalf of an unauthorised caller would leak whether the evidence exists.
// Rejection is a refused lifecycle transition.
//
// It carries two things that a single fmt.Errorf cannot. The canonical ErrorCode is the
// wire contract: a caller on another service needs to see AUTHORIZATION_ERROR rather than
// prose, and it is what the closed taxonomy in docs/03 requires. The wrapped sentinel is
// the local cause, so errors.Is keeps working for in-process checks.
//
// Conflating the two by formatting an ErrorCode with %w is not possible, and formatting it
// as %s would discard the code's machine-readable role, which is precisely the part that
// must not be lost. go vet rejects the first form, and the second would be worse than a
// compile error because it would compile.
type Rejection struct {
	// Code is the canonical error code from docs/03.
	Code contracts.ErrorCode
	// Cause is the local sentinel, reachable through errors.Is.
	Cause error
	// Reason is the human-facing explanation. Never parsed.
	Reason string
}

// Error satisfies error, leading with the code so a log consumer that pattern-matches on
// the stable part stays correct if the wording changes.
func (r Rejection) Error() string {
	return fmt.Sprintf("%s: %s", r.Code, r.Reason)
}

// Unwrap exposes the local sentinel to errors.Is and errors.As.
func (r Rejection) Unwrap() error { return r.Cause }

// reject builds a Rejection with a formatted reason.
func reject(code contracts.ErrorCode, cause error, format string, args ...any) Rejection {
	return Rejection{Code: code, Cause: cause, Reason: fmt.Sprintf(format, args...)}
}

func Apply(req Request) (Outcome, error) {
	if !req.From.Valid() {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"strategy %s reports unknown state %q; an unknown state is not treated as a default",
			req.StrategyID, req.From)
	}
	if req.StrategyID.IsZero() {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"strategy id is required")
	}
	if req.StrategyID.Prefix() != contracts.PrefixStrategy {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"strategy id must carry the %q prefix, got %q",
			contracts.PrefixStrategy, req.StrategyID.Prefix())
	}
	if req.ActorType == "" || req.ActorID == "" {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"actor_id and actor_type are both required; an unattributed transition is not auditable")
	}
	if len(req.IdempotencyKey) < 8 {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"idempotency key must be at least 8 characters; a transition without one "+
				"could be applied twice on retry")
	}
	if req.From.IsTerminal() {
		return Outcome{}, terminalError(req)
	}

	declared, ok := byCmd[req.Command]
	if !ok {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"%q is not a known lifecycle command; unknown commands are unsupported", req.Command)
	}
	// The command must belong to the transition the caller claims to be making. Checking
	// the state alone would let a caller name a real command that belongs to a different
	// edge, which is a confused-deputy shape rather than a typo.
	if declared.From != req.From {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"command %q is declared for %s -> %s but the request claims state %s",
			req.Command, declared.From, declared.To, req.From)
	}

	if !actorPermitted(declared, req.ActorType) {
		return Outcome{}, reject(contracts.CodeAuthorization, contracts.ErrInvalidContractValue,
			"actor type %s may not perform %s (%s -> %s); permitted: %s",
			req.ActorType, req.Command, declared.From, declared.To,
			describeActors(declared.PermittedActors))
	}

	if !preconditionSatisfied(declared.Precondition, req.PreconditionsSatisfied) {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"transition %s (%s -> %s) requires precondition %q",
			req.Command, declared.From, declared.To, declared.Precondition)
	}
	if strings.TrimSpace(req.Reference) == "" {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"transition %s requires a reference to the evidence satisfying %q, "+
				"which is what the audit record cites",
			req.Command, declared.Precondition)
	}

	return Outcome{
		StrategyID:       req.StrategyID,
		Transition:       declared,
		EventType:        declared.EventType,
		AuditRecord:      declared.AuditRecord,
		IdempotencyScope: declared.IdempotencyScope,
		FailureBehavior:  declared.FailureBehavior,
	}, nil
}

// terminalError builds the refusal for a strategy in a terminal state. It names the legal
// successors so the caller is told what would have been valid, not merely that this was not.
func terminalError(req Request) error {
	next := NextStates(req.From)
	if len(next) == 0 {
		return reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"strategy %s is in terminal state %s and has no onward transition",
			req.StrategyID, req.From)
	}
	return reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
		"strategy %s is in terminal state %s; no transition out of it exists, so %q cannot apply",
		req.StrategyID, req.From, req.Command)
}

func actorPermitted(t Transition, actor contracts.ActorType) bool {
	for _, permitted := range t.PermittedActors {
		if permitted == actor {
			return true
		}
	}
	return false
}

func preconditionSatisfied(required Precondition, satisfied []Precondition) bool {
	for _, p := range satisfied {
		if p == required {
			return true
		}
	}
	return false
}

func describeActors(actors []contracts.ActorType) string {
	parts := make([]string, 0, len(actors))
	for _, a := range actors {
		parts = append(parts, a.String())
	}
	return strings.Join(parts, ", ")
}
