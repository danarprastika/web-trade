// Package config implements typed, schema-validated, signed, immutable configuration
// snapshots for the control plane.
//
// It exists because of a specific hazard in this system: a trading limit is a financial
// control, and a limit that can be altered at runtime by anything less than a signed,
// reviewed, attributable change is not a control at all. docs/17 section 1 is explicit
// that configuration is "immutable after activation" and that services "do not read
// arbitrary mutable key/value settings during a financial decision".
//
// Four properties are load-bearing, and each maps to one of WI-112's acceptance criteria:
//
//  1. A snapshot is rejected unless it is structurally valid, attributable, and within its
//     configured freshness. Invalid, stale, and unsigned configuration is refused rather
//     than defaulted (AC1).
//  2. Undocumented configuration cannot enter the snapshot at all. Decoding is strict, so
//     an unknown field is a rejection and not something a future schema version could
//     quietly introduce into a live account (AC2).
//  3. Drift between the signed snapshot and what the runtime actually resolved is detected
//     and alerted, and the alert is monotonic: recovery automation cannot clear it
//     (AC3, and docs/25 line 41).
//  4. Unknown feature flags never grant authority, and the last verified safe snapshot may
//     be used only inside its configured freshness window (AC4).
//
// The fail-safe direction is the whole design. docs/17 section 2 states that missing
// limits, unknown precision, stale inputs, or unavailable state "means reject" and that "no
// default value may silently imply permission to trade". Every zero value in this package is
// therefore the restrictive one: an unset limit is absent rather than unlimited, an unset
// flag is off rather than on, and an unconfigured subject is disabled for risk-increasing
// actions rather than enabled.
package config

import (
	"fmt"
	"sort"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Environment is a promotion stage. The ladder is closed and ordered, and promotion runs
// one step at a time. docs/17 section 1 requires the sequence
// dev, test, staging, paper, shadow, live.
type Environment string

// The closed set of environments, in promotion order.
const (
	EnvDev     Environment = "dev"
	EnvTest    Environment = "test"
	EnvStaging Environment = "staging"
	EnvPaper   Environment = "paper"
	EnvShadow  Environment = "shadow"
	EnvLive    Environment = "live"
)

// environmentOrder is the promotion ladder. Position in this slice is the promotion rank;
// a snapshot may only be promoted into an environment exactly one step ahead of the one it
// was verified in.
//
// This slice is the single source of truth for the ladder. The Env constants above are
// deliberately not the source, because a constant set and a rank set can drift apart and
// the failure is silent: an environment absent from the ladder would be one that the
// promotion check silently treats as unknown, and an unknown environment must be refused
// rather than ranked. Valid and Rank both derive from here, and a test asserts the two
// constant sets are identical in content.
var environmentOrder = []Environment{EnvDev, EnvTest, EnvStaging, EnvPaper, EnvShadow, EnvLive}

var environmentRank = func() map[Environment]int {
	m := make(map[Environment]int, len(environmentOrder))
	for i, e := range environmentOrder {
		m[e] = i
	}
	return m
}()

// ErrInvalidConfig is the sentinel behind every refusal in this package, so callers can use
// errors.Is to attribute a rejection to configuration rather than to an unrelated fault.
var ErrInvalidConfig = contracts.ErrInvalidContractValue

// Valid reports whether the environment is in the closed ladder.
func (e Environment) Valid() bool {
	_, ok := environmentRank[e]
	return ok
}

// Rank is the promotion position, or -1 for an unknown environment.
func (e Environment) Rank() int {
	if r, ok := environmentRank[e]; ok {
		return r
	}
	return -1
}

// AllEnvironments returns the ladder in promotion order.
func AllEnvironments() []Environment {
	out := make([]Environment, len(environmentOrder))
	copy(out, environmentOrder)
	return out
}

// ParseEnvironment resolves an environment name, refusing anything off the ladder.
func ParseEnvironment(s string) (Environment, error) {
	e := Environment(s)
	if !e.Valid() {
		return "", fmt.Errorf("%w: %q is not a known environment; the promotion ladder is closed", ErrInvalidConfig, s)
	}
	return e, nil
}

// AggregationScope is what a limit aggregates over. A limit without a scope is meaningless:
// "max order notional 1000" means one very different thing per order than per account.
type AggregationScope string

// The aggregation scopes.
const (
	ScopePerOrder      AggregationScope = "PER_ORDER"
	ScopePerAccount    AggregationScope = "PER_ACCOUNT"
	ScopePerStrategy   AggregationScope = "PER_STRATEGY"
	ScopePerInstrument AggregationScope = "PER_INSTRUMENT"
	ScopeGlobal        AggregationScope = "GLOBAL"
)

var aggregationScopes = map[AggregationScope]struct{}{
	ScopePerOrder: {}, ScopePerAccount: {}, ScopePerStrategy: {},
	ScopePerInstrument: {}, ScopeGlobal: {},
}

func (a AggregationScope) valid() bool {
	_, ok := aggregationScopes[a]
	return ok
}

// Boundary is whether a limit at exactly the configured value passes.
//
// This is recorded rather than assumed because a half-open versus closed boundary is the
// difference between rejecting a trade that is exactly at the limit and accepting it, and
// getting that wrong in the permissive direction is a silent risk hole. docs/17 section 3
// requires each numeric limit to state boundary inclusivity explicitly.
type Boundary string

// The boundary inclusions.
const (
	// BoundaryInclusive passes a value exactly equal to the limit.
	BoundaryInclusive Boundary = "INCLUSIVE"
	// BoundaryExclusive rejects a value exactly equal to the limit.
	BoundaryExclusive Boundary = "EXCLUSIVE"
)

var boundaries = map[Boundary]struct{}{BoundaryInclusive: {}, BoundaryExclusive: {}}

func (b Boundary) valid() bool {
	_, ok := boundaries[b]
	return ok
}

// SourceOfTruth names the system a limit's value is measured against. A limit whose source
// is not authoritative is not a control, so this is recorded with the limit rather than
// assumed at the call site.
type SourceOfTruth string

// The sources of truth.
const (
	// SourceLedger is the append-only financial record.
	SourceLedger SourceOfTruth = "LEDGER"
	// SourceOMS is the canonical order state.
	SourceOMS SourceOfTruth = "OMS"
	// SourceReconciliation is the reconciled venue/account state.
	SourceReconciliation SourceOfTruth = "RECONCILIATION"
	// SourceMarketData is the normalised market snapshot.
	SourceMarketData SourceOfTruth = "MARKET_DATA"
	// SourceOperator is a human attestation with an approval record.
	SourceOperator SourceOfTruth = "OPERATOR"
)

var sourcesOfTruth = map[SourceOfTruth]struct{}{
	SourceLedger: {}, SourceOMS: {}, SourceReconciliation: {},
	SourceMarketData: {}, SourceOperator: {},
}

func (s SourceOfTruth) valid() bool {
	_, ok := sourcesOfTruth[s]
	return ok
}

// MissingDataPolicy is what happens when a limit's source cannot be read.
//
// The default zero value is MissingDataReject, which is the fail-safe choice: an
// unreadable source must not be silently treated as a passing limit.
type MissingDataPolicy string

// The missing-data policies.
const (
	// MissingDataReject fails the control when the source is unavailable.
	MissingDataReject MissingDataPolicy = "REJECT"
	// MissingDataUseLastKnown uses a bounded previously recorded value. It is only
	// acceptable where the limit's window is short, and the window itself bounds the
	// staleness, so this is still fail-safe within that window.
	MissingDataUseLastKnown MissingDataPolicy = "USE_LAST_KNOWN"
)

var missingDataPolicies = map[MissingDataPolicy]struct{}{
	MissingDataReject: {}, MissingDataUseLastKnown: {},
}

func (m MissingDataPolicy) valid() bool {
	_, ok := missingDataPolicies[m]
	return ok
}

// Limit is one numeric financial control.
//
// Every field required by docs/17 section 3 is present and none of them has a permissive
// zero value. The type is deliberately verbose: a limit is written once, reviewed, signed,
// and then enforced on every risk-increasing order, so the cost of stating its unit,
// scope, window, boundary, source, and missing-data behaviour is paid at authoring time
// and never at trading time.
type Limit struct {
	// ID is the stable name of the control, such as "max_order_notional".
	ID string `json:"id"`
	// Amount is the threshold when the control is denominated in a currency. Exactly one of
	// Amount and Quantity must be non-nil, because docs/17 section 3 requires each numeric
	// limit to specify "currency or unit": a notional has a currency and a position size has
	// a unit, and forcing one shape onto both would either invent a currency for a count or
	// reduce a notional to a bare number.
	//
	// The fields are pointers because contracts.Money and contracts.Quantity deliberately
	// refuse to encode an unset value. That refusal is the right behaviour for a wire type,
	// and a pointer is what lets "this control has no amount" survive canonicalisation
	// without weakening either type.
	Amount *contracts.Money `json:"amount,omitempty"`
	// Quantity is the threshold when the control is denominated in a unit.
	Quantity *contracts.Quantity `json:"quantity,omitempty"`
	// Aggregation is what the threshold aggregates over.
	Aggregation AggregationScope `json:"aggregation"`
	// Window is the measurement window. A zero window is rejected at validation: a limit
	// with no window is a limit that never resets, which is either an unbounded block or a
	// permanent pass depending on the implementation, and neither is acceptable.
	Window time.Duration `json:"window"`
	// Boundary states whether a value exactly equal to the threshold passes.
	Boundary Boundary `json:"boundary"`
	// Source is the system the value is measured against.
	Source SourceOfTruth `json:"source"`
	// OnMissing is the behaviour when Source is unavailable.
	OnMissing MissingDataPolicy `json:"on_missing"`
	// Description is the reviewer-facing statement of intent. It is required because the
	// approval in docs/17 section 6 is a human review, and a reviewer cannot meaningfully
	// approve a control that does not say what it is for.
	Description string `json:"description"`
}

// IsAmount reports whether the limit is currency-denominated.
func (l Limit) IsAmount() bool { return l.Amount != nil }

// IsQuantity reports whether the limit is unit-denominated.
func (l Limit) IsQuantity() bool { return l.Quantity != nil }

// Describe renders the threshold for an audit record, naming its denomination.
func (l Limit) Describe() string {
	switch {
	case l.IsAmount():
		return l.Amount.String() + " " + l.Amount.Currency()
	case l.IsQuantity():
		return l.Quantity.String() + " " + string(l.Quantity.Unit())
	default:
		return "unset"
	}
}

// Validate checks that the limit states every required dimension.
func (l Limit) Validate() error {
	if strings.TrimSpace(l.ID) == "" {
		return fmt.Errorf("%w: a limit must have an id", ErrInvalidConfig)
	}
	// Exactly one denomination. Both set is ambiguous, and neither set is the permissive
	// failure the whole package is built to avoid.
	switch {
	case l.IsAmount() && l.IsQuantity():
		return fmt.Errorf("%w: limit %q states both a currency amount and a unit quantity; "+
			"a control is denominated in one or the other", ErrInvalidConfig, l.ID)
	case !l.IsAmount() && !l.IsQuantity():
		return fmt.Errorf("%w: limit %q has no value; an absent limit is not an unlimited limit", ErrInvalidConfig, l.ID)
	}
	if l.IsAmount() && l.Amount.Currency() == "" {
		return fmt.Errorf("%w: limit %q must state its currency", ErrInvalidConfig, l.ID)
	}
	if l.IsQuantity() && l.Quantity.Unit() == "" {
		return fmt.Errorf("%w: limit %q must state its unit", ErrInvalidConfig, l.ID)
	}
	if !l.Aggregation.valid() {
		return fmt.Errorf("%w: limit %q has unknown aggregation scope %q", ErrInvalidConfig, l.ID, l.Aggregation)
	}
	if l.Window <= 0 {
		return fmt.Errorf("%w: limit %q must state a positive measurement window", ErrInvalidConfig, l.ID)
	}
	if !l.Boundary.valid() {
		return fmt.Errorf("%w: limit %q must state boundary inclusivity, got %q", ErrInvalidConfig, l.ID, l.Boundary)
	}
	if !l.Source.valid() {
		return fmt.Errorf("%w: limit %q must name a source of truth, got %q", ErrInvalidConfig, l.ID, l.Source)
	}
	if !l.OnMissing.valid() {
		return fmt.Errorf("%w: limit %q must state behaviour on missing data, got %q", ErrInvalidConfig, l.ID, l.OnMissing)
	}
	if strings.TrimSpace(l.Description) == "" {
		return fmt.Errorf("%w: limit %q must carry a description for reviewer approval", ErrInvalidConfig, l.ID)
	}
	return nil
}

// Policy is the risk policy dimension set. docs/17 section 3 requires each of these to be
// explicitly defined for the account, strategy, instrument, and environment scope.
//
// Every field is a map or a list rather than a scalar because a policy applies to a scope
// that must be enumerated. A missing entry is an absent control, and an absent control is a
// rejection, never a wildcard.
type Policy struct {
	// PermittedMarkets, Venues, Instruments, OrderTypes, Directions are the closed
	// allow-lists. Anything not listed is denied.
	PermittedMarkets     []string `json:"permitted_markets"`
	PermittedVenues      []string `json:"permitted_venues"`
	PermittedInstruments []string `json:"permitted_instruments"`
	PermittedOrderTypes  []string `json:"permitted_order_types"`
	PermittedDirections  []string `json:"permitted_directions"`
	// MaxOrderNotional and MaxOrderQuantity bound a single order.
	MaxOrderNotional contracts.Money    `json:"max_order_notional"`
	MaxOrderQuantity contracts.Quantity `json:"max_order_quantity"`
	// MaxGrossExposure, MaxNetExposure, MaxLeverage, MaxConcentration, MaxOpenOrders.
	MaxGrossExposure contracts.Money   `json:"max_gross_exposure"`
	MaxNetExposure   contracts.Money   `json:"max_net_exposure"`
	MaxLeverage      contracts.Decimal `json:"max_leverage"`
	MaxConcentration contracts.Decimal `json:"max_concentration"`
	MaxOpenOrders    contracts.Decimal `json:"max_open_orders"`
	// LossThreshold and DrawdownThreshold with their windows and sources.
	LossThreshold     contracts.Money   `json:"loss_threshold"`
	LossWindow        time.Duration     `json:"loss_window"`
	DrawdownThreshold contracts.Decimal `json:"drawdown_threshold"`
	DrawdownWindow    time.Duration     `json:"drawdown_window"`
	DrawdownSource    SourceOfTruth     `json:"drawdown_source"`
	// MarketDataMaxAge and MaxPriceDeviation bound stale and dislocated inputs.
	MarketDataMaxAge  time.Duration     `json:"market_data_max_age"`
	MaxPriceDeviation contracts.Decimal `json:"max_price_deviation"`
	// OrderRateLimit and CancelRateLimit bound flow.
	OrderRateLimit  contracts.Decimal `json:"order_rate_limit"`
	CancelRateLimit contracts.Decimal `json:"cancel_rate_limit"`
	RateWindow      time.Duration     `json:"rate_window"`
	// OperatingModes and Schedule bound when the strategy may act.
	OperatingModes []string `json:"operating_modes"`
	// HaltAuthority and ReEnableAuthority name who may halt and who may re-enable.
	// docs/17 section 5 requires re-enable to be separated from halt authority and to need
	// a two-person approval for system-wide live re-enable.
	HaltAuthority     contracts.ActorType `json:"halt_authority"`
	ReEnableAuthority contracts.ActorType `json:"re_enable_authority"`
	// EscalationContacts is the notification path for a breach.
	EscalationContacts []string `json:"escalation_contacts"`
	// SettlementAssumptions records fee, funding, margin, and settlement treatment where
	// applicable. It is free text because it is venue- and jurisdiction-specific, but it is
	// required to be present so a reviewer confirms the assumption rather than inheriting an
	// implicit one.
	SettlementAssumptions string `json:"settlement_assumptions"`
	// Limits is the full set of named numeric controls, each carrying its own scope,
	// window, boundary, source, and missing-data behaviour.
	Limits []Limit `json:"limits"`
}

// requiredListFields names the policy dimensions that must be non-empty. They are checked
// as a set so a caller learns every missing dimension in one rejection rather than one per
// attempt, which matters when the fix is a review conversation rather than a code change.
var requiredListFields = []struct {
	name  string
	value func(Policy) []string
}{
	{"permitted_markets", func(p Policy) []string { return p.PermittedMarkets }},
	{"permitted_venues", func(p Policy) []string { return p.PermittedVenues }},
	{"permitted_instruments", func(p Policy) []string { return p.PermittedInstruments }},
	{"permitted_order_types", func(p Policy) []string { return p.PermittedOrderTypes }},
	{"permitted_directions", func(p Policy) []string { return p.PermittedDirections }},
	{"operating_modes", func(p Policy) []string { return p.OperatingModes }},
	{"escalation_contacts", func(p Policy) []string { return p.EscalationContacts }},
}

// requiredDecimalFields names the numeric policy dimensions that must be explicitly set.
var requiredDecimalFields = []struct {
	name string
	ok   func(Policy) bool
}{
	{"max_order_notional", func(p Policy) bool { return p.MaxOrderNotional.Amount().IsSet() }},
	{"max_order_quantity", func(p Policy) bool { return p.MaxOrderQuantity.Value().IsSet() }},
	{"max_gross_exposure", func(p Policy) bool { return p.MaxGrossExposure.Amount().IsSet() }},
	{"max_net_exposure", func(p Policy) bool { return p.MaxNetExposure.Amount().IsSet() }},
	{"max_leverage", func(p Policy) bool { return p.MaxLeverage.IsSet() }},
	{"max_concentration", func(p Policy) bool { return p.MaxConcentration.IsSet() }},
	{"max_open_orders", func(p Policy) bool { return p.MaxOpenOrders.IsSet() }},
	{"loss_threshold", func(p Policy) bool { return p.LossThreshold.Amount().IsSet() }},
	{"drawdown_threshold", func(p Policy) bool { return p.DrawdownThreshold.IsSet() }},
	{"max_price_deviation", func(p Policy) bool { return p.MaxPriceDeviation.IsSet() }},
	{"order_rate_limit", func(p Policy) bool { return p.OrderRateLimit.IsSet() }},
	{"cancel_rate_limit", func(p Policy) bool { return p.CancelRateLimit.IsSet() }},
}

// Validate checks that every required policy dimension is present and coherent.
//
// docs/17 section 3 is unusually firm that "the platform supplies no universal live numeric
// trading limits" and that "until the complete policy is validated and approved, live
// activation is blocked". This function is that gate: it refuses an incomplete policy
// outright rather than filling gaps with defaults, which is what makes the platform's limits
// the owner's decision and not this code's.
func (p Policy) Validate() error {
	var missing []string
	for _, f := range requiredListFields {
		if len(f.value(p)) == 0 {
			missing = append(missing, f.name)
		}
	}
	for _, f := range requiredDecimalFields {
		if !f.ok(p) {
			missing = append(missing, f.name)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		// A closed fail-safe rule rather than an unresolved design choice, per docs/17
		// section 3, so the message says so rather than inviting a workaround.
		return fmt.Errorf("%w: policy is missing %d required dimension(s): %s; "+
			"live activation is blocked until the complete policy is supplied, because the "+
			"platform provides no universal numeric limits and no default may imply permission to trade",
			ErrInvalidConfig, len(missing), strings.Join(missing, ", "))
	}

	if p.MarketDataMaxAge <= 0 {
		return fmt.Errorf("%w: market_data_max_age must be positive; a zero freshness limit "+
			"would accept stale input", ErrInvalidConfig)
	}
	if p.LossWindow <= 0 || p.DrawdownWindow <= 0 {
		return fmt.Errorf("%w: loss and drawdown thresholds must each state a positive measurement window", ErrInvalidConfig)
	}
	if !p.DrawdownSource.valid() {
		return fmt.Errorf("%w: drawdown must name a source of truth, got %q", ErrInvalidConfig, p.DrawdownSource)
	}
	if p.RateWindow <= 0 {
		return fmt.Errorf("%w: order and cancel rate limits must share a positive measurement window", ErrInvalidConfig)
	}
	if p.MaxOrderNotional.Currency() == "" || p.MaxGrossExposure.Currency() == "" || p.MaxNetExposure.Currency() == "" {
		return fmt.Errorf("%w: notional and exposure limits must each state a currency", ErrInvalidConfig)
	}
	if !p.HaltAuthority.Valid() {
		return fmt.Errorf("%w: halt_authority must be a known actor type, got %q", ErrInvalidConfig, p.HaltAuthority)
	}
	if !p.ReEnableAuthority.Valid() {
		return fmt.Errorf("%w: re_enable_authority must be a known actor type, got %q", ErrInvalidConfig, p.ReEnableAuthority)
	}
	// docs/17 section 5 requires the authority to clear a halt to be distinct from the
	// authority that raised it, and explicitly excludes a model or strategy from both.
	if err := forbidSelfAuthority("halt_authority", p.HaltAuthority); err != nil {
		return err
	}
	if err := forbidSelfAuthority("re_enable_authority", p.ReEnableAuthority); err != nil {
		return err
	}
	if p.HaltAuthority == p.ReEnableAuthority {
		return fmt.Errorf("%w: halt and re-enable authority must be separated; one actor holding "+
			"both can raise a halt and immediately clear it", ErrInvalidConfig)
	}
	if strings.TrimSpace(p.SettlementAssumptions) == "" {
		return fmt.Errorf("%w: fee, funding, margin, and settlement assumptions must be stated; "+
			"an unstated assumption is an implicit one", ErrInvalidConfig)
	}

	if len(p.Limits) == 0 {
		return fmt.Errorf("%w: policy declares no numeric controls", ErrInvalidConfig)
	}
	seen := make(map[string]struct{}, len(p.Limits))
	for _, l := range p.Limits {
		if err := l.Validate(); err != nil {
			return err
		}
		if _, dup := seen[l.ID]; dup {
			return fmt.Errorf("%w: limit %q is declared twice; a duplicate control is "+
				"ambiguous about which one applies", ErrInvalidConfig, l.ID)
		}
		seen[l.ID] = struct{}{}
	}
	return nil
}

// Limit returns the named control.
func (p Policy) Limit(id string) (Limit, bool) {
	for _, l := range p.Limits {
		if l.ID == id {
			return l, true
		}
	}
	return Limit{}, false
}

// LimitIDs returns every declared control name in sorted order, so two revisions can be
// compared deterministically.
func (p Policy) LimitIDs() []string {
	out := make([]string, 0, len(p.Limits))
	for _, l := range p.Limits {
		out = append(out, l.ID)
	}
	sort.Strings(out)
	return out
}

// forbidSelfAuthority rejects an actor that may not hold a control-plane authority.
// docs/17 section 6: "No model or strategy may modify its own risk policy or grant itself
// permission."
func forbidSelfAuthority(field string, actor contracts.ActorType) error {
	if actor == contracts.ActorAgent {
		return fmt.Errorf("%w: %s must not be an agent; an AI or model actor may not hold "+
			"control-plane authority over its own policy", ErrInvalidConfig, field)
	}
	return nil
}
