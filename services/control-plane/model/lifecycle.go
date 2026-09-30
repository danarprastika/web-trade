package model

import (
	"fmt"
	"sort"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// State is a model lifecycle state. The set is closed and taken verbatim from docs/07
// section 1: "REGISTERED -> EVALUATED -> VALIDATED -> APPROVED -> PAPER -> SHADOW ->
// PROMOTED -> MONITORED -> RETIRED".
type State string

// The closed set of lifecycle states.
const (
	StateRegistered State = "REGISTERED"
	StateEvaluated  State = "EVALUATED"
	StateValidated  State = "VALIDATED"
	StateApproved   State = "APPROVED"
	StatePaper      State = "PAPER"
	StateShadow     State = "SHADOW"
	StatePromoted   State = "PROMOTED"
	StateMonitored  State = "MONITORED"
	StateRetired    State = "RETIRED"
	// StateQuarantined is not in the documented progression. It is a terminal hold applied
	// out of band when a model or its producing workload is compromised, and it is declared
	// here rather than being a flag on the record because a quarantine that is not a state
	// is a quarantine that a promotion path can be written to ignore.
	StateQuarantined State = "QUARANTINED"
)

var allStates = []State{
	StateRegistered, StateEvaluated, StateValidated, StateApproved, StatePaper,
	StateShadow, StatePromoted, StateMonitored, StateRetired, StateQuarantined,
}

// Valid reports whether the state is in the closed set.
func (s State) Valid() bool {
	for _, k := range allStates {
		if k == s {
			return true
		}
	}
	return false
}

// AllStates returns every state in lifecycle order, with QUARANTINED last because it is
// reachable from anywhere and is not part of the progression.
func AllStates() []State {
	out := make([]State, len(allStates))
	copy(out, allStates)
	return out
}

// ParseState resolves a state name, rejecting anything outside the closed set.
func ParseState(s string) (State, error) {
	st := State(s)
	if !st.Valid() {
		return "", reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"%q is not a known model state; unknown states are unsupported, not mapped "+
				"to a default", s)
	}
	return st, nil
}

// IsTerminal reports whether the state has no onward transition.
func (s State) IsTerminal() bool { return s == StateRetired || s == StateQuarantined }

// Command is a lifecycle transition request. Commands are explicit, mirroring the strategy
// lifecycle: a state change is an event with an actor, not a field assignment.
type Command string

// The command types, one per declared transition.
const (
	CommandRecordEvaluation Command = "model.evaluation.recorded"
	// CommandRegister is the model's entry into the lifecycle. It is the only command with
	// no prior state, which is why it is the only one permitted an empty source.
	CommandRegister         Command = "model.registered"
	CommandRecordValidation Command = "model.validation.recorded"
	CommandApprove          Command = "model.approved"
	CommandPromoteToPaper   Command = "model.paper.promoted"
	CommandPromoteToShadow  Command = "model.shadow.promoted"
	CommandPromote          Command = "model.promoted"
	CommandStartMonitoring  Command = "model.monitoring.started"
	CommandRetire           Command = "model.retired"
	CommandQuarantine       Command = "model.quarantined"
	CommandClearQuarantine  Command = "model.quarantine.cleared"
)

// Precondition is a named, checkable requirement. Naming them keeps the requirement
// referenceable by a test and by the audit record instead of living in prose that drifts.
type Precondition string

// The named preconditions.
const (
	// PreconditionEvaluationEvidence means an evaluation report digest exists.
	PreconditionEvaluationEvidence Precondition = "evaluation_evidence_recorded"
	// PreconditionModelRecord is the evidence registration requires: the complete
	// eleven-field model record, not a name and a version. A model whose limitations are
	// unrecorded is one whose failure modes are unknown, and registering it would put that
	// unknown model into the lifecycle.
	PreconditionModelRecord Precondition = "model_record_complete"
	// PreconditionValidationEvidence means validation was performed against held-out data
	// and the result is recorded.
	PreconditionValidationEvidence Precondition = "validation_evidence_recorded"
	// PreconditionIndependentApproval means an approval exists from a reviewer who is
	// neither the owner nor the author.
	PreconditionIndependentApproval Precondition = "independent_approval_recorded"
	// PreconditionRollbackReady means a rollback artifact is recorded and current.
	PreconditionRollbackReady Precondition = "rollback_artifact_present"
	// PreconditionMonitoringPolicy means a monitoring policy is attached.
	PreconditionMonitoringPolicy Precondition = "monitoring_policy_attached"
	// PreconditionNotQuarantined means neither the model nor its producing workload is
	// under quarantine.
	PreconditionNotQuarantined Precondition = "not_quarantined"
	// PreconditionNoOpenExposure means the model holds no exposure, so it can be retired
	// or rolled back without stranding a position.
	PreconditionNoOpenExposure Precondition = "no_open_exposure"
	// PreconditionForensicPreserved means forensic evidence has been preserved and the
	// compromise has been independently reviewed before a quarantine may be cleared.
	PreconditionForensicPreserved Precondition = "forensic_evidence_preserved"
)

// Transition is one fully declared edge of the lifecycle graph.
type Transition struct {
	From State
	To   State
	// Command is the request type that attempts this transition.
	Command Command
	// PermittedActors is the closed set of actor types allowed to invoke it.
	PermittedActors []contracts.ActorType
	// Precondition is the named evidence this transition requires.
	Precondition Precondition
	// EventType is the immutable audit event the successful transition emits.
	EventType string
	// IdempotencyScope names the scope a caller must key its retry within.
	IdempotencyScope string
	// AuditRecord describes what is written to the audit chain on success.
	AuditRecord string
	// RequiresIndependentApprover marks a transition whose actor must be a person other
	// than the record's owner and author. This is the mechanical form of docs/07's
	// "Research authors cannot self-approve a model for live use", and it is enforced in
	// Apply against the actor id rather than left to a reviewer's memory.
	RequiresIndependentApprover bool
	// FailureBehavior is what a refusal does to the model.
	FailureBehavior FailureBehavior
	// MultiSource marks a transition whose command is deliberately declared from more
	// than one source state, so that a single command can be a valid request from any of
	// them. The quarantine command is the only such command: a compromise can arrive while
	// a model is in any state, and requiring a different command per state would mean the
	// responder had to know the model's state to respond to a compromise.
	//
	// The field is required to be set consistently by VerifyDeclaration, because the
	// alternative is an implicit rule: a command appearing on several edges would mean
	// two different things depending on which edge the lookup happened to find, and the
	// difference would be a request being applied to the wrong transition.
	MultiSource bool
}

// FailureBehavior is what happens when a transition cannot be applied cleanly.
type FailureBehavior string

// The failure behaviours.
const (
	// FailureDenyRemain means the state is unchanged and the request is refused.
	FailureDenyRemain FailureBehavior = "DENY_REMAIN_IN_STATE"
	// FailureHaltAndReconcile means the model is halted and reconciliation is required
	// before it can move again. Used where a partially applied transition would leave the
	// platform unable to establish the true state.
	FailureHaltAndReconcile FailureBehavior = "HALT_AND_RECONCILE"
)

// The actor sets. They are spelled out rather than composed with append because a shared
// backing array is a real hazard: appending to one set could otherwise overwrite the elements
// of another if a capacity were ever reused.
var (
	// pipelineActors may advance a model through the states whose evidence is produced by a
	// pipeline rather than by a person.
	pipelineActors = []contracts.ActorType{contracts.ActorService, contracts.ActorSystem}
	// humanActors is the set permitted to grant authority. An agent is deliberately absent:
	// docs/25 section 3.6 is explicit that AI proposes while deterministic policy and human
	// approval govern sensitive transitions, so an AI actor may never be the actor of record
	// for a lifecycle change.
	humanActors = []contracts.ActorType{contracts.ActorHuman}
	// humanAndSystem may perform operator-initiated or automated suspensions.
	humanAndSystem = []contracts.ActorType{contracts.ActorHuman, contracts.ActorSystem}
	// anyNonAgent is every actor type except an agent and a strategy.
	anyNonAgent = []contracts.ActorType{
		contracts.ActorHuman, contracts.ActorService, contracts.ActorSystem,
	}
	// securityActors responds to a compromise. It is restricted to human and system
	// identities so that the entity that is being shut down cannot be the one deciding to
	// shut itself down on a schedule of its own choosing.
	securityActors = []contracts.ActorType{contracts.ActorHuman, contracts.ActorSystem}
)

// transitions is the declared lifecycle graph, exactly the chain in docs/07 plus the
// out-of-band quarantine edges.
var transitions = []Transition{
	{
		// Registration is the model's entry into the lifecycle, so its source state is
		// empty: a model that does not exist yet is not in a state, and inventing a
		// "DRAFT" or "UNREGISTERED" state to give it one would add a state that docs/07
		// does not describe and that no rule would ever move the model out of.
		//
		// Declaring it here rather than hardcoding an event type in the journal is what
		// keeps registration inside the same declared, audit-emitting set as every other
		// state change. Before this edge existed, a model could enter the registry with no
		// declared transition, no event type, and no idempotency scope, which is precisely
		// the gap gate G5's first acceptance criterion is written against.
		From: "", To: StateRegistered, Command: CommandRegister,
		PermittedActors:  pipelineActors,
		Precondition:     PreconditionModelRecord,
		EventType:        "model.registered",
		IdempotencyScope: "model/lifecycle/register",
		AuditRecord:      "model entered REGISTERED with the eleven-field model record",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateRegistered, To: StateEvaluated, Command: CommandRecordEvaluation,
		PermittedActors:  pipelineActors,
		Precondition:     PreconditionEvaluationEvidence,
		EventType:        "model.evaluation.recorded",
		IdempotencyScope: "model/lifecycle/evaluation",
		AuditRecord:      "model entered EVALUATED with the evaluation report digest",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateEvaluated, To: StateValidated, Command: CommandRecordValidation,
		PermittedActors:  pipelineActors,
		Precondition:     PreconditionValidationEvidence,
		EventType:        "model.validation.recorded",
		IdempotencyScope: "model/lifecycle/validation",
		AuditRecord:      "model entered VALIDATED with the held-out validation result digest",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateValidated, To: StateApproved, Command: CommandApprove,
		// Approval is the first state that carries authority, so it is human-gated, and
		// it additionally requires an approver who is neither owner nor author. docs/07
		// section 2 requires an independent reviewer; making it a property of the
		// transition is what stops it from depending on who reads the ticket.
		PermittedActors:             humanActors,
		Precondition:                PreconditionIndependentApproval,
		EventType:                   "model.approved",
		IdempotencyScope:            "model/lifecycle/approve",
		AuditRecord:                 "model APPROVED by a named independent reviewer, recording the approval digest",
		RequiresIndependentApprover: true,
		FailureBehavior:             FailureDenyRemain,
	},
	{
		From: StateApproved, To: StatePaper, Command: CommandPromoteToPaper,
		PermittedActors:  pipelineActors,
		Precondition:     PreconditionNotQuarantined,
		EventType:        "model.paper.promoted",
		IdempotencyScope: "model/lifecycle/paper",
		AuditRecord:      "model entered PAPER with the approved version and deployment scope",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StatePaper, To: StateShadow, Command: CommandPromoteToShadow,
		PermittedActors:  pipelineActors,
		Precondition:     PreconditionNotQuarantined,
		EventType:        "model.shadow.promoted",
		IdempotencyScope: "model/lifecycle/shadow",
		AuditRecord:      "model entered SHADOW with the paper-trading evidence reference",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateShadow, To: StatePromoted, Command: CommandPromote,
		// Promotion to a state that can affect real execution stays human-gated and stays
		// subject to the independence rule, because this is the edge a compromised model
		// would most want to reach.
		PermittedActors:             humanActors,
		Precondition:                PreconditionRollbackReady,
		EventType:                   "model.promoted",
		IdempotencyScope:            "model/lifecycle/promote",
		AuditRecord:                 "model PROMOTED with the rollback artifact digest and monitoring policy",
		RequiresIndependentApprover: true,
		FailureBehavior:             FailureHaltAndReconcile,
	},
	{
		From: StatePromoted, To: StateMonitored, Command: CommandStartMonitoring,
		PermittedActors:  pipelineActors,
		Precondition:     PreconditionMonitoringPolicy,
		EventType:        "model.monitoring.started",
		IdempotencyScope: "model/lifecycle/monitor",
		AuditRecord:      "model entered MONITORED under the named drift and degradation policy",
		FailureBehavior:  FailureDenyRemain,
	},
	{
		From: StateMonitored, To: StateRetired, Command: CommandRetire,
		PermittedActors:  anyNonAgent,
		Precondition:     PreconditionNoOpenExposure,
		EventType:        "model.retired",
		IdempotencyScope: "model/lifecycle/retire",
		AuditRecord:      "model RETIRED with the disposition of any residual position",
		FailureBehavior:  FailureDenyRemain,
	},
	// Quarantine is reachable from every non-terminal state. Declaring it per state rather
	// than as a single wildcard is deliberate: an explicit edge is one the compiler and the
	// transition table both check, whereas a wildcard is a rule that holds until someone
	// needs it to.
	{
		From: StateRegistered, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureDenyRemain,
	},
	{
		From: StateEvaluated, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureDenyRemain,
	},
	{
		From: StateValidated, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureDenyRemain,
	},
	{
		From: StateApproved, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureDenyRemain,
	},
	{
		From: StatePaper, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureDenyRemain,
	},
	{
		From: StateShadow, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureDenyRemain,
	},
	{
		From: StatePromoted, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureHaltAndReconcile,
	},
	{
		From: StateMonitored, To: StateQuarantined, Command: CommandQuarantine,
		MultiSource:      true,
		PermittedActors:  securityActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantined",
		IdempotencyScope: "model/lifecycle/quarantine",
		AuditRecord: "model QUARANTINED: workload identity revoked, artifacts quarantined, " +
			"promotion blocked, forensic evidence preserved",
		FailureBehavior: FailureHaltAndReconcile,
	},
	{
		From: StateQuarantined, To: StateRetired, Command: CommandClearQuarantine,
		// Human only, and deliberately not securityActors. The quarantine edge permits a
		// system actor because an automated control must be able to shut a compromised
		// model down immediately, but the reverse is not true: letting a system clear a
		// quarantine would mean a compromised workload could schedule its own restoration,
		// which is the whole failure docs/25 section 6 is written against. Recovery from a
		// security incident is a human decision taken after forensic review.
		PermittedActors:  humanActors,
		Precondition:     PreconditionForensicPreserved,
		EventType:        "model.quarantine.cleared",
		IdempotencyScope: "model/lifecycle/unquarantine",
		AuditRecord: "model quarantine cleared by a named reviewer; promotion remains blocked " +
			"until the model re-enters the lifecycle from REGISTERED with a new version",
		RequiresIndependentApprover: true,
		FailureBehavior:             FailureDenyRemain,
	},
}

// transitionKey is the (state, command) pair a request is resolved by.
//
// It is a named type rather than an inline anonymous struct for two reasons. A composite
// literal used as a map index operand must be parenthesized, and repeating a three-line
// anonymous struct at every lookup site made that trap easy to fall into. More importantly,
// the name carries the reason the key is a pair: a request names the state it claims and
// the command it carries, and both must match the declared edge, so neither alone is
// sufficient to identify a transition.
type transitionKey struct {
	state   State
	command Command
}

var (
	byFromTo = map[[2]State]Transition{}
	// byFromCmd is the request lookup key.
	//
	// Keying by command alone was a real defect found by the declaration test: the
	// quarantine command is declared from eight source states, so a single-valued map kept
	// only the last edge and a request to quarantine a model in REGISTERED was rejected as
	// if the command did not belong to the claimed state. The failure mode was silent -
	// quarantine from seven of eight states would not have applied, and a compromised
	// model sitting in one of them would have stayed promotable.
	byFromCmd = map[transitionKey]Transition{}
	// byCmd is retained for commands that are declared from exactly one source state, so
	// that a caller asking "what does this command do" gets an unambiguous answer. It is
	// populated only for single-source commands.
	byCmd = map[Command]Transition{}
)

func init() {
	counts := make(map[Command]int, len(transitions))
	for _, t := range transitions {
		counts[t.Command]++
	}
	for _, t := range transitions {
		byFromTo[[2]State{t.From, t.To}] = t
		byFromCmd[transitionKey{state: t.From, command: t.Command}] = t
		if counts[t.Command] == 1 {
			byCmd[t.Command] = t
		}
	}
}

// lookup resolves a request's (state, command) pair to its declared transition.
func lookup(from State, cmd Command) (Transition, bool) {
	t, ok := byFromCmd[transitionKey{state: from, command: cmd}]
	return t, ok
}

// transitionsFrom returns the declared onward transitions from a state.
func transitionsFrom(s State) []Transition {
	var out []Transition
	for _, t := range transitions {
		if t.From == s {
			out = append(out, t)
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].To != out[j].To {
			return out[i].To < out[j].To
		}
		return out[i].Command < out[j].Command
	})
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
//
// The registry is authoritative, so this is a proposal the registry decides on, exactly as
// the strategy lifecycle treats a lifecycle request.
type Request struct {
	ModelID contracts.Identifier
	From    State
	Command Command
	ActorID string
	// ActorType is the kind of identity acting.
	ActorType contracts.ActorType
	// PreconditionsSatisfied lists the preconditions the caller asserts are met. The engine
	// requires the transition's own precondition to appear here; asserting extra names is
	// harmless, and asserting a different one is refused.
	PreconditionsSatisfied []Precondition
	// IdempotencyKey is the caller's key for this logical transition.
	IdempotencyKey string
	// Reference is a pointer to the evidence the precondition names.
	Reference string
	// Record is the model record the transition applies to. It is required for the
	// transitions that carry the independence requirement, because the approver is checked
	// against the record's owner and author.
	Record *Record
}

// Outcome is the result of a successful transition.
type Outcome struct {
	ModelID          contracts.Identifier
	Transition       Transition
	EventType        string
	AuditRecord      string
	IdempotencyScope string
	FailureBehavior  FailureBehavior
	// ApprovalRecord is the digest the caller supplied for an approval transition, carried
	// forward so the caller writes it into the record in the same transaction as the state
	// change.
	ApprovalRecord Digest
}

// Apply validates a proposed transition and returns the resulting outcome.
//
// The order of checks is deliberate and is the security-relevant part of this function:
//
//  1. the state is validated before the command is looked up, so an unknown state is
//     reported as an unknown state rather than as a missing transition;
//  2. authority is checked before preconditions, because an actor without permission has no
//     standing to assert that evidence exists, and evaluating a precondition on its behalf
//     would leak whether it does;
//  3. independence is checked last of the authorization checks, against the record, because
//     it is the check that a self-approving model would otherwise be able to satisfy by
//     omitting the record entirely.
//
// Step 3 is why Record is required rather than optional for those transitions. If the record
// were optional, "no record supplied" would be the way to skip the independence check, and a
// check that can be skipped by omission is not a check.
func Apply(req Request) (Outcome, error) {
	if req.From != "" && !req.From.Valid() {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"model reports unknown state %q; an unknown state is not treated as a default",
			req.From)
	}
	if req.ModelID.IsZero() {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"model id is required")
	}
	if req.ModelID.Prefix() != contracts.PrefixModel {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"model id must carry the %q prefix, got %q",
			contracts.PrefixModel, req.ModelID.Prefix())
	}
	if req.ActorType == "" || strings.TrimSpace(req.ActorID) == "" {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"actor_id and actor_type are both required; an unattributed transition is not auditable")
	}
	if len(req.IdempotencyKey) < 8 {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"idempotency key must be at least 8 characters; a transition without one "+
				"could be applied twice on retry")
	}
	if req.From.IsTerminal() {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"model is in terminal state %s; no transition out of it exists", req.From)
	}

	declared, ok := lookup(req.From, req.Command)
	if !ok {
		return Outcome{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"command %q is not declared for state %s; unknown commands and undeclared "+
				"transitions are unsupported", req.Command, req.From)
	}
	// A quarantined model must not be promotable by any path. The precondition is checked
	// here in addition to being declared on each transition, so that adding a new
	// promotion edge without the precondition cannot silently reopen the door.
	if declared.To != StateQuarantined && req.From == StateQuarantined {
		return Outcome{}, reject(contracts.CodeAuthorization, ErrCompromised,
			"model is quarantined; %q cannot apply until the quarantine is cleared and the "+
				"model re-enters the lifecycle", req.Command)
	}

	if !actorPermitted(declared, req.ActorType) {
		return Outcome{}, reject(contracts.CodeAuthorization, contracts.ErrInvalidContractValue,
			"actor type %s may not perform %s (%s -> %s); permitted: %s",
			req.ActorType, req.Command, declared.From, declared.To,
			describeActors(declared.PermittedActors))
	}

	if declared.RequiresIndependentApprover {
		if err := checkIndependence(req, declared); err != nil {
			return Outcome{}, err
		}
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

	out := Outcome{
		ModelID:          req.ModelID,
		Transition:       declared,
		EventType:        declared.EventType,
		AuditRecord:      declared.AuditRecord,
		IdempotencyScope: declared.IdempotencyScope,
		FailureBehavior:  declared.FailureBehavior,
	}
	if declared.To == StateApproved {
		// An approval without a well-formed approval artifact is not an approval, and
		// recording the state without the digest would produce exactly the gap docs/07
		// lists approval_record as a required field to close.
		d := Digest(req.Reference)
		if !d.Valid() {
			return Outcome{}, reject(contracts.CodeValidation, ErrUnverifiedDigest,
				"approval reference must be a valid sha-256 digest of the approval artifact")
		}
		out.ApprovalRecord = d
	}
	return out, nil
}

// checkIndependence refuses an approval whose actor is the party it certifies.
//
// The rule is broader than docs/07's "research authors cannot self-approve a model for live
// use". It also refuses approval by the model's owner, because a record whose owner can
// approve it has no independent reviewer in any meaningful sense, and the intent of the
// requirement is separation of duties rather than a narrower rule about one role.
//
// A model cannot appear in its own approval chain. The model identity is never compared
// against the approver because a model has no actor id; what a self-authorizing model would
// attempt is to supply an approver it controls, and the only way to establish that the
// approver is independent is to require an identity the model does not control, which is
// what ActorHuman plus a named, distinct reviewer identity provides.
func checkIndependence(req Request, t Transition) error {
	if req.Record == nil {
		return reject(contracts.CodeAuthorization, ErrSelfAuthorization,
			"%s (%s -> %s) requires the model record so the approver can be checked against "+
				"its owner and author; supplying no record is not a way to skip that check",
			t.Command, t.From, t.To)
	}
	actor := strings.TrimSpace(req.ActorID)
	if strings.EqualFold(actor, strings.TrimSpace(req.Record.Owner)) {
		return reject(contracts.CodeAuthorization, ErrSelfAuthorization,
			"%s: approver %q is the model owner; docs/07 requires an independent reviewer",
			t.Command, actor)
	}
	if strings.EqualFold(actor, strings.TrimSpace(req.Record.Author)) {
		return reject(contracts.CodeAuthorization, ErrSelfAuthorization,
			"%s: approver %q is the model author; a research author cannot self-approve a "+
				"model for live use", t.Command, actor)
	}
	return nil
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

// declarationProblem is a defect in the transition table itself, as opposed to a rejected
// request. It is separated so that a table defect is never reported as a caller's error: a
// caller cannot cause a duplicate command, and a gate that reads "invalid request" for a
// malformed table would send an investigator looking in the wrong place.
type declarationProblem struct {
	msg string
}

func (d declarationProblem) Error() string { return d.msg }

func (d declarationProblem) Unwrap() error { return contracts.ErrInvalidContractValue }

// VerifyDeclaration checks the transition table for internal consistency.
//
// It is exported so that a gate can call it, and it is a test as well as a runtime
// guarantee, because the properties it checks are properties of the table: exactly one
// command per transition, no undeclared state, and a quarantined model reachable as a
// destination from every non-terminal state.
//
// The last property is the one that matters most. docs/25 section 6 requires that a
// compromised research worker results in promotion being blocked. If any state could not be
// quarantined, then a model sitting in that state could still be promoted after a compromise,
// and the failure would be a gap in this table rather than a policy decision anyone made.
func verifyDeclaration(table []Transition, states []State) error {
	byCommand := make(map[Command][]Transition, len(table))
	for _, t := range table {
		// Registration is the one transition with no prior state, because a model that does
		// not exist yet is not in a state. The allowance is made narrow deliberately: only
		// this command, only into REGISTERED, and only once. A second empty-source edge, or
		// an empty source on any other command, would mean a model could be teleported into
		// the lifecycle from nowhere, bypassing whatever the losing edge required.
		if t.From == "" {
			if t.Command != CommandRegister || t.To != StateRegistered {
				return declarationProblem{fmt.Sprintf(
					"transition %s declares an empty source state, which only %s may do, and "+
						"only into REGISTERED", t.Command, CommandRegister)}
			}
		} else if !t.From.Valid() {
			return declarationProblem{fmt.Sprintf(
				"transition %s declares unknown source state %q", t.Command, t.From)}
		}
		if !t.To.Valid() {
			return declarationProblem{fmt.Sprintf(
				"transition %s declares unknown destination state %q", t.Command, t.To)}
		}
		if t.Precondition == "" {
			return declarationProblem{fmt.Sprintf(
				"transition %s (%s -> %s) declares no precondition",
				t.Command, t.From, t.To)}
		}
		if t.EventType == "" {
			return declarationProblem{fmt.Sprintf(
				"transition %s (%s -> %s) declares no audit event", t.Command, t.From, t.To)}
		}
		if t.IdempotencyScope == "" {
			return declarationProblem{fmt.Sprintf(
				"transition %s (%s -> %s) declares no idempotency scope",
				t.Command, t.From, t.To)}
		}
		if t.AuditRecord == "" {
			return declarationProblem{fmt.Sprintf(
				"transition %s (%s -> %s) declares no audit record", t.Command, t.From, t.To)}
		}
		if t.FailureBehavior != FailureDenyRemain && t.FailureBehavior != FailureHaltAndReconcile {
			return declarationProblem{fmt.Sprintf(
				"transition %s declares unknown failure behaviour %q",
				t.Command, t.FailureBehavior)}
		}
		if len(t.PermittedActors) == 0 {
			return declarationProblem{fmt.Sprintf(
				"transition %s (%s -> %s) permits no actor", t.Command, t.From, t.To)}
		}
		for _, a := range t.PermittedActors {
			if a == contracts.ActorAgent || a == contracts.ActorStrategy {
				return declarationProblem{fmt.Sprintf(
					"transition %s permits actor type %s; docs/25 section 3.6 forbids an AI or "+
						"strategy actor being the actor of record for a lifecycle change",
					t.Command, a)}
			}
		}
		byCommand[t.Command] = append(byCommand[t.Command], t)
	}

	// A command must resolve unambiguously. If it is declared on more than one edge, every
	// one of those edges must say so, because the flag is what distinguishes "one command
	// with several valid sources" from "two commands that happen to share a name".
	for cmd, edges := range byCommand {
		multi := len(edges) > 1
		for _, e := range edges {
			if e.MultiSource != multi {
				return declarationProblem{fmt.Sprintf(
					"command %q is declared on %d edges but MultiSource is %t on the %s -> %s "+
						"edge; the flag must be consistent across every edge of a command",
					cmd, len(edges), e.MultiSource, e.From, e.To)}
			}
		}
		// A multi-source command must not appear in the single-source lookup, or a caller
		// would be able to resolve it ambiguously through byCmd.
		if multi {
			if _, present := singleSource(table)[cmd]; present {
				return declarationProblem{fmt.Sprintf(
					"command %q is multi-source but is also present in the single-source "+
						"lookup; it must be resolvable only by (state, command)", cmd)}
			}
		}
	}

	// Every non-terminal state must be able to reach quarantine.
	for _, s := range states {
		if s.IsTerminal() {
			continue
		}
		canQuarantine := false
		for _, t := range edgesFrom(table, s) {
			if t.To == StateQuarantined {
				canQuarantine = true
				break
			}
		}
		if !canQuarantine {
			return declarationProblem{fmt.Sprintf(
				"state %s has no transition to QUARANTINED; a model in this state could be "+
					"promoted after a compromise", s)}
		}
	}

	// No transition may leave quarantine for a non-terminal state. A cleared quarantine
	// must route through RETIRED and then re-enter the lifecycle, so that a compromised
	// model cannot be waved forward by clearing its quarantine.
	//
	// The rule is stated over every edge, not over one named pair. It used to test only
	// QUARANTINED -> EVALUATED, which is narrower than the comment above it: a forged edge
	// to any other non-terminal state, MONITORED or PAPER or PROMOTED, satisfied the check
	// as written. A check that is narrower than the property it names is the same defect as
	// no check, because a reader trusts the comment.
	for _, t := range edgesFrom(table, StateQuarantined) {
		if !t.To.IsTerminal() {
			return declarationProblem{fmt.Sprintf(
				"transition %s leaves QUARANTINED for %s; a cleared model must retire and "+
					"re-enter the lifecycle rather than resume in place", t.Command, t.To)}
		}
	}
	return nil
}

// VerifyDeclaration checks the package's own declared transition table.
//
// It is the public face of verifyDeclaration, which takes the table as an argument so that
// the declaration rules can be tested against malformed tables. Without that, every guard in
// there is unreachable by a test: the real table satisfies all of them, so deleting a guard
// changes nothing observable and the rule it protects is written down but not enforced. That
// is a mutation-survived result, not a theoretical concern - it is what happened to the
// empty-source guard, which survived because nothing ever handed the verifier a table with
// an undeclared empty source.
func VerifyDeclaration() error { return verifyDeclaration(transitions, allStates) }

// singleSource returns the commands declared on exactly one edge, which is the set that may
// be resolved without also naming a source state.
func singleSource(table []Transition) map[Command]Transition {
	counts := make(map[Command]int, len(table))
	for _, t := range table {
		counts[t.Command]++
	}
	out := make(map[Command]Transition, len(counts))
	for _, t := range table {
		if counts[t.Command] == 1 {
			out[t.Command] = t
		}
	}
	return out
}

// edgesFrom returns the table's onward edges from a state, in a stable order so that a
// declaration problem is reported the same way twice.
func edgesFrom(table []Transition, s State) []Transition {
	var out []Transition
	for _, t := range table {
		if t.From == s {
			out = append(out, t)
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].To != out[j].To {
			return out[i].To < out[j].To
		}
		return out[i].Command < out[j].Command
	})
	return out
}
