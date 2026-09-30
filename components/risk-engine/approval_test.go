package riskengine

import (
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// docs/17 section 4 requires a risk approval to be "bound to the exact command, instrument,
// quantity, price constraints, account, environment, and policy revision" and states that
// "any material change invalidates approval and requires reevaluation".
//
// The tests below pin that binding field by field, and then pin the consequence: a rejection
// yields no approval, no approval yields no permit, and no permit means no live submission.

func submissionFor(t *testing.T, ic Intent) SubmissionRequest {
	t.Helper()
	return SubmissionRequest{
		CommandID:     ic.CommandID,
		CorrelationID: ic.CorrelationID,
		Venue:         ic.Venue,
		IssuedAt:      ic.IssuedAt,
	}
}

func TestAnApprovalIsBoundToTheCommandThatEarnedIt(t *testing.T) {
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	result := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	binding, ok := result.Binding()
	if !ok {
		t.Fatal("an approved result must expose its binding")
	}
	if binding.CommandID != ic.CommandID {
		t.Errorf("binding names command %s, want %s", binding.CommandID, ic.CommandID)
	}
	if binding.PolicyRevision != policy.Revision {
		t.Errorf("binding names policy revision %s, want %s", binding.PolicyRevision, policy.Revision)
	}
	if !result.Approval.ValidAt(result.EvaluatedAt) {
		t.Error("a freshly issued approval must be valid at the evaluation time")
	}
}

// The binding must cover every field docs/17 names. Each case changes one field and expects
// the approval to stop authorising the command.
func TestAMaterialChangeInvalidatesTheApproval(t *testing.T) {
	price := func(t *testing.T, v string) *contracts.Money {
		return ptr(scaledMoney(t, fixtureCurrency, v, 2))
	}

	cases := map[string]func(*Intent){
		"command id":     func(ic *Intent) { ic.CommandID = otherID(t, contracts.PrefixCommand) },
		"account id":     func(ic *Intent) { ic.AccountID = otherID(t, contracts.PrefixLedger) },
		"strategy id":    func(ic *Intent) { ic.StrategyID = otherID(t, contracts.PrefixStrategy) },
		"instrument":     func(ic *Intent) { ic.Instrument = "ETH-USDT" },
		"venue":          func(ic *Intent) { ic.Venue = "VENUE_B" },
		"market":         func(ic *Intent) { ic.Market = "PERPETUAL" },
		"direction":      func(ic *Intent) { ic.Direction = DirSell },
		"order type":     func(ic *Intent) { ic.OrderType = "MARKET" },
		"quantity":       func(ic *Intent) { ic.Quantity = quantity(t, "BASE_ASSET", "6") },
		"price":          func(ic *Intent) { ic.LimitPrice = price(t, "101.00") },
		"price currency": func(ic *Intent) { ic.LimitPrice = ptr(scaledMoney(t, "EUR", "100.00", 2)) },
		"price presence": func(ic *Intent) { ic.LimitPrice = nil },
		"environment":    func(ic *Intent) { ic.Environment = "SIMULATION" },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			ic := baselineIntent(t)
			policy := baselinePolicy(t)
			approved := evaluate(t, ic, baselineFacts(t), policy, Advisory{})
			requireApproved(t, approved)

			changed := baselineIntent(t)
			mutate(&changed)

			ok, reason := approved.Approval.Permits(changed, policy, approved.EvaluatedAt)
			if ok {
				t.Fatalf("an approval must not survive a change to %s", name)
			}
			if !strings.Contains(reason, "reevaluation") {
				t.Errorf("the refusal should say reevaluation is required, got: %s", reason)
			}
		})
	}
}

func TestBindingReportsWhichFieldChanged(t *testing.T) {
	// A refusal that names the differing field is actionable; one that only says "does not
	// match" sends the reader back to diff two commands by hand.
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	approved := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	changed := baselineIntent(t)
	changed.Quantity = quantity(t, "BASE_ASSET", "6")

	_, reason := approved.Approval.Permits(changed, policy, approved.EvaluatedAt)
	if !strings.Contains(reason, "quantity") {
		t.Errorf("the refusal should name the changed field, got: %s", reason)
	}
	if !strings.Contains(reason, "1 field(s) differ") {
		t.Errorf("the refusal should say how many fields differ, got: %s", reason)
	}
}

func TestAnApprovalIsInvalidatedByANewPolicyRevision(t *testing.T) {
	// The approval names the policy it was made under. A policy that has moved on may hold
	// different limits, so an approval made under the old one is not transferable.
	ic := baselineIntent(t)
	approved := evaluate(t, ic, baselineFacts(t), baselinePolicy(t), Advisory{})

	rotated := baselinePolicy(t)
	rotated.Revision = "cfg-0008"

	ok, reason := approved.Approval.Permits(ic, rotated, approved.EvaluatedAt)
	if ok {
		t.Fatal("an approval must not authorise a command under a different policy revision")
	}
	if !strings.Contains(reason, "cfg-0008") {
		t.Errorf("the refusal should name the active revision, got: %s", reason)
	}
}

func TestAnApprovalExpires(t *testing.T) {
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	result := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	// The last instant of validity is one nanosecond before expiry, and the boundary itself
	// is already invalid. A permit valid at the expiry instant is the classic off-by-one.
	lastValid := contracts.TimestampFrom(result.Approval.ExpiresAt.Time().Add(-time.Nanosecond))
	if ok, _ := result.Approval.Permits(ic, policy, lastValid); !ok {
		t.Error("an approval must be valid one nanosecond before it expires")
	}

	for _, at := range []contracts.Timestamp{
		result.Approval.ExpiresAt,
		contracts.TimestampFrom(result.Approval.ExpiresAt.Time().Add(time.Second)),
	} {
		ok, reason := result.Approval.Permits(ic, policy, at)
		if ok {
			t.Errorf("an approval must not be valid at %s", at)
		}
		if !strings.Contains(reason, "expired") {
			t.Errorf("the refusal should say the approval expired, got: %s", reason)
		}
	}
}

func TestAnApprovalIsInvalidBeforeItWasIssued(t *testing.T) {
	// A decision dated before the approval exists is a clock problem, not a valid early use.
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	result := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	before := contracts.TimestampFrom(result.Approval.IssuedAt.Time().Add(-time.Second))
	ok, reason := result.Approval.Permits(ic, policy, before)
	if ok {
		t.Fatal("an approval must not be valid before it was issued")
	}
	if !strings.Contains(reason, "in the future") {
		t.Errorf("the refusal should identify the clock disagreement, got: %s", reason)
	}
}

func TestAZeroApprovalAuthorisesNothing(t *testing.T) {
	// The zero value must not be accidentally permissive, which is why every check in
	// Permits is reached only after this one.
	var approval Approval
	ok, reason := approval.Permits(baselineIntent(t), baselinePolicy(t), ts(t, baselineNow))
	if ok {
		t.Fatal("a zero approval must authorise nothing")
	}
	if !strings.Contains(reason, "no risk approval") {
		t.Errorf("the refusal should say no approval exists, got: %s", reason)
	}
	if !approval.IsZero() {
		t.Error("a zero Approval must report IsZero")
	}
}

func TestARejectedCommandYieldsNoPermit(t *testing.T) {
	// This is the whole of "a risk-rejected command creates no live submission", expressed as
	// a value the submission path cannot be handed.
	facts := baselineFacts(t)
	facts.Position.Value.Leverage = contracts.MustParseDecimal("3.0")

	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	rejected := evaluate(t, ic, facts, policy, Advisory{})

	if _, err := GrantPermit(rejected, ic, policy, rejected.EvaluatedAt); err == nil {
		t.Fatal("a rejected command must not produce a permit")
	} else if !strings.Contains(err.Error(), "rejected by") {
		t.Errorf("the refusal should say which controls rejected, got: %v", err)
	}
}

func TestAnApprovalGrantsAPermitForItsOwnSubmission(t *testing.T) {
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	approved := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	permit, err := GrantPermit(approved, ic, policy, approved.EvaluatedAt)
	if err != nil {
		t.Fatalf("an approved command should produce a permit: %v", err)
	}
	if permit.CommandID != ic.CommandID {
		t.Errorf("permit covers %s, want %s", permit.CommandID, ic.CommandID)
	}
	if err := permit.Admit(submissionFor(t, ic), approved.EvaluatedAt); err != nil {
		t.Errorf("a valid submission should be admitted: %v", err)
	}
}

func TestASubmissionWithoutAPermitIsRefused(t *testing.T) {
	// The load-bearing property: the submission path has nothing to accept unless the Risk
	// Engine granted it. A zero permit must therefore be refused, not treated as a bypass.
	var permit Permit
	err := permit.Admit(submissionFor(t, baselineIntent(t)), ts(t, baselineNow))
	if err == nil {
		t.Fatal("a submission with no permit must be refused")
	}
	if !strings.Contains(err.Error(), "no permit was presented") {
		t.Errorf("the refusal should say no permit was presented, got: %v", err)
	}
}

func TestASubmissionMustNameThePermittedCommandAndVenue(t *testing.T) {
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	approved := evaluate(t, ic, baselineFacts(t), policy, Advisory{})
	permit, err := GrantPermit(approved, ic, policy, approved.EvaluatedAt)
	if err != nil {
		t.Fatalf("permit should be granted: %v", err)
	}
	now := approved.EvaluatedAt

	t.Run("wrong command", func(t *testing.T) {
		req := submissionFor(t, ic)
		req.CommandID = otherID(t, contracts.PrefixCommand)
		if err := permit.Admit(req, now); err == nil {
			t.Error("a submission naming a different command must be refused")
		}
	})
	t.Run("no venue", func(t *testing.T) {
		req := submissionFor(t, ic)
		req.Venue = ""
		if err := permit.Admit(req, now); err == nil {
			t.Error("a submission naming no venue must be refused")
		}
	})
	t.Run("no correlation id", func(t *testing.T) {
		req := submissionFor(t, ic)
		req.CorrelationID = contracts.Identifier{}
		if err := permit.Admit(req, now); err == nil {
			t.Error("a submission with no correlation id must be refused")
		}
	})
	t.Run("expired permit", func(t *testing.T) {
		err := permit.Admit(submissionFor(t, ic), contracts.TimestampFrom(permit.ExpiresAt.Time()))
		if err == nil {
			t.Fatal("a submission at the expiry instant must be refused")
		}
		if !strings.Contains(err.Error(), "expired") {
			t.Errorf("the refusal should say the permit expired, got: %v", err)
		}
	})
}

func TestAnExpiredApprovalGrantsNoPermit(t *testing.T) {
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	approved := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	after := contracts.TimestampFrom(approved.Approval.ExpiresAt.Time().Add(time.Second))
	if _, err := GrantPermit(approved, ic, policy, after); err == nil {
		t.Fatal("an expired approval must not grant a permit")
	}
}

func TestAResultClaimingApprovalWithoutCarryingOneIsAnInternalDefect(t *testing.T) {
	// A result that says APPROVED but has no approval is a contradiction. It is refused as an
	// internal fault rather than treated as a risk decision, because a caller that reached
	// this state has a bug, and quietly returning a risk rejection would hide it.
	result := Result{Verdict: Approved, CommandID: baselineIntent(t).CommandID}
	_, err := GrantPermit(result, baselineIntent(t), baselinePolicy(t), ts(t, baselineNow))
	if err == nil {
		t.Fatal("a contradictory result must be refused")
	}
	if !strings.Contains(err.Error(), "defect rather than a risk decision") {
		t.Errorf("the refusal should identify this as a defect, got: %v", err)
	}
}

func TestAPermitRefusesAnApprovalForADifferentCommand(t *testing.T) {
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	approved := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	// A result stamped with one command but submitted for another is a wiring fault.
	mismatched := approved
	mismatched.CommandID = otherID(t, contracts.PrefixCommand)

	if _, err := GrantPermit(mismatched, ic, policy, approved.EvaluatedAt); err == nil {
		t.Fatal("a result stamped for another command must not grant a permit")
	}
}

func TestApprovalLifetimeBoundsThePermit(t *testing.T) {
	// The permit inherits the approval's expiry rather than getting a fresh window, so a
	// submission cannot be deferred past the approval that authorised it.
	ic := baselineIntent(t)
	policy := baselinePolicy(t)
	approved := evaluate(t, ic, baselineFacts(t), policy, Advisory{})

	permit, err := GrantPermit(approved, ic, policy, approved.EvaluatedAt)
	if err != nil {
		t.Fatalf("permit should be granted: %v", err)
	}
	if permit.ExpiresAt != approved.Approval.ExpiresAt {
		t.Errorf("permit expires at %s but the approval expires at %s",
			permit.ExpiresAt, approved.Approval.ExpiresAt)
	}

	// A generous but bounded lifetime is still bounded, and the boundary is exact.
	generous, err := Evaluate(ic, baselineFacts(t), policy, Advisory{}, 5*time.Minute)
	if err != nil {
		t.Fatalf("evaluation failed: %v", err)
	}
	span := generous.Approval.ExpiresAt.Time().Sub(generous.Approval.IssuedAt.Time())
	if span != 5*time.Minute {
		t.Errorf("approval lifetime is %s, want 5m", span)
	}
}

func TestAnUnboundedApprovalLifetimeIsRefused(t *testing.T) {
	// docs/17 section 4 requires a short-lived approval. The lifetime is a caller-supplied
	// input, so a config or adapter bug could set it to a value that makes an approval outlive
	// the process that issued it. The bound is enforced by the engine rather than trusted to
	// the caller, and it is not configurable.
	ic := baselineIntent(t)
	facts := baselineFacts(t)
	policy := baselinePolicy(t)

	for _, lifetime := range []time.Duration{MaxApprovalLifetime + time.Second, 24 * time.Hour, time.Duration(1<<63 - 1)} {
		if _, err := Evaluate(ic, facts, policy, Advisory{}, lifetime); err == nil {
			t.Errorf("an approval lifetime of %s must be refused", lifetime)
		}
	}

	// The boundary itself is allowed, so the limit is inclusive rather than off by one.
	if _, err := Evaluate(ic, facts, policy, Advisory{}, MaxApprovalLifetime); err != nil {
		t.Errorf("the maximum approval lifetime itself must be accepted: %v", err)
	}
}
