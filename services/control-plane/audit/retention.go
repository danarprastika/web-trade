package audit

import (
	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// RetentionYears is the retention period docs/22 section 4 requires for financial,
// access, approval, and control records.
const RetentionYears = 7

// DeletionRequest is an application to delete audit evidence.
//
// Deletion is the one operation this package must make hard, because everything else it
// exists to do is prevent. docs/22 section 4 permits deletion only after retention
// expiry, legal-hold clearance, and two-person approval, and requires the deletion event
// itself to be retained.
type DeletionRequest struct {
	// Partition is the evidence to delete.
	Partition string
	// FirstSequence and LastSequence bound it.
	FirstSequence int64
	LastSequence  int64
	// RequestedBy is the first approver.
	RequestedBy string
	// ApprovedBy is the second approver.
	ApprovedBy string
	// LegalHoldCleared records that no legal hold is in force.
	LegalHoldCleared bool
	// RetentionExpired records that the seven-year period has elapsed.
	RetentionExpired bool
	// Now is the current time, supplied rather than read.
	Now Timestamp
}

// Timestamp is the audit package's timestamp, re-exported so callers building a deletion
// request do not have to import the contracts package directly.
type Timestamp = contracts.Timestamp

// EvaluateDeletion decides whether a deletion request may proceed.
//
// Every precondition is checked and every failure is named, because an operator who is
// refused needs to know which one is missing, and a request that fails several at once
// should not require a guessing game to fix.
func EvaluateDeletion(req DeletionRequest) error {
	if req.Partition == "" {
		return reject(contracts.CodeValidation, "partition is required")
	}
	if req.FirstSequence < 1 || req.LastSequence < req.FirstSequence {
		return reject(contracts.CodeValidation,
			"deletion range must be a valid ascending range, got %d..%d", req.FirstSequence, req.LastSequence)
	}
	if !req.RetentionExpired {
		return reject(contracts.CodeAuthorization,
			"audit evidence is retained for %d years and has not reached expiry", RetentionYears)
	}
	if !req.LegalHoldCleared {
		return reject(contracts.CodeAuthorization, "a legal hold is in force; evidence cannot be deleted")
	}
	if req.RequestedBy == "" || req.ApprovedBy == "" {
		return reject(contracts.CodeAuthorization, "deletion requires two named people: requester and approver")
	}
	// Two-person approval means two people. The same person approving their own request
	// satisfies the letter of a two-approver form and none of its purpose.
	if req.RequestedBy == req.ApprovedBy {
		return reject(contracts.CodeAuthorization,
			"deletion requires two distinct people; %s requested and approved it", req.RequestedBy)
	}
	return nil
}

// DeletionEvent records that evidence was deleted.
//
// The deletion event is itself audit evidence and is retained, which is what makes the
// deletion auditable rather than merely permitted.
type DeletionEvent struct {
	AuditID       string
	Partition     string
	FirstSequence int64
	LastSequence  int64
	RequestedBy   string
	ApprovedBy    string
	DeletedAt     Timestamp
}

// NewDeletionEvent validates a request and, if it passes, returns the retained record of
// the deletion.
func NewDeletionEvent(req DeletionRequest) (DeletionEvent, error) {
	if err := EvaluateDeletion(req); err != nil {
		return DeletionEvent{}, err
	}
	// The identity is derived from the request so that a retried deletion produces the
	// same event rather than a second one.
	identity := "del-" + req.Partition + "-" +
		itoa64(req.FirstSequence) + "-" + itoa64(req.LastSequence)
	return DeletionEvent{
		AuditID:       identity,
		Partition:     req.Partition,
		FirstSequence: req.FirstSequence,
		LastSequence:  req.LastSequence,
		RequestedBy:   req.RequestedBy,
		ApprovedBy:    req.ApprovedBy,
		DeletedAt:     req.Now,
	}, nil
}
