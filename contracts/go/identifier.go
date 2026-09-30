package contracts

import (
	"errors"
	"fmt"
)

// Identifier prefixes defined by docs/03_CANONICAL_CONTRACTS.md. The payload alphabet is
// Crockford Base32, which omits I, L, O, and U to avoid transcription ambiguity with 1 and 0.
const (
	PrefixCommand    = "cmd_"
	PrefixEvent      = "evt_"
	PrefixOrder      = "ord_"
	PrefixStrategy   = "str_"
	PrefixModel      = "mdl_"
	PrefixRun        = "run_"
	PrefixPosition   = "pos_"
	PrefixLedger     = "led_"
	payloadLength    = 26
	maxIdentifierLen = len(PrefixStrategy) + payloadLength
)

var validPrefixes = map[string]struct{}{
	PrefixCommand:  {},
	PrefixEvent:    {},
	PrefixOrder:    {},
	PrefixStrategy: {},
	PrefixModel:    {},
	PrefixRun:      {},
	PrefixPosition: {},
	PrefixLedger:   {},
}

// ErrInvalidIdentifier is returned when an identifier does not satisfy the canonical format.
var ErrInvalidIdentifier = errors.New("invalid canonical identifier")

// Identifier is a typed, prefixed, lowercase Crockford Base32 identifier.
//
// The zero value is deliberately invalid: an unset Identifier fails validation, so a
// forgotten field is a construction error rather than a plausible-looking value that
// silently reaches a venue.
type Identifier struct {
	prefix  string
	payload string
}

// String returns the canonical textual form, for example "ord_01hq3k7m9x2f5rb8n0v6c4tqwx".
func (i Identifier) String() string {
	return i.prefix + i.payload
}

// Prefix returns the entity prefix including its trailing underscore.
func (i Identifier) Prefix() string { return i.prefix }

// IsZero reports whether the identifier was never set.
func (i Identifier) IsZero() bool { return i.prefix == "" && i.payload == "" }

// ParseIdentifier parses the canonical textual form.
//
// The payload must be lowercase. Uppercase input is rejected rather than normalised: a
// producer emitting "ORD_..." is a bug, and silently fixing it would hide that bug behind a
// value that looks correct. The conformance corpus case identifier/reject-uppercase pins
// exactly this behaviour.
func ParseIdentifier(s string) (Identifier, error) {
	if len(s) > maxIdentifierLen {
		return Identifier{}, fmt.Errorf("%w: %q exceeds %d characters", ErrInvalidIdentifier, s, maxIdentifierLen)
	}

	for prefix := range validPrefixes {
		if len(s) > len(prefix) && s[:len(prefix)] == prefix {
			payload := s[len(prefix):]
			if len(payload) != payloadLength {
				return Identifier{}, fmt.Errorf(
					"%w: %q payload must be exactly %d characters, got %d",
					ErrInvalidIdentifier, s, payloadLength, len(payload),
				)
			}
			for i := 0; i < len(payload); i++ {
				if !isCrockfordLower(payload[i]) {
					return Identifier{}, fmt.Errorf(
						"%w: %q contains %q at offset %d, which is outside lowercase Crockford Base32",
						ErrInvalidIdentifier, s, string(payload[i]), i,
					)
				}
			}
			return Identifier{prefix: prefix, payload: payload}, nil
		}
	}

	return Identifier{}, fmt.Errorf("%w: %q has no registered prefix", ErrInvalidIdentifier, s)
}

// isCrockfordLower reports whether b is a lowercase Crockford Base32 character.
//
// The alphabet is 0-9, a-h, j, k, m, n, p-t, v-z. Note the deliberate gaps: i, l, o, u
// are excluded because they are routinely confused with 1 and 0 when transcribed by hand,
// by voice, or by optical character recognition.
func isCrockfordLower(b byte) bool {
	switch {
	case b >= '0' && b <= '9':
		return true
	case b >= 'a' && b <= 'h':
		return true
	case b == 'j' || b == 'k':
		return true
	case b == 'm' || b == 'n':
		return true
	case b >= 'p' && b <= 't':
		return true
	case b >= 'v' && b <= 'z':
		return true
	default:
		return false
	}
}
