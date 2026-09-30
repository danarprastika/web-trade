package contracts

import (
	"errors"
	"fmt"
	"regexp"
	"time"
)

// ErrInvalidTimestamp means a timestamp violates the contract.
var ErrInvalidTimestamp = errors.New("invalid canonical timestamp")

// timestampPattern mirrors contracts/schema/timestamp.schema.json exactly:
//
//	^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,9})?Z$
//
// The schema is applied as a pattern rather than delegated to time.Parse. Probed against
// Go 1.26.2, time.Parse(time.RFC3339Nano, ...) accepts a numeric offset and accepts a
// tenth fractional digit by truncating it, both of which this contract forbids. The
// corpus cases reject-non-utc-offset and reject-picosecond-fraction each pin one of
// those, and each fails if the check is handed to time.Parse. A space separator is
// rejected by both, and the pattern pins it as defence in depth against the standard
// library loosening or tightening independently of the contract.
//
// The pattern is necessary but not sufficient: it admits impossible calendar dates such
// as 2026-02-30, so ParseTime also consults time.Parse for real-calendar validation.
var timestampPattern = regexp.MustCompile(
	`^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,9})?Z$`,
)

// MaxFractionDigits is the storage precision: nanoseconds.
const MaxFractionDigits = 9

// Timestamp is a UTC instant with nanosecond precision.
//
// The trailing 'Z' is mandatory. timestamp.schema.json states that "a stored timestamp
// with a non-zero offset is invalid, not merely non-canonical", so this type normalises
// to UTC at the edge and never stores an offset. Parse rejects an offset rather than
// converting it, because a producer emitting "+07:00" is reporting a clock that is not the
// platform's, and converting would hide that.
type Timestamp struct {
	instant time.Time
}

// ParseTimestamp parses the canonical form and normalises it to UTC.
func ParseTimestamp(s string) (Timestamp, error) {
	if !timestampPattern.MatchString(s) {
		return Timestamp{}, fmt.Errorf(
			"%w: %q must be UTC RFC 3339 with an optional 1-9 digit fraction and a trailing 'Z'",
			ErrInvalidTimestamp, s,
		)
	}
	// The pattern already constrains the shape, so this parse only has to read it. Using
	// RFC3339Nano with the 'Z' literal is safe: the pattern guarantees the zone is Z.
	parsed, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		// The pattern can admit a day that exists in the pattern but not in the calendar,
		// for example 2026-02-30. time.Parse is the authority on that.
		return Timestamp{}, fmt.Errorf("%w: %q is not a real instant: %v", ErrInvalidTimestamp, s, err)
	}
	return Timestamp{instant: parsed.UTC()}, nil
}

// MustParseTimestamp is ParseTimestamp for constants and tests.
func MustParseTimestamp(s string) Timestamp {
	ts, err := ParseTimestamp(s)
	if err != nil {
		panic(fmt.Sprintf("contracts: invalid constant timestamp %q: %v", s, err))
	}
	return ts
}

// TimestampFrom converts a time.Time, normalising to UTC.
//
// A non-UTC input is normalised rather than rejected here because the value is already
// constructed in-process; the rejection path belongs to ParseTimestamp, which handles
// untrusted text.
func TimestampFrom(t time.Time) Timestamp { return Timestamp{instant: t.UTC()} }

// IsZero reports whether the Timestamp was never set.
func (ts Timestamp) IsZero() bool { return ts.instant.IsZero() }

// Time returns the underlying instant in UTC.
func (ts Timestamp) Time() time.Time { return ts.instant }

// String renders the canonical form, always with nine fractional digits.
//
// timestamp.schema.json says producers SHOULD emit nine digits, so output is normalised
// even when the input was shorter. Input is therefore normalised rather than round-tripped
// verbatim; the decimal type is the one that must preserve trailing zeros, because
// trailing zeros in a timestamp are not significant.
func (ts Timestamp) String() string {
	return ts.instant.UTC().Format("2006-01-02T15:04:05.000000000Z")
}

// Before reports whether ts is strictly earlier than other.
func (ts Timestamp) Before(other Timestamp) bool { return ts.instant.Before(other.instant) }

// After reports whether ts is strictly later than other.
func (ts Timestamp) After(other Timestamp) bool { return ts.instant.After(other.instant) }

// Equal reports whether the two instants are the same.
func (ts Timestamp) Equal(other Timestamp) bool { return ts.instant.Equal(other.instant) }

// IsWithinSkew reports whether ts lies within the given window around reference.
//
// Clock drift is a first-class signal (timestamp.schema.json, docs/08). A source outside
// the window is unhealthy rather than silently trusted, so this is a predicate a caller
// can act on rather than a normalisation that discards the evidence.
func (ts Timestamp) IsWithinSkew(reference Timestamp, window time.Duration) bool {
	delta := ts.instant.Sub(reference.instant)
	if delta < 0 {
		delta = -delta
	}
	return delta <= window
}

// ErrInvalidContractValue means a value violates its contract.
var ErrInvalidContractValue = errors.New("invalid contract value")

// ErrorCode is the closed canonical error taxonomy from docs/03.
//
// The code is the stable machine contract. The accompanying message is human-facing and
// is never parsed, which is why it lives on ContractError rather than being part of the
// code's identity.
type ErrorCode string

// The eleven canonical error codes.
const (
	CodeValidation             ErrorCode = "VALIDATION_ERROR"
	CodeAuthentication         ErrorCode = "AUTHENTICATION_ERROR"
	CodeAuthorization          ErrorCode = "AUTHORIZATION_ERROR"
	CodeConflict               ErrorCode = "CONFLICT"
	CodeRiskRejected           ErrorCode = "RISK_REJECTED"
	CodeRateLimited            ErrorCode = "RATE_LIMITED"
	CodeDependencyUnavailable  ErrorCode = "DEPENDENCY_UNAVAILABLE"
	CodeTimeoutUnknown         ErrorCode = "TIMEOUT_UNKNOWN"
	CodeDataStale              ErrorCode = "DATA_STALE"
	CodeReconciliationRequired ErrorCode = "RECONCILIATION_REQUIRED"
	CodeInternal               ErrorCode = "INTERNAL_ERROR"
)

var errorCodes = map[ErrorCode]struct{}{
	CodeValidation: {}, CodeAuthentication: {}, CodeAuthorization: {},
	CodeConflict: {}, CodeRiskRejected: {}, CodeRateLimited: {},
	CodeDependencyUnavailable: {}, CodeTimeoutUnknown: {}, CodeDataStale: {},
	CodeReconciliationRequired: {}, CodeInternal: {},
}

// AllErrorCodes returns the taxonomy in a stable order, for documentation and tests.
func AllErrorCodes() []ErrorCode {
	return []ErrorCode{
		CodeValidation, CodeAuthentication, CodeAuthorization, CodeConflict,
		CodeRiskRejected, CodeRateLimited, CodeDependencyUnavailable,
		CodeTimeoutUnknown, CodeDataStale, CodeReconciliationRequired, CodeInternal,
	}
}

// String returns the wire form.
func (c ErrorCode) String() string { return string(c) }

// Valid reports whether the code is in the closed set.
func (c ErrorCode) Valid() bool {
	_, ok := errorCodes[c]
	return ok
}

// ParseErrorCode resolves a code name. An unknown value is an error rather than being
// mapped to INTERNAL_ERROR, because docs/03 requires unknown enum values to be treated as
// unsupported and never silently mapped.
func ParseErrorCode(s string) (ErrorCode, error) {
	c := ErrorCode(s)
	if !c.Valid() {
		return "", fmt.Errorf(
			"%w: %q is not a canonical error code; unknown values are unsupported, not mapped to a default",
			ErrInvalidContractValue, s,
		)
	}
	return c, nil
}

// IsDeny reports whether the code represents a denial that must not be overridden by a
// downstream component.
//
// Authorization policy cannot approve or override financial risk (ADR-018), and the Risk
// Engine veto is authoritative and final (docs/25 §3.1), so RISK_REJECTED is a deny. The
// identity and authorization codes are also denials: a failed identity dependency denies
// risk-increasing actions (docs/06 §8).
func (c ErrorCode) IsDeny() bool {
	switch c {
	case CodeRiskRejected, CodeAuthentication, CodeAuthorization:
		return true
	default:
		return false
	}
}

// TriggersReconciliation reports whether the code means authoritative state could not be
// established and a reconciliation or recovery workflow must start (docs/01 §6).
func (c ErrorCode) TriggersReconciliation() bool {
	return c == CodeTimeoutUnknown || c == CodeReconciliationRequired
}

// FailsClosed reports whether a dependency failure on this code must stop new
// risk-increasing work rather than degrading (docs/01 §6).
func (c ErrorCode) FailsClosed() bool {
	return c == CodeDependencyUnavailable || c == CodeDataStale || c.TriggersReconciliation()
}

// ContractError is the canonical error value.
type ContractError struct {
	code          ErrorCode
	message       string
	correlationID Identifier
	retryable     bool
	// details is structured, log-safe context. It is typed as an opaque map so no
	// credential can be smuggled in by a helper that assumes the map is safe.
	details map[string]any
}

// Error bounds maxMessageLength from error.schema.json.
const maxMessageLength = 1024

// NewContractError builds a canonical error, validating it against error.schema.json.
func NewContractError(code ErrorCode, message string, retryable bool) (ContractError, error) {
	if !code.Valid() {
		return ContractError{}, fmt.Errorf(
			"%w: %q is not a canonical error code", ErrInvalidContractValue, code,
		)
	}
	if len(message) < 1 {
		return ContractError{}, fmt.Errorf("%w: message must be non-empty", ErrInvalidContractValue)
	}
	if len(message) > maxMessageLength {
		return ContractError{}, fmt.Errorf(
			"%w: message is %d characters, exceeding the %d-character limit",
			ErrInvalidContractValue, len(message), maxMessageLength,
		)
	}
	// error.schema.json requires retryable to be FALSE for every risk-increasing command
	// whose prior outcome is unknown. TIMEOUT_UNKNOWN is precisely the code that means the
	// outcome is unknown, so a retryable timeout would permit a retry that could duplicate
	// exposure. docs/09 invariant 3 forbids exactly that.
	if code == CodeTimeoutUnknown && retryable {
		return ContractError{}, fmt.Errorf(
			"%w: %s may not be marked retryable; a retry after an unknown outcome "+
				"could increase exposure and must instead trigger reconciliation",
			ErrInvalidContractValue, code,
		)
	}
	return ContractError{code: code, message: message, retryable: retryable}, nil
}

// WithCorrelation attaches a correlation identifier.
func (e ContractError) WithCorrelation(id Identifier) ContractError {
	e.correlationID = id
	return e
}

// WithDetails attaches structured, log-safe context.
func (e ContractError) WithDetails(details map[string]any) ContractError {
	e.details = details
	return e
}

// Code returns the stable machine-readable code.
func (e ContractError) Code() ErrorCode { return e.code }

// Message returns the human-facing message. Never parse it.
func (e ContractError) Message() string { return e.message }

// CorrelationID returns the correlation identifier and whether one is set.
func (e ContractError) CorrelationID() (Identifier, bool) {
	if e.correlationID.IsZero() {
		return Identifier{}, false
	}
	return e.correlationID, true
}

// Retryable reports whether an identical retry could succeed without operator action.
func (e ContractError) Retryable() bool { return e.retryable }

// Details returns the structured context.
func (e ContractError) Details() map[string]any { return e.details }

// Error satisfies the error interface. The machine contract is the code, so the code leads
// the string; a log consumer that pattern-matches on this will not break if the message
// is reworded.
func (e ContractError) Error() string {
	return fmt.Sprintf("%s: %s", e.code, e.message)
}
