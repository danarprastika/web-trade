package ledger

import (
	"fmt"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Side is which way a fill traded.
type Side string

const (
	// SideBuy increases the position in the instrument.
	SideBuy Side = "BUY"
	// SideSell decreases it.
	SideSell Side = "SELL"
)

var sides = map[Side]struct{}{SideBuy: {}, SideSell: {}}

// Valid reports whether the side is in the closed set.
func (s Side) Valid() bool {
	_, ok := sides[s]
	return ok
}

func (s Side) String() string { return string(s) }

// Fill is an executed fill that has already been validated by the OMS.
//
// "Validated" is the load-bearing word. A fill reaches the ledger only after the OMS has
// recorded it as executed, because docs/04 section 'Portfolio integrity' makes positions a
// derivation of validated fills rather than of venue reports or of anything anyone believes
// happened. The OMS owns order state and is the only component that can say a fill is real;
// this package trusts that and adds nothing to it.
//
// The venue's own order reference is carried for reconciliation but is never an identity.
// The canonical identity is the OMS order, and a venue reference that differed from it would
// be a reconciliation case rather than a reason to post under a different key.
type Fill struct {
	// OrderID is the OMS canonical order identity.
	OrderID contracts.Identifier
	// Instrument is the canonical instrument code, which is also the position asset.
	Instrument string
	// Side is the direction of the trade.
	Side Side
	// Quantity is the executed quantity, positive.
	Quantity contracts.Decimal
	// Price is the execution price per unit of instrument, positive.
	Price contracts.Decimal
	// QuoteCurrency is the currency the notional is denominated in.
	QuoteCurrency string
	// Fee is the explicit fee. It is zero when there is none, and it is never folded into
	// the notional: a netted fee is a fee nobody can account for.
	Fee contracts.Decimal
	// FeeCurrency is the currency the fee is denominated in. It is required whenever the
	// fee is non-zero, and refused when the fee is zero, because a fee line with a currency
	// and no fee is a posting that should not exist.
	FeeCurrency string
	// Portfolio is the account the cash leg is booked against.
	Portfolio string
	// Venue is the counterparty whose clearing account absorbs the legs.
	Venue string
	// VenueOrderRef is the venue's own reference, carried for reconciliation only.
	VenueOrderRef string
	// ExecutedAt is the venue's reported execution time.
	ExecutedAt contracts.Timestamp
	// SourceCommandID is the OMS command that recorded the fill.
	SourceCommandID contracts.Identifier
	// CorrelationID ties the entry to the request chain.
	CorrelationID contracts.Identifier
	// IdempotencyKey makes a replayed fill recording a no-op. A venue that reports the same
	// execution twice is normal, and posting it twice would double a position.
	IdempotencyKey string
}

func (f Fill) validate() error {
	if f.OrderID.IsZero() {
		return fmt.Errorf("fill names no OMS order; a fill with no order cannot be traced " +
			"back to the state machine that validated it")
	}
	if f.OrderID.Prefix() != contracts.PrefixOrder {
		return fmt.Errorf("order id %q does not carry the %q prefix", f.OrderID, contracts.PrefixOrder)
	}
	if strings.TrimSpace(f.Instrument) == "" {
		return fmt.Errorf("fill names no instrument")
	}
	if !f.Side.Valid() {
		return fmt.Errorf("fill side %q is not in the closed set", f.Side)
	}
	if !f.Quantity.IsSet() || f.Quantity.Sign() <= 0 {
		return fmt.Errorf("fill quantity %s must be a positive amount", f.Quantity)
	}
	if !f.Price.IsSet() || f.Price.Sign() <= 0 {
		return fmt.Errorf("fill price %s must be a positive amount", f.Price)
	}
	if strings.TrimSpace(f.QuoteCurrency) == "" {
		return fmt.Errorf("fill names no quote currency")
	}
	if !f.Fee.IsSet() {
		return fmt.Errorf("fill has no fee amount; a fee is zero, not absent, because an " +
			"absent fee and a zero fee are different claims about the venue")
	}
	if f.Fee.Sign() < 0 {
		return fmt.Errorf("fill fee %s is negative; a rebate is a different posting", f.Fee)
	}
	feeIsZero := f.Fee.IsZero()
	if feeIsZero && strings.TrimSpace(f.FeeCurrency) != "" {
		return fmt.Errorf("fill has a zero fee but names currency %q; a fee line with a "+
			"currency and no amount should not be posted", f.FeeCurrency)
	}
	if !feeIsZero && strings.TrimSpace(f.FeeCurrency) == "" {
		return fmt.Errorf("fill has a non-zero fee of %s but names no currency", f.Fee)
	}
	if strings.TrimSpace(f.Portfolio) == "" {
		return fmt.Errorf("fill names no portfolio to book cash against")
	}
	if strings.TrimSpace(f.Venue) == "" {
		return fmt.Errorf("fill names no venue, so the trade has no counterparty and " +
			"cannot balance")
	}
	if err := f.validateExecutedAt(); err != nil {
		return err
	}
	if f.SourceCommandID.IsZero() {
		return fmt.Errorf("fill names no source command")
	}
	if f.SourceCommandID.Prefix() != contracts.PrefixCommand {
		return fmt.Errorf("source command id %q does not carry the %q prefix",
			f.SourceCommandID, contracts.PrefixCommand)
	}
	if f.CorrelationID.IsZero() {
		return fmt.Errorf("fill names no correlation id")
	}
	if strings.TrimSpace(f.IdempotencyKey) == "" {
		return fmt.Errorf("fill has no idempotency key; venues repeat execution reports " +
			"and a replayed fill would double the position")
	}
	return nil
}

func (f Fill) validateExecutedAt() error {
	if f.ExecutedAt.IsZero() {
		return fmt.Errorf("fill has no execution time; a financial posting with no time " +
			"cannot be ordered against any other posting")
	}
	return nil
}

// Notional is the exact product of quantity and price in the quote currency.
func (f Fill) Notional() (contracts.Decimal, error) {
	return f.Quantity.Multiply(f.Price)
}

// EntriesForFill builds the balanced postings for one validated fill.
//
// The shape is the same for both sides, and only the directions change. A buy takes the
// position up and the cash down; a sell does the reverse. In both cases the instrument legs
// balance against each other, the quote legs balance against each other, and the clearing
// account absorbs the difference so that the trade is a change of composition rather than a
// creation or destruction of value.
//
// The venue clearing legs are what make this balance. Without them, a buy would debit a
// position in BTC and credit cash in USD with nothing on the other side of either, and the
// entry would be an unbalanced injection of value.
func EntriesForFill(f Fill, entryID contracts.Identifier, postedAt contracts.Timestamp) (Entry, error) {
	if err := f.validate(); err != nil {
		return Entry{}, reject(contracts.CodeValidation, "fill is not postable: %v", err)
	}
	if entryID.IsZero() || entryID.Prefix() != contracts.PrefixLedger {
		return Entry{}, reject(contracts.CodeValidation,
			"ledger entry id %q must be a canonical %q identifier", entryID, contracts.PrefixLedger)
	}

	notional, err := f.Notional()
	if err != nil {
		return Entry{}, reject(contracts.CodeValidation,
			"computing the notional for %s: %v", f.Instrument, err)
	}

	// The position and clearing legs follow the side; the cash leg runs the other way.
	positionDirection, cashDirection := Debit, Credit
	if f.Side == SideSell {
		positionDirection, cashDirection = Credit, Debit
	}

	lines := []Line{
		{Account: AccountPosition, Subject: f.Instrument, Asset: f.Instrument,
			Direction: positionDirection, Amount: f.Quantity},
		{Account: AccountClearing, Subject: f.Venue, Asset: f.Instrument,
			Direction: positionDirection.Opposite(), Amount: f.Quantity},
		{Account: AccountCash, Subject: f.Portfolio, Asset: f.QuoteCurrency,
			Direction: cashDirection, Amount: notional},
		{Account: AccountClearing, Subject: f.Venue, Asset: f.QuoteCurrency,
			Direction: cashDirection.Opposite(), Amount: notional},
	}

	if !f.Fee.IsZero() {
		// A fee is an expense we owe the venue: it leaves cash and reduces what the venue
		// claims. It is booked to its own account so it remains visible to every consumer
		// instead of being netted into the notional.
		lines = append(lines,
			Line{Account: AccountFee, Subject: f.Venue, Asset: f.FeeCurrency,
				Direction: Debit, Amount: f.Fee},
			Line{Account: AccountClearing, Subject: f.Venue, Asset: f.FeeCurrency,
				Direction: Credit, Amount: f.Fee},
		)
	}

	entry := Entry{
		EntryID:         entryID,
		PostedAt:        postedAt,
		Lines:           lines,
		SourceCommandID: f.SourceCommandID,
		CorrelationID:   f.CorrelationID,
		IdempotencyKey:  f.IdempotencyKey,
	}
	// Validated here as well as in Append so a caller that wants to inspect a posting
	// before committing it gets the same answer the store would give.
	if err := entry.validate(); err != nil {
		return Entry{}, reject(contracts.CodeValidation,
			"the postings generated for fill %s do not form a valid entry: %v", f.OrderID, err)
	}
	return entry, nil
}
