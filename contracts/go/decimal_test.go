package contracts

import (
	"errors"
	"strings"
	"testing"
)

// TestParseDecimalCorpus covers every decimal case in the shared conformance corpus.
// Written from the corpus file rather than from the implementation, so a change to the
// implementation cannot quietly redefine what the contract accepts.
func TestParseDecimalCorpus(t *testing.T) {
	accept := []string{"1234", "-0.0001", "0"}
	reject := []string{
		"1.234e3",  // exponent
		"0123.45",  // leading zero
		"123.",     // trailing dot
		"+123",     // bare plus
		"",         // empty
		"-",        // sign only
		".5",       // no integer part
		"1.2.3",    // two points
		"1e5",      // exponent without decimal point
		" 1.5",     // leading space
		"1.5 ",     // trailing space
		"1,5",      // comma decimal separator
		"NaN",      // not a number
		"Infinity", // not finite
	}

	for _, s := range accept {
		if _, err := ParseDecimal(s); err != nil {
			t.Errorf("ParseDecimal(%q) = error %v, want accept", s, err)
		}
	}
	for _, s := range reject {
		if _, err := ParseDecimal(s); err == nil {
			t.Errorf("ParseDecimal(%q) = nil error, want reject", s)
		}
	}
}

func TestDecimalRoundTripPreservesTrailingZeros(t *testing.T) {
	// decimal.schema.json: "trailing zeros are otherwise preserved verbatim to avoid
	// silent precision loss". This is the case a naive big.Float or float64 loses.
	for _, s := range []string{"1.500", "0.00000001", "-0.0001", "1234.5678", "0", "100.00"} {
		d, err := ParseDecimal(s)
		if err != nil {
			t.Fatalf("ParseDecimal(%q): %v", s, err)
		}
		if got := d.String(); got != s {
			t.Errorf("round trip %q = %q, want %q", s, got, s)
		}
	}
}

func TestDecimalZeroValueIsUnsetNotZero(t *testing.T) {
	// An unset Decimal must not behave like 0, or a forgotten field becomes a balance.
	var d Decimal
	if d.IsSet() {
		t.Error("zero value Decimal reports IsSet() = true")
	}
	if d.IsZero() {
		t.Error("zero value Decimal reports IsZero() = true; an unset value is not numeric zero")
	}
	if d.String() != "" {
		t.Errorf("zero value String() = %q, want empty", d.String())
	}
	if _, err := d.Add(MustParseDecimal("1")); !errors.Is(err, ErrInvalidDecimal) {
		t.Errorf("Add on unset operand = %v, want ErrInvalidDecimal", err)
	}
	if Zero().String() != "0" {
		t.Errorf("Zero().String() = %q, want \"0\"", Zero().String())
	}
}

func TestDecimalNegativeZeroNormalises(t *testing.T) {
	// The schema pattern would permit "-0", but storing it would make equal values
	// compare unequal textually and leak a sign convention into storage.
	d, err := ParseDecimal("-0")
	if err != nil {
		t.Fatalf("ParseDecimal(\"-0\"): %v", err)
	}
	if got := d.String(); got != "0" {
		t.Errorf("ParseDecimal(\"-0\").String() = %q, want \"0\"", got)
	}
	if !d.IsZero() {
		t.Error("ParseDecimal(\"-0\").IsZero() = false, want true")
	}
}

func TestDecimalRejectsOverlongInput(t *testing.T) {
	// maxLength is 40. A 41-character value must be refused, not truncated.
	long := "1" + strings.Repeat("0", 40)
	if _, err := ParseDecimal(long); !errors.Is(err, ErrInvalidDecimal) {
		t.Errorf("ParseDecimal(41 chars) = %v, want ErrInvalidDecimal", err)
	}
}

func TestDecimalExceedsInt64Exactly(t *testing.T) {
	// 38 significant digits is permitted by the schema and far beyond int64. A float64 or
	// int64 implementation would corrupt this silently.
	const big38 = "99999999999999999999999999999999999999"
	d := MustParseDecimal(big38)
	if d.String() != big38 {
		t.Errorf("round trip = %q, want %q", d.String(), big38)
	}
	one := MustParseDecimal("1")
	sum, err := d.Add(one)
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if sum.String() != "100000000000000000000000000000000000000" {
		t.Errorf("Add = %q, want 100000000000000000000000000000000000000", sum.String())
	}
}

func TestDecimalArithmeticIsExact(t *testing.T) {
	// 0.1 + 0.2 == 0.3 exactly. In float64 it does not: the sum is 0.30000000000000004.
	// This test is the reason the type exists.
	a := MustParseDecimal("0.1")
	b := MustParseDecimal("0.2")
	sum, err := a.Add(b)
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if sum.String() != "0.3" {
		t.Errorf("0.1 + 0.2 = %q, want 0.3", sum.String())
	}

	// Addition widens to the wider scale rather than narrowing away precision.
	tenth, hundredth := MustParseDecimal("1.5"), MustParseDecimal("1.50")
	added, err := tenth.Add(hundredth)
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if added.String() != "3.00" {
		t.Errorf("1.5 + 1.50 = %q, want 3.00", added.String())
	}
}

func TestDecimalSubtractAcrossSigns(t *testing.T) {
	// Regression guard: an earlier implementation computed d + o - o for Sub, which
	// silently returned the left operand.
	got, err := MustParseDecimal("10").Sub(MustParseDecimal("3"))
	if err != nil {
		t.Fatalf("Sub: %v", err)
	}
	if got.String() != "7" {
		t.Errorf("10 - 3 = %q, want 7", got.String())
	}
	got, err = MustParseDecimal("3").Sub(MustParseDecimal("10"))
	if err != nil {
		t.Fatalf("Sub: %v", err)
	}
	if got.String() != "-7" {
		t.Errorf("3 - 10 = %q, want -7", got.String())
	}
}

func TestDecimalCmpIgnoresScale(t *testing.T) {
	c, err := MustParseDecimal("0.50").Cmp(MustParseDecimal("0.5"))
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if c != 0 {
		t.Errorf("0.50 cmp 0.5 = %d, want 0", c)
	}
	c, err = MustParseDecimal("0.49").Cmp(MustParseDecimal("0.5"))
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if c >= 0 {
		t.Errorf("0.49 cmp 0.5 = %d, want < 0", c)
	}
}

func TestDecimalNeg(t *testing.T) {
	if got := MustParseDecimal("0.0001").Neg().String(); got != "-0.0001" {
		t.Errorf("Neg(0.0001) = %q, want -0.0001", got)
	}
	if got := MustParseDecimal("-0.0001").Neg().String(); got != "0.0001" {
		t.Errorf("Neg(-0.0001) = %q, want 0.0001", got)
	}
}

func TestDecimalRescaleRefusesToRound(t *testing.T) {
	// quantity.schema.json: rounding is only ever performed by an explicitly named,
	// audited policy. RescaleTo must refuse rather than invent digits.
	if _, err := MustParseDecimal("1.005").RescaleTo(2); err == nil {
		t.Error("RescaleTo(2) on 1.005 = nil error, want refusal to round")
	}
	// Widening is always allowed, and appends zeros.
	got, err := MustParseDecimal("1.5").RescaleTo(4)
	if err != nil {
		t.Fatalf("RescaleTo(4): %v", err)
	}
	if got.String() != "1.5000" {
		t.Errorf("RescaleTo(4) of 1.5 = %q, want 1.5000", got.String())
	}
	// Narrowing with only zero digits discarded is lossless and permitted.
	got, err = MustParseDecimal("1.500").RescaleTo(1)
	if err != nil {
		t.Fatalf("RescaleTo(1) on 1.500: %v", err)
	}
	if got.String() != "1.5" {
		t.Errorf("RescaleTo(1) of 1.500 = %q, want 1.5", got.String())
	}
	// Out-of-range scale is refused.
	if _, err := MustParseDecimal("1.5").RescaleTo(39); !errors.Is(err, ErrScaleOutOfRange) {
		t.Errorf("RescaleTo(39) = %v, want ErrScaleOutOfRange", err)
	}
}
