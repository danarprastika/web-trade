package riskengine

import (
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ControlOutcome is one control's result.
type ControlOutcome string

// The control outcomes.
const (
	// ControlPassed means the control found no violation.
	ControlPassed ControlOutcome = "PASSED"
	// ControlFailed means the control found a violation.
	ControlFailed ControlOutcome = "FAILED"
	// ControlUnavailable means the control could not read its source. It is a distinct
	// outcome from FAILED because the two call for different remediation: a failed control
	// is a risk decision, an unavailable control is an infrastructure problem. Both reject.
	ControlUnavailable ControlOutcome = "SOURCE_UNAVAILABLE"
)

func (c ControlOutcome) failed() bool { return c != ControlPassed }

// ControlResult is one control's evaluated outcome.
type ControlResult struct {
	// ID is the control.
	ID ControlID
	// Outcome is what the control concluded.
	Outcome ControlOutcome
	// Reason explains a non-passing outcome, and is empty for a pass.
	Reason string
	// Observed is the value the control compared against the threshold, for a reviewer who
	// needs to see what was measured rather than only that it passed.
	Observed string
	// Threshold is the configured limit, for the same reason.
	Threshold string
}

// Verdict is the overall decision.
type Verdict string

// The verdicts.
const (
	// Approved means every mandatory control passed.
	Approved Verdict = "APPROVED"
	// Rejected means at least one mandatory control failed.
	Rejected Verdict = "REJECTED"
)

// Result is the evaluation outcome.
//
// It carries what docs/17 section 4 requires: the verdict, the policy revision, the
// evaluated facts, the failed controls, a timestamp, and a correlation id. The field order
// here is the field order in the struct, and the result is built by appending to fixed
// slices, so two evaluations of the same inputs produce identical bytes.
type Result struct {
	// Verdict is the decision.
	Verdict Verdict
	// PolicyRevision is the configuration revision that produced it.
	PolicyRevision string
	// Environment is the environment evaluated against.
	Environment string
	// Controls is every control's outcome, in the fixed evaluation order.
	Controls []ControlResult
	// Failures are the non-passing controls, in evaluation order.
	Failures []ControlResult
	// EvaluatedAt is the evaluation time, taken from the facts rather than a clock.
	EvaluatedAt contracts.Timestamp
	// CorrelationID ties the decision to the request.
	CorrelationID contracts.Identifier
	// CommandID is the command this result covers.
	CommandID contracts.Identifier
	// Approval is the short-lived approval bound to this exact command, or nil when the
	// verdict is a rejection. A rejection therefore cannot yield a Permit, which is the
	// mechanical form of "no risk-rejected command creates a live submission".
	Approval *Approval
}

// Failed reports whether any control failed.
func (r Result) Failed() bool { return r.Verdict == Rejected }

// Passed reports whether every control passed.
func (r Result) Passed() bool { return r.Verdict == Approved }

// Binding returns the value fingerprint the result is bound to, or false when rejected.
func (r Result) Binding() (Binding, bool) {
	if r.Approval == nil {
		return Binding{}, false
	}
	return r.Approval.Binding, true
}

// control is one mandatory check. It receives everything it needs and returns a verdict.
//
// Controls are pure functions of their arguments. There is no context to thread, no logger,
// and no clock, because any of those would be a way for the result to depend on something
// other than the declared inputs.
type control func(ic Intent, facts Facts, policy Policy) ControlResult

// controlRegistry maps each mandatory control to its implementation, in evaluation order.
//
// It is a slice rather than a map so that iteration order is fixed. A map would make the
// report order depend on Go's randomised map iteration, which would make the result
// non-deterministic even though the decision is not.
var controlRegistry = []struct {
	id  ControlID
	run control
}{
	{ControlAccountAuthorization, checkAccountAuthorization},
	{ControlStrategyDeployment, checkStrategyDeployment},
	{ControlInstrumentEligibility, checkInstrumentEligibility},
	{ControlVenueAvailability, checkVenueAvailability},
	{ControlPricePrecision, checkPricePrecision},
	{ControlNotionalLimits, checkNotionalLimits},
	{ControlPositionLimits, checkPositionLimits},
	{ControlExposureLimits, checkExposureLimits},
	{ControlConcentrationLimits, checkConcentrationLimits},
	{ControlLeverageLimits, checkLeverageLimits},
	{ControlLossDrawdown, checkLossDrawdown},
	{ControlMarketDataStale, checkMarketDataStale},
	{ControlDuplicateOrder, checkDuplicateOrder},
	{ControlRateLimits, checkRateLimits},
	{ControlHaltState, checkHaltState},
}

// pass builds a passing result.
func pass(id ControlID, observed, threshold string) ControlResult {
	return ControlResult{ID: id, Outcome: ControlPassed, Observed: observed, Threshold: threshold}
}

// fail builds a failing result.
func fail(id ControlID, reason, observed, threshold string) ControlResult {
	return ControlResult{ID: id, Outcome: ControlFailed, Reason: reason, Observed: observed, Threshold: threshold}
}

// unavailable builds a source-unavailable result.
func unavailable(id ControlID, reason, threshold string) ControlResult {
	return ControlResult{ID: id, Outcome: ControlUnavailable, Reason: reason, Threshold: threshold}
}

// MaxApprovalLifetime is the longest approval the engine will issue.
//
// docs/17 section 4 requires a risk approval to be short-lived. A lifetime with no upper
// bound is not short-lived by any reading, and because the lifetime is a caller-supplied
// input, a config or adapter bug could otherwise set it to a value that makes an approval
// outlive the process that issued it. The bound is a structural safety limit rather than a
// risk limit, so it lives here as a constant instead of in the policy: no configuration
// should be able to widen it.
const MaxApprovalLifetime = 15 * time.Minute

// Evaluate runs every mandatory control against a risk-increasing command.
//
// The signature is the design. It takes an Intent, the Facts, the Policy, an Advisory, and
// an approval lifetime. The Advisory is accepted and never read. There is no logger, no
// clock, no context, and no error channel, because each of those would be a way for the
// decision to depend on something the caller could vary.
//
// approvalLifetime bounds how long an approval may be reused. docs/17 section 4 requires a
// risk approval to be short-lived; the lifetime is an input rather than a constant so a
// deployment can set it and so a test can drive the boundary exactly.
func Evaluate(ic Intent, facts Facts, policy Policy, advisory Advisory, approvalLifetime time.Duration) (Result, error) {
	// The advisory parameter is bound to a name and deliberately never used. Naming it makes
	// the intent explicit at the signature and gives a reader somewhere to look.
	_ = advisory

	if err := ic.validate(); err != nil {
		return Result{}, err
	}
	if err := facts.validate(); err != nil {
		return Result{}, err
	}
	if err := policy.validate(); err != nil {
		return Result{}, err
	}
	if approvalLifetime <= 0 {
		return Result{}, reject(contracts.CodeValidation,
			"approval lifetime must be positive; a non-expiring approval is not short-lived")
	}
	if approvalLifetime > MaxApprovalLifetime {
		return Result{}, reject(contracts.CodeValidation,
			"approval lifetime %s exceeds the maximum of %s; docs/17 section 4 requires a "+
				"short-lived approval, and the bound is not configurable because a "+
				"configuration that could widen it would be an implied permission",
			approvalLifetime, MaxApprovalLifetime)
	}

	result := Result{
		PolicyRevision: policy.Revision,
		Environment:    policy.Environment,
		// Preallocated to the control count so appending never reallocates, which keeps the
		// result's backing array fixed as well as its order.
		Controls:      make([]ControlResult, 0, len(controlRegistry)),
		EvaluatedAt:   facts.Now,
		CorrelationID: ic.CorrelationID,
		CommandID:     ic.CommandID,
	}

	for _, entry := range controlRegistry {
		result.Controls = append(result.Controls, entry.run(ic, facts, policy))
	}

	// docs/04: "a single failed mandatory control rejects the order." The conjunction is
	// over every control, with no weighting, no override, and no partial credit.
	rejected := false
	for _, c := range result.Controls {
		if c.Outcome.failed() {
			rejected = true
			break
		}
	}
	if rejected {
		result.Verdict = Rejected
		result.Failures = make([]ControlResult, 0, len(result.Controls))
		for _, c := range result.Controls {
			if c.Outcome.failed() {
				result.Failures = append(result.Failures, c)
			}
		}
		// No approval is produced, so no Permit can be derived, so the submission path
		// cannot be reached. This is the whole of "a risk-rejected command creates no live
		// submission", expressed as an invariant rather than as a caller's discipline.
		return result, nil
	}

	result.Verdict = Approved
	approval, err := issueApproval(ic, facts, policy, approvalLifetime)
	if err != nil {
		return Result{}, err
	}
	result.Approval = &approval
	return result, nil
}
