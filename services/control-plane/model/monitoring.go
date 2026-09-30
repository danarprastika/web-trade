package model

import (
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Metric is a monitored signal. docs/07 section 4 names the required set: "input drift,
// output distribution drift, prediction stability, strategy performance, rejection rate, data
// freshness, and model-service health."
type Metric string

// The monitored signals, all required by docs/07 section 4.
const (
	MetricInputDrift     Metric = "INPUT_DRIFT"
	MetricOutputDrift    Metric = "OUTPUT_DISTRIBUTION_DRIFT"
	MetricPredictionStab Metric = "PREDICTION_STABILITY"
	MetricStrategyPerf   Metric = "STRATEGY_PERFORMANCE"
	MetricRejectionRate  Metric = "REJECTION_RATE"
	MetricDataFreshness  Metric = "DATA_FRESHNESS"
	MetricServiceHealth  Metric = "MODEL_SERVICE_HEALTH"
)

var allMetrics = []Metric{
	MetricInputDrift, MetricOutputDrift, MetricPredictionStab, MetricStrategyPerf,
	MetricRejectionRate, MetricDataFreshness, MetricServiceHealth,
}

// Valid reports whether the metric is in the closed set.
func (m Metric) Valid() bool {
	for _, k := range allMetrics {
		if k == m {
			return true
		}
	}
	return false
}

// AllMetrics returns the monitored signals in the order docs/07 lists them.
func AllMetrics() []Metric {
	out := make([]Metric, len(allMetrics))
	copy(out, allMetrics)
	return out
}

// MonitoringPolicy is the breach behaviour for one monitored signal.
//
// The policy is a threshold and an action, not a score. A monitor that computed a health
// number and left the response to a human would be a monitor that can be outvoted, and
// docs/07 section 4 is explicit that "a breached model threshold causes automatic pause of
// the affected strategy/model deployment." The automatic is the part with teeth, so the
// action is declared in the policy and Apply returns the action rather than a boolean.
type MonitoringPolicy struct {
	Metric Metric
	// Threshold is the breach boundary as a canonical decimal string. It is a string
	// because the canonical arithmetic in this repository is exact decimal and
	// float64 would reintroduce the imprecision the money types exist to prevent; a
	// threshold compared with a float is a threshold that can be crossed by rounding.
	Threshold string
	// AutoPause reports whether a breach pauses the affected deployment automatically. It
	// is a field rather than being always true because a policy that could opt out of
	// pausing would be a policy field that a misconfiguration could silence. It is
	// required to be true, which the constructor enforces, and is recorded so that the
	// audit record shows the policy that was in force.
	AutoPause bool
	// Comparison names the breach direction: "ABOVE" or "BELOW". It is explicit because
	// freshness and prediction stability breach in the opposite direction from rejection
	// rate, and a single implicit "greater than" would invert half the policy set.
	Comparison string
}

// The comparison directions.
const (
	CompareAbove = "ABOVE"
	CompareBelow = "BELOW"
)

// NewMonitoringPolicy builds a policy, refusing one that would not pause automatically.
//
// The refusal is the enforcement of docs/07 section 4 rather than a convenience. A policy
// with AutoPause false is a policy that permits a breached model to keep running, and while
// there is a legitimate argument for a warning-only mode, that argument belongs in a
// separate signal whose breach is defined as a warning. Making it a field on this type
// means the same policy struct cannot mean both things.
func NewMonitoringPolicy(metric Metric, threshold, comparison string, autoPause bool) (MonitoringPolicy, error) {
	if !metric.Valid() {
		return MonitoringPolicy{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"monitoring metric %q is not one of the signals docs/07 section 4 requires", metric)
	}
	if strings.TrimSpace(threshold) == "" {
		return MonitoringPolicy{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"monitoring policy for %s has no threshold", metric)
	}
	if comparison != CompareAbove && comparison != CompareBelow {
		return MonitoringPolicy{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"monitoring comparison %q is not %q or %q; freshness breaches below the threshold "+
				"and rejection rate breaches above it", comparison, CompareAbove, CompareBelow)
	}
	if !autoPause {
		return MonitoringPolicy{}, reject(contracts.CodeAuthorization, ErrToolNotPermitted,
			"monitoring policy for %s may not disable automatic pause; docs/07 section 4 "+
				"requires a breached threshold to automatically pause the affected deployment",
			metric)
	}
	return MonitoringPolicy{
		Metric:     metric,
		Threshold:  threshold,
		Comparison: comparison,
		AutoPause:  autoPause,
	}, nil
}

// Observation is one measurement of a monitored signal.
type Observation struct {
	Metric Metric
	// Value is the measured value as a canonical decimal string, for the same exactness
	// reason as the threshold.
	Value string
	// Breached reports the measured breach. It is supplied by the evaluator that owns the
	// signal's semantics, because deciding whether a string is "above" 0.85 depends on
	// what the number means, and this package does not interpret arbitrary domain values.
	Breached bool
}

// Monitor evaluates observations against a model's policies.
type Monitor struct {
	ModelID contracts.Identifier
	// Policies is the declared policy set. Every signal in docs/07 section 4 must be
	// present, and NewMonitor refuses an incomplete set.
	Policies []MonitoringPolicy
}

// NewMonitor builds a monitor, refusing a policy set that does not cover every required
// signal.
//
// An incomplete policy set is the specific failure this prevents. A monitor that watches
// rejection rate but not data freshness will report a model as healthy while it is being
// fed stale inputs, and the health report is what an operator acts on. The refusal is
// therefore on the whole set rather than per-policy: each policy can be individually
// well-formed and the coverage gap is still a gap.
func NewMonitor(modelID contracts.Identifier, policies []MonitoringPolicy) (*Monitor, error) {
	if modelID.IsZero() || modelID.Prefix() != contracts.PrefixModel {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"monitor requires a model id carrying the %q prefix", contracts.PrefixModel)
	}
	covered := make(map[Metric]bool, len(policies))
	for _, p := range policies {
		if !p.Metric.Valid() {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"policy declares unknown metric %q", p.Metric)
		}
		if covered[p.Metric] {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"metric %s has more than one policy; a signal with two thresholds has no "+
					"defined breach", p.Metric)
		}
		if !p.AutoPause {
			return nil, reject(contracts.CodeAuthorization, ErrToolNotPermitted,
				"policy for %s does not pause automatically", p.Metric)
		}
		covered[p.Metric] = true
	}
	var missing []string
	for _, m := range allMetrics {
		if !covered[m] {
			missing = append(missing, string(m))
		}
	}
	if len(missing) > 0 {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"monitoring policy for model %s does not cover %s; docs/07 section 4 requires "+
				"input drift, output distribution drift, prediction stability, strategy "+
				"performance, rejection rate, data freshness, and model-service health",
			modelID, strings.Join(missing, ", "))
	}
	return &Monitor{ModelID: modelID, Policies: policies}, nil
}

// Breach is a detected threshold breach.
type Breach struct {
	Metric   Metric
	Policy   MonitoringPolicy
	Observed Observation
	// AutoPause is true when the policy requires the deployment to be paused. It is
	// carried on the breach rather than implied by its presence so that a caller reading
	// only the breach knows the required action without consulting the policy.
	AutoPause bool
}

// Evaluate returns every breach in a set of observations.
//
// An observation for a metric with no policy is a report of an unknown signal, and it is
// returned as an error rather than ignored: silently dropping it would mean a caller
// believed they had reported a signal that was in fact unmonitored.
func (m *Monitor) Evaluate(observations []Observation) ([]Breach, error) {
	byMetric := make(map[Metric]MonitoringPolicy, len(m.Policies))
	for _, p := range m.Policies {
		byMetric[p.Metric] = p
	}
	var out []Breach
	seen := make(map[Metric]bool, len(observations))
	for _, o := range observations {
		policy, ok := byMetric[o.Metric]
		if !ok {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"observation for %s has no policy; an unmonitored signal reported as "+
					"monitored is worse than an absent one", o.Metric)
		}
		if !o.Metric.Valid() {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"observation declares unknown metric %q", o.Metric)
		}
		if seen[o.Metric] {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"metric %s was observed more than once in a single evaluation", o.Metric)
		}
		seen[o.Metric] = true
		if strings.TrimSpace(o.Value) == "" {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"observation for %s has no value", o.Metric)
		}
		if o.Breached {
			out = append(out, Breach{
				Metric:    o.Metric,
				Policy:    policy,
				Observed:  o,
				AutoPause: policy.AutoPause,
			})
		}
	}
	return out, nil
}

// RequiresPause reports whether any breach obliges an automatic pause.
func RequiresPause(breaches []Breach) bool {
	for _, b := range breaches {
		if b.AutoPause {
			return true
		}
	}
	return false
}
