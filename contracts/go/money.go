package contracts

import (
	"errors"
	"fmt"
	"regexp"
)

// ErrInvalidMoney means a money value violates the contract.
var ErrInvalidMoney = errors.New("invalid canonical money")

// ErrCurrencyMismatch means two amounts carry different currencies.
//
// This is a distinct sentinel rather than a wrapped ErrInvalidMoney because
// money.schema.json names it as its own invariant: "a currency mismatch between an amount
// and a venue or account is a hard rejection, not a conversion". A caller reconciling
// against a venue must be able to tell that specific refusal apart from a malformed
// amount, and errors.Is is the only way to do that across a service boundary.
var ErrCurrencyMismatch = errors.New("currency mismatch")

// currencyPattern is the schema pattern ^[A-Z][A-Z0-9]{1,11}$: an ISO 4217 alphabetic
// code, or an explicitly configured asset code for a digital asset. Lowercase is rejected
// rather than upcased, because a producer emitting "usd" has a defect that silent
// normalisation would hide.
var currencyPattern = regexp.MustCompile(`^[A-Z][A-Z0-9]{1,11}$`)

// Money is an amount bound to a currency. Never a bare number, never a float.
//
// The currency is not optional and is never inferred. docs/03 requires an explicit
// currency, and money.schema.json states that "a currency mismatch between an amount and
// a venue or account is a hard rejection, not a conversion". Carrying the currency in the
// type is what makes that check possible at the boundary rather than after a conversion has
// already happened.
type Money struct {
	currency string
	amount   Decimal
	// scale is the optional explicit minor-unit scale, absent when the amount's own digit
	// count is authoritative. Pointer semantics because absent and zero differ: scale 0 is
	// a real, declared scale, while absent means "unspecified".
	scale *int32
}

// NewMoney builds a Money without an explicit scale.
func NewMoney(currency string, amount Decimal) (Money, error) {
	return NewMoneyWithScale(currency, amount, nil)
}

// NewMoneyWithScale builds a Money with an explicit minor-unit scale.
func NewMoneyWithScale(currency string, amount Decimal, scale *int32) (Money, error) {
	if !amount.IsSet() {
		return Money{}, fmt.Errorf("%w: amount is unset", ErrInvalidMoney)
	}
	if !currencyPattern.MatchString(currency) {
		return Money{}, fmt.Errorf(
			"%w: currency %q must match %s", ErrInvalidMoney, currency, currencyPattern,
		)
	}
	if scale != nil {
		if *scale < 0 || *scale > decimalMaxScale {
			return Money{}, fmt.Errorf("%w: scale %d is outside 0..%d", ErrScaleOutOfRange, *scale, decimalMaxScale)
		}
	}
	return Money{currency: currency, amount: amount, scale: scale}, nil
}

// Currency returns the currency or asset code.
func (m Money) Currency() string { return m.currency }

// Amount returns the amount.
func (m Money) Amount() Decimal { return m.amount }

// Scale returns the explicit scale, and whether one was declared.
func (m Money) Scale() (int32, bool) {
	if m.scale == nil {
		return 0, false
	}
	return *m.scale, true
}

// String renders the amount only, for logging. The currency is deliberately not folded
// into this string, so a log line can never be read as a bare number.
func (m Money) String() string { return m.amount.String() }

// ValidatePrecisionAgainst reports whether the amount's own scale is compatible with the
// declared minor-unit scale, and returns an error if it is not.
//
// A mismatch is a rejection, never a rounding. docs/03 requires amount precision to be
// validated before submission, and quantity.schema.json states that a non-conforming
// quantity is "rejected, never rounded silently".
func (m Money) ValidatePrecisionAgainst(declaredScale int32) error {
	if declaredScale < 0 || declaredScale > decimalMaxScale {
		return fmt.Errorf("%w: declared scale %d is outside 0..%d", ErrScaleOutOfRange, declaredScale, decimalMaxScale)
	}
	if m.amount.Scale() > declaredScale {
		return fmt.Errorf(
			"%w: amount %q has %d decimal places but the currency's scale is %d",
			ErrInvalidMoney, m.amount.String(), m.amount.Scale(), declaredScale,
		)
	}
	return nil
}

// RequireSameCurrency reports an error unless the two amounts share a currency.
//
// This is the check the contract requires at a venue or account boundary. It is a
// comparison, never a conversion: converting would change a financial value as a side
// effect of a boundary check.
func (m Money) RequireSameCurrency(other Money) error {
	if m.currency != other.currency {
		return fmt.Errorf(
			"%w: %q and %q; conversion is not permitted at a boundary",
			ErrCurrencyMismatch, m.currency, other.currency,
		)
	}
	return nil
}

// Add returns the exact sum. The currencies must match; a sum across currencies is a
// modelling error, not something to resolve by picking one side's currency.
func (m Money) Add(other Money) (Money, error) {
	if err := m.RequireSameCurrency(other); err != nil {
		return Money{}, err
	}
	sum, err := m.amount.Add(other.amount)
	if err != nil {
		return Money{}, err
	}
	// The explicit scale, if declared, must survive the operation: widening the amount
	// never changes the currency's minor-unit scale.
	return NewMoneyWithScale(m.currency, sum, m.scale)
}

// Sub returns the exact difference. The currencies must match.
//
// A ledger cannot function without subtraction: every position, balance, and realised PnL
// entry is a debit against a credit, and a ledger that only accumulates is a ledger that
// cannot be reconciled against a venue. The currency check is the same hard rejection as
// Add, because a difference across currencies is a conversion masquerading as arithmetic.
func (m Money) Sub(other Money) (Money, error) {
	if err := m.RequireSameCurrency(other); err != nil {
		return Money{}, err
	}
	diff, err := m.amount.Sub(other.amount)
	if err != nil {
		return Money{}, err
	}
	return NewMoneyWithScale(m.currency, diff, m.scale)
}

// Cmp compares two amounts by exact value, ignoring scale: 1.50 and 1.5 are equal.
//
// It returns -1, 0, or 1, and refuses to compare across currencies. Returning 0 for two
// different currencies would let a caller treat a EUR balance as satisfying a USD
// obligation, which is exactly the class of error this platform exists to prevent.
func (m Money) Cmp(other Money) (int, error) {
	if err := m.RequireSameCurrency(other); err != nil {
		return 0, err
	}
	return m.amount.Cmp(other.amount)
}

// Equal reports whether two amounts have the same currency and the same exact value.
func (m Money) Equal(other Money) bool {
	if m.currency != other.currency {
		return false
	}
	if !m.amount.IsSet() || !other.amount.IsSet() {
		return m.amount.IsSet() == other.amount.IsSet()
	}
	c, err := m.amount.Cmp(other.amount)
	return err == nil && c == 0
}

// ErrInvalidQuantity means a quantity violates the contract.
var ErrInvalidQuantity = errors.New("invalid canonical quantity")

// QuantityUnit is the closed set of quantity units from quantity.schema.json.
//
// docs/03 requires that "unknown enum values are treated as unsupported, not silently
// mapped", so this is a closed set with no default case that guesses.
type QuantityUnit string

// The permitted quantity units.
const (
	UnitBaseAsset  QuantityUnit = "BASE_ASSET"
	UnitQuoteAsset QuantityUnit = "QUOTE_ASSET"
	UnitContract   QuantityUnit = "CONTRACT"
	UnitLot        QuantityUnit = "LOT"
	UnitShare      QuantityUnit = "SHARE"
	UnitUnits      QuantityUnit = "UNITS"
)

var validUnits = map[QuantityUnit]struct{}{
	UnitBaseAsset: {}, UnitQuoteAsset: {}, UnitContract: {},
	UnitLot: {}, UnitShare: {}, UnitUnits: {},
}

// String returns the wire form.
func (u QuantityUnit) String() string { return string(u) }

// Valid reports whether the unit is in the closed set.
func (u QuantityUnit) Valid() bool {
	_, ok := validUnits[u]
	return ok
}

// ParseQuantityUnit resolves a unit name, rejecting anything outside the closed set.
func ParseQuantityUnit(s string) (QuantityUnit, error) {
	u := QuantityUnit(s)
	if !u.Valid() {
		return "", fmt.Errorf(
			"%w: %q is not a known unit; unknown values are unsupported, not mapped to a default",
			ErrInvalidQuantity, s,
		)
	}
	return u, nil
}

// Quantity is an instrument quantity or price with optional venue scale metadata.
//
// Sign carries no direction. quantity.schema.json states that "direction is carried by
// the order side, not the sign of the quantity", so this type deliberately does not
// expose a direction or a "long/short" interpretation.
type Quantity struct {
	value Decimal
	unit  QuantityUnit
	scale *int32
}

// NewQuantity builds a Quantity without explicit venue scale.
func NewQuantity(value Decimal, unit QuantityUnit) (Quantity, error) {
	return NewQuantityWithScale(value, unit, nil)
}

// NewQuantityWithScale builds a Quantity with an explicit venue scale.
func NewQuantityWithScale(value Decimal, unit QuantityUnit, scale *int32) (Quantity, error) {
	if !value.IsSet() {
		return Quantity{}, fmt.Errorf("%w: value is unset", ErrInvalidQuantity)
	}
	if !unit.Valid() {
		return Quantity{}, fmt.Errorf(
			"%w: %q is not a known unit; unknown values are unsupported", ErrInvalidQuantity, unit,
		)
	}
	if scale != nil && (*scale < 0 || *scale > decimalMaxScale) {
		return Quantity{}, fmt.Errorf("%w: scale %d is outside 0..%d", ErrScaleOutOfRange, *scale, decimalMaxScale)
	}
	return Quantity{value: value, unit: unit, scale: scale}, nil
}

// Value returns the decimal value.
func (q Quantity) Value() Decimal { return q.value }

// Unit returns the unit of measure.
func (q Quantity) Unit() QuantityUnit { return q.unit }

// Scale returns the explicit venue scale, and whether one was declared.
func (q Quantity) Scale() (int32, bool) {
	if q.scale == nil {
		return 0, false
	}
	return *q.scale, true
}

// String renders the value only, for logging.
func (q Quantity) String() string { return q.value.String() }

// ValidateVenuePrecision reports an error when the value carries more decimal places than
// the venue permits.
//
// Rejection, not rounding: quantity.schema.json forbids silent rounding and permits it
// only via an explicitly named, audited policy.
func (q Quantity) ValidateVenuePrecision(venueScale int32) error {
	if venueScale < 0 || venueScale > decimalMaxScale {
		return fmt.Errorf("%w: venue scale %d is outside 0..%d", ErrScaleOutOfRange, venueScale, decimalMaxScale)
	}
	if q.value.Scale() > venueScale {
		return fmt.Errorf(
			"%w: value %q has %d decimal places but the venue permits %d",
			ErrInvalidQuantity, q.value.String(), q.value.Scale(), venueScale,
		)
	}
	return nil
}
