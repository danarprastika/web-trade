// Package oms implements the Order Management System: the single owner of canonical
// internal order lifecycle state.
//
// Authority boundary. The OMS owns internal order state. A venue adapter reports
// observations; it never rewrites the OMS state machine (docs/25 section 3.2). A timeout
// produces an UNKNOWN outcome that is reconciled, never a rejection or a fill inferred
// from the absence of a response (docs/25 section 3.3).
//
// Halt is monotonic. A halt may only be cleared by an explicitly authorised command, and
// never by a lower-privilege action, stale configuration, a feature flag, or recovery
// automation (docs/25 section 3.9).
//
// Four properties make the state machine authoritative rather than decorative, and each is
// mechanical rather than conventional:
//
//  1. Closed states and declared transitions. An unknown state, an unknown command, or an
//     undeclared edge is a controlled rejection, never a guess. docs/03 requires unknown enum
//     values to be treated as unsupported rather than silently mapped.
//  2. Optimistic concurrency. Every transition carries the version it expected to advance
//     from, and the stored version must match. docs/01 section 8 prohibits last-write-wins for
//     authoritative financial state, and a write that merely overwrote a newer state would
//     discard a fill.
//  3. One canonical identity. An order is created with exactly one canonical id and keeps it
//     for its whole life. A venue's own order reference is recorded as an observation about
//     that order; it never becomes, replaces, or is used in place of the canonical id.
//  4. UNKNOWN is honest. A submission that timed out enters UNKNOWN and stays there until
//     evidence resolves it. No timeout, retry, or absence of a response may convert UNKNOWN
//     into a rejection or a fill (docs/04, docs/25 section 3.3).
//
// The package is pure domain logic. It submits nothing and talks to no venue. Submission is
// the execution layer's job and it may proceed only from an outcome carrying a valid risk
// approval, and the import test in order_test.go enforces that this package cannot reach a
// network client or a risk-approving type.
package oms

import (
	"fmt"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ErrInvalidOrderInput is the sentinel behind every refusal, so a caller can attribute a
// rejection to order handling rather than to an unrelated fault.
var ErrInvalidOrderInput = contracts.ErrInvalidContractValue

// Rejection is a refused order transition.
//
// It carries a canonical ErrorCode and a local sentinel for the same reason the strategy and
// risk packages carry one: a caller on another service needs the machine-readable code, and
// errors.Is must keep working in process. Formatting an ErrorCode with %w is not valid Go,
// and formatting it with %s would discard exactly the part that must survive.
type Rejection struct {
	// Code is the canonical error code from docs/03.
	Code contracts.ErrorCode
	// Cause is the local sentinel, reachable through errors.Is.
	Cause error
	// Reason is the human-facing explanation. Never parsed.
	Reason string
	// RequiresReconciliation marks a rejection that docs/01 section 8 places "into a
	// controlled reconciliation path": a version conflict, or a request that presupposes a
	// state the OMS cannot confirm. It is a flag rather than a side effect because a caller
	// must be able to tell a conflict that needs reconciling from an ordinary bad request,
	// and it is the one rejection whose *handling* is not "fix the input and retry".
	RequiresReconciliation bool
}

func (r Rejection) Error() string { return fmt.Sprintf("%s: %s", r.Code, r.Reason) }

// Unwrap exposes the local sentinel to errors.Is and errors.As.
func (r Rejection) Unwrap() error { return r.Cause }

func reject(code contracts.ErrorCode, format string, args ...any) Rejection {
	return Rejection{Code: code, Cause: ErrInvalidOrderInput, Reason: fmt.Sprintf(format, args...)}
}

// conflict builds a version-conflict rejection, which docs/01 section 8 routes to
// reconciliation rather than to the caller's retry.
func conflict(format string, args ...any) Rejection {
	r := reject(contracts.CodeConflict, format, args...)
	r.RequiresReconciliation = true
	return r
}

// State is a canonical internal order state. The set is closed and taken verbatim from
// docs/04 section "Order lifecycle".
type State string

// The closed set of order states.
const (
	StateCreated         State = "CREATED"
	StateRiskPending     State = "RISK_PENDING"
	StateRiskApproved    State = "RISK_APPROVED"
	StateSubmitting      State = "SUBMITTING"
	StateAcknowledged    State = "ACKNOWLEDGED"
	StatePartiallyFilled State = "PARTIALLY_FILLED"
	StateFilled          State = "FILLED"
	StateCancelled       State = "CANCELLED"
	StateRejected        State = "REJECTED"
	StateExpired         State = "EXPIRED"
	StateUnknown         State = "UNKNOWN"
)

// allStates is the closed set in the documented order, used for reporting and for coverage
// assertions. The order is the documented progression, not alphabetical.
var allStates = []State{
	StateCreated, StateRiskPending, StateRiskApproved, StateSubmitting,
	StateAcknowledged, StatePartiallyFilled, StateFilled,
	StateCancelled, StateRejected, StateExpired, StateUnknown,
}

var stateIndex = func() map[State]struct{} {
	m := make(map[State]struct{}, len(allStates))
	for _, s := range allStates {
		m[s] = struct{}{}
	}
	return m
}()

// Valid reports whether the state is in the closed set.
func (s State) Valid() bool {
	_, ok := stateIndex[s]
	return ok
}

// AllStates returns every order state in the documented order.
func AllStates() []State {
	out := make([]State, len(allStates))
	copy(out, allStates)
	return out
}

// terminalStates are the states with no onward transition.
//
// UNKNOWN is deliberately absent: an UNKNOWN order is not finished, it is unresolved, and
// treating it as terminal is the error docs/25 section 3.3 exists to prevent.
var terminalStates = map[State]bool{
	StateFilled:    true,
	StateCancelled: true,
	StateRejected:  true,
	StateExpired:   true,
}

// IsTerminal reports whether the state has no onward transition.
func (s State) IsTerminal() bool { return terminalStates[s] }

// String renders the state for an audit record and a log line.
func (s State) String() string { return string(s) }

// Command is a lifecycle command. Commands are explicit: docs/04 states that transitions are
// explicit commands producing immutable audit events.
type Command string

// The closed set of order commands.
//
// The split matters. Commands originate inside the control plane (the OMS, the risk engine,
// an operator), while observations originate outside it (a venue adapter). They are separate
// types rather than one enum so that no call site can pass a venue's report in as an
// operator's command, which would let an adapter drive the state machine by claiming to be
// something it is not.
const (
	// CmdSubmitForRisk moves a created order to risk evaluation.
	CmdSubmitForRisk Command = "SUBMIT_FOR_RISK"
	// CmdRecordRiskApproval records the Risk Engine's approval.
	CmdRecordRiskApproval Command = "RECORD_RISK_APPROVAL"
	// CmdRecordRiskRejection records the Risk Engine's rejection.
	CmdRecordRiskRejection Command = "RECORD_RISK_REJECTION"
	// CmdSubmitToVenue moves an approved order to submission.
	CmdSubmitToVenue Command = "SUBMIT_TO_VENUE"
	// CmdCancel cancels an order that has not reached a terminal state.
	CmdCancel Command = "CANCEL"
	// CmdRecordSubmissionTimeout records that a submission produced no response.
	//
	// It is internal: it is requested because a response did not arrive, which is the absence
	// of an observation rather than an observation. No adapter may request it, because an
	// adapter that reports "I timed out" is claiming an outcome it cannot know.
	CmdRecordSubmissionTimeout Command = "RECORD_SUBMISSION_TIMEOUT"
	// CmdRecordReconciliation records that a reconciliation case has resolved an UNKNOWN
	// order, which is the only thing that permits a resubmission.
	CmdRecordReconciliation Command = "RECORD_RECONCILIATION"
	// CmdRaiseHalt halts an order.
	CmdRaiseHalt Command = "RAISE_HALT"
	// CmdClearHalt clears an active halt on the order.
	CmdClearHalt Command = "CLEAR_HALT"
)

var allCommands = []Command{
	CmdSubmitForRisk, CmdRecordRiskApproval, CmdRecordRiskRejection,
	CmdSubmitToVenue, CmdCancel, CmdRecordSubmissionTimeout,
	CmdRecordReconciliation, CmdRaiseHalt, CmdClearHalt,
}

var commandIndex = func() map[Command]struct{} {
	m := make(map[Command]struct{}, len(allCommands))
	for _, c := range allCommands {
		m[c] = struct{}{}
	}
	return m
}()

// Valid reports whether the command is in the closed set.
func (c Command) Valid() bool {
	_, ok := commandIndex[c]
	return ok
}

// AllCommands returns every command in the declared order.
func AllCommands() []Command {
	out := make([]Command, len(allCommands))
	copy(out, allCommands)
	return out
}

// ObservationKind is what a venue adapter reports.
//
// The set is closed and, critically, narrower than State. An adapter cannot report
// "CANCELLED_BY_RISK" or "APPROVED_BY_RISK" or "UNKNOWN" because it observed nothing of the
// kind: those are internal facts. The kind set is the adapter's whole vocabulary, and the OMS
// alone decides which internal state each kind implies.
type ObservationKind string

// The closed set of adapter observations.
const (
	// ObsAcknowledged is a venue confirming the order is live.
	ObsAcknowledged ObservationKind = "ACKNOWLEDGED"
	// ObsPartiallyFilled is a venue reporting a fill that leaves quantity outstanding.
	ObsPartiallyFilled ObservationKind = "PARTIALLY_FILLED"
	// ObsFilled is a venue reporting the order fully filled.
	ObsFilled ObservationKind = "FILLED"
	// ObsRejected is a venue refusing the order.
	ObsRejected ObservationKind = "REJECTED"
	// ObsExpired is a venue reporting the order expired unfilled.
	ObsExpired ObservationKind = "EXPIRED"
	// ObsCancelled is a venue confirming the order is no longer live.
	ObsCancelled ObservationKind = "CANCELLED"
)

var allObservations = []ObservationKind{
	ObsAcknowledged, ObsPartiallyFilled, ObsFilled,
	ObsRejected, ObsExpired, ObsCancelled,
}

var observationIndex = func() map[ObservationKind]struct{} {
	m := make(map[ObservationKind]struct{}, len(allObservations))
	for _, o := range allObservations {
		m[o] = struct{}{}
	}
	return m
}()

// Valid reports whether the observation kind is in the closed set.
func (o ObservationKind) Valid() bool {
	_, ok := observationIndex[o]
	return ok
}

// AllObservationKinds returns every observation kind in the declared order.
func AllObservationKinds() []ObservationKind {
	out := make([]ObservationKind, len(allObservations))
	copy(out, allObservations)
	return out
}

// Direction is the side of an order.
//
// It is declared here rather than imported from the risk engine because the OMS and the Risk
// Engine are separate protected capabilities (docs/25 line 37), and a component boundary that
// exists only to share an enum is a boundary worth being able to delete later.
type Direction string

// The order directions.
const (
	DirBuy  Direction = "BUY"
	DirSell Direction = "SELL"
)

// Sign is the signed multiplier a direction applies to a quantity.
func (d Direction) Sign() int {
	if d == DirSell {
		return -1
	}
	return 1
}

func (d Direction) valid() bool { return d == DirBuy || d == DirSell }

func (d Direction) String() string { return string(d) }

// NewOrderRequest is a request to create a canonical order.
//
// Creation is the only place a canonical identity is minted. Every later reference to the
// order uses the id produced here.
type NewOrderRequest struct {
	// CommandID is the canonical id of the command that creates the order. The OMS derives
	// the order's own identity from it, so a retried creation of the same command produces
	// the same identity rather than a second order.
	CommandID contracts.Identifier
	// AccountID and StrategyID identify the order's owner and originator.
	AccountID  contracts.Identifier
	StrategyID contracts.Identifier
	// Instrument, Venue, and Market say what is traded and where.
	Instrument string
	Venue      string
	Market     string
	// Direction, OrderType, Quantity, and LimitPrice describe the order.
	Direction  Direction
	OrderType  string
	Quantity   contracts.Quantity
	LimitPrice *contracts.Money
	// IdempotencyKey scopes this creation. A retried creation with the same key is the same
	// order, not a new one.
	IdempotencyKey string
	// RequestedAt is when the command was issued. Supplied rather than read from a clock so
	// the result is a pure function of its inputs.
	RequestedAt contracts.Timestamp
	// Environment is the promotion stage the order is for.
	Environment string
}

// Order is the canonical internal order.
//
// Every field is either immutable for the order's life or advanced only by a declared
// transition. There is no field an adapter can write: ApplyObservation advances State and
// CumulativeFilled and nothing else.
type Order struct {
	// OrderID is the canonical identity, minted once at creation and never changed. This is
	// what makes "every accepted order has exactly one canonical identity" structural: there
	// is no setter, and no path that reassigns it.
	OrderID contracts.Identifier
	// CommandID is the command that created the order.
	CommandID contracts.Identifier
	// AccountID and StrategyID identify the owner and originator.
	AccountID  contracts.Identifier
	StrategyID contracts.Identifier
	// Instrument, Venue, and Market say what is traded and where.
	Instrument string
	Venue      string
	Market     string
	// Direction, OrderType, Quantity, and LimitPrice describe the order and never change. An
	// amendment is a new order; mutating these in place would rewrite a financial fact about
	// something already submitted.
	Direction  Direction
	OrderType  string
	Quantity   contracts.Quantity
	LimitPrice *contracts.Money
	// IdempotencyKey scopes creation.
	IdempotencyKey string
	// Environment is the promotion stage.
	Environment string

	// State is the current canonical state.
	State State
	// Version is the optimistic-concurrency counter. It increments by exactly one per
	// applied transition, so a caller can detect that something else advanced the order.
	Version uint64
	// CumulativeFilled is the total filled quantity. It only ever increases and never exceeds
	// Quantity; both are enforced on every fill observation.
	CumulativeFilled contracts.Quantity

	// VenueOrderRef is the venue's own identifier for this order, once known. It is
	// evidence about the order, never a substitute for OrderID.
	VenueOrderRef string
	// RiskApprovalRef is the Risk Engine approval this order was authorised under.
	RiskApprovalRef string
	// RiskRejectionRef is the Risk Engine rejection, when the order was refused.
	RiskRejectionRef string
	// ReconciliationCaseID is the case that resolved an UNKNOWN order. It is required before
	// a resubmission is permitted, which is what makes "reconcile before any retry that could
	// duplicate exposure" a rule rather than an intention.
	ReconciliationCaseID string
	// SubmissionAttempt counts submissions to the venue. It exists so a retry after a
	// reconciled UNKNOWN is visible in the audit record as a retry rather than as a first
	// attempt.
	SubmissionAttempt uint32

	// Halt is the halt state attached to this order. It is monotonic; see Halt.
	Halt Halt

	// RequestedAt is when the order was created.
	RequestedAt contracts.Timestamp
	// UpdatedAt is when the order last changed.
	UpdatedAt contracts.Timestamp
}

// Halt is a halt attached to an order.
//
// Monotonicity is a property of the type rather than of the caller's discipline: the only
// transition that clears Halted is CmdClearHalt, and that transition requires a human actor
// and an exact halt reference. No other command, no observation, and no recovery path can set
// it back to false.
type Halt struct {
	// Active reports whether the halt is in force.
	Active bool
	// Ref is the identifier of the halt, which an authority must present to clear it. It is
	// the exact-diff requirement: clearing halt A by presenting halt B's reference is refused.
	Ref string
	// Scope is the halt level, recorded for the audit record.
	Scope string
	// RaisedAt is when the halt took effect.
	RaisedAt contracts.Timestamp
	// RaisedBy is the actor that raised the halt. Recorded for the audit record; it does not
	// confer authority, because authority to clear is about who is asking now, not who
	// raised it.
	RaisedBy contracts.ActorType
}

// validateNewOrder checks a creation request is well formed.
//
// The checks are the ones that must hold before an identity is minted, because an order that
// exists with a missing account is an order that later risk evaluation cannot be bound to.
func (r NewOrderRequest) validate() error {
	if r.CommandID.IsZero() {
		return reject(contracts.CodeValidation, "command id is required; an unattributed order "+
			"is not auditable")
	}
	if r.CommandID.Prefix() != contracts.PrefixCommand {
		return reject(contracts.CodeValidation, "command id must carry the %q prefix, got %q",
			contracts.PrefixCommand, r.CommandID.Prefix())
	}
	if r.AccountID.IsZero() {
		return reject(contracts.CodeValidation, "account id is required")
	}
	if r.StrategyID.IsZero() {
		return reject(contracts.CodeValidation, "strategy id is required")
	}
	if r.Instrument == "" || r.Venue == "" || r.Market == "" {
		return reject(contracts.CodeValidation, "instrument, venue, and market are all required")
	}
	if !r.Direction.valid() {
		return reject(contracts.CodeValidation, "unknown order direction %q", r.Direction)
	}
	if r.OrderType == "" {
		return reject(contracts.CodeValidation, "order type is required")
	}
	if !r.Quantity.Value().IsSet() {
		return reject(contracts.CodeValidation, "quantity is required")
	}
	if r.Quantity.Value().Sign() <= 0 {
		return reject(contracts.CodeValidation, "order quantity %s must be positive; a "+
			"non-positive quantity has no meaning as an order",
			r.Quantity.Value())
	}
	if r.RequestedAt.IsZero() {
		return reject(contracts.CodeValidation, "requested_at is required")
	}
	if r.Environment == "" {
		return reject(contracts.CodeValidation, "environment is required")
	}
	if len(r.IdempotencyKey) < 8 {
		return reject(contracts.CodeValidation, "idempotency key must be at least 8 characters; "+
			"an order created without one could be created twice on retry")
	}
	return nil
}

// Notional is the order's size, computed rather than supplied.
//
// The OMS does not need this for a limit decision, but it records it so a reviewer can see
// the order's size without recomputing it, and so the value is exact: the engine computes it
// with the same canonical decimal arithmetic the risk engine uses, rather than in a float.
func (o Order) Notional() (contracts.Money, error) {
	if o.LimitPrice == nil {
		return contracts.Money{}, reject(contracts.CodeValidation,
			"order %s is a market order and carries no price, so it has no notional", o.OrderID)
	}
	product, err := o.LimitPrice.Amount().Multiply(o.Quantity.Value())
	if err != nil {
		return contracts.Money{}, err
	}
	return contracts.NewMoney(o.LimitPrice.Currency(), product)
}

// RemainingQuantity is the unfilled quantity.
func (o Order) RemainingQuantity() (contracts.Quantity, error) {
	filled, err := o.CumulativeFilled.Value().Cmp(contracts.MustParseDecimal("0"))
	if err != nil {
		return contracts.Quantity{}, err
	}
	if filled == 0 {
		return o.Quantity, nil
	}
	remaining, err := o.Quantity.Value().Sub(o.CumulativeFilled.Value())
	if err != nil {
		return contracts.Quantity{}, err
	}
	return contracts.NewQuantity(remaining, o.Quantity.Unit())
}

// Halted reports whether the order is stopped by a halt.
func (o Order) Halted() bool { return o.Halt.Active }

// String renders the order for a log line. It is deliberately short: the full record is in
// the audit chain, and a log line that carried every field would make the interesting part
// hard to find.
func (o Order) String() string {
	return fmt.Sprintf("order %s v%d %s %s %s %s", o.OrderID, o.Version, o.State,
		o.Direction, o.Quantity, o.Instrument)
}

// Observation is what a venue adapter reports.
//
// There is no State field and no TargetState field. An adapter says what it saw, and the OMS
// alone decides which internal state that implies. This is the mechanical form of docs/25
// section 3.2: an adapter reports observations, it does not rewrite the state machine.
type Observation struct {
	// Kind is what the venue reported.
	Kind ObservationKind
	// VenueOrderRef is the venue's own identifier. It is recorded as evidence; it is never
	// used to identify the order, because the venue chose it and the platform did not.
	VenueOrderRef string
	// CumulativeFilled is the venue's running total for the order. Required for a fill
	// observation and refused otherwise, because a partial fill with no running total cannot
	// be checked against the order quantity and would make overfill undetectable.
	CumulativeFilled contracts.Quantity
	// OccurredAt is when the venue says it happened.
	OccurredAt contracts.Timestamp
	// Evidence is the adapter's supporting record: a venue message id, a response payload
	// digest, or a reconciliation reference. It is required for every observation, because
	// UNKNOWN is resolved by evidence and an observation with none cannot resolve anything.
	Evidence string
}

// validate checks the observation is well formed independently of the current state.
func (o Observation) validate() error {
	if !o.Kind.Valid() {
		return reject(contracts.CodeValidation,
			"unknown observation %q; an adapter's vocabulary is closed and an unknown "+
				"observation is unsupported, not mapped to a default", o.Kind)
	}
	if o.OccurredAt.IsZero() {
		return reject(contracts.CodeValidation, "observation requires an occurrence time")
	}
	if strings.TrimSpace(o.Evidence) == "" {
		return reject(contracts.CodeValidation, "observation requires evidence; an "+
			"unevidenced observation cannot resolve an UNKNOWN order")
	}
	if o.Kind == ObsPartiallyFilled || o.Kind == ObsFilled {
		if !o.CumulativeFilled.Value().IsSet() {
			return reject(contracts.CodeValidation,
				"a fill observation must carry the venue's cumulative filled quantity; "+
					"without it an overfill cannot be detected")
		}
	}
	return nil
}

// Actor is who is asking for a transition.
type Actor struct {
	ID   string
	Type contracts.ActorType
}

func (a Actor) valid() error {
	if strings.TrimSpace(a.ID) == "" {
		return reject(contracts.CodeAuthorization, "actor id is required; an unattributed "+
			"transition is not auditable")
	}
	if !a.Type.Valid() {
		return reject(contracts.CodeAuthorization, "unknown actor type %q", a.Type)
	}
	return nil
}

// String renders the actor for an audit record.
func (a Actor) String() string { return string(a.Type) + ":" + a.ID }
