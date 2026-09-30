package authz

import (
	"fmt"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ErrUnauthorized is the sentinel behind every refusal, so a caller can attribute a
// rejection to authorization rather than to an unrelated fault.
var ErrUnauthorized = contracts.ErrInvalidContractValue

// Rejection is a refused authorization decision.
//
// It carries a canonical ErrorCode and a local sentinel for the same reason the other
// domain packages each carry one: a caller on another service needs the machine-readable
// code, and errors.Is must keep working in process.
type Rejection struct {
	// Code is the canonical error code from docs/03.
	Code contracts.ErrorCode
	// Cause is the local sentinel, reachable through errors.Is.
	Cause error
	// Reason is the human-facing explanation. Never parsed.
	Reason string
}

func (r Rejection) Error() string { return fmt.Sprintf("%s: %s", r.Code, r.Reason) }

// Unwrap exposes the local sentinel to errors.Is and errors.As.
func (r Rejection) Unwrap() error { return r.Cause }

func reject(code contracts.ErrorCode, format string, args ...any) Rejection {
	return Rejection{Code: code, Cause: ErrUnauthorized, Reason: fmt.Sprintf(format, args...)}
}

// Refusal is why a request was not allowed.
//
// It is a closed set rather than a free string, because "denied" and "allowed because no
// rule was consulted" must not be the same value: docs/21 section 4 requires deny by
// default, so a refusal is the expected outcome of a request that has no grant, and an
// operator reading a refusal needs to know which of the several reasons applied.
type Refusal string

const (
	// RefusedNoRule is the deny-by-default case: no rule allowed the request.
	RefusedNoRule Refusal = "NO_MATCHING_RULE"
	// RefusedExplicitly is an explicit deny, which outranks any allow.
	RefusedExplicitly Refusal = "EXPLICIT_DENY"
	// RefusedOutOfScope is a scope violation: market, account, environment, or resource.
	RefusedOutOfScope Refusal = "OUT_OF_SCOPE"
	// RefusedSessionInvalid covers expiry, idle timeout, and revocation.
	RefusedSessionInvalid Refusal = "SESSION_INVALID"
	// RefusedStaleContext is the fail-closed case: the context or policy bundle is older
	// than the configured window, so the request was not evaluated on its merits.
	RefusedStaleContext Refusal = "STALE_CONTEXT"
	// RefusedAuthStrength is insufficient authentication strength, including a missing or
	// stale step-up for a privileged action.
	RefusedAuthStrength Refusal = "INSUFFICIENT_AUTH_STRENGTH"
	// RefusedApprovalRequired means a privileged action needs a valid approval that the
	// request did not carry.
	RefusedApprovalRequired Refusal = "APPROVAL_REQUIRED"
	// RefusedSelfApproval is a requester attempting to approve their own change.
	RefusedSelfApproval Refusal = "SELF_APPROVAL"
	// RefusedWildcardLive is a wildcard grant presented for a live financial operation,
	// which docs/21 section 4 prohibits outright.
	RefusedWildcardLive Refusal = "WILDCARD_LIVE_PROHIBITED"
	// RefusedRiskIsNotAuthorization is returned when a caller asks this package to
	// approve financial risk. It always is, and always will be: that is ADR-018.
	RefusedRiskIsNotAuthorization Refusal = "RISK_NOT_AUTHORIZATION"
)

// Decision is the outcome of evaluating a request.
type Decision struct {
	// Allowed is true only when every check passed.
	Allowed bool
	// Refusal is why the request was refused, and is empty when it was allowed.
	Refusal Refusal
	// Reason is the human-facing explanation. Never parsed.
	Reason string
	// PolicyBundleDigest records which bundle decided this, as docs/21 section 10 requires
	// every decision to do. It is recorded even on a refusal, because "which policy
	// refused me" is the first question anyone asks.
	PolicyBundleDigest string
	// PolicyBundleAge is how old that bundle was at decision time.
	PolicyBundleAge time.Duration
}

// Allow and Deny return the two shapes of decision, so a caller cannot produce a Decision
// that is simultaneously allowed and refused.
func allow(digest string, age time.Duration) Decision {
	return Decision{Allowed: true, PolicyBundleDigest: digest, PolicyBundleAge: age}
}

func deny(refusal Refusal, digest string, age time.Duration, format string, args ...any) Decision {
	return Decision{
		Refusal:            refusal,
		Reason:             fmt.Sprintf(format, args...),
		PolicyBundleDigest: digest,
		PolicyBundleAge:    age,
	}
}
