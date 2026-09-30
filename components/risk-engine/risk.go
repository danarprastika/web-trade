// Package risk implements the deterministic Risk Engine veto for risk-increasing domain
// commands.
//
// This package is the single point at which new risk may be refused. docs/25 invariant 1
// states that "the Risk Engine is the deterministic veto for risk-increasing domain
// commands" and that "AI output, model confidence, operator UI state, and venue response
// cannot override it". The whole design of this file follows from that one sentence.
//
// Three properties make the veto real rather than advisory:
//
//  1. Determinism. The result is a pure function of the command intent, the established
//     facts, and the signed policy revision. Nothing else is an input. There is no clock
//     call, no randomness, no map iteration order in the output, and no network. The same
//     inputs always produce byte-identical output, which is what makes a rejection
//     auditable and replayable (docs/17 section 4).
//  2. Fail closed. Every absent, unavailable, or unreadable input is a rejection. A control
//     that cannot read its source does not pass by default, and a required policy control
//     that is missing from the projection is a rejection rather than an unlimited allowance.
//     This follows docs/25 invariant 10 and docs/17 section 2.
//  3. No override channel. The evaluation function accepts an Advisory value carrying model
//     confidence, UI state, and venue responses, and it deliberately does not read it. The
//     field is present rather than omitted so that a test can prove it is inert rather than
//     merely absent; an absent field could be reintroduced by a later signature change,
//     whereas an ignored field is covered by a test that fails if anyone starts reading it.
//
// The engine is pure decision logic. It does not place, amend, or cancel an order, and it
// cannot. Producing a Permit requires a valid, unexpired approval bound to the exact command
// (docs/17 section 4), so a rejected command has no path to a live submission: the only way
// to obtain the value the submission path demands is to be approved, and a rejection never
// produces one.
package riskengine

import (
	"fmt"
	"sort"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ErrInvalidRiskInput is the sentinel behind every refusal, so a caller can attribute a
// rejection to risk evaluation rather than to an unrelated fault.
var ErrInvalidRiskInput = contracts.ErrInvalidContractValue

// Rejection is a refused evaluation.
//
// It carries a canonical ErrorCode and a local sentinel for the same reason the strategy
// and configuration packages carry one: a caller on another service needs the machine
// readable code, and errors.Is must keep working in process. Formatting an ErrorCode with
// %w is not valid Go, and formatting it with %s would discard exactly the part that must
// survive.
type Rejection struct {
	// Code is the canonical error code from docs/03.
	Code contracts.ErrorCode
	// Cause is the local sentinel, reachable through errors.Is.
	Cause error
	// Reason is the human-facing explanation. Never parsed.
	Reason string
}

func (r Rejection) Error() string { return fmt.Sprintf("%s: %s", r.Code, r.Reason) }

// Unwrap exposes the local sentinel to errors.Is and errors.As.
func (r Rejection) Unwrap() error { return r.Cause }

func reject(code contracts.ErrorCode, format string, args ...any) Rejection {
	return Rejection{Code: code, Cause: ErrInvalidRiskInput, Reason: fmt.Sprintf(format, args...)}
}

// Direction is the side of an order.
type Direction string

// The order directions.
const (
	DirBuy  Direction = "BUY"
	DirSell Direction = "SELL"
)

func (d Direction) valid() bool { return d == DirBuy || d == DirSell }

// Sign is the signed multiplier a direction applies to an exposure.
func (d Direction) Sign() int {
	if d == DirSell {
		return -1
	}
	return 1
}

// DeploymentStatus is a strategy's deployment state, projected.
//
// This is a narrow projection rather than the lifecycle State type from the control-plane
// strategy package, and that is deliberate: components/risk-engine is a separate module and
// must not depend on a service, and more importantly the engine needs one question answered
// (may this strategy act) rather than the whole lifecycle. Keeping the projection narrow
// also keeps the engine's input surface small, which is the property that makes "no
// unintended input" auditable.
type DeploymentStatus string

// The deployment statuses.
const (
	// StatusUnknown means the deployment state could not be established, which is a
	// rejection under docs/25 invariant 10 rather than an optimistic default.
	StatusUnknown DeploymentStatus = "UNKNOWN"
	// StatusNotDeployed means the strategy has not reached a deployed state.
	StatusNotDeployed DeploymentStatus = "NOT_DEPLOYED"
	// StatusDeployed is the only status that permits a risk-increasing command.
	StatusDeployed DeploymentStatus = "DEPLOYED"
	// StatusPaused means the strategy is halted.
	StatusPaused DeploymentStatus = "PAUSED"
	// StatusRetired means the strategy is finished.
	StatusRetired DeploymentStatus = "RETIRED"
)

func (d DeploymentStatus) valid() bool {
	switch d {
	case StatusUnknown, StatusNotDeployed, StatusDeployed, StatusPaused, StatusRetired:
		return true
	}
	return false
}

// VenueStatus is a venue's operational state.
type VenueStatus string

// The venue statuses.
const (
	VenueAvailable   VenueStatus = "AVAILABLE"
	VenueHalted      VenueStatus = "HALTED"
	VenueUnavailable VenueStatus = "UNAVAILABLE"
)

func (v VenueStatus) valid() bool {
	switch v {
	case VenueAvailable, VenueHalted, VenueUnavailable:
		return true
	}
	return false
}

// HaltScope is a level of the halt hierarchy.
//
// docs/04 states the order SYSTEM_HALT > VENUE_HALT > MARKET_HALT > STRATEGY_HALT >
// ACCOUNT_HALT and that "a higher-level halt cannot be bypassed by a lower-level enable
// command". Rank encodes that: a higher rank is more severe, and an active halt at rank R
// blocks every scope of rank R or below.
type HaltScope string

// The halt scopes.
const (
	HaltAccount  HaltScope = "ACCOUNT_HALT"
	HaltStrategy HaltScope = "STRATEGY_HALT"
	HaltMarket   HaltScope = "MARKET_HALT"
	HaltVenue    HaltScope = "VENUE_HALT"
	HaltSystem   HaltScope = "SYSTEM_HALT"
)

// haltRanks is the hierarchy, least to most severe. It is the single source of truth for
// severity ordering, exactly as the environment ladder is in the configuration package.
var haltRanks = map[HaltScope]int{
	HaltAccount: 1, HaltStrategy: 2, HaltMarket: 3, HaltVenue: 4, HaltSystem: 5,
}

// haltOrder is the hierarchy in severity order, used so reporting is deterministic.
var haltOrder = []HaltScope{HaltAccount, HaltStrategy, HaltMarket, HaltVenue, HaltSystem}

func (h HaltScope) valid() bool {
	_, ok := haltRanks[h]
	return ok
}

// Rank is the severity rank, or -1 for an unknown scope.
func (h HaltScope) Rank() int {
	if r, ok := haltRanks[h]; ok {
		return r
	}
	return -1
}

// String renders the scope for an audit record.
func (h HaltScope) String() string { return string(h) }

// HaltRecord is one active halt.
type HaltRecord struct {
	// Scope is the level the halt was raised at.
	Scope HaltScope
	// Reason is the operator-facing cause.
	Reason string
	// RaisedAt is when the halt took effect. docs/17 section 5 requires halt activation to
	// be immediately effective, so this is informational rather than a grace period.
	RaisedAt contracts.Timestamp
	// Authority is the actor that raised the halt. docs/17 section 5 requires the owning
	// authority to clear it, and a model may never hold that authority.
	Authority contracts.ActorType
}

// valid reports whether the record is coherent.
func (h HaltRecord) valid() bool {
	return h.Scope.valid() && h.Reason != "" && !h.RaisedAt.IsZero() && h.Authority.Valid()
}

// HaltState is the set of active halts.
//
// It is a value type with an explicit slice rather than a map so that evaluation order and
// reporting order are fixed, which is a precondition for determinism.
type HaltState struct {
	active []HaltRecord
}

// NewHaltState builds a halt state from records, rejecting incoherent ones.
func NewHaltState(records ...HaltRecord) (HaltState, error) {
	state := HaltState{active: make([]HaltRecord, 0, len(records))}
	for _, r := range records {
		if !r.valid() {
			return HaltState{}, reject(contracts.CodeValidation,
				"halt record at %s is not coherent; it needs a known scope, a reason, a "+
					"timestamp, and a known authority", r.Scope)
		}
		// docs/17 section 5 and docs/25 invariant 9: a model may never hold halt authority,
		// because an AI that could raise a halt it could then influence is a second
		// authority over risk.
		if r.Authority == contracts.ActorAgent {
			return HaltState{}, reject(contracts.CodeAuthorization,
				"halt at %s was raised by an agent; halt authority may not be held by a model", r.Scope)
		}
		state.active = append(state.active, r)
	}
	sort.SliceStable(state.active, func(i, j int) bool {
		return state.active[i].Scope.Rank() > state.active[j].Scope.Rank()
	})
	return state, nil
}

// Active returns the halts in severity order, most severe first.
func (h HaltState) Active() []HaltRecord {
	out := make([]HaltRecord, len(h.active))
	copy(out, h.active)
	return out
}

// Highest returns the most severe active halt.
func (h HaltState) Highest() (HaltRecord, bool) {
	if len(h.active) == 0 {
		return HaltRecord{}, false
	}
	return h.active[0], true
}

// Blocks reports whether an active halt at or above the given scope stops risk-increasing
// action.
//
// This is the monotonicity rule from docs/25 invariant 9 in code: a halt at SYSTEM stops
// everything at every scope, and no lower-scope enable can clear it. A caller cannot pass a
// narrower scope to escape a broader halt, because the comparison is rank-based rather than
// equality-based.
func (h HaltState) Blocks(scope HaltScope) bool {
	if !scope.valid() {
		// An unknown scope cannot be reasoned about, and guessing it might be permissive.
		return true
	}
	for _, r := range h.active {
		if r.Scope.Rank() >= scope.Rank() {
			return true
		}
	}
	return false
}

// Blocking returns the halts that stop risk-increasing action at the given scope.
func (h HaltState) Blocking(scope HaltScope) []HaltRecord {
	var out []HaltRecord
	for _, r := range h.active {
		if !scope.valid() || r.Scope.Rank() >= scope.Rank() {
			out = append(out, r)
		}
	}
	return out
}

// Fact is a measured value plus whether it could actually be read.
//
// The availability bit is a separate field rather than being inferred from a zero value,
// because "the position is zero" and "the position could not be read" are different facts
// with opposite risk consequences. A generic wrapper makes it awkward to construct a fact
// without stating availability, which is the failure mode that would let an unreadable
// source look like a passing one.
type Fact[T any] struct {
	// Value is the measured value. It is only meaningful when Available is true.
	Value T
	// Available reports whether the value could be read from its source of truth.
	Available bool
}

// Measured builds an available fact.
func Measured[T any](v T) Fact[T] { return Fact[T]{Value: v, Available: true} }

// Unmeasured builds an unavailable fact.
func Unmeasured[T any]() Fact[T] { var zero T; return Fact[T]{Value: zero, Available: false} }

// MarketSnapshot is the market state a submission is priced against.
type MarketSnapshot struct {
	// LastPrice is the venue's last price for the instrument.
	LastPrice contracts.Money
	// ObservedAt is when the venue reported it. Staleness is measured from here, not from
	// the command, because a fresh command quoting a stale price is still a stale price.
	ObservedAt contracts.Timestamp
	// VenuePrice is the price the command is priced at, so price deviation can be compared
	// without recomputing it in a way that could round differently.
	VenuePrice contracts.Money
	// Precision is the venue's declared price scale. docs/17 section 2 lists unknown
	// precision as a rejection reason, so it is data rather than a constant.
	Precision int32
}

// PositionSnapshot is the account's position and exposure state.
type PositionSnapshot struct {
	// Quantity is the current signed position in the instrument's base unit.
	Quantity contracts.Quantity
	// Notional is the absolute position value.
	Notional contracts.Money
	// GrossExposure is total absolute exposure across the account.
	GrossExposure contracts.Money
	// NetExposure is directional exposure.
	NetExposure contracts.Money
	// Leverage is account leverage.
	Leverage contracts.Decimal
	// Concentration is the largest single position as a fraction of the account.
	Concentration contracts.Decimal
	// RealisedLossInWindow is realised loss over the policy's measurement window.
	RealisedLossInWindow contracts.Money
	// Drawdown is the current drawdown as a fraction.
	Drawdown contracts.Decimal
	// OpenOrders is the number of open orders for the account.
	OpenOrders contracts.Decimal
}

// AccountSnapshot is the account's own state.
type AccountSnapshot struct {
	// SubjectEnabled reports whether the account is enabled for risk-increasing actions.
	// docs/17 section 2 requires a new account to start disabled.
	SubjectEnabled bool
	// OrdersInWindow is the command count over the policy's rate window.
	OrdersInWindow contracts.Decimal
	// CancelsInWindow is the cancel count over the same window.
	CancelsInWindow contracts.Decimal
}

// InstrumentSnapshot is an instrument's eligibility state.
type InstrumentSnapshot struct {
	// Eligible reports whether the instrument is permitted in this policy scope.
	Eligible bool
	// PricePrecision is the instrument's declared price scale.
	PricePrecision int32
	// QuantityPrecision is the instrument's declared quantity scale.
	QuantityPrecision int32
}

// Facts is every established input the controls evaluate.
//
// The type is closed and every field is required, which is what "establishes authoritative
// state" means in practice. Each fact carries its own availability so a control can apply
// the policy's missing-data behaviour rather than assuming a value.
type Facts struct {
	// Now is the evaluation time, supplied rather than read from a clock so the result is
	// a pure function of its inputs and therefore replayable.
	Now contracts.Timestamp
	// Market is the market snapshot.
	Market Fact[MarketSnapshot]
	// Position is the account's position and exposure state.
	Position Fact[PositionSnapshot]
	// Account is the account's own state.
	Account Fact[AccountSnapshot]
	// Instrument is the instrument's eligibility and precision.
	Instrument Fact[InstrumentSnapshot]
	// StrategyStatus is the strategy's deployment state. It is a value rather than a Fact
	// because an unknown status is itself the fail-safe answer, and StatusUnknown exists to
	// express that; making it optional would add a second way to express the same state.
	StrategyStatus DeploymentStatus
	// Venue is the venue's operational state.
	Venue VenueStatus
	// Halts is the active halt set.
	Halts HaltState
	// ReconciliationOpen reports whether a material reconciliation case is unresolved.
	// docs/17 section 2 lists an unresolved material case as a rejection reason.
	ReconciliationOpen bool
	// DuplicateOf is the fingerprint of an existing open order matching this command, or
	// empty when none matched. docs/04 requires duplicate-order detection.
	DuplicateOf string
	// OrderType is the order's type, checked against the policy's permitted list.
	OrderType string
	// Market is permitted in this policy scope, checked against the policy allow-lists.
	MarketListed bool
	// VenueListed reports whether the venue is in the policy's permitted venues.
	// It is a fact rather than a policy field so that a policy listing a venue the platform
	// does not know about is still a mismatch.
	VenueListed bool
}

// validate checks the facts are internally coherent, so a control never has to defend
// against an impossible combination such as a direction that is neither buy nor sell.
func (f Facts) validate() error {
	if f.Now.IsZero() {
		return reject(contracts.CodeValidation, "evaluation time is required; the engine does not read a clock")
	}
	if !f.StrategyStatus.valid() {
		return reject(contracts.CodeValidation, "unknown strategy deployment status %q", f.StrategyStatus)
	}
	if !f.Venue.valid() {
		return reject(contracts.CodeValidation, "unknown venue status %q", f.Venue)
	}
	if f.Market.Available {
		if !f.Market.Value.LastPrice.Amount().IsSet() {
			return reject(contracts.CodeValidation, "market snapshot has no last price")
		}
		if f.Market.Value.ObservedAt.IsZero() {
			return reject(contracts.CodeValidation, "market snapshot has no observation time")
		}
	}
	return nil
}

// ControlID names a mandatory control from docs/04 section "Risk gate".
type ControlID string

// The fifteen mandatory controls, in the order docs/04 lists them. The order is fixed
// because the evaluation report is a deterministic function of the inputs, and a report
// whose order varied between runs would not be reviewable.
const (
	ControlAccountAuthorization  ControlID = "account_and_environment_authorization"
	ControlStrategyDeployment    ControlID = "strategy_deployment_status"
	ControlInstrumentEligibility ControlID = "instrument_eligibility"
	ControlVenueAvailability     ControlID = "venue_availability"
	ControlPricePrecision        ControlID = "price_and_quantity_precision"
	ControlNotionalLimits        ControlID = "notional_limits"
	ControlPositionLimits        ControlID = "position_limits"
	ControlExposureLimits        ControlID = "exposure_limits"
	ControlConcentrationLimits   ControlID = "concentration_limits"
	ControlLeverageLimits        ControlID = "leverage_limits"
	ControlLossDrawdown          ControlID = "loss_and_drawdown_controls"
	ControlMarketDataStale       ControlID = "stale_market_data_controls"
	ControlDuplicateOrder        ControlID = "duplicate_order_detection"
	ControlRateLimits            ControlID = "rate_and_throttle_limits"
	ControlHaltState             ControlID = "kill_halt_state"
)

// mandatoryControls is the evaluated order. Every risk-increasing command passes all
// fifteen; docs/04 states that "a single failed mandatory control rejects the order", which
// is why the engine is a conjunction rather than a scored sum.
var mandatoryControls = []ControlID{
	ControlAccountAuthorization,
	ControlStrategyDeployment,
	ControlInstrumentEligibility,
	ControlVenueAvailability,
	ControlPricePrecision,
	ControlNotionalLimits,
	ControlPositionLimits,
	ControlExposureLimits,
	ControlConcentrationLimits,
	ControlLeverageLimits,
	ControlLossDrawdown,
	ControlMarketDataStale,
	ControlDuplicateOrder,
	ControlRateLimits,
	ControlHaltState,
}

// MandatoryControls returns the control ids in evaluation order.
func MandatoryControls() []ControlID {
	out := make([]ControlID, len(mandatoryControls))
	copy(out, mandatoryControls)
	return out
}
