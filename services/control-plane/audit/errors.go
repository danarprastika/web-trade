package audit

import (
	"fmt"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ErrInvalidAudit is the sentinel behind every refusal, so a caller can attribute a
// rejection to the audit chain rather than to an unrelated fault.
var ErrInvalidAudit = contracts.ErrInvalidContractValue

// Rejection is a refused audit operation.
//
// It carries a canonical ErrorCode and a local sentinel for the same reason the ledger,
// OMS, strategy, and risk packages each carry one: a caller on another service needs
// the machine-readable code, and errors.Is must keep working in process.
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
	return Rejection{Code: code, Cause: ErrInvalidAudit, Reason: fmt.Sprintf(format, args...)}
}

// Finding is one integrity problem the verifier discovered.
//
// A verifier that returns only a boolean cannot be acted on. Every finding names the
// partition and sequence it was found at, and the class of tampering it corresponds to,
// because the operational response differs: a chain break stops privileged mutations,
// while an unexpected checkpoint means the key that signed a batch is no longer one the
// verifier trusts.
type Finding struct {
	// Kind classifies the integrity failure. See the Finding* constants.
	Kind FindingKind
	// Partition is the tenant or owner scope the failure was found in.
	Partition string
	// Sequence is the record sequence the failure was found at, or -1 when the failure
	// is not attributable to a single record.
	Sequence int64
	// Detail is the human-facing explanation. Never parsed.
	Detail string
}

// FindingKind classifies an integrity failure.
type FindingKind string

const (
	// FindingTamper is a record whose recomputed hash does not match its recorded hash.
	FindingTamper FindingKind = "TAMPER"
	// FindingDeletion is a gap in the sequence, meaning a record was removed.
	FindingDeletion FindingKind = "DELETION"
	// FindingReorder is a record whose previous-hash link does not name the record that
	// actually precedes it, meaning records were moved relative to one another.
	FindingReorder FindingKind = "REORDER"
	// FindingReplay is a record reusing a sequence already consumed in its partition.
	FindingReplay FindingKind = "REPLAY"
	// FindingSignature is a checkpoint or record signature that does not verify, or one
	// signed by a key the verifier does not trust.
	FindingSignature FindingKind = "SIGNATURE"
	// FindingCheckpoint is a missing, out-of-order, or unexpected checkpoint.
	FindingCheckpoint FindingKind = "CHECKPOINT"
	// FindingRestore is a chain that does not resume from its last signed checkpoint,
	// meaning a restore lost or reordered evidence.
	FindingRestore FindingKind = "RESTORE"
)

// Severity reports how a finding must be handled.
//
// Every finding is SEV-1. docs/22 section 3 is explicit that a chain break, a missing
// sequence, a signature failure, or an unexpected checkpoint is a SEV-1 security event,
// and the required response is to stop privileged mutations and risk-increasing activity,
// preserve evidence, and alert. This function exists so that a caller sweeping findings
// cannot accidentally treat one class as less serious than another.
func (f Finding) Severity() string { return "SEV-1" }

// Verification is the outcome of checking a chain.
type Verification struct {
	// OK is true only when Findings is empty. A partial verification is not a pass.
	OK bool
	// RecordsChecked is the number of records the verifier actually inspected.
	RecordsChecked int
	// CheckpointsChecked is the number of checkpoints the verifier actually inspected.
	CheckpointsChecked int
	// Findings are every integrity problem found, in the order discovered. A verifier
	// that stops at the first problem would let a second, independent tampering attempt
	// hide behind the first, so it reports all of them.
	Findings []Finding
}
