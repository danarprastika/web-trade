package authz

import (
	"crypto/sha256"
	"encoding/hex"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Approval binds a second person to an exact change.
//
// docs/21 section 6 requires that a distinct approver reviews the exact diff and that any
// change to the diff invalidates the approval. Binding an approval to a digest of the diff
// is what makes that mechanical: the approver signs the change, not the request to change
// something, so altering the change after the fact produces a different digest and the
// approval simply no longer applies.
//
// An approval is also bound to the approver, so self-approval is unrepresentable rather
// than merely discouraged.
type Approval struct {
	// RequestID identifies the approval request.
	RequestID string
	// DiffDigest is the SHA-256 of the exact proposed diff.
	DiffDigest string
	// RequestedBy is the person proposing the change.
	RequestedBy string
	// ApprovedBy is the second person. It must differ from RequestedBy.
	ApprovedBy string
	// ApprovedAt is when the approval was given.
	ApprovedAt time.Time
	// ExpiresAt is when the approval lapses. docs/21 section 6 caps it at 24 hours.
	ExpiresAt time.Time
	// PolicyVersion is the policy the approver evaluated against.
	PolicyVersion string
}

// IsExpired reports whether the approval has lapsed.
func (a Approval) IsExpired(now time.Time) bool {
	return !a.ExpiresAt.IsZero() && now.After(a.ExpiresAt)
}

// DiffDigest returns the digest of a proposed change.
//
// The caller passes the canonical rendering of the diff rather than a struct, because the
// approver must be shown exactly the bytes that were hashed. A caller that renders the
// same change two different ways produces two digests and the approval stops applying,
// which is the safe direction: a change nobody agreed to is a change nobody approved.
func DiffDigest(canonicalDiff string) string {
	sum := sha256.Sum256([]byte(canonicalDiff))
	return hex.EncodeToString(sum[:])
}

// ApprovalRequest is a request to have a change approved.
type ApprovalRequest struct {
	// RequestID identifies the request.
	RequestID string
	// DiffDigest is the digest of the exact proposed diff, as shown to the approver.
	DiffDigest string
	// RequestedBy is the person proposing the change.
	RequestedBy string
	// Scope is the scope the change applies to.
	Scope Scope
	// Reason is the justification.
	Reason string
	// RequestedAt is when the request was made.
	RequestedAt time.Time
}

// NewApproval produces an approval binding a second person to an exact change.
//
// Every condition docs/21 section 6 puts on an approval is checked here, once, so a caller
// that has an approval in hand cannot have obtained it through a path that skipped a rule.
func NewApproval(req ApprovalRequest, approver string, now time.Time) (Approval, error) {
	if strings.TrimSpace(req.RequestID) == "" {
		return Approval{}, reject(contracts.CodeValidation, "request id is required")
	}
	if len(req.DiffDigest) != sha256.Size*2 {
		return Approval{}, reject(contracts.CodeValidation,
			"a diff digest must be a %d-character SHA-256 hex; got %d", sha256.Size*2, len(req.DiffDigest))
	}
	if strings.TrimSpace(req.RequestedBy) == "" {
		return Approval{}, reject(contracts.CodeValidation, "requester is required")
	}
	if strings.TrimSpace(approver) == "" {
		return Approval{}, reject(contracts.CodeValidation, "approver is required")
	}
	// Dual control means two people. The same person approving their own change satisfies
	// a two-approver form and none of its purpose.
	if req.RequestedBy == approver {
		return Approval{}, reject(contracts.CodeAuthorization,
			"%s requested this change and may not approve it", approver)
	}
	// A privileged grant already has its own expiry; an approval inherits the shorter of
	// the two so a change cannot be approved into an unbounded window.
	expiry := now.Add(ApprovalTTL)
	if !req.RequestedAt.IsZero() {
		if elapsed := now.Sub(req.RequestedAt); elapsed > ApprovalTTL {
			return Approval{}, reject(contracts.CodeAuthorization,
				"the approval request is %s old, beyond the %s limit", elapsed.Round(time.Second), ApprovalTTL)
		}
		if req.RequestedAt.Add(ApprovalTTL).Before(expiry) {
			expiry = req.RequestedAt.Add(ApprovalTTL)
		}
	}

	return Approval{
		RequestID:     req.RequestID,
		DiffDigest:    req.DiffDigest,
		RequestedBy:   req.RequestedBy,
		ApprovedBy:    approver,
		ApprovedAt:    now,
		ExpiresAt:     expiry,
		PolicyVersion: "policy-v1",
	}, nil
}

// CheckApproval verifies an approval is valid for a change being applied now.
//
// The caller supplies the diff it is about to apply, not the digest it recorded earlier, so
// that a change made after approval is caught here rather than trusted.
func (a Approval) CheckApproval(req ApprovalRequest, canonicalDiff string, now time.Time) error {
	if a.IsExpired(now) {
		return reject(contracts.CodeAuthorization,
			"the approval expired at %s", a.ExpiresAt.Format(time.RFC3339))
	}
	if a.RequestedBy == a.ApprovedBy {
		return reject(contracts.CodeAuthorization, "an approval must have two distinct people")
	}
	// The exact-diff check. This is the whole point of the type.
	if DiffDigest(canonicalDiff) != a.DiffDigest {
		return reject(contracts.CodeAuthorization,
			"the change no longer matches the approved diff; any change to the diff invalidates the approval")
	}
	if a.DiffDigest != req.DiffDigest {
		return reject(contracts.CodeAuthorization,
			"the approval is bound to a different change than the one being requested")
	}
	return nil
}
