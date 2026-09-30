package ledger

import (
	"fmt"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ErrInvalidEntry is the sentinel behind every refusal, so a caller can attribute a rejection
// to the ledger rather than to an unrelated fault.
var ErrInvalidEntry = contracts.ErrInvalidContractValue

// Rejection is a refused posting.
//
// It carries a canonical ErrorCode and a local sentinel for the same reason the OMS, strategy,
// and risk packages each carry one: a caller on another service needs the machine-readable
// code, and errors.Is must keep working in process. Formatting an ErrorCode with %w is not
// valid Go, and formatting it with %s would discard exactly the part that must survive.
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
	return Rejection{Code: code, Cause: ErrInvalidEntry, Reason: fmt.Sprintf(format, args...)}
}
