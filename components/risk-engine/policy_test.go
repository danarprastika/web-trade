package riskengine

import (
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// A control may be quantitative or qualitative, and the engine decides which by the control's
// id rather than by whichever fields happen to be populated. These tests pin that decision,
// because getting it wrong is permissive in one direction and confusing in the other.

func TestControlValidAcceptsWellFormedControls(t *testing.T) {
	policy := baselinePolicy(t)
	for _, id := range MandatoryControls() {
		control := policy.Controls[id]
		if err := control.valid(); err != nil {
			t.Errorf("baseline control %s should be valid: %v", id, err)
		}
	}
}

func TestQuantitativeControlRequiresAThreshold(t *testing.T) {
	policy := baselinePolicy(t)
	control := policy.Controls[ControlNotionalLimits]
	control.Amount = nil

	err := control.valid()
	if err == nil {
		t.Fatal("a quantitative control with no threshold must be rejected, because an absent " +
			"limit is an unlimited allowance")
	}
	if !strings.Contains(err.Error(), "not an unlimited control") {
		t.Errorf("error should name the failure mode, got: %v", err)
	}
}

func TestQualitativeControlMustDeclareNoThreshold(t *testing.T) {
	policy := baselinePolicy(t)
	control := policy.Controls[ControlHaltState]
	control.NoThreshold = false

	err := control.valid()
	if err == nil {
		t.Fatal("a qualitative control must declare NoThreshold explicitly, so that an " +
			"omitted control is never silently read as unlimited")
	}
	if !strings.Contains(err.Error(), "declare NoThreshold") {
		t.Errorf("error should require the explicit declaration, got: %v", err)
	}
}

func TestQualitativeControlRejectsAnUnusedThreshold(t *testing.T) {
	policy := baselinePolicy(t)
	control := policy.Controls[ControlHaltState]

	// A threshold on a qualitative control is never read. Accepting one would leave a policy
	// author believing a limit is enforced when nothing compares against it.
	amount := money(t, fixtureCurrency, "1.00")
	control.Amount = &amount
	control.NoThreshold = false

	err := control.valid()
	if err == nil {
		t.Fatal("a qualitative control carrying a threshold must be rejected")
	}
	if !strings.Contains(err.Error(), "never read") {
		t.Errorf("error should explain the threshold is never enforced, got: %v", err)
	}
}

func TestControlRejectsMoreThanOneDenomination(t *testing.T) {
	policy := baselinePolicy(t)
	control := policy.Controls[ControlNotionalLimits]
	qty := quantity(t, "BASE_ASSET", "1")
	control.Quantity = &qty

	err := control.valid()
	if err == nil {
		t.Fatal("a control denominated in two currencies or units at once must be rejected")
	}
	if !strings.Contains(err.Error(), "more than one denomination") {
		t.Errorf("error should name the failure mode, got: %v", err)
	}
}

func TestControlRejectsContradictoryQuantitativeDeclaration(t *testing.T) {
	policy := baselinePolicy(t)
	control := policy.Controls[ControlLeverageLimits]
	control.NoThreshold = true

	err := control.valid()
	if err == nil {
		t.Fatal("a quantitative control that also declares no threshold must be rejected")
	}
	if !strings.Contains(err.Error(), "contradict") {
		t.Errorf("error should name the contradiction, got: %v", err)
	}
}

func TestControlRejectsUnstatedBoundaryAndMissingBehaviour(t *testing.T) {
	policy := baselinePolicy(t)

	control := policy.Controls[ControlNotionalLimits]
	control.Boundary = ""
	if err := control.valid(); err == nil {
		t.Error("an unstated boundary must be rejected rather than assumed inclusive or exclusive")
	}

	control = policy.Controls[ControlNotionalLimits]
	control.OnMissing = ""
	if err := control.valid(); err == nil {
		t.Error("an unstated missing-data behaviour must be rejected rather than assumed")
	}

	control = policy.Controls[ControlNotionalLimits]
	control.Scope = "SOMETHING_ELSE"
	if err := control.valid(); err == nil {
		t.Error("an unknown scope must be rejected")
	}
}

func TestControlDescribeNamesItsDenomination(t *testing.T) {
	policy := baselinePolicy(t)
	cases := map[ControlID]string{
		ControlNotionalLimits: "10000.00 USDT",
		ControlPositionLimits: "100 BASE_ASSET",
		ControlLeverageLimits: "2.0 dimensionless",
		ControlHaltState:      "no numeric threshold (qualitative control)",
	}
	for id, want := range cases {
		if got := policy.Controls[id].Describe(); got != want {
			t.Errorf("control %s describes as %q, want %q", id, got, want)
		}
	}
}

func TestPolicyValidationRejectsAMissingControl(t *testing.T) {
	policy := baselinePolicy(t)
	delete(policy.Controls, ControlLeverageLimits)

	_, err := Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime)
	if err == nil {
		t.Fatal("a policy missing a mandatory control must be rejected, because the engine " +
			"supplies no default threshold")
	}
	if !strings.Contains(err.Error(), "missing 1 mandatory control") {
		t.Errorf("error should report the missing control, got: %v", err)
	}
	if !strings.Contains(err.Error(), string(ControlLeverageLimits)) {
		t.Errorf("error should name the missing control, got: %v", err)
	}
}

func TestPolicyValidationReportsEveryMissingControlAtOnce(t *testing.T) {
	// A caller fixing a policy should learn about every gap in one refusal, not one control
	// per deployment attempt.
	policy := baselinePolicy(t)
	delete(policy.Controls, ControlLeverageLimits)
	delete(policy.Controls, ControlConcentrationLimits)

	_, err := Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime)
	if err == nil {
		t.Fatal("a policy missing mandatory controls must be rejected")
	}
	if !strings.Contains(err.Error(), "missing 2 mandatory control") {
		t.Errorf("error should report both missing controls, got: %v", err)
	}
}

func TestPolicyValidationRejectsEmptyAllowLists(t *testing.T) {
	// An empty allow-list denies everything rather than permitting it, but the engine refuses
	// to run at all, because a policy author who has enumerated no venues has not configured
	// this control.
	policy := baselinePolicy(t)
	policy.PermittedVenues = nil

	_, err := Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime)
	if err == nil {
		t.Fatal("an empty allow-list must be rejected rather than treated as a live list")
	}
	if !strings.Contains(err.Error(), "empty permitted_venues allow-list") {
		t.Errorf("error should name the empty list, got: %v", err)
	}
}

func TestPolicyValidationRejectsAnUnsetDrawdownThreshold(t *testing.T) {
	policy := baselinePolicy(t)
	policy.DrawdownThreshold = contracts.Decimal{}

	_, err := Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime)
	if err == nil {
		t.Fatal("an unset drawdown threshold must be rejected, because absent means unbounded")
	}
	if !strings.Contains(err.Error(), "unbounded drawdown allowance") {
		t.Errorf("error should explain the consequence, got: %v", err)
	}
}

func TestPolicyValidationRejectsNonPositiveWindows(t *testing.T) {
	for name, mutate := range map[string]func(*Policy){
		"loss window":     func(p *Policy) { p.LossWindow = 0 },
		"drawdown window": func(p *Policy) { p.DrawdownWindow = 0 },
		"rate window":     func(p *Policy) { p.RateWindow = 0 },
		"market data age": func(p *Policy) { p.MarketDataMaxAge = 0 },
	} {
		t.Run(name, func(t *testing.T) {
			policy := baselinePolicy(t)
			mutate(&policy)
			if _, err := Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime); err == nil {
				t.Fatalf("a non-positive %s must be rejected", name)
			}
		})
	}
}

func TestPolicyValidationRequiresRevisionAndEnvironment(t *testing.T) {
	policy := baselinePolicy(t)
	policy.Revision = ""
	if _, err := Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime); err == nil {
		t.Error("a policy without a revision must be rejected, because a decision cannot be traced to it")
	}

	policy = baselinePolicy(t)
	policy.Environment = ""
	if _, err := Evaluate(baselineIntent(t), baselineFacts(t), policy, Advisory{}, baselineLifetime); err == nil {
		t.Error("a policy without an environment must be rejected")
	}
}

func TestNonPositiveApprovalLifetimeIsRejected(t *testing.T) {
	// An approval that does not expire is not short-lived, so the lifetime is a validated
	// input rather than a constant the engine assumes.
	for _, lifetime := range []time.Duration{0, -time.Second} {
		_, err := Evaluate(baselineIntent(t), baselineFacts(t), baselinePolicy(t), Advisory{}, lifetime)
		if err == nil {
			t.Errorf("approval lifetime %s must be rejected", lifetime)
			continue
		}
		if !strings.Contains(err.Error(), "not short-lived") {
			t.Errorf("error should explain the consequence, got: %v", err)
		}
	}
}
