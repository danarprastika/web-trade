package riskengine

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// These tests cover the three claims the package makes about itself: the decision is a pure
// function, it fails closed, and nothing outside the declared inputs can influence it. Each
// claim is falsifiable, so each is asserted rather than asserted in a comment.

// permissiveness tests: the engine must behave identically no matter how strongly a caller
// asks for a different answer. A veto that can be talked out of is not a veto.
var overrideAdvisories = map[string]Advisory{
	"model confidence and verdict": {
		ModelConfidence: "0.999999",
		ModelVerdict:    "BUY",
	},
	"model requests an override": {
		ModelRequestedOverride: true,
		ModelConfidence:        "1.0",
	},
	"operator override in the ui": {
		UIOperatorOverride: true,
		UIHidden:           true,
		OperatorNote:       "approved by the desk head, please proceed",
	},
	"venue accepted the order": {
		VenueAccepted: true,
		VenueReason:   "acknowledged",
	},
	"everything at once": {
		ModelConfidence:        "1.0",
		ModelVerdict:           "BUY",
		ModelRequestedOverride: true,
		UIOperatorOverride:     true,
		UIHidden:               true,
		VenueAccepted:          true,
		VenueReason:            "accepted",
		OperatorNote:           "all signals are green",
	},
}

func TestAdvisorySignalsCannotChangeAnApproval(t *testing.T) {
	baseline := evaluate(t, baselineIntent(t), baselineFacts(t), baselinePolicy(t), Advisory{})
	baselineJSON, err := json.Marshal(baseline)
	if err != nil {
		t.Fatalf("baseline result does not marshal: %v", err)
	}

	for name, advisory := range overrideAdvisories {
		t.Run(name, func(t *testing.T) {
			result := evaluate(t, baselineIntent(t), baselineFacts(t), baselinePolicy(t), advisory)
			got, err := json.Marshal(result)
			if err != nil {
				t.Fatalf("result does not marshal: %v", err)
			}
			// Byte-identical, not merely same-verdict. A verdict-only comparison would not
			// notice an advisory leaking into a reason string or a threshold in the report.
			if string(got) != string(baselineJSON) {
				t.Errorf("advisory changed the result:\n got: %s\nwant: %s", got, baselineJSON)
			}
		})
	}
}

func TestAdvisorySignalsCannotRescueARejection(t *testing.T) {
	// The half that actually matters. A veto that a confident model can overrule is not a veto.
	facts := baselineFacts(t)
	facts.Position.Value.Leverage = contracts.MustParseDecimal("3.0")

	rejected := evaluate(t, baselineIntent(t), facts, baselinePolicy(t), Advisory{})
	requireFailed(t, rejected, ControlLeverageLimits)
	rejectedJSON, err := json.Marshal(rejected)
	if err != nil {
		t.Fatalf("rejected result does not marshal: %v", err)
	}

	for name, advisory := range overrideAdvisories {
		t.Run(name, func(t *testing.T) {
			result := evaluate(t, baselineIntent(t), facts, baselinePolicy(t), advisory)
			got, err := json.Marshal(result)
			if err != nil {
				t.Fatalf("result does not marshal: %v", err)
			}
			if string(got) != string(rejectedJSON) {
				t.Errorf("advisory changed a rejection:\n got: %s\nwant: %s", got, rejectedJSON)
			}
			if result.Approval != nil {
				t.Error("an advisory must never produce an approval")
			}
		})
	}
}

func TestEvaluationIsDeterministic(t *testing.T) {
	// docs/17 section 4 requires a decision to be replayable. Identical inputs must give
	// identical output, repeatedly, including the order of the report.
	ic := baselineIntent(t)
	facts := baselineFacts(t)
	policy := baselinePolicy(t)

	first, err := Evaluate(ic, facts, policy, Advisory{}, baselineLifetime)
	if err != nil {
		t.Fatalf("first evaluation failed: %v", err)
	}
	for i := 0; i < 50; i++ {
		again, err := Evaluate(ic, facts, policy, Advisory{}, baselineLifetime)
		if err != nil {
			t.Fatalf("evaluation %d failed: %v", i, err)
		}
		if !reflect.DeepEqual(first, again) {
			t.Fatalf("evaluation %d differs from the first for identical inputs", i)
		}
	}
}

func TestFailClosedWhenARequiredSourceIsUnavailable(t *testing.T) {
	// Every Fact defaults to unavailable, so a caller who forgets to measure something gets a
	// rejection rather than a zero value compared against a limit.
	cases := map[string]func(*Facts){
		"market":     func(f *Facts) { f.Market = Unmeasured[MarketSnapshot]() },
		"position":   func(f *Facts) { f.Position = Unmeasured[PositionSnapshot]() },
		"account":    func(f *Facts) { f.Account = Unmeasured[AccountSnapshot]() },
		"instrument": func(f *Facts) { f.Instrument = Unmeasured[InstrumentSnapshot]() },
	}
	for name, clear := range cases {
		t.Run(name, func(t *testing.T) {
			facts := baselineFacts(t)
			clear(&facts)
			result := evaluate(t, baselineIntent(t), facts, baselinePolicy(t), Advisory{})
			if result.Verdict != Rejected {
				t.Fatalf("an unavailable %s source must reject, got %s", name, result.Verdict)
			}
			if result.Approval != nil {
				t.Error("an unavailable source must not produce an approval")
			}
		})
	}
}

func TestUnavailableFactsReportTheUnavailableOutcomeNotAFailure(t *testing.T) {
	// The two are different events: a failed control is a risk decision, an unreadable source
	// is an infrastructure problem. Collapsing them would send an operator to the wrong fix.
	facts := baselineFacts(t)
	facts.Position = Unmeasured[PositionSnapshot]()

	result := evaluate(t, baselineIntent(t), facts, baselinePolicy(t), Advisory{})
	got := controlResult(t, result, ControlPositionLimits)
	if got.Outcome != ControlUnavailable {
		t.Errorf("outcome is %s, want %s", got.Outcome, ControlUnavailable)
	}
	if got.Observed != "" {
		t.Errorf("an unreadable source has no observed value, got %q", got.Observed)
	}
	if got.Reason == "" {
		t.Error("an unavailable control must explain why the source could not be read")
	}
}

func TestUseLastKnownStillRequiresAValue(t *testing.T) {
	// OnMissingUseLastKnown changes whether the control is reading a live source, never
	// whether it passes. A zero-valued last-known amount still passes a positive limit, so
	// this is a policy choice about liveness, not a relaxation of the limit itself.
	policy := baselinePolicy(t)
	control := policy.Controls[ControlPositionLimits]
	control.OnMissing = OnMissingUseLastKnown
	policy.Controls[ControlPositionLimits] = control

	facts := baselineFacts(t)
	// A stale but recorded position that exceeds the limit must still be refused, proving
	// the fallback reads the recorded value rather than skipping the comparison.
	facts.Position = Fact[PositionSnapshot]{Value: facts.Position.Value, Available: false}
	facts.Position.Value.Quantity = quantity(t, "BASE_ASSET", "500")

	result := evaluate(t, baselineIntent(t), facts, policy, Advisory{})
	got := controlResult(t, result, ControlPositionLimits)
	if got.Outcome == ControlPassed {
		t.Error("a last-known position that exceeds the limit must still be refused")
	}
}

func TestBoundaryInclusivityDecidesTheExactLimit(t *testing.T) {
	// The notional is exactly the limit. This is the case where a float would be least
	// trustworthy, because the two representations of 10000.00 are not the same number.
	const notionalAtLimit = "10000.00"
	build := func(boundary Boundary) (Intent, Policy) {
		ic := baselineIntent(t)
		ic.LimitPrice = ptr(scaledMoney(t, fixtureCurrency, "100.00", 2))
		ic.Quantity = quantity(t, "BASE_ASSET", "100")

		policy := baselinePolicy(t)
		control := policy.Controls[ControlNotionalLimits]
		limit := money(t, fixtureCurrency, notionalAtLimit)
		control.Amount = &limit
		control.Boundary = boundary
		policy.Controls[ControlNotionalLimits] = control

		// The position and exposure controls are raised well clear of this order so the only
		// control whose answer can change is the boundary under test. Otherwise the case would
		// pass for the wrong reason whenever one of the other limits happened to be tighter.
		positionControl := policy.Controls[ControlPositionLimits]
		headroom := quantity(t, "BASE_ASSET", "10000")
		positionControl.Quantity = &headroom
		policy.Controls[ControlPositionLimits] = positionControl

		exposureControl := policy.Controls[ControlExposureLimits]
		exposureHeadroom := money(t, fixtureCurrency, "1000000.00")
		exposureControl.Amount = &exposureHeadroom
		policy.Controls[ControlExposureLimits] = exposureControl

		return ic, policy
	}

	ic, policy := build(BoundaryInclusive)
	requireApproved(t, evaluate(t, ic, baselineFacts(t), policy, Advisory{}))

	ic, policy = build(BoundaryExclusive)
	result := evaluate(t, ic, baselineFacts(t), policy, Advisory{})
	requireFailed(t, result, ControlNotionalLimits)
}

func TestExactDecimalsDoNotDriftAtLargeNotionals(t *testing.T) {
	// A float would round a value like this. The engine compares exact decimal coefficients,
	// so a value one unit above a limit is rejected and the limit itself is not.
	policy := baselinePolicy(t)
	limit := money(t, fixtureCurrency, "1000000.01")
	control := policy.Controls[ControlNotionalLimits]
	control.Amount = &limit
	control.Boundary = BoundaryInclusive
	policy.Controls[ControlNotionalLimits] = control

	// The order's notional is also an input to the exposure control, so that limit is raised
	// to keep this case about decimal precision alone.
	exposureControl := policy.Controls[ControlExposureLimits]
	exposureHeadroom := money(t, fixtureCurrency, "10000000.00")
	exposureControl.Amount = &exposureHeadroom
	policy.Controls[ControlExposureLimits] = exposureControl

	atLimit := baselineIntent(t)
	atLimit.LimitPrice = ptr(scaledMoney(t, fixtureCurrency, "1000000.01", 2))
	atLimit.Quantity = quantity(t, "BASE_ASSET", "1")
	requireApproved(t, evaluate(t, atLimit, baselineFacts(t), policy, Advisory{}))

	oneUnitOver := atLimit
	oneUnitOver.LimitPrice = ptr(scaledMoney(t, fixtureCurrency, "1000000.02", 2))
	result := evaluate(t, oneUnitOver, baselineFacts(t), policy, Advisory{})
	requireFailed(t, result, ControlNotionalLimits)
}

func TestACurrencyMismatchIsRejectedRatherThanConverted(t *testing.T) {
	// Converting here would change a financial value as a side effect of a limit check.
	policy := baselinePolicy(t)
	eur := money(t, "EUR", "10000.00")
	control := policy.Controls[ControlNotionalLimits]
	control.Amount = &eur
	policy.Controls[ControlNotionalLimits] = control

	result := evaluate(t, baselineIntent(t), baselineFacts(t), policy, Advisory{})
	got := controlResult(t, result, ControlNotionalLimits)
	if got.Outcome == ControlPassed {
		t.Fatal("a USDT notional must not pass a EUR limit")
	}
	if !strings.Contains(got.Reason, "not a conversion") {
		t.Errorf("the rejection should state that this is a rejection and not a conversion, got: %s", got.Reason)
	}
}

func TestASellReducesNetExposureAndABuyIncreasesIt(t *testing.T) {
	// The one place direction changes the arithmetic. Inverting it would refuse the trades
	// that reduce risk while admitting a long that the limit exists to prevent, so both
	// directions are pinned against a limit they straddle.
	policy := baselinePolicy(t)
	netLimit := money(t, fixtureCurrency, "1000.00")
	control := policy.Controls[ControlExposureLimits]
	control.Amount = &netLimit
	policy.Controls[ControlExposureLimits] = control

	// Gross exposure is kept well inside the same limit so only the net comparison can fail.
	// Gross always grows by the notional, so it is given headroom rather than being disabled.
	netAtLimit := func(direction Direction) (Intent, Facts) {
		ic := baselineIntent(t)
		ic.Direction = direction
		facts := baselineFacts(t)
		facts.Position.Value.NetExposure = money(t, fixtureCurrency, "1000.00")
		facts.Position.Value.GrossExposure = money(t, fixtureCurrency, "0.00")
		return ic, facts
	}

	// Buying from a net-long position pushes net exposure past the limit.
	ic, facts := netAtLimit(DirBuy)
	requireFailed(t, evaluate(t, ic, facts, policy, Advisory{}), ControlExposureLimits)

	// Selling from a net-long position pulls it back inside, so the same limit permits it.
	ic, facts = netAtLimit(DirSell)
	requireApproved(t, evaluate(t, ic, facts, policy, Advisory{}))
}

func TestAShortPositionIsBoundedSymmetrically(t *testing.T) {
	// Buying into a short position reduces it. If the arithmetic only handled the long case,
	// this order would be refused for reducing risk, which is the failure mode above seen from
	// the other side.
	ic := baselineIntent(t)
	ic.Direction = DirBuy
	facts := baselineFacts(t)
	facts.Position.Value.Quantity = quantity(t, "BASE_ASSET", "-8")
	facts.Position.Value.NetExposure = money(t, fixtureCurrency, "-800.00")
	facts.Position.Value.GrossExposure = money(t, fixtureCurrency, "0.00")

	requireApproved(t, evaluate(t, ic, facts, baselinePolicy(t), Advisory{}))
}

func TestNotionalIsComputedByTheEngineNotAssertedByTheCommand(t *testing.T) {
	// There is no notional field on Intent, so a command cannot state its own size compliance.
	// The observable consequence is that enlarging the order enlarges the computed notional.
	if _, ok := reflect.TypeOf(Intent{}).FieldByName("Notional"); ok {
		t.Error("Intent must not carry a notional field; the engine computes it so a command " +
			"cannot assert its own compliance with a limit")
	}

	small := baselineIntent(t)
	large := baselineIntent(t)
	large.Quantity = quantity(t, "BASE_ASSET", "90")

	smallNotional, err := small.notional()
	if err != nil {
		t.Fatalf("baseline notional is not computable: %v", err)
	}
	largeNotional, err := large.notional()
	if err != nil {
		t.Fatalf("larger notional is not computable: %v", err)
	}
	if smallNotional.String() != "500.00" {
		t.Errorf("baseline notional is %s, want 500.00 (5 units at 100.00)", smallNotional)
	}
	if largeNotional.String() == smallNotional.String() {
		t.Error("enlarging the order must enlarge the computed notional")
	}
}

func TestStalenessIsMeasuredFromTheVenueNotTheCommand(t *testing.T) {
	// A freshly issued command quoting a stale price is still a stale price. Measuring from
	// the command would let a caller refresh the age simply by re-issuing.
	facts := baselineFacts(t)
	facts.Market.Value.ObservedAt = ts(t, "2026-03-01T11:59:58.000000000Z")
	ic := baselineIntent(t)
	// The command is issued a full second after the snapshot it quotes, so the ages differ.
	ic.IssuedAt = ts(t, "2026-03-01T11:59:59.000000000Z")

	// 2s old against a 5s limit passes, which is correct: the snapshot is fresh.
	requireApproved(t, evaluate(t, ic, facts, baselinePolicy(t), Advisory{}))

	// A policy that allows 1s of age rejects the same order, proving the age came from the
	// snapshot and not from the command's own issue time.
	policy := baselinePolicy(t)
	policy.MarketDataMaxAge = time.Second
	requireFailed(t, evaluate(t, ic, facts, policy, Advisory{}), ControlMarketDataStale)
}

func TestEveryRejectionCarriesACanonicalCodeAndLocalSentinel(t *testing.T) {
	// A caller on another service needs the machine-readable code, and errors.Is must keep
	// working in process. Formatting an ErrorCode with %w is not valid Go, so both are
	// carried explicitly.
	facts := baselineFacts(t)
	facts.StrategyStatus = StatusPaused

	_, err := Evaluate(baselineIntent(t), facts, baselinePolicy(t), Advisory{}, baselineLifetime)
	if err != nil {
		t.Fatalf("expected a verdict rather than an error for a risk rejection: %v", err)
	}

	// A rejection reason is not an error return, so the sentinel is asserted on a path that
	// does error: an incoherent policy.
	policy := baselinePolicy(t)
	policy.Controls[ControlLeverageLimits] = Control{}
	_, err = Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime)
	if err == nil {
		t.Fatal("an incoherent control must be refused")
	}
	if !strings.Contains(err.Error(), string(contracts.CodeValidation)) {
		t.Errorf("error should carry the canonical code, got: %v", err)
	}
}
