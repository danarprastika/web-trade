package riskengine

import (
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Scope is what a control aggregates over.
//
// It is declared here rather than imported from the configuration package so that the engine
// has no dependency on a service, and so that a projection bug in the adapter is confined to
// one small type with a test on both sides of it.
type Scope string

// The aggregation scopes.
const (
	ScopePerOrder      Scope = "PER_ORDER"
	ScopePerAccount    Scope = "PER_ACCOUNT"
	ScopePerStrategy   Scope = "PER_STRATEGY"
	ScopePerInstrument Scope = "PER_INSTRUMENT"
	ScopeGlobal        Scope = "GLOBAL"
)

var scopes = map[Scope]struct{}{
	ScopePerOrder: {}, ScopePerAccount: {}, ScopePerStrategy: {},
	ScopePerInstrument: {}, ScopeGlobal: {},
}

func (s Scope) valid() bool {
	_, ok := scopes[s]
	return ok
}

// Boundary is whether a value exactly equal to a control's threshold passes.
//
// Recorded rather than assumed, because the difference between rejecting a value exactly at
// the limit and accepting it is a real risk difference and getting it wrong permissively is
// a silent hole.
type Boundary string

// The boundary inclusions.
const (
	BoundaryInclusive Boundary = "INCLUSIVE"
	BoundaryExclusive Boundary = "EXCLUSIVE"
)

var boundaries = map[Boundary]struct{}{BoundaryInclusive: {}, BoundaryExclusive: {}}

func (b Boundary) valid() bool {
	_, ok := boundaries[b]
	return ok
}

// OnMissing is what a control does when its source cannot be read.
//
// The zero value is deliberately not a member of the set, so a control constructed without
// stating its missing-data behaviour is rejected rather than assumed to reject. That is a
// little stricter than needed, and deliberately so: the alternative is a control that
// silently inherits a permissive default.
type OnMissing string

// The missing-data behaviours.
const (
	// OnMissingReject fails the control when its source is unavailable.
	OnMissingReject OnMissing = "REJECT"
	// OnMissingUseLastKnown evaluates against the last recorded value instead. The value is
	// still the same value, so this only changes whether the control is recorded as reading
	// a live source, never whether it passes.
	OnMissingUseLastKnown OnMissing = "USE_LAST_KNOWN"
)

var onMissingSet = map[OnMissing]struct{}{OnMissingReject: {}, OnMissingUseLastKnown: {}}

func (o OnMissing) valid() bool {
	_, ok := onMissingSet[o]
	return ok
}

// Control is one mandatory risk control as the engine evaluates it.
//
// A control is either quantitative, carrying a threshold in exactly one denomination, or
// qualitative, carrying none. The split is explicit rather than inferred from which fields
// happen to be nil, because a qualitative control that silently acquired no threshold and a
// quantitative one that silently lost its threshold look identical otherwise, and the second
// of those is the dangerous case.
type Control struct {
	// ID names the control. It is matched against the mandatory control ids, so a control
	// the engine does not know is inert rather than silently permissive.
	ID ControlID
	// Amount is the threshold when the control is currency-denominated.
	Amount *contracts.Money
	// Quantity is the threshold when the control is unit-denominated.
	Quantity *contracts.Quantity
	// Ratio is the threshold when the control is dimensionless: a ratio such as leverage or
	// concentration, or a count such as the order rate. Dimensionless thresholds are exact
	// decimals rather than float percentages, because a percentage would reintroduce the
	// rounding error at exactly the boundary where a decision flips.
	Ratio *contracts.Decimal
	// Scope is what the threshold aggregates over.
	Scope Scope
	// Boundary states whether a value exactly equal to the threshold passes.
	Boundary Boundary
	// Window is the measurement window for rate and loss controls.
	Window time.Duration
	// OnMissing is the behaviour when the control's source is unavailable.
	OnMissing OnMissing
	// NoThreshold declares that a qualitative control has no numeric limit.
	//
	// It must be set explicitly. Without it, a qualitative control that failed to declare a
	// threshold and a quantitative one that lost its threshold would both validate as empty,
	// and the second case is a silently unlimited limit, which is the one failure mode the
	// whole fail-closed design exists to prevent.
	NoThreshold bool
}

// numericControls are the controls whose decision is a comparison against a number.
//
// The rest are qualitative: they compare state against a required condition rather than a
// threshold, so requiring a number of them would force a policy author to invent a limit that
// has no meaning, and a meaningless number that nobody trusts is worse than none.
var numericControls = map[ControlID]bool{
	ControlNotionalLimits:      true,
	ControlPositionLimits:      true,
	ControlExposureLimits:      true,
	ControlConcentrationLimits: true,
	ControlLeverageLimits:      true,
	ControlLossDrawdown:        true,
	ControlRateLimits:          true,
}

// IsNumeric reports whether the control is compared against a numeric threshold.
func (c Control) IsNumeric() bool { return numericControls[c.ID] }

// Describe renders the threshold for an audit record, naming its denomination.
func (c Control) Describe() string {
	switch {
	case c.Amount != nil:
		return c.Amount.String() + " " + c.Amount.Currency()
	case c.Quantity != nil:
		return c.Quantity.String() + " " + string(c.Quantity.Unit())
	case c.Ratio != nil:
		return c.Ratio.String() + " dimensionless"
	case c.NoThreshold:
		return "no numeric threshold (qualitative control)"
	default:
		return "unset"
	}
}

// valid checks a control is coherent with its kind.
//
// The denomination rules are decided by the control's id, not by whichever fields the caller
// happened to populate, so a control cannot be made to validate by choosing a different
// denomination for the same limit.
func (c Control) valid() error {
	set := 0
	for _, present := range []bool{c.Amount != nil, c.Quantity != nil, c.Ratio != nil} {
		if present {
			set++
		}
	}
	if set > 1 {
		return reject(contracts.CodeValidation,
			"control %s states more than one denomination; a control is denominated in "+
				"exactly one of a currency, a unit, or a dimensionless threshold", c.ID)
	}

	if !c.Scope.valid() {
		return reject(contracts.CodeValidation, "control %s has unknown scope %q", c.ID, c.Scope)
	}
	if !c.Boundary.valid() {
		return reject(contracts.CodeValidation,
			"control %s must state boundary inclusivity, got %q", c.ID, c.Boundary)
	}
	if !c.OnMissing.valid() {
		return reject(contracts.CodeValidation,
			"control %s must state behaviour on missing data, got %q", c.ID, c.OnMissing)
	}
	if c.Window < 0 {
		return reject(contracts.CodeValidation, "control %s has a negative window", c.ID)
	}

	if c.IsNumeric() {
		if set == 0 {
			return reject(contracts.CodeValidation,
				"control %s has no threshold; an absent control is not an unlimited control", c.ID)
		}
		if c.NoThreshold {
			return reject(contracts.CodeValidation,
				"control %s is quantitative but declares no threshold; the two statements "+
					"contradict each other", c.ID)
		}
		return nil
	}

	if set != 0 {
		return reject(contracts.CodeValidation,
			"control %s is qualitative but states a threshold of %s; a threshold on a "+
				"qualitative control is never read, so stating one is a limit the author "+
				"believes is enforced and is not", c.ID, c.Describe())
	}
	if !c.NoThreshold {
		return reject(contracts.CodeValidation,
			"control %s is qualitative and must declare NoThreshold explicitly", c.ID)
	}
	return nil
}

// permitsAmount reports whether an observed amount passes the control's threshold,
// applying the boundary rule.
//
// The comparison is exact integer decimal arithmetic throughout, so a value exactly at the
// threshold is decided by the boundary and not by floating point drift. That is why a
// limit is never expressed as a float: at a boundary the two would disagree.
func (c Control) permitsAmount(observed contracts.Money) (bool, error) {
	if c.Amount == nil {
		return false, reject(contracts.CodeValidation,
			"control %s is not currency-denominated and cannot be compared with %s", c.ID, observed)
	}
	if err := observed.RequireSameCurrency(*c.Amount); err != nil {
		// money.schema.json states that a currency mismatch is a hard rejection, not a
		// conversion. A limit in one currency must not be silently applied to another.
		return false, reject(contracts.CodeValidation,
			"control %s is denominated in %s but the observed amount is %s; a currency "+
				"mismatch is a rejection, not a conversion", c.ID, c.Amount.Currency(), observed.Currency())
	}
	cmp, err := observed.Cmp(*c.Amount)
	if err != nil {
		return false, err
	}
	if c.Boundary == BoundaryExclusive {
		return cmp < 0, nil
	}
	return cmp <= 0, nil
}

// permitsQuantity reports whether an observed quantity passes the control's threshold.
func (c Control) permitsQuantity(observed contracts.Quantity) (bool, error) {
	if c.Quantity == nil {
		return false, reject(contracts.CodeValidation,
			"control %s is not unit-denominated and cannot be compared with %s", c.ID, observed)
	}
	if observed.Unit() != c.Quantity.Unit() {
		return false, reject(contracts.CodeValidation,
			"control %s is denominated in %s but the observed quantity is in %s",
			c.ID, c.Quantity.Unit(), observed.Unit())
	}
	cmp, err := observed.Value().Cmp(c.Quantity.Value())
	if err != nil {
		return false, err
	}
	if c.Boundary == BoundaryExclusive {
		return cmp < 0, nil
	}
	return cmp <= 0, nil
}

// Policy is the projection of the signed configuration the engine evaluates.
//
// Every field is required. A missing field is not a permissive default: the engine refuses
// to evaluate at all, because a policy that cannot answer a mandatory control has no safe
// interpretation. This is the reason the engine is safe despite the adapter that builds this
// projection: a projection bug shows up as a rejection, never as a permission.
type Policy struct {
	// Revision is the configuration revision. It is bound into the result so a decision can
	// be traced to the exact policy that produced it.
	Revision string
	// Environment is the promotion stage this policy is for.
	Environment string
	// PermittedInstruments, Venues, Markets, OrderTypes, and Directions are closed
	// allow-lists. Anything absent is denied.
	PermittedInstruments []string
	PermittedVenues      []string
	PermittedMarkets     []string
	PermittedOrderTypes  []string
	PermittedDirections  []string
	// MarketDataMaxAge is the maximum age of a market snapshot.
	MarketDataMaxAge time.Duration
	// DrawdownThreshold is the drawdown ratio bound. It sits on the policy rather than in a
	// Control because realised loss and drawdown share one mandatory control id while being
	// denominated differently, and forcing both into one Control would mean one of them
	// reused the other's denomination.
	DrawdownThreshold contracts.Decimal
	// LossWindow is the measurement window for realised loss.
	LossWindow time.Duration
	// DrawdownWindow is the measurement window for drawdown.
	DrawdownWindow time.Duration
	// RateWindow is the measurement window for order and cancel counts.
	RateWindow time.Duration
	// Controls are the named numeric limits, keyed by control id.
	Controls map[ControlID]Control
}

// Lookup returns a named control.
func (p Policy) Lookup(id ControlID) (Control, bool) {
	c, ok := p.Controls[id]
	return c, ok
}

// permitsListed reports whether a value appears in an allow-list.
//
// A nil or empty allow-list denies everything, which is the fail-safe direction: an operator
// who has not enumerated the permitted venues has not permitted any venue.
func permitsListed(list []string, value string) bool {
	if value == "" || len(list) == 0 {
		return false
	}
	for _, entry := range list {
		if entry == value {
			return true
		}
	}
	return false
}

// validate checks the policy is complete enough to evaluate every mandatory control.
func (p Policy) validate() error {
	if p.Revision == "" {
		return reject(contracts.CodeValidation, "policy revision is required")
	}
	if p.Environment == "" {
		return reject(contracts.CodeValidation, "policy environment is required")
	}
	// Every numeric control the engine evaluates must be present and well formed. The
	// iteration is over a sorted id list so a caller learns about every missing control in
	// one refusal rather than one per attempt.
	var missing []string
	for _, id := range mandatoryControls {
		control, ok := p.Controls[id]
		if !ok {
			missing = append(missing, string(id))
			continue
		}
		if err := control.valid(); err != nil {
			return err
		}
	}
	if len(missing) > 0 {
		return reject(contracts.CodeValidation,
			"policy revision %s is missing %d mandatory control(s): %v; the engine supplies no "+
				"default threshold, because a default limit is an implied permission to trade",
			p.Revision, len(missing), missing)
	}
	for name, list := range map[string][]string{
		"permitted_instruments": p.PermittedInstruments,
		"permitted_venues":      p.PermittedVenues,
		"permitted_markets":     p.PermittedMarkets,
		"permitted_order_types": p.PermittedOrderTypes,
		"permitted_directions":  p.PermittedDirections,
	} {
		if len(list) == 0 {
			return reject(contracts.CodeValidation,
				"policy revision %s has an empty %s allow-list; an empty allow-list denies "+
					"everything rather than permitting it", p.Revision, name)
		}
	}
	if p.MarketDataMaxAge <= 0 {
		return reject(contracts.CodeValidation,
			"policy revision %s must state a positive market data freshness limit", p.Revision)
	}
	if !p.DrawdownThreshold.IsSet() {
		return reject(contracts.CodeValidation,
			"policy revision %s must state a drawdown threshold; an absent threshold is an "+
				"unbounded drawdown allowance", p.Revision)
	}
	if p.LossWindow <= 0 || p.DrawdownWindow <= 0 || p.RateWindow <= 0 {
		return reject(contracts.CodeValidation,
			"policy revision %s must state positive loss, drawdown, and rate windows", p.Revision)
	}
	return nil
}

// Intent is the risk-increasing command being evaluated.
//
// It carries only what the command asks for. It carries no opinion about whether it should
// be allowed, which is what lets a later reader be confident that nothing in the command
// could have influenced the outcome.
type Intent struct {
	// CommandID is the canonical command identifier.
	CommandID contracts.Identifier
	// CorrelationID ties the decision to the request that produced it.
	CorrelationID contracts.Identifier
	// AccountID is the account the order is for.
	AccountID contracts.Identifier
	// StrategyID is the strategy placing the order.
	StrategyID contracts.Identifier
	// Instrument is the instrument being traded.
	Instrument string
	// Venue is the venue the order targets.
	Venue string
	// Market is the market the instrument belongs to.
	Market string
	// Direction is the side of the order.
	Direction Direction
	// OrderType is the order's type.
	OrderType string
	// Quantity is the order size in the instrument's base unit.
	Quantity contracts.Quantity
	// LimitPrice is the order's price constraint. A market order has none, which is why a
	// missing price is a separate case rather than a zero price.
	LimitPrice *contracts.Money
	// IssuedAt is when the command was issued.
	IssuedAt contracts.Timestamp
	// Environment is the environment the command targets.
	Environment string
}

// HasPriceConstraint reports whether the command carries a price constraint.
func (i Intent) HasPriceConstraint() bool { return i.LimitPrice != nil }

func (i Intent) validate() error {
	if i.CommandID.IsZero() {
		return reject(contracts.CodeValidation, "command id is required; an unattributed order is not auditable")
	}
	if i.CorrelationID.IsZero() {
		return reject(contracts.CodeValidation, "correlation id is required")
	}
	if i.AccountID.IsZero() {
		return reject(contracts.CodeValidation, "account id is required")
	}
	if i.StrategyID.IsZero() {
		return reject(contracts.CodeValidation, "strategy id is required")
	}
	if i.Instrument == "" || i.Venue == "" || i.Market == "" {
		return reject(contracts.CodeValidation, "instrument, venue, and market are all required")
	}
	if !i.Direction.valid() {
		return reject(contracts.CodeValidation, "unknown order direction %q", i.Direction)
	}
	if i.OrderType == "" {
		return reject(contracts.CodeValidation, "order type is required")
	}
	if !i.Quantity.Value().IsSet() {
		return reject(contracts.CodeValidation, "quantity is required")
	}
	if i.IssuedAt.IsZero() {
		return reject(contracts.CodeValidation, "issued_at is required")
	}
	if i.Environment == "" {
		return reject(contracts.CodeValidation, "environment is required")
	}
	return nil
}

// Advisory carries signals that are explicitly not authority.
//
// It is accepted by Evaluate and never read. The field is present rather than absent so a
// test can prove it is inert: an absent field could be reintroduced by a signature change,
// while an ignored field is covered by a test that fails if any read of it appears.
type Advisory struct {
	// ModelConfidence is a model-reported confidence, for example "0.99".
	ModelConfidence string
	// ModelVerdict is a model-reported recommendation, for example "BUY".
	ModelVerdict string
	// ModelRequestedOverride is a model asking for the veto to be waived.
	ModelRequestedOverride bool
	// UIHidden reports whether a UI control was hidden or disabled.
	UIHidden bool
	// UIOperatorOverride is an operator asking for the veto to be waived.
	UIOperatorOverride bool
	// VenueAccepted is a venue's acknowledgement of a prior submission.
	VenueAccepted bool
	// VenueReason is the venue's stated reason.
	VenueReason string
	// OperatorNote is free text from an operator.
	OperatorNote string
}
