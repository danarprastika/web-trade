package riskengine

import (
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The fixtures below build a baseline in which every one of the fifteen mandatory controls
// passes. Tests then change exactly one thing and assert on exactly one control.
//
// The discipline matters: a test that mutates several inputs and asserts a single verdict
// passes for the wrong reason as often as the right one, and a risk gate is the worst place
// to have a test that cannot say which control actually stopped the order.

const (
	// fixtureEnv is an environment name. The engine treats it as an opaque string and only
	// compares it to the policy's own environment, which is why it does not import the
	// control-plane's stage constants: the projection is deliberately narrower than the
	// source type, and a test that hard-codes the engine's copy is what keeps it narrow.
	fixtureEnv = "PRODUCTION"

	fixtureInstrument = "BTC-USDT"
	fixtureVenue      = "VENUE_A"
	fixtureMarket     = "SPOT"
	fixtureOrderType  = "LIMIT"
	fixtureCurrency   = "USDT"
)

// id builds a valid identifier with a canonical prefix and a 26-character Crockford Base32
// payload. The zero character is in the alphabet, so this is the shortest valid payload.
func id(t *testing.T, prefix string) contracts.Identifier {
	t.Helper()
	parsed, err := contracts.ParseIdentifier(prefix + strings.Repeat("0", 26))
	if err != nil {
		t.Fatalf("fixture identifier %s... is not valid: %v", prefix, err)
	}
	return parsed
}

// otherID builds a second, different identifier with the same prefix, so a test can change
// one identifier field while keeping it a valid one. The payload must stay exactly 26
// characters or the identifier is rejected, which is why this is a separate helper rather
// than a modified string at each call site.
func otherID(t *testing.T, prefix string) contracts.Identifier {
	t.Helper()
	parsed, err := contracts.ParseIdentifier(prefix + "1" + strings.Repeat("0", 25))
	if err != nil {
		t.Fatalf("mutated identifier %s... is not valid: %v", prefix, err)
	}
	return parsed
}

func money(t *testing.T, currency, amount string) contracts.Money {
	t.Helper()
	m, err := contracts.NewMoney(currency, contracts.MustParseDecimal(amount))
	if err != nil {
		t.Fatalf("fixture money %s %s is not valid: %v", amount, currency, err)
	}
	return m
}

func scaledMoney(t *testing.T, currency, amount string, scale int32) contracts.Money {
	t.Helper()
	m, err := contracts.NewMoneyWithScale(currency, contracts.MustParseDecimal(amount), &scale)
	if err != nil {
		t.Fatalf("fixture scaled money %s %s is not valid: %v", amount, currency, err)
	}
	return m
}

// quantityUnits maps the fixture's short names onto the closed unit set, so a test can write
// "BASE_ASSET" as a string without every call site handling an error return.
var quantityUnits = map[string]contracts.QuantityUnit{
	"BASE_ASSET":  contracts.UnitBaseAsset,
	"QUOTE_ASSET": contracts.UnitQuoteAsset,
	"CONTRACT":    contracts.UnitContract,
}

func quantity(t *testing.T, unit, value string) contracts.Quantity {
	t.Helper()
	q, err := contracts.NewQuantity(contracts.MustParseDecimal(value), quantityUnits[unit])
	if err != nil {
		t.Fatalf("fixture quantity %s %s is not valid: %v", value, unit, err)
	}
	return q
}

func ts(t *testing.T, s string) contracts.Timestamp {
	t.Helper()
	parsed, err := contracts.ParseTimestamp(s)
	if err != nil {
		t.Fatalf("fixture timestamp %q is not valid: %v", s, err)
	}
	return parsed
}

// The baseline evaluation time. Every timestamp in the fixtures is expressed relative to it
// so a reader can see the ages involved.
const (
	baselineNow         = "2026-03-01T12:00:00.000000000Z"
	baselineMarketFresh = "2026-03-01T11:59:58.000000000Z"
	baselineIssued      = "2026-03-01T11:59:59.000000000Z"
)

const baselineLifetime = 30 * time.Second

// baselinePolicy is a complete, coherent policy in which every mandatory control is stated.
//
// The limits are chosen so the baseline order sits comfortably inside all of them, which
// means a boundary test can move exactly one limit to the order's value and watch the
// comparison decide it.
func baselinePolicy(t *testing.T) Policy {
	t.Helper()

	amount := func(v string) *contracts.Money {
		m := money(t, fixtureCurrency, v)
		return &m
	}
	qty := func(v string) *contracts.Quantity {
		q := quantity(t, "BASE_ASSET", v)
		return &q
	}
	ratio := func(v string) *contracts.Decimal {
		d := contracts.MustParseDecimal(v)
		return &d
	}
	qualitative := func(id ControlID) Control {
		return Control{ID: id, Scope: ScopeGlobal, Boundary: BoundaryInclusive, OnMissing: OnMissingReject, NoThreshold: true}
	}

	return Policy{
		Revision: "cfg-0007",
		// The environment is an opaque string to this engine; it is only compared with the
		// command's own environment.
		Environment:          fixtureEnv,
		PermittedInstruments: []string{fixtureInstrument},
		PermittedVenues:      []string{fixtureVenue},
		PermittedMarkets:     []string{fixtureMarket},
		PermittedOrderTypes:  []string{"LIMIT", "MARKET"},
		PermittedDirections:  []string{string(DirBuy), string(DirSell)},
		MarketDataMaxAge:     5 * time.Second,
		DrawdownThreshold:    contracts.MustParseDecimal("0.10"),
		LossWindow:           time.Hour,
		DrawdownWindow:       time.Hour,
		RateWindow:           time.Minute,
		Controls: map[ControlID]Control{
			ControlAccountAuthorization:  qualitative(ControlAccountAuthorization),
			ControlStrategyDeployment:    qualitative(ControlStrategyDeployment),
			ControlInstrumentEligibility: qualitative(ControlInstrumentEligibility),
			ControlVenueAvailability:     qualitative(ControlVenueAvailability),
			ControlPricePrecision:        qualitative(ControlPricePrecision),
			ControlDuplicateOrder:        qualitative(ControlDuplicateOrder),
			ControlMarketDataStale:       qualitative(ControlMarketDataStale),
			ControlHaltState:             qualitative(ControlHaltState),

			ControlNotionalLimits: {
				ID: ControlNotionalLimits, Amount: amount("10000.00"),
				Scope: ScopePerOrder, Boundary: BoundaryInclusive, OnMissing: OnMissingReject,
			},
			ControlExposureLimits: {
				ID: ControlExposureLimits, Amount: amount("50000.00"),
				Scope: ScopePerAccount, Boundary: BoundaryInclusive, OnMissing: OnMissingReject,
			},
			ControlLossDrawdown: {
				ID: ControlLossDrawdown, Amount: amount("1000.00"),
				Scope: ScopePerStrategy, Boundary: BoundaryInclusive, OnMissing: OnMissingReject,
				Window: time.Hour,
			},
			ControlPositionLimits: {
				ID: ControlPositionLimits, Quantity: qty("100"),
				Scope: ScopePerInstrument, Boundary: BoundaryInclusive, OnMissing: OnMissingReject,
			},
			ControlConcentrationLimits: {
				ID: ControlConcentrationLimits, Ratio: ratio("0.25"),
				Scope: ScopePerAccount, Boundary: BoundaryInclusive, OnMissing: OnMissingReject,
			},
			ControlLeverageLimits: {
				ID: ControlLeverageLimits, Ratio: ratio("2.0"),
				Scope: ScopePerAccount, Boundary: BoundaryInclusive, OnMissing: OnMissingReject,
			},
			ControlRateLimits: {
				ID: ControlRateLimits, Ratio: ratio("100"),
				Scope: ScopePerAccount, Boundary: BoundaryInclusive, OnMissing: OnMissingReject,
				Window: time.Minute,
			},
		},
	}
}

// baselineFacts is a complete set of established facts in which every control passes.
//
// Every Fact is explicitly available. A test for fail-closed behaviour starts from this and
// clears one availability bit, so the difference between the passing and failing case is
// exactly the bit under test.
func baselineFacts(t *testing.T) Facts {
	t.Helper()

	halts, err := NewHaltState()
	if err != nil {
		t.Fatalf("baseline halt state is not valid: %v", err)
	}

	return Facts{
		Now: ts(t, baselineNow),
		Market: Measured(MarketSnapshot{
			LastPrice:  money(t, fixtureCurrency, "100.00"),
			ObservedAt: ts(t, baselineMarketFresh),
			VenuePrice: money(t, fixtureCurrency, "100.00"),
			Precision:  2,
		}),
		Position: Measured(PositionSnapshot{
			Quantity:             quantity(t, "BASE_ASSET", "10"),
			Notional:             money(t, fixtureCurrency, "1000.00"),
			GrossExposure:        money(t, fixtureCurrency, "2000.00"),
			NetExposure:          money(t, fixtureCurrency, "1000.00"),
			Leverage:             contracts.MustParseDecimal("1.0"),
			Concentration:        contracts.MustParseDecimal("0.10"),
			RealisedLossInWindow: money(t, fixtureCurrency, "0.00"),
			Drawdown:             contracts.MustParseDecimal("0.01"),
			OpenOrders:           contracts.MustParseDecimal("0"),
		}),
		Account: Measured(AccountSnapshot{
			SubjectEnabled:  true,
			OrdersInWindow:  contracts.MustParseDecimal("4"),
			CancelsInWindow: contracts.MustParseDecimal("1"),
		}),
		Instrument: Measured(InstrumentSnapshot{
			Eligible:          true,
			PricePrecision:    2,
			QuantityPrecision: 8,
		}),
		StrategyStatus:     StatusDeployed,
		Venue:              VenueAvailable,
		Halts:              halts,
		ReconciliationOpen: false,
		DuplicateOf:        "",
		OrderType:          fixtureOrderType,
		MarketListed:       true,
		VenueListed:        true,
	}
}

// baselineIntent is a limit buy of 5 base units at 100.00, for a notional of 500.00.
func baselineIntent(t *testing.T) Intent {
	t.Helper()
	return Intent{
		CommandID:     id(t, contracts.PrefixCommand),
		CorrelationID: id(t, contracts.PrefixEvent),
		AccountID:     id(t, contracts.PrefixLedger),
		StrategyID:    id(t, contracts.PrefixStrategy),
		Instrument:    fixtureInstrument,
		Venue:         fixtureVenue,
		Market:        fixtureMarket,
		Direction:     DirBuy,
		OrderType:     fixtureOrderType,
		Quantity:      quantity(t, "BASE_ASSET", "5"),
		LimitPrice:    ptr(scaledMoney(t, fixtureCurrency, "100.00", 2)),
		IssuedAt:      ts(t, baselineIssued),
		Environment:   fixtureEnv,
	}
}

func ptr[T any](v T) *T { return &v }

// evaluate runs the engine on the baseline and fails the test if the inputs were not
// actually coherent. A helper that did this would let a broken fixture masquerade as a
// passing baseline, so it is the caller's job to notice.
func evaluate(t *testing.T, ic Intent, facts Facts, policy Policy, advisory Advisory) Result {
	t.Helper()
	result, err := Evaluate(ic, facts, policy, advisory, baselineLifetime)
	if err != nil {
		t.Fatalf("Evaluate returned an unexpected error: %v", err)
	}
	return result
}

// controlResult returns the outcome of one control.
func controlResult(t *testing.T, result Result, id ControlID) ControlResult {
	t.Helper()
	for _, c := range result.Controls {
		if c.ID == id {
			return c
		}
	}
	t.Fatalf("control %s is not present in the result", id)
	return ControlResult{}
}

// requireFailed asserts that exactly the named controls rejected, and reports anything else
// that also failed. Naming only the expected failures is what makes a test catch an
// unintended second failure instead of quietly tolerating one.
func requireFailed(t *testing.T, result Result, expected ...ControlID) {
	t.Helper()
	got := make(map[ControlID]bool, len(result.Failures))
	for _, f := range result.Failures {
		got[f.ID] = true
	}
	for _, want := range expected {
		if !got[want] {
			t.Errorf("expected control %s to reject, but it passed; result: %+v", want, result.Verdict)
		}
		delete(got, want)
	}
	for unexpected := range got {
		t.Errorf("control %s also rejected but was not expected: %q", unexpected,
			controlResult(t, result, unexpected).Reason)
	}
	if result.Verdict != Rejected {
		t.Errorf("expected verdict REJECTED, got %s", result.Verdict)
	}
	if result.Approval != nil {
		t.Error("a rejected result must not carry an approval")
	}
}

func requireApproved(t *testing.T, result Result) {
	t.Helper()
	if result.Verdict != Approved {
		reasons := make([]string, 0, len(result.Failures))
		for _, f := range result.Failures {
			reasons = append(reasons, string(f.ID)+": "+f.Reason)
		}
		t.Fatalf("expected APPROVED, got REJECTED: %s", strings.Join(reasons, "; "))
	}
	if result.Approval == nil {
		t.Fatal("an approved result must carry an approval")
	}
}
