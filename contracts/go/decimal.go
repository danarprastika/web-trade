package contracts

import (
	"errors"
	"fmt"
	"math/big"
	"strings"
)

// Canonical decimal constraints, from contracts/schema/decimal.schema.json.
//
// The schema pattern is ^-?(0|[1-9][0-9]*)(\.[0-9]+)?$ with maxLength 40. The pattern is
// re-implemented here rather than approximated by a float parse, because the whole point
// of the type is to refuse everything the contract refuses.
const (
	decimalMaxLength = 40
	decimalMaxScale  = 38
)

// Errors returned by decimal operations. All wrap ErrInvalidDecimal so callers can
// distinguish a contract violation from an internal fault with errors.Is.
var (
	// ErrInvalidDecimal means the text does not satisfy the canonical decimal pattern.
	ErrInvalidDecimal = errors.New("invalid canonical decimal")

	// ErrScaleOutOfRange means an explicit scale falls outside the permitted 0..38 range.
	ErrScaleOutOfRange = errors.New("decimal scale out of range")
)

// Decimal is a base-10 decimal value that never touches IEEE-754 floating point.
//
// Two properties are load-bearing and both are exercised by the tests:
//
//  1. Exactness. The value is held as an arbitrary-precision integer coefficient plus a
//     decimal scale, not as a float64. A float64 has a 53-bit mantissa, so 0.1 is not
//     representable; a financial value that rounds on the way in is a defect that no
//     amount of downstream precision can undo.
//
//  2. Verbatim round-trip. The original canonical text is retained, so trailing zeros
//     survive. decimal.schema.json requires that "trailing zeros are otherwise preserved
//     verbatim to avoid silent precision loss" — a Decimal that parsed "1.500" and
//     serialised "1.5" would be losing information the contract told us to keep.
//
// The zero value is unset rather than numeric zero. An unset Decimal fails String and
// arithmetic, so a forgotten field is a construction error rather than a plausible 0.
type Decimal struct {
	// coeff is the value multiplied by 10^scale. big.Int is used because the schema
	// permits up to 38 significant digits, well beyond int64's ~19.
	coeff *big.Int
	scale int32
	// text is the canonical wire form exactly as parsed or as produced by arithmetic.
	// Retained for round-trip fidelity; coeff/scale alone cannot reproduce it.
	text string
}

// IsSet reports whether the Decimal was constructed or parsed.
func (d Decimal) IsSet() bool { return d.coeff != nil }

// String returns the canonical textual form, for example "-0.0001".
//
// The form always satisfies the schema pattern: no exponent, no leading zeros, no
// trailing dot, no bare plus.
func (d Decimal) String() string {
	if !d.IsSet() {
		return ""
	}
	return d.text
}

// Scale returns the number of digits after the decimal point.
func (d Decimal) Scale() int32 {
	if !d.IsSet() {
		return 0
	}
	return d.scale
}

// Sign returns -1, 0, or +1, matching math/big.Int.Sign.
func (d Decimal) Sign() int {
	if !d.IsSet() {
		return 0
	}
	return d.coeff.Sign()
}

// IsZero reports whether the value is numeric zero. An unset Decimal is not zero: it has
// no value at all, and treating it as zero is how an uninitialised field becomes a
// plausible-looking balance.
func (d Decimal) IsZero() bool { return d.IsSet() && d.coeff.Sign() == 0 }

// ParseDecimal parses the canonical decimal form.
//
// Rejected: JSON-style numbers (a Go float has already lost the value before this sees
// it, so accepting float64 here would defeat the type), exponents, leading zeros, a
// trailing dot, a bare plus sign, and any non-canonical whitespace. Uppercase or
// whitespace-padded input is rejected rather than trimmed, because a producer emitting
// " 0.5" has a bug that silent trimming would hide.
func ParseDecimal(s string) (Decimal, error) {
	if len(s) == 0 {
		return Decimal{}, fmt.Errorf("%w: empty string", ErrInvalidDecimal)
	}
	if len(s) > decimalMaxLength {
		return Decimal{}, fmt.Errorf(
			"%w: %q is %d characters, exceeding the %d-character limit",
			ErrInvalidDecimal, s, len(s), decimalMaxLength,
		)
	}

	body := s
	negative := false
	if strings.HasPrefix(body, "-") {
		negative = true
		body = body[1:]
	}
	// A bare plus is explicitly rejected above; confirm no second sign slipped through.
	if strings.HasPrefix(body, "+") {
		return Decimal{}, fmt.Errorf("%w: %q uses a bare plus sign", ErrInvalidDecimal, s)
	}

	intPart, fracPart, hasFrac := strings.Cut(body, ".")
	if intPart == "" {
		return Decimal{}, fmt.Errorf("%w: %q has no integer part", ErrInvalidDecimal, s)
	}
	// "0" is legal; "00" and "0123" are not. This is the leading-zero rule the schema
	// encodes via (0|[1-9][0-9]*).
	if len(intPart) > 1 && intPart[0] == '0' {
		return Decimal{}, fmt.Errorf("%w: %q has a leading zero", ErrInvalidDecimal, s)
	}
	for i := 0; i < len(intPart); i++ {
		if intPart[i] < '0' || intPart[i] > '9' {
			return Decimal{}, fmt.Errorf("%w: %q contains a non-digit %q", ErrInvalidDecimal, s, string(intPart[i]))
		}
	}

	if hasFrac {
		// A trailing dot ("123.") yields an empty fraction, which the schema rejects.
		if fracPart == "" {
			return Decimal{}, fmt.Errorf("%w: %q has a trailing decimal point", ErrInvalidDecimal, s)
		}
		if len(fracPart) > decimalMaxScale {
			return Decimal{}, fmt.Errorf(
				"%w: %q has %d fractional digits, exceeding the maximum scale of %d",
				ErrInvalidDecimal, s, len(fracPart), decimalMaxScale,
			)
		}
		for i := 0; i < len(fracPart); i++ {
			if fracPart[i] < '0' || fracPart[i] > '9' {
				return Decimal{}, fmt.Errorf("%w: %q contains a non-digit in the fraction", ErrInvalidDecimal, s)
			}
		}
	}

	scale := int32(0)
	if hasFrac {
		scale = int32(len(fracPart))
	}

	// Build the coefficient by concatenating the digit runs, so the coefficient is exact
	// for any length the schema permits.
	digits := intPart + fracPart
	coeff, ok := new(big.Int).SetString(digits, 10)
	if !ok {
		return Decimal{}, fmt.Errorf("%w: %q could not be read as a base-10 integer", ErrInvalidDecimal, s)
	}
	if negative {
		coeff.Neg(coeff)
	}

	// Normalise a negative zero to "0". The schema pattern would permit "-0", but
	// emitting it would make equal values compare unequal textually and would let a
	// sign convention leak into storage. Zero is written as "0".
	if coeff.Sign() == 0 {
		return Decimal{coeff: new(big.Int), scale: 0, text: "0"}, nil
	}

	return Decimal{coeff: coeff, scale: scale, text: s}, nil
}

// MustParseDecimal is ParseDecimal for constants and tests. It panics on failure, so it
// must not be used on input that originates outside the program.
func MustParseDecimal(s string) Decimal {
	d, err := ParseDecimal(s)
	if err != nil {
		panic(fmt.Sprintf("contracts: invalid constant decimal %q: %v", s, err))
	}
	return d
}

// Zero returns an explicit numeric zero, distinct from the unset zero value.
func Zero() Decimal { return MustParseDecimal("0") }

// align returns d's coefficient rescaled to target, which must be >= d's own scale.
// Widening is always lossless because it only appends zeros.
func (d Decimal) align(target int32) *big.Int {
	if d.scale == target {
		return new(big.Int).Set(d.coeff)
	}
	shift := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(target-d.scale)), nil)
	return new(big.Int).Mul(d.coeff, shift)
}

// Add returns the exact sum, rescaled to the wider of the two scales.
//
// No rounding occurs. Aligning two exact decimals to a common scale is a multiplication
// by a power of ten, so the result is exact.
func (d Decimal) Add(other Decimal) (Decimal, error) {
	return d.addSub(other, false)
}

// Sub returns the exact difference, rescaled to the wider of the two scales.
func (d Decimal) Sub(other Decimal) (Decimal, error) {
	return d.addSub(other, true)
}

func (d Decimal) addSub(other Decimal, subtract bool) (Decimal, error) {
	if !d.IsSet() || !other.IsSet() {
		return Decimal{}, fmt.Errorf("%w: operand is unset", ErrInvalidDecimal)
	}
	target := d.scale
	if other.scale > target {
		target = other.scale
	}
	left := d.align(target)
	right := other.align(target)

	var sum *big.Int
	if subtract {
		sum = new(big.Int).Sub(left, right)
	} else {
		sum = new(big.Int).Add(left, right)
	}

	// The arithmetic result is rendered at `target` scale with trailing zeros preserved,
	// matching the wider operand. This keeps "1.50" + "1.50" reading as "3.00" rather
	// than silently narrowing to "3", which is the precision loss the contract forbids.
	return Decimal{coeff: sum, scale: target, text: formatDecimal(sum, target)}, nil
}

// Multiply returns the exact product.
//
// The result scale is the sum of the operand scales, because the fractional digits of the
// two operands genuinely combine: 1.5 times 1.5 is 2.25, and reducing that to scale 1 would
// mean rounding. quantity.schema.json states that "rounding is only ever performed by an
// explicitly named, audited rounding policy", so no rounding happens here and the exact
// product is returned instead.
//
// A pair whose combined scale exceeds the schema maximum is refused rather than truncated.
// Truncation is the dangerous direction here: a caller computing an order's notional and
// silently losing digits at the far end would understate the order's size, and a limit
// checked against an understated value passes when it should fail.
func (d Decimal) Multiply(other Decimal) (Decimal, error) {
	if !d.IsSet() || !other.IsSet() {
		return Decimal{}, fmt.Errorf("%w: operand is unset", ErrInvalidDecimal)
	}
	scale := d.scale + other.scale
	if scale > decimalMaxScale {
		return Decimal{}, fmt.Errorf(
			"%w: product scale %d (%d + %d) exceeds the maximum scale of %d",
			ErrScaleOutOfRange, scale, d.scale, other.scale, decimalMaxScale,
		)
	}
	product := new(big.Int).Mul(d.coeff, other.coeff)
	return Decimal{coeff: product, scale: scale, text: formatDecimal(product, scale)}, nil
}

// Cmp compares two decimals by numeric value, ignoring scale. 0.50 and 0.5 are equal.
func (d Decimal) Cmp(other Decimal) (int, error) {
	if !d.IsSet() || !other.IsSet() {
		return 0, fmt.Errorf("%w: operand is unset", ErrInvalidDecimal)
	}
	target := d.scale
	if other.scale > target {
		target = other.scale
	}
	return d.align(target).Cmp(other.align(target)), nil
}

// Neg returns the additive inverse.
func (d Decimal) Neg() Decimal {
	if !d.IsSet() {
		return Decimal{}
	}
	coeff := new(big.Int).Neg(d.coeff)
	text := d.text
	if coeff.Sign() == 0 {
		text = "0"
	} else if !strings.HasPrefix(text, "-") {
		text = "-" + text
	} else {
		text = text[1:]
	}
	return Decimal{coeff: coeff, scale: d.scale, text: text}
}

// RescaleTo returns the same value expressed at the given scale, or an error if that
// would require discarding digits.
//
// Rounding is deliberately absent. quantity.schema.json states that "rounding is only
// ever performed by an explicitly named, audited rounding policy", so this function
// refuses rather than guessing. A caller that needs a rounded value must say which policy
// it is applying and record that decision.
func (d Decimal) RescaleTo(target int32) (Decimal, error) {
	if !d.IsSet() {
		return Decimal{}, fmt.Errorf("%w: operand is unset", ErrInvalidDecimal)
	}
	if target < 0 || target > decimalMaxScale {
		return Decimal{}, fmt.Errorf("%w: %d is outside 0..%d", ErrScaleOutOfRange, target, decimalMaxScale)
	}
	if target > d.scale {
		// Widening: append zeros. Always lossless.
		return Decimal{
			coeff: d.align(target),
			scale: target,
			text:  widenText(d.text, d.scale, target),
		}, nil
	}
	if target == d.scale {
		return d, nil
	}
	// Narrowing: only permitted when the discarded digits are all zero, which is a lossless
	// representation change rather than a rounding.
	divisor := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(d.scale-target)), nil)
	quotient, remainder := new(big.Int).QuoRem(d.coeff, divisor, new(big.Int))
	if remainder.Sign() != 0 {
		return Decimal{}, fmt.Errorf(
			"%w: narrowing %q to scale %d would discard non-zero digits; an explicit rounding policy is required",
			ErrInvalidDecimal, d.text, target,
		)
	}
	return Decimal{coeff: quotient, scale: target, text: formatDecimal(quotient, target)}, nil
}

// widenText renders value at a larger scale by appending zeros, preserving the sign.
func widenText(text string, from, to int32) string {
	if from == to {
		return text
	}
	intPart, fracPart, hasFrac := strings.Cut(text, ".")
	if !hasFrac {
		fracPart = ""
	}
	return intPart + "." + fracPart + strings.Repeat("0", int(to-from))
}

// formatDecimal renders a coefficient at the given scale. A zero coefficient always
// renders as "0" with no fractional part, matching ParseDecimal's normalisation.
func formatDecimal(coeff *big.Int, scale int32) string {
	if coeff.Sign() == 0 {
		return "0"
	}
	negative := coeff.Sign() < 0
	abs := new(big.Int).Abs(coeff)
	digits := abs.String()

	var text string
	switch {
	case scale == 0:
		text = digits
	case len(digits) > int(scale):
		cut := len(digits) - int(scale)
		text = digits[:cut] + "." + digits[cut:]
	default:
		// Pad on the left so the point lands the right number of places from the end.
		text = "0." + strings.Repeat("0", int(scale)-len(digits)) + digits
	}
	if negative {
		text = "-" + text
	}
	return text
}
