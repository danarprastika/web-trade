package contracts

import (
	"errors"
	"strings"
	"testing"
)

// TestErrorCodeTaxonomyIsClosed pins the eleven canonical codes from docs/03.
//
// A closed set with no default case is deliberate: docs/03 requires unknown enum values to
// be treated as unsupported rather than silently mapped, so an unrecognised code arriving
// from a peer service must surface as an error instead of degrading into a code the
// platform believes it understands.
func TestErrorCodeTaxonomyIsClosed(t *testing.T) {
	all := AllErrorCodes()
	if len(all) != 11 {
		t.Errorf("taxonomy has %d codes, want 11", len(all))
	}
	seen := map[ErrorCode]bool{}
	for _, c := range all {
		if !c.Valid() {
			t.Errorf("code %q reported invalid", c)
		}
		if seen[c] {
			t.Errorf("code %q appears twice in AllErrorCodes", c)
		}
		seen[c] = true
	}
	for _, s := range []string{"", "validation_error", "NOT_A_CODE", "RISK", "TIMEOUT"} {
		if _, err := ParseErrorCode(s); err == nil {
			t.Errorf("ParseErrorCode(%q) = nil error, want reject", s)
		}
	}
	if _, err := ParseErrorCode("RISK_REJECTED"); err != nil {
		t.Errorf("ParseErrorCode(RISK_REJECTED) = %v, want accept", err)
	}
}

// TestDenyCodesCannotBeOverridden pins that RISK_REJECTED and the two identity codes are
// denials.
//
// Authorization policy cannot approve or override financial risk (ADR-018) and the Risk
// Engine veto is final (docs/25 §3.1), so if RISK_REJECTED were not a deny, a downstream
// component could treat a veto as a soft failure and proceed.
func TestDenyCodesCannotBeOverridden(t *testing.T) {
	deny := []ErrorCode{CodeRiskRejected, CodeAuthentication, CodeAuthorization}
	for _, c := range deny {
		if !c.IsDeny() {
			t.Errorf("code %q does not report IsDeny() = true", c)
		}
	}
	// These are failures but not denials. A dependency outage is retried, not vetoed.
	notDeny := []ErrorCode{
		CodeValidation, CodeConflict, CodeRateLimited, CodeDependencyUnavailable,
		CodeTimeoutUnknown, CodeDataStale, CodeReconciliationRequired, CodeInternal,
	}
	for _, c := range notDeny {
		if c.IsDeny() {
			t.Errorf("code %q reports IsDeny() = true, want false", c)
		}
	}
}

// TestTimeoutUnknownRejectsRetryable is the load-bearing test for this file.
//
// error.schema.json requires retryable to be FALSE for a risk-increasing command whose
// prior outcome is unknown. TIMEOUT_UNKNOWN is exactly the code meaning the outcome is
// unknown, so marking it retryable would authorise a retry that may duplicate exposure.
// docs/09 invariant 3 forbids that, and reconciliation is the correct response instead.
func TestTimeoutUnknownRejectsRetryable(t *testing.T) {
	if _, err := NewContractError(CodeTimeoutUnknown, "venue did not answer", true); err == nil {
		t.Fatal("NewContractError(TIMEOUT_UNKNOWN, retryable=true) = nil error, want rejection")
	} else if !errors.Is(err, ErrInvalidContractValue) {
		t.Errorf("error %v does not wrap ErrInvalidContractValue", err)
	}
	// Not retryable is the only permitted form of this error.
	e, err := NewContractError(CodeTimeoutUnknown, "venue did not answer", false)
	if err != nil {
		t.Fatalf("NewContractError with retryable=false: %v", err)
	}
	if e.Retryable() {
		t.Error("Retryable() = true, want false")
	}
	// Every other code may be retryable, or the taxonomy would be unusable for transient
	// dependency faults.
	if _, err := NewContractError(CodeDependencyUnavailable, "feed down", true); err != nil {
		t.Errorf("DEPENDENCY_UNAVAILABLE with retryable=true = %v, want accept", err)
	}
}

func TestContractErrorMessageBounds(t *testing.T) {
	if _, err := NewContractError(CodeValidation, "", false); err == nil {
		t.Error("empty message accepted, want reject")
	}
	// maxLength is 1024.
	if _, err := NewContractError(CodeValidation, strings.Repeat("x", 1024), false); err != nil {
		t.Errorf("1024-character message = %v, want accept", err)
	}
	if _, err := NewContractError(CodeValidation, strings.Repeat("x", 1025), false); err == nil {
		t.Error("1025-character message accepted, want reject")
	}
	// An unknown code cannot be constructed, so it can never be observed downstream.
	if _, err := NewContractError(ErrorCode("MADE_UP"), "boom", false); err == nil {
		t.Error("unknown error code accepted, want reject")
	}
}

func TestContractErrorCarriesCorrelationAndDetails(t *testing.T) {
	id, err := ParseIdentifier("cmd_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	base, err := NewContractError(CodeRiskRejected, "position limit exceeded", false)
	if err != nil {
		t.Fatalf("NewContractError: %v", err)
	}
	if _, ok := base.CorrelationID(); ok {
		t.Error("CorrelationID() reports set on a fresh error")
	}

	e := base.WithCorrelation(id).WithDetails(map[string]any{"limit": 100, "actual": 150})
	got, ok := e.CorrelationID()
	if !ok || got != id {
		t.Errorf("CorrelationID() = %v, %v, want the attached id", got, ok)
	}
	if d := e.Details(); d["limit"] != 100 || d["actual"] != 150 {
		t.Errorf("Details() = %v, want the attached context", d)
	}
	// The builder returns a copy: mutating one must not retroactively change the other, or
	// an error already logged elsewhere would change underneath the log.
	if _, ok := base.CorrelationID(); ok {
		t.Error("WithCorrelation mutated the receiver; it must return a copy")
	}
	if base.Details() != nil {
		t.Error("WithDetails mutated the receiver; it must return a copy")
	}
}

// TestContractErrorStringLeadsWithCode pins that the stable machine contract is the code.
// A log consumer pattern-matching the code stays correct even if the message is reworded.
func TestContractErrorStringLeadsWithCode(t *testing.T) {
	e, err := NewContractError(CodeDataStale, "position feed is 30s old", false)
	if err != nil {
		t.Fatalf("NewContractError: %v", err)
	}
	if got := e.Error(); got != "DATA_STALE: position feed is 30s old" {
		t.Errorf("Error() = %q, want the code first", got)
	}
	if e.Code() != CodeDataStale {
		t.Errorf("Code() = %q, want DATA_STALE", e.Code())
	}
	if e.Message() != "position feed is 30s old" {
		t.Errorf("Message() = %q, want the human-facing text", e.Message())
	}
}

func TestContractErrorSatisfiesErrorInterface(t *testing.T) {
	e, err := NewContractError(CodeInternal, "unexpected", false)
	if err != nil {
		t.Fatalf("NewContractError: %v", err)
	}
	// A ContractError must be usable wherever error is expected, since it crosses service
	// boundaries as a value rather than being re-wrapped by the caller.
	var asError error = e
	if !strings.Contains(asError.Error(), "INTERNAL_ERROR") {
		t.Errorf("as error = %q, want it to carry the code", asError.Error())
	}
}
