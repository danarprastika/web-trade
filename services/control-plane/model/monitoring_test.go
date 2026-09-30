package model

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

func fullPolicies(t *testing.T) []MonitoringPolicy {
	t.Helper()
	specs := []struct {
		metric     Metric
		threshold  string
		comparison string
	}{
		{MetricInputDrift, "0.20", CompareAbove},
		{MetricOutputDrift, "0.25", CompareAbove},
		{MetricPredictionStab, "0.70", CompareBelow},
		{MetricStrategyPerf, "-0.05", CompareBelow},
		{MetricRejectionRate, "0.40", CompareAbove},
		{MetricDataFreshness, "5", CompareBelow},
		{MetricServiceHealth, "0.99", CompareBelow},
	}
	out := make([]MonitoringPolicy, 0, len(specs))
	for _, s := range specs {
		p, err := NewMonitoringPolicy(s.metric, s.threshold, s.comparison, true)
		if err != nil {
			t.Fatalf("NewMonitoringPolicy(%s): %v", s.metric, err)
		}
		out = append(out, p)
	}
	return out
}

func mustMonitor(t *testing.T) *Monitor {
	t.Helper()
	m, err := NewMonitor(mustModelID(t), fullPolicies(t))
	if err != nil {
		t.Fatalf("NewMonitor: %v", err)
	}
	return m
}

func observation(metric Metric, value string, breached bool) Observation {
	return Observation{Metric: metric, Value: value, Breached: breached}
}

// TestACompleteMonitoringSetIsAccepted is the positive control.
func TestACompleteMonitoringSetIsAccepted(t *testing.T) {
	if _, err := NewMonitor(mustModelID(t), fullPolicies(t)); err != nil {
		t.Fatalf("a monitoring set covering every docs/07 signal was refused: %v", err)
	}
}

// TestIncompleteMonitoringSetsAreRefused is the property that matters here.
//
// A monitor that watches rejection rate but not data freshness will report a model as
// healthy while it is being fed stale inputs, and the health report is what an operator
// acts on. The test removes each required signal in turn so that the refusal is attributed
// to the specific gap rather than to a count.
func TestIncompleteMonitoringSetsAreRefused(t *testing.T) {
	for _, missing := range AllMetrics() {
		var kept []MonitoringPolicy
		for _, p := range fullPolicies(t) {
			if p.Metric != missing {
				kept = append(kept, p)
			}
		}
		_, err := NewMonitor(mustModelID(t), kept)
		if err == nil {
			t.Errorf("a monitoring set with no policy for %s was accepted", missing)
			continue
		}
		if !strings.Contains(err.Error(), string(missing)) {
			t.Errorf("the refusal for a missing %s policy does not name it: %v", missing, err)
		}
	}
}

// TestAPolicyMayNotDisableAutomaticPause: docs/07 section 4 requires a breached threshold
// to automatically pause the affected deployment, and the "automatic" is the part with
// teeth.
func TestAPolicyMayNotDisableAutomaticPause(t *testing.T) {
	_, err := NewMonitoringPolicy(MetricRejectionRate, "0.40", CompareAbove, false)
	if err == nil {
		t.Error("a policy that does not pause automatically was accepted; a breached " +
			"threshold must pause the affected deployment")
	}
}

// TestComparisonDirectionMustBeExplicit: freshness and prediction stability breach below
// their thresholds and rejection rate breaches above, so an implicit "greater than" would
// invert half the policy set.
func TestComparisonDirectionMustBeExplicit(t *testing.T) {
	for _, bad := range []string{"", "GREATER", "less"} {
		if _, err := NewMonitoringPolicy(MetricDataFreshness, "5", bad, true); err == nil {
			t.Errorf("a policy with comparison %q was accepted", bad)
		}
	}
	for _, ok := range []string{CompareAbove, CompareBelow} {
		if _, err := NewMonitoringPolicy(MetricRejectionRate, "0.40", ok, true); err != nil {
			t.Errorf("a policy with valid comparison %q was refused: %v", ok, err)
		}
	}
}

// TestAnUnknownMetricIsRejected: an unmonitored signal must not be accepted as one.
func TestAnUnknownMetricIsRejected(t *testing.T) {
	if _, err := NewMonitoringPolicy(Metric("VIBES"), "1", CompareAbove, true); err == nil {
		t.Error("a policy for an unknown metric was accepted")
	}
}

// TestTwoPoliciesForOneSignalIsRefused: a signal with two thresholds has no defined breach.
func TestTwoPoliciesForOneSignalIsRefused(t *testing.T) {
	policies := fullPolicies(t)
	policies = append(policies, policies[0])
	if _, err := NewMonitor(mustModelID(t), policies); err == nil {
		t.Error("two policies for the same metric were accepted; a signal with two " +
			"thresholds has no defined breach")
	}
}

// TestABreachRequiresAPause checks the automatic response itself: a detected breach
// obliges a pause rather than producing a report somebody can read and decline.
func TestABreachRequiresAPause(t *testing.T) {
	m := mustMonitor(t)
	breaches, err := m.Evaluate([]Observation{
		observation(MetricInputDrift, "0.31", true),
		observation(MetricOutputDrift, "0.10", false),
		observation(MetricPredictionStab, "0.90", false),
		observation(MetricStrategyPerf, "0.02", false),
		observation(MetricRejectionRate, "0.15", false),
		observation(MetricDataFreshness, "2", false),
		observation(MetricServiceHealth, "0.999", false),
	})
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if len(breaches) != 1 {
		t.Fatalf("%d breaches detected, want 1", len(breaches))
	}
	if breaches[0].Metric != MetricInputDrift {
		t.Errorf("breach reported for %s, want INPUT_DRIFT", breaches[0].Metric)
	}
	if !breaches[0].AutoPause {
		t.Error("the breach does not carry an automatic pause")
	}
	if !RequiresPause(breaches) {
		t.Error("RequiresPause returned false for a breached signal whose policy pauses")
	}
}

// TestNoBreachMeansNoPause: the complement, so a pause cannot be triggered by a healthy
// model.
func TestNoBreachMeansNoPause(t *testing.T) {
	m := mustMonitor(t)
	obs := make([]Observation, 0, len(AllMetrics()))
	for _, p := range fullPolicies(t) {
		obs = append(obs, observation(p.Metric, p.Threshold, false))
	}
	breaches, err := m.Evaluate(obs)
	if err != nil {
		t.Fatalf("Evaluate: %v", err)
	}
	if len(breaches) != 0 {
		t.Errorf("%d breaches detected on a fully healthy set", len(breaches))
	}
	if RequiresPause(breaches) {
		t.Error("a pause was required with no breach")
	}
}

// TestAnObservationWithNoPolicyIsRefused: silently dropping it would mean a caller
// believed they had reported a signal that was in fact unmonitored.
func TestAnObservationWithNoPolicyIsRefused(t *testing.T) {
	m := mustMonitor(t)
	_, err := m.Evaluate([]Observation{observation(Metric("NOT_A_SIGNAL"), "1", false)})
	if err == nil {
		t.Error("an observation for an unmonitored signal was accepted")
	}
}

// TestDuplicateObservationsAreRefused: two values for one signal in one evaluation have no
// defined meaning, and taking the last would be arbitrary.
func TestDuplicateObservationsAreRefused(t *testing.T) {
	m := mustMonitor(t)
	_, err := m.Evaluate([]Observation{
		observation(MetricDataFreshness, "2", false),
		observation(MetricDataFreshness, "9", false),
	})
	if err == nil {
		t.Error("the same signal was observed twice in one evaluation and both were accepted")
	}
}

// TestAnObservationWithNoValueIsRefused: a breach flag with no value cannot be audited.
func TestAnObservationWithNoValueIsRefused(t *testing.T) {
	m := mustMonitor(t)
	_, err := m.Evaluate([]Observation{observation(MetricInputDrift, "  ", true)})
	if err == nil {
		t.Error("an observation with no value was accepted")
	}
}

// TestMonitorRequiresAModelIdentifier.
func TestMonitorRequiresAModelIdentifier(t *testing.T) {
	if _, err := NewMonitor(contracts.Identifier{}, fullPolicies(t)); err == nil {
		t.Error("a monitor with no model identifier was accepted")
	}
	strategy, err := contracts.ParseIdentifier("str_" + modelBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	if _, err := NewMonitor(strategy, fullPolicies(t)); err == nil {
		t.Error("a monitor bound to a non-model identifier was accepted")
	}
}

// TestThresholdsAreNotFloatingPoint: the canonical arithmetic in this repository is exact
// decimal, and a threshold compared with a float is a threshold that can be crossed by
// rounding. The field type makes the requirement structural rather than conventional.
func TestThresholdsAreNotFloatingPoint(t *testing.T) {
	p, err := NewMonitoringPolicy(MetricRejectionRate, "0.40", CompareAbove, true)
	if err != nil {
		t.Fatalf("NewMonitoringPolicy: %v", err)
	}
	// A threshold is carried as text, so a caller cannot smuggle a float64 in through a
	// numeric literal without a conversion this package would have to permit explicitly.
	if p.Threshold != "0.40" {
		t.Errorf("threshold = %q, want the value as supplied", p.Threshold)
	}
}
