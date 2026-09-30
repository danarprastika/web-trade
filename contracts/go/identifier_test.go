package contracts

import (
	"errors"
	"testing"
)

// These cases mirror the identifier section of contracts/fixtures/conformance.json. The
// corpus is the shared cross-language contract (docs/02 section 9); this test asserts that
// the Go binding agrees with it rather than re-deriving the rules.
//
// The corpus itself is executed end to end by tests/contracts/validate_contracts.py. A
// binding that disagreed with these cases could not be promoted.
func TestParseIdentifier(t *testing.T) {
	t.Parallel()

	const valid = "01hq3k7m9x2f5rb8n0v6c4tqwx"

	tests := []struct {
		name    string
		input   string
		wantErr bool
	}{
		// Accept: identifier/accept-valid-order
		{name: "accept valid order", input: PrefixOrder + valid},
		{name: "accept valid command", input: PrefixCommand + valid},
		{name: "accept valid event", input: PrefixEvent + valid},
		{name: "accept valid ledger", input: PrefixLedger + valid},

		// Reject: identifier/reject-uppercase
		{name: "reject uppercase", input: "ORD_01HQ3K7M9X2F5RB8N0V6C4TQWX", wantErr: true},
		{name: "reject mixed case", input: PrefixOrder + "01HQ3k7m9x2f5rb8n0v6c4tqwx", wantErr: true},

		// Reject: identifier/reject-ambiguous-char-{i,l,o,u}
		{name: "reject ambiguous i", input: PrefixOrder + "01hq3k7m9x2f5rb8n0v6c4tqiw", wantErr: true},
		{name: "reject ambiguous l", input: PrefixOrder + "01hq3k7m9x2f5rb8n0v6c4tlqx", wantErr: true},
		{name: "reject ambiguous o", input: PrefixOrder + "01hq3k7m9x2f5rb8n0v6c4toqx", wantErr: true},
		{name: "reject ambiguous u", input: PrefixOrder + "01hq3k7m9x2f5rb8n0v6c4tuqx", wantErr: true},

		// Reject: identifier/reject-unknown-prefix
		{name: "reject unknown prefix", input: "xyz_" + valid, wantErr: true},
		{name: "reject no prefix", input: valid, wantErr: true},

		// Reject: identifier/reject-short-payload
		{name: "reject short payload", input: PrefixOrder + "01hq3k7m9x2f5rb8n0v6c4tq", wantErr: true},
		{name: "reject long payload", input: PrefixOrder + valid + "x", wantErr: true},

		// Additional binding-level rejections
		{name: "reject empty", input: "", wantErr: true},
		{name: "reject prefix only", input: PrefixOrder, wantErr: true},
		{name: "reject whitespace", input: PrefixOrder + " " + valid[1:], wantErr: true},
		{name: "reject hyphen", input: PrefixOrder + "01hq3k7m9x2f5rb8n-0v6c4tqwx", wantErr: true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()

			got, err := ParseIdentifier(tt.input)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("ParseIdentifier(%q) = %q, want error", tt.input, got)
				}
				if !errors.Is(err, ErrInvalidIdentifier) {
					t.Fatalf("ParseIdentifier(%q) error = %v, want ErrInvalidIdentifier", tt.input, err)
				}
				return
			}
			if err != nil {
				t.Fatalf("ParseIdentifier(%q) unexpected error: %v", tt.input, err)
			}
			if got.String() != tt.input {
				t.Errorf("round trip = %q, want %q", got.String(), tt.input)
			}
			if got.IsZero() {
				t.Error("parsed identifier reported IsZero")
			}
		})
	}
}

func TestZeroIdentifierIsInvalid(t *testing.T) {
	t.Parallel()

	var id Identifier
	if !id.IsZero() {
		t.Error("the zero Identifier must report IsZero")
	}
	// A forgotten field must not produce a plausible-looking value.
	if id.String() != "" {
		t.Errorf("zero Identifier stringified to %q, want empty", id.String())
	}
}

func TestIdentifierPrefixIsPreserved(t *testing.T) {
	t.Parallel()

	const payload = "01hq3k7m9x2f5rb8n0v6c4tqwx"

	for _, prefix := range []string{
		PrefixCommand, PrefixEvent, PrefixOrder, PrefixStrategy,
		PrefixModel, PrefixRun, PrefixPosition, PrefixLedger,
	} {
		id, err := ParseIdentifier(prefix + payload)
		if err != nil {
			t.Fatalf("ParseIdentifier(%q) unexpected error: %v", prefix+payload, err)
		}
		if id.Prefix() != prefix {
			t.Errorf("Prefix() = %q, want %q", id.Prefix(), prefix)
		}
	}
}
