package riskengine

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The baseline approves. Every test below changes exactly one input and asserts that exactly
// the expected control rejects, with a reason that names the cause.
//
// That pairing is the point. A risk gate whose tests only assert "something rejected" passes
// just as happily when the wrong control rejects, and a gate that rejects for the wrong reason
// is one edit away from rejecting for no reason at all.

func TestBaselineApproves(t *testing.T) {
	// If this fails, every other test in the file is measuring the wrong baseline.
	result := evaluate(t, baselineIntent(t), baselineFacts(t), baselinePolicy(t), Advisory{})
	requireApproved(t, result)
	if len(result.Controls) != len(mandatoryControls) {
		t.Errorf("expected %d control results, got %d", len(mandatoryControls), len(result.Controls))
	}
	if result.Failures != nil {
		t.Errorf("an approved result must carry no failures, got %d", len(result.Failures))
	}
}

func TestControlsAreReportedInTheFixedDeclaredOrder(t *testing.T) {
	result := evaluate(t, baselineIntent(t), baselineFacts(t), baselinePolicy(t), Advisory{})
	if len(result.Controls) != len(MandatoryControls()) {
		t.Fatalf("expected %d controls, got %d", len(MandatoryControls()), len(result.Controls))
	}
	for i, want := range MandatoryControls() {
		if result.Controls[i].ID != want {
			t.Errorf("control %d is %s, want %s; a report whose order varies is not reviewable",
				i, result.Controls[i].ID, want)
		}
	}
}

// rejectCase is one control's failing condition.
type rejectCase struct {
	name string
	// ids are the controls that must reject. More than one appears where a violation
	// genuinely couples controls: the notional is an input to both the notional and the
	// exposure control, so a command whose notional cannot be computed is refused by both.
	// Naming the coupling explicitly is better than tuning the fixture until only one fires,
	// which would hide a real dependency.
	ids    []ControlID
	mutate func(t *testing.T, ic *Intent, facts *Facts, policy *Policy)
	// wantsReason, when set, must appear in the rejection of ids[0]. A rejection a reviewer
	// cannot act on is only half a control.
	wantsReason string
}

func TestEachMandatoryControlRejectsItsOwnViolation(t *testing.T) {
	cases := []rejectCase{
		{
			name: "account disabled",
			ids:  []ControlID{ControlAccountAuthorization},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Account.Value.SubjectEnabled = false
			},
			wantsReason: "not enabled",
		},
		{
			name: "account state unreadable",
			// The rate control reads the same account fact, so losing that source stops both.
			ids: []ControlID{ControlAccountAuthorization, ControlRateLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Account = Unmeasured[AccountSnapshot]()
			},
		},
		{
			name: "command minted for another environment",
			ids:  []ControlID{ControlAccountAuthorization},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.Environment = "SIMULATION"
			},
			wantsReason: "scoped to",
		},
		{
			name: "strategy not deployed",
			ids:  []ControlID{ControlStrategyDeployment},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.StrategyStatus = StatusNotDeployed
			},
			wantsReason: "not deployed",
		},
		{
			name: "strategy status unknown",
			ids:  []ControlID{ControlStrategyDeployment},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.StrategyStatus = StatusUnknown
			},
			wantsReason: "not treated as deployed",
		},
		{
			name: "instrument not eligible",
			ids:  []ControlID{ControlInstrumentEligibility},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Instrument.Value.Eligible = false
			},
			wantsReason: "not eligible",
		},
		{
			name: "instrument not in the policy",
			ids:  []ControlID{ControlInstrumentEligibility},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.Instrument = "ETH-USDT"
			},
			wantsReason: "permitted instruments",
		},
		{
			name: "market not in the policy",
			ids:  []ControlID{ControlInstrumentEligibility},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.Market = "PERPETUAL"
			},
			wantsReason: "permitted markets",
		},
		{
			name: "order type not permitted",
			ids:  []ControlID{ControlInstrumentEligibility},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.OrderType = "STOP_LIMIT"
			},
			wantsReason: "order type",
		},
		{
			name: "direction not permitted",
			ids:  []ControlID{ControlInstrumentEligibility},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				// The baseline order is a BUY, so permitting only SELL is what makes the
				// direction unlisted.
				policy.PermittedDirections = []string{string(DirSell)}
			},
			wantsReason: "direction",
		},
		{
			name: "venue halted",
			ids:  []ControlID{ControlVenueAvailability},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Venue = VenueHalted
			},
			wantsReason: "halted",
		},
		{
			name: "venue unavailable",
			ids:  []ControlID{ControlVenueAvailability},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Venue = VenueUnavailable
			},
		},
		{
			name: "venue not in the policy",
			ids:  []ControlID{ControlVenueAvailability},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.Venue = "VENUE_B"
			},
			wantsReason: "permitted venues",
		},
		{
			name: "venue listed in policy but unknown to the platform",
			ids:  []ControlID{ControlVenueAvailability},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.VenueListed = false
			},
			wantsReason: "not known to the platform",
		},
		{
			name: "price carries more precision than the instrument declares",
			ids:  []ControlID{ControlPricePrecision},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.LimitPrice = ptr(scaledMoney(t, fixtureCurrency, "100.005", 3))
			},
			wantsReason: "precision",
		},
		{
			name: "quantity carries more precision than the instrument declares",
			ids:  []ControlID{ControlPricePrecision},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.Quantity = quantity(t, "BASE_ASSET", "5.123456789")
			},
			wantsReason: "precision",
		},
		{
			name: "instrument and venue disagree on precision",
			ids:  []ControlID{ControlPricePrecision},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Market.Value.Precision = 4
			},
			wantsReason: "disagreeing",
		},
		{
			name: "notional over the limit",
			ids:  []ControlID{ControlNotionalLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				// The notional is raised through price and size together so the position
				// control stays satisfied; a case that tripped two limits would prove nothing
				// about the notional control in isolation.
				ic.LimitPrice = ptr(scaledMoney(t, fixtureCurrency, "1000.00", 2))
				ic.Quantity = quantity(t, "BASE_ASSET", "15")
			},
			wantsReason: "notional",
		},
		{
			name: "market order with no price cannot be notional-bounded",
			// The exposure control computes the notional too, so an uncomputable notional
			// stops it as well.
			ids: []ControlID{ControlNotionalLimits, ControlExposureLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.OrderType = "MARKET"
				ic.LimitPrice = nil
			},
			wantsReason: "priced against the venue",
		},
		{
			name: "notional denominated in another currency",
			// Exposure adds the notional to a USDT gross exposure, so a EUR notional is a
			// currency mismatch there too. Neither control converts.
			ids: []ControlID{ControlNotionalLimits, ControlExposureLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.LimitPrice = ptr(scaledMoney(t, "EUR", "100.00", 2))
			},
			wantsReason: "not a conversion",
		},
		{
			name: "resulting position over the limit",
			ids:  []ControlID{ControlPositionLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				ic.Quantity = quantity(t, "BASE_ASSET", "95")
			},
			wantsReason: "exceeds",
		},
		{
			name: "gross exposure over the limit",
			ids:  []ControlID{ControlExposureLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Position.Value.GrossExposure = money(t, fixtureCurrency, "49900.00")
			},
			wantsReason: "gross exposure",
		},
		{
			name: "net exposure over the limit",
			ids:  []ControlID{ControlExposureLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Position.Value.NetExposure = money(t, fixtureCurrency, "49900.00")
			},
			wantsReason: "net exposure",
		},
		{
			name: "concentration over the limit",
			ids:  []ControlID{ControlConcentrationLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Position.Value.Concentration = contracts.MustParseDecimal("0.30")
			},
			wantsReason: "concentration",
		},
		{
			name: "leverage over the limit",
			ids:  []ControlID{ControlLeverageLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Position.Value.Leverage = contracts.MustParseDecimal("3.0")
			},
			wantsReason: "leverage",
		},
		{
			name: "realised loss over the limit",
			ids:  []ControlID{ControlLossDrawdown},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Position.Value.RealisedLossInWindow = money(t, fixtureCurrency, "-1500.00")
			},
			wantsReason: "realised loss",
		},
		{
			name: "drawdown over the threshold",
			ids:  []ControlID{ControlLossDrawdown},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Position.Value.Drawdown = contracts.MustParseDecimal("0.20")
			},
			wantsReason: "drawdown",
		},
		{
			name: "market data older than the freshness limit",
			ids:  []ControlID{ControlMarketDataStale},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Market.Value.ObservedAt = ts(t, "2026-03-01T11:59:00.000000000Z")
			},
			wantsReason: "freshness",
		},
		{
			name: "market data dated in the future",
			ids:  []ControlID{ControlMarketDataStale},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Market.Value.ObservedAt = ts(t, "2026-03-01T12:00:30.000000000Z")
			},
			wantsReason: "disagrees with itself",
		},
		{
			name: "command duplicates an open order",
			ids:  []ControlID{ControlDuplicateOrder},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.DuplicateOf = "ord_00000000000000000000000000"
			},
			wantsReason: "duplicates open order",
		},
		{
			name: "material reconciliation case unresolved",
			ids:  []ControlID{ControlDuplicateOrder},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.ReconciliationOpen = true
			},
			wantsReason: "unresolved",
		},
		{
			name: "order rate at the limit counts this order past it",
			ids:  []ControlID{ControlRateLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				// 100 orders are already in the window and the limit is 100, so counting
				// this command is what makes it 101. Comparing before adding would permit
				// exactly one order past every boundary.
				facts.Account.Value.OrdersInWindow = contracts.MustParseDecimal("100")
			},
			wantsReason: "order rate",
		},
		{
			name: "cancel rate over the limit",
			ids:  []ControlID{ControlRateLimits},
			mutate: func(t *testing.T, ic *Intent, facts *Facts, policy *Policy) {
				facts.Account.Value.CancelsInWindow = contracts.MustParseDecimal("101")
			},
			wantsReason: "cancel rate",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			ic := baselineIntent(t)
			facts := baselineFacts(t)
			policy := baselinePolicy(t)
			tc.mutate(t, &ic, &facts, &policy)

			result := evaluate(t, ic, facts, policy, Advisory{})
			requireFailed(t, result, tc.ids...)

			primary := controlResult(t, result, tc.ids[0])
			if primary.Outcome != ControlFailed && primary.Outcome != ControlUnavailable {
				t.Errorf("outcome is %s, expected a non-passing outcome", primary.Outcome)
			}
			if tc.wantsReason != "" && !strings.Contains(primary.Reason, tc.wantsReason) {
				t.Errorf("reason should mention %q, got: %s", tc.wantsReason, primary.Reason)
			}
			// A source-unavailable outcome legitimately records no observed value, because
			// there is no value to record. A genuine violation must record what was measured.
			if primary.Outcome == ControlFailed && primary.Observed == "" {
				t.Errorf("a violated control must record what it observed so a reviewer can " +
					"see the measured value rather than only that it failed")
			}
		})
	}
}

func TestEveryMandatoryControlHasATestCase(t *testing.T) {
	// Coverage of the control registry is a property worth asserting directly: a new control
	// added to the list without a test would otherwise sail through review, because nothing
	// would exercise its rejection path.
	covered := map[ControlID]bool{
		ControlAccountAuthorization:  true,
		ControlStrategyDeployment:    true,
		ControlInstrumentEligibility: true,
		ControlVenueAvailability:     true,
		ControlPricePrecision:        true,
		ControlNotionalLimits:        true,
		ControlPositionLimits:        true,
		ControlExposureLimits:        true,
		ControlConcentrationLimits:   true,
		ControlLeverageLimits:        true,
		ControlLossDrawdown:          true,
		ControlMarketDataStale:       true,
		ControlDuplicateOrder:        true,
		ControlRateLimits:            true,
		ControlHaltState:             true, // covered in halt_test.go
	}
	for _, id := range MandatoryControls() {
		if !covered[id] {
			t.Errorf("mandatory control %s has no rejection-path test", id)
		}
	}
	if len(controlRegistry) != len(mandatoryControls) {
		t.Errorf("the registry has %d entries but %d controls are mandatory",
			len(controlRegistry), len(mandatoryControls))
	}
	for i, entry := range controlRegistry {
		if entry.id != mandatoryControls[i] {
			t.Errorf("registry position %d is %s but the mandatory order says %s; the two must "+
				"agree or the report order is not the declared order", i, entry.id, mandatoryControls[i])
		}
	}
}
