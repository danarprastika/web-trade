package contracts

import (
	"errors"
	"strings"
	"testing"
)

// canonicalBody is a 26-character lowercase Crockford Base32 payload, the fixed length
// identifier.schema.json requires. The schema's own examples are lowercase, and a
// producer emitting uppercase is in violation, so these tests use lowercase throughout.
const canonicalBody = "01hq3k7m9x2f5rb8n0v6c4tqwx"

// The contracts package deliberately exposes no panicking constructors. A Must-style API
// would be convenient here, but a panic path inside a financial contract library turns a
// malformed venue payload into a process-terminating fault instead of a handled rejection,
// which is the opposite of the contract's intent. The helpers below keep that decision
// honest: they panic only in test code, where a failure is already fatal.
func mustMoney(t *testing.T, currency string, amount Decimal) Money {
	t.Helper()
	m, err := NewMoney(currency, amount)
	if err != nil {
		t.Fatalf("NewMoney(%q, %q): unexpected error %v", currency, amount.String(), err)
	}
	return m
}

func mustMoneyScale(t *testing.T, currency string, amount Decimal, scale *int32) Money {
	t.Helper()
	m, err := NewMoneyWithScale(currency, amount, scale)
	if err != nil {
		t.Fatalf("NewMoneyWithScale(%q, %q, %v): unexpected error %v", currency, amount.String(), scale, err)
	}
	return m
}

func mustQuantity(t *testing.T, value Decimal, unit QuantityUnit) Quantity {
	t.Helper()
	q, err := NewQuantity(value, unit)
	if err != nil {
		t.Fatalf("NewQuantity(%q, %q): unexpected error %v", value.String(), unit, err)
	}
	return q
}

func mustQuantityScale(t *testing.T, value Decimal, unit QuantityUnit, scale *int32) Quantity {
	t.Helper()
	q, err := NewQuantityWithScale(value, unit, scale)
	if err != nil {
		t.Fatalf("NewQuantityWithScale(%q, %q, %v): unexpected error %v", value.String(), unit, scale, err)
	}
	return q
}

// TestIdentifierCorpus covers every identifier case in the shared conformance corpus.
//
// The pattern is ^(cmd|evt|ord|str|mdl|run|pos|led)_[0-9a-hjkmnp-tv-z]{26}$ with
// maxLength 30. Three properties are easy to get wrong and are each pinned here: the
// payload length is fixed at 26, the payload is lowercase, and the prefix set is closed
// at eight values.
func TestIdentifierCorpus(t *testing.T) {
	valid := []string{
		"ord_" + canonicalBody,
		"cmd_" + canonicalBody,
		"evt_" + canonicalBody,
		"pos_" + canonicalBody,
		"str_" + canonicalBody,
		"mdl_" + canonicalBody,
		"led_" + canonicalBody,
		"run_" + canonicalBody,
	}
	for _, s := range valid {
		if _, err := ParseIdentifier(s); err != nil {
			t.Errorf("ParseIdentifier(%q) = error %v, want accept", s, err)
		}
	}

	invalid := []string{
		"",                                      // empty
		canonicalBody,                           // no prefix
		"ORD_" + canonicalBody,                  // uppercase prefix
		"ord_" + strings.ToUpper(canonicalBody), // uppercase payload: canonical form is lowercase
		"xyz_" + canonicalBody,                  // prefix outside the closed set of eight
		"job_" + canonicalBody,                  // plausible prefix, but not registered
		"ord_",                                  // prefix only
		"ord_" + canonicalBody[:25],             // 25-character payload: length is fixed at 26
		"ord_" + canonicalBody + "0",            // 27-character payload
		"ord_01hq3k7m9x2f5rb8n0v6c4tqwx\n",      // trailing newline
		" ord_" + canonicalBody,                 // leading space
		"ord_i" + canonicalBody[1:],             // 'i' is excluded by Crockford Base32
		"ord_l" + canonicalBody[1:],             // 'l' is excluded by Crockford Base32
		"ord_o" + canonicalBody[1:],             // 'o' is excluded by Crockford Base32
		"ord_u" + canonicalBody[1:],             // 'u' is excluded by Crockford Base32
		"ord_01hq3k7m9x2f5rb8n0v6c4tqw-",        // hyphen outside the payload alphabet
	}
	for _, s := range invalid {
		if _, err := ParseIdentifier(s); err == nil {
			t.Errorf("ParseIdentifier(%q) = nil error, want reject", s)
		}
	}
}

// TestIdentifierPayloadMayBeginWithALetter pins that the payload alphabet is not
// digit-initial. The pattern character class [0-9a-hjkmnp-tv-z] permits a leading letter,
// so an implementation that assumed a ULID-style always-digit first character would reject
// valid identifiers.
func TestIdentifierPayloadMayBeginWithALetter(t *testing.T) {
	// Derived rather than hand-written: a hand-typed 26-character payload is easy to
	// undercount, which produced a 25-character case that failed for the wrong reason.
	letterInitial := "ord_a" + canonicalBody[1:]
	if _, err := ParseIdentifier(letterInitial); err != nil {
		t.Errorf("ParseIdentifier(%q) = %v, want accept", letterInitial, err)
	}
}

// TestIdentifierExcludedLetters pins the Crockford alphabet. I, L, O, and U are omitted to
// avoid transcription ambiguity with 1 and 0, so an identifier carrying them is a
// transcription error and must be refused rather than normalised.
func TestIdentifierExcludedLetters(t *testing.T) {
	for _, excluded := range []byte{'i', 'l', 'o', 'u'} {
		raw := "ord_01hq3k7m9x2f5rb8n0v6c4" + string(excluded) + "w"
		if _, err := ParseIdentifier(raw); err == nil {
			t.Errorf("ParseIdentifier accepted excluded letter %q in %q", excluded, raw)
		}
	}
}

func TestIdentifierPrefixAgreement(t *testing.T) {
	id, err := ParseIdentifier("ord_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	if id.Prefix() != PrefixOrder {
		t.Errorf("Prefix() = %q, want %q", id.Prefix(), PrefixOrder)
	}
	if !(id.Prefix() == PrefixOrder) {
		t.Error("HasPrefix(ord_) = false, want true")
	}
	if id.Prefix() == PrefixCommand {
		t.Error("HasPrefix(cmd_) = true, want false")
	}
	if got := id.String(); got != "ord_"+canonicalBody {
		t.Errorf("String() = %q, want the input", got)
	}
}

func TestIdentifierZeroValueIsUnset(t *testing.T) {
	// The zero value must be inert. A forgotten command_id must be caught by envelope
	// validation, not silently compare equal to every other unset command.
	var id Identifier
	if !id.IsZero() {
		t.Error("zero value Identifier reports IsZero() = false")
	}
	if id.Prefix() != "" {
		t.Errorf("zero value Prefix() = %q, want empty", id.Prefix())
	}
	parsed, err := ParseIdentifier("ord_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	if parsed == (Identifier{}) {
		t.Error("a parsed identifier equals the zero value")
	}
}

func TestMoneyCorpus(t *testing.T) {
	// money.schema.json binds amount by $ref to decimal.schema.json, which supplies the
	// pattern and maxLength 40. It adds no minLength, so a single-digit amount is valid.
	for _, s := range []string{"1", "1.0", "0.00", "999999.99", "1500000"} {
		if _, err := NewMoney("USD", MustParseDecimal(s)); err != nil {
			t.Errorf("NewMoney(%q) = error %v, want accept", s, err)
		}
	}
	// Money carries a Decimal, so the decimal length bounds are already enforced by
	// ParseDecimal and covered by TestDecimalRejectsOverlongInput. Re-testing them here
	// through MustParseDecimal would only assert that a panic happened.
}

// TestMoneyRejectsUnsetAmount checks the one malformed amount Money can actually be asked
// to reject, because every other malformed amount is refused by ParseDecimal before it can
// be constructed. NewMoney must still refuse an unset amount, or a zero-value Money would
// pass silently as a genuine zero balance.
//
// Note what this test deliberately does not do: it does not try to build Money around a
// malformed decimal string. That path is unreachable by construction, since ParseDecimal
// rejects the string first and MustParseDecimal panics on it. Attempting it would test
// nothing while making a malformed value look like a Money concern.
func TestMoneyRejectsUnsetAmount(t *testing.T) {
	if _, err := NewMoney("USD", Decimal{}); !errors.Is(err, ErrInvalidMoney) {
		t.Errorf("NewMoney with an unset amount = %v, want ErrInvalidMoney", err)
	}
	if _, err := NewMoneyWithScale("USD", Decimal{}, nil); !errors.Is(err, ErrInvalidMoney) {
		t.Errorf("NewMoneyWithScale with an unset amount = %v, want ErrInvalidMoney", err)
	}
}

func TestMoneyRequiresCurrency(t *testing.T) {
	// The pattern is ^[A-Z][A-Z0-9]{1,11}$, so a total length of 2 to 12. A two-character
	// code is therefore valid, and only a single character is too short.
	for _, s := range []string{"A1", "US", "USD", "EUR", "IDR", "JPY", "BTC", "USDD", "XBT2"} {
		if _, err := NewMoney(s, MustParseDecimal("1.00")); err != nil {
			t.Errorf("NewMoney(currency=%q) = error %v, want accept", s, err)
		}
	}
	for _, s := range []string{"", "U", "usd", "Usd", "US D", "USDDDDDDDDDDD", "1USD"} {
		if _, err := NewMoney(s, MustParseDecimal("1.00")); err == nil {
			t.Errorf("NewMoney(currency=%q) = nil error, want reject", s)
		}
	}
}

func TestMoneyCurrencyIsPartOfTheValue(t *testing.T) {
	usd := mustMoney(t, "USD", MustParseDecimal("1.00"))
	eur := mustMoney(t, "EUR", MustParseDecimal("1.00"))
	if usd.Equal(eur) {
		t.Error("1.00 USD compared equal to 1.00 EUR; currency is part of the value")
	}
	if usd.Currency() != "USD" {
		t.Errorf("Currency() = %q, want USD", usd.Currency())
	}
}

func TestMoneyRejectsCurrencyMismatch(t *testing.T) {
	// The schema invariant is that a currency mismatch "is a hard rejection, not a
	// conversion". No operation may quietly resolve one.
	usd := mustMoney(t, "USD", MustParseDecimal("100.00"))
	eur := mustMoney(t, "EUR", MustParseDecimal("10.00"))

	if err := usd.RequireSameCurrency(eur); !errors.Is(err, ErrCurrencyMismatch) {
		t.Errorf("RequireSameCurrency = %v, want ErrCurrencyMismatch", err)
	}
	if _, err := usd.Add(eur); !errors.Is(err, ErrCurrencyMismatch) {
		t.Errorf("Add = %v, want ErrCurrencyMismatch", err)
	}
	if _, err := usd.Sub(eur); !errors.Is(err, ErrCurrencyMismatch) {
		t.Errorf("Sub = %v, want ErrCurrencyMismatch", err)
	}
	if _, err := usd.Cmp(eur); !errors.Is(err, ErrCurrencyMismatch) {
		t.Errorf("Cmp = %v, want ErrCurrencyMismatch", err)
	}
}

func TestMoneyArithmeticIsExact(t *testing.T) {
	// 0.01 + 0.02 == 0.03. In float64 the sum is 0.03000000000000000255, and a ledger
	// built on it can never reconcile against a venue. This is why no float crosses here.
	sum, err := mustMoney(t, "USD", MustParseDecimal("0.01")).
		Add(mustMoney(t, "USD", MustParseDecimal("0.02")))
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if sum.Amount().String() != "0.03" {
		t.Errorf("0.01 + 0.02 = %q, want 0.03", sum.Amount().String())
	}

	diff, err := mustMoney(t, "USD", MustParseDecimal("100.00")).
		Sub(mustMoney(t, "USD", MustParseDecimal("0.01")))
	if err != nil {
		t.Fatalf("Sub: %v", err)
	}
	if diff.Amount().String() != "99.99" {
		t.Errorf("100.00 - 0.01 = %q, want 99.99", diff.Amount().String())
	}

	// Subtraction must cross zero into negative, and a negative balance is a normal
	// ledger state rather than an error.
	neg, err := mustMoney(t, "USD", MustParseDecimal("5.00")).
		Sub(mustMoney(t, "USD", MustParseDecimal("7.00")))
	if err != nil {
		t.Fatalf("Sub: %v", err)
	}
	if neg.Amount().String() != "-2.00" {
		t.Errorf("5.00 - 7.00 = %q, want -2.00", neg.Amount().String())
	}
}

func TestMoneyCmpIgnoresScaleButNotCurrency(t *testing.T) {
	// 1.50 and 1.5 are the same amount, not two different ones.
	c, err := mustMoney(t, "USD", MustParseDecimal("1.50")).Cmp(mustMoney(t, "USD", MustParseDecimal("1.5")))
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if c != 0 {
		t.Errorf("1.50 cmp 1.5 = %d, want 0", c)
	}
	c, err = mustMoney(t, "USD", MustParseDecimal("1.49")).Cmp(mustMoney(t, "USD", MustParseDecimal("1.5")))
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if c >= 0 {
		t.Errorf("1.49 cmp 1.5 = %d, want < 0", c)
	}
	if !mustMoney(t, "USD", MustParseDecimal("1.50")).Equal(mustMoney(t, "USD", MustParseDecimal("1.5"))) {
		t.Error("Equal(1.50, 1.5) = false, want true; scale is not part of the value")
	}
}

func TestMoneyScaleSurvivesArithmetic(t *testing.T) {
	// An explicitly declared venue scale must not be dropped by an arithmetic operation,
	// or the next venue submission would carry a different precision than the one the
	// amount was validated against.
	scale := int32(8)
	btc := mustMoneyScale(t, "BTC", MustParseDecimal("0.00000001"), &scale)
	if got, ok := btc.Scale(); !ok || got != 8 {
		t.Errorf("Scale() = %d, %v, want 8, true", got, ok)
	}
	sum, err := btc.Add(mustMoneyScale(t, "BTC", MustParseDecimal("0.00000001"), &scale))
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if got, ok := sum.Scale(); !ok || got != 8 {
		t.Errorf("after Add, Scale() = %d, %v, want 8, true", got, ok)
	}
	if sum.Amount().String() != "0.00000002" {
		t.Errorf("0.00000001 + 0.00000001 = %q, want 0.00000002", sum.Amount().String())
	}
	// An out-of-range scale is refused; the schema bounds it to 0..38.
	for _, bad := range []int32{-1, 39} {
		if _, err := NewMoneyWithScale("USD", MustParseDecimal("1.00"), &bad); err == nil {
			t.Errorf("NewMoneyWithScale(scale=%d) = nil error, want reject", bad)
		}
	}
}

func TestQuantityCorpus(t *testing.T) {
	// quantity.schema.json requires both value and unit, with unit drawn from a closed
	// set of six. An unknown unit is unsupported, not mapped to a default.
	for _, s := range []string{"0", "1", "0.0001", "1000.25", "0.5"} {
		if _, err := NewQuantity(MustParseDecimal(s), UnitBaseAsset); err != nil {
			t.Errorf("NewQuantity(%q) = error %v, want accept", s, err)
		}
	}
	// The value bounds come from decimal.schema.json and are covered by the decimal tests;
	// a malformed value cannot be handed to NewQuantity at all.
	for _, u := range []QuantityUnit{UnitBaseAsset, UnitQuoteAsset, UnitContract, UnitLot, UnitShare, UnitUnits} {
		if !u.Valid() {
			t.Errorf("unit %q reported invalid, want valid", u)
		}
	}
	for _, s := range []string{"", "base_asset", "CURRENCY", "BASE ASSET", "UNITS_X"} {
		if _, err := ParseQuantityUnit(s); err == nil {
			t.Errorf("ParseQuantityUnit(%q) = nil error, want reject", s)
		}
	}
}

// TestQuantitySignCarriesNoDirection pins the schema invariant that "positive and negative
// quantities are both valid; direction is carried by the order side, not the sign". A
// binding that rejected negatives would force a short position to be expressed as a
// positive quantity plus a side, which is how a sell gets recorded as a buy.
func TestQuantitySignCarriesNoDirection(t *testing.T) {
	for _, s := range []string{"-1", "-0.5", "-0.0001"} {
		if _, err := NewQuantity(MustParseDecimal(s), UnitBaseAsset); err != nil {
			t.Errorf("NewQuantity(%q) = error %v, want accept; a negative quantity is valid", s, err)
		}
	}
	if _, err := NewQuantity(MustParseDecimal("-1"), "BASE"); err == nil {
		t.Error("NewQuantity with an unknown unit accepted, want reject")
	}
}

func TestQuantityRejectsVenueOverprecision(t *testing.T) {
	// The invariant is that a non-conforming quantity is "rejected, never rounded
	// silently". Rounding belongs to an explicitly named, audited policy.
	q, err := NewQuantity(MustParseDecimal("1.23456"), UnitBaseAsset)
	if err != nil {
		t.Fatalf("NewQuantity: %v", err)
	}
	if err := q.ValidateVenuePrecision(2); err == nil {
		t.Error("1.23456 accepted at a venue scale of 2, want rejection rather than rounding")
	}
	if err := q.ValidateVenuePrecision(5); err != nil {
		t.Errorf("1.23456 rejected at a venue scale of 5: %v", err)
	}
	if err := q.ValidateVenuePrecision(-1); !errors.Is(err, ErrScaleOutOfRange) {
		t.Errorf("negative venue scale = %v, want ErrScaleOutOfRange", err)
	}
	if err := q.ValidateVenuePrecision(39); !errors.Is(err, ErrScaleOutOfRange) {
		t.Errorf("venue scale 39 = %v, want ErrScaleOutOfRange", err)
	}
}

func TestQuantityCarriesVenueScale(t *testing.T) {
	scale := int32(8)
	q, err := NewQuantityWithScale(MustParseDecimal("0.5"), UnitQuoteAsset, &scale)
	if err != nil {
		t.Fatalf("NewQuantityWithScale: %v", err)
	}
	if got, ok := q.Scale(); !ok || got != 8 {
		t.Errorf("Scale() = %d, %v, want 8, true", got, ok)
	}
	if q.Unit() != UnitQuoteAsset {
		t.Errorf("Unit() = %q, want QUOTE_ASSET", q.Unit())
	}
	if q.Value().String() != "0.5" {
		t.Errorf("Value() = %q, want 0.5", q.Value().String())
	}
}
