package ledger

import (
	"fmt"
	"sort"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// AccountKind is the closed set of ledger accounts.
//
// The set is small on purpose. Every account here exists because a trade has to land
// somewhere, and adding a kind is a change to the meaning of the books, not a refactor.
type AccountKind string

const (
	// AccountCash is cash and settled balances we hold.
	AccountCash AccountKind = "CASH"
	// AccountPosition is the quantity held in an instrument.
	AccountPosition AccountKind = "POSITION"
	// AccountRealizedPnL is realised profit and loss. It is an expense-or-income account,
	// and it is populated by a correction or settlement, not by the fill itself; a fill
	// does not know the cost basis it is closing.
	AccountRealizedPnL AccountKind = "REALIZED_PNL"
	// AccountFee is explicit fees. Fees are posted to their own account rather than being
	// netted into cash or into the position, because netting them makes the fee invisible
	// to every downstream consumer and unreviewable after the fact.
	AccountFee AccountKind = "FEE"
	// AccountClearing is the venue counterparty: what we owe the venue, or what it owes us.
	//
	// This is the account that makes a trade balance. A buy converts cash into a position,
	// which is a change of composition and not of total, so the two legs cannot balance
	// against each other. The clearing leg records what moved to the venue. Its running
	// balance is the venue exposure, which is worth surfacing on its own account: a
	// clearing balance that does not settle is a real operational signal.
	AccountClearing AccountKind = "EXTERNAL_CLEARING"
)

var accountKinds = map[AccountKind]struct{}{
	AccountCash: {}, AccountPosition: {}, AccountRealizedPnL: {},
	AccountFee: {}, AccountClearing: {},
}

// Valid reports whether the account kind is in the closed set.
func (k AccountKind) Valid() bool {
	_, ok := accountKinds[k]
	return ok
}

func (k AccountKind) String() string { return string(k) }

// Direction is which side of an account a posting lands on.
type Direction string

const (
	// Debit increases an asset we hold or an expense.
	Debit Direction = "DEBIT"
	// Credit decreases an asset we hold or an income.
	Credit Direction = "CREDIT"
)

var directions = map[Direction]struct{}{Debit: {}, Credit: {}}

// Valid reports whether the direction is in the closed set.
func (d Direction) Valid() bool {
	_, ok := directions[d]
	return ok
}

func (d Direction) String() string { return string(d) }

// Opposite returns the direction that undoes this one, which is what a compensating entry
// uses on every line.
func (d Direction) Opposite() Direction {
	if d == Debit {
		return Credit
	}
	return Debit
}

// Line is one posting to one account in one asset.
type Line struct {
	// Account is the ledger account.
	Account AccountKind `json:"account"`
	// Subject names what within the account: the instrument for a position, the account
	// for cash, the venue for clearing. It is a subject, not an identity, so it carries no
	// prefix requirement.
	Subject string `json:"subject"`
	// Asset is the canonical code the amount is denominated in: a currency such as USD, or
	// an instrument such as BTC-USD.
	Asset string `json:"asset"`
	// Direction is the side.
	Direction Direction `json:"direction"`
	// Amount is always positive. A negative amount would make the sign of a posting
	// ambiguous against the direction, and an entry whose meaning depends on which of two
	// encodings a reader happened to find is not auditable.
	Amount contracts.Decimal `json:"amount"`
}

func (l Line) validate() error {
	if !l.Account.Valid() {
		return fmt.Errorf("account %q is not in the closed set", l.Account)
	}
	if !l.Direction.Valid() {
		return fmt.Errorf("line direction %q is not in the closed set", l.Direction)
	}
	if strings.TrimSpace(l.Subject) == "" {
		return fmt.Errorf("line on account %s names no subject", l.Account)
	}
	if strings.TrimSpace(l.Asset) == "" {
		return fmt.Errorf("line on account %s names no asset", l.Account)
	}
	if !l.Amount.IsSet() {
		return fmt.Errorf("line on account %s has no amount", l.Account)
	}
	if l.Amount.Sign() <= 0 {
		return fmt.Errorf("line on account %s has a non-positive amount %s; a posting's "+
			"sign is carried by its direction, not by a signed quantity", l.Account, l.Amount)
	}
	// A position is held in exactly one instrument. Carrying a subject and an asset that
	// disagree would let a position of one instrument be posted into another, which is the
	// kind of error that survives every total check because each is individually plausible.
	if l.Account == AccountPosition && l.Asset != l.Subject {
		return fmt.Errorf("position line has subject %q and asset %q; a position is held in "+
			"one instrument and these must agree", l.Subject, l.Asset)
	}
	return nil
}

// signed returns the amount with the direction applied, for summation only.
func (l Line) signed() contracts.Decimal {
	if l.Direction == Debit {
		return l.Amount
	}
	return l.Amount.Neg()
}

// Entry is an append-only, balanced set of postings.
type Entry struct {
	// EntryID is the canonical identity, minted once and never replaced.
	EntryID contracts.Identifier `json:"entry_id"`
	// Sequence is the ledger-wide total order. It is assigned by the store at append time,
	// not by the caller, because a caller-assigned sequence would let two entries claim
	// the same position and make the order ambiguous.
	Sequence int64 `json:"sequence"`
	// PostedAt is the time of posting, supplied by the caller because this package reads
	// no clock.
	PostedAt contracts.Timestamp `json:"posted_at"`
	// Lines are the postings. At least two: an entry with one line cannot balance.
	Lines []Line `json:"lines"`
	// SourceCommandID is the authoritative command that caused this entry. Every entry
	// references its source (docs/05 section 'Ledger'), so an entry that cannot be traced
	// to a command is refused rather than stored as unattributable.
	SourceCommandID contracts.Identifier `json:"source_command_id"`
	// CorrelationID ties this entry to the request that caused it, so a whole chain of
	// entries from one decision can be found together.
	CorrelationID contracts.Identifier `json:"correlation_id"`
	// CorrectsEntryID is set only on a compensating entry, and names the entry it reverses.
	CorrectsEntryID contracts.Identifier `json:"corrects_entry_id,omitempty"`
	// Reason is required on a compensating entry and forbidden on any other, so a
	// correction is always self-describing and an ordinary post is never mistaken for one.
	Reason string `json:"reason,omitempty"`
	// IdempotencyKey makes a replay of the same logical posting a no-op. The store keys
	// uniqueness on the source command and this key together, so the same key from a
	// different command is a different posting rather than a silent collision.
	IdempotencyKey string `json:"idempotency_key"`
}

// IsCompensation reports whether this entry reverses another.
func (e Entry) IsCompensation() bool { return !e.CorrectsEntryID.IsZero() }

// validate checks everything that can be checked about a single entry in isolation.
// Whether a compensation is *permitted* additionally needs the store, because it depends on
// the entry being corrected existing and not already being corrected.
func (e Entry) validate() error {
	if e.EntryID.IsZero() {
		return fmt.Errorf("entry has no canonical identity")
	}
	if e.EntryID.Prefix() != contracts.PrefixLedger {
		return fmt.Errorf("entry id %q does not carry the %q prefix", e.EntryID, contracts.PrefixLedger)
	}
	// The zero Timestamp is unset, and a posting with no time cannot be ordered against
	// any other posting, so it is refused rather than sorting first.
	if e.PostedAt.IsZero() {
		return fmt.Errorf("entry has no posting time; a financial posting with no time " +
			"cannot be ordered against any other posting")
	}
	if e.SourceCommandID.IsZero() {
		return fmt.Errorf("entry has no source command; docs/05 requires every entry to " +
			"reference the command or event that caused it")
	}
	if e.SourceCommandID.Prefix() != contracts.PrefixCommand {
		return fmt.Errorf("source command id %q does not carry the %q prefix",
			e.SourceCommandID, contracts.PrefixCommand)
	}
	if e.CorrelationID.IsZero() {
		return fmt.Errorf("entry has no correlation id; docs/05 requires every entry to " +
			"reference its correlation identifier")
	}
	if strings.TrimSpace(e.IdempotencyKey) == "" {
		return fmt.Errorf("entry has no idempotency key; without one a replayed request " +
			"would post a second time")
	}
	if len(e.Lines) < 2 {
		return fmt.Errorf("entry has %d line(s); an entry must post at least two lines to "+
			"balance", len(e.Lines))
	}
	for i, line := range e.Lines {
		if err := line.validate(); err != nil {
			return fmt.Errorf("line %d: %w", i, err)
		}
	}

	// A reason belongs to a correction and to nothing else.
	switch {
	case e.IsCompensation() && strings.TrimSpace(e.Reason) == "":
		return fmt.Errorf("compensating entry %s corrects %s but records no reason; a "+
			"correction must be self-describing", e.EntryID, e.CorrectsEntryID)
	case !e.IsCompensation() && strings.TrimSpace(e.Reason) != "":
		return fmt.Errorf("entry %s is not a correction but records the reason %q; a reason "+
			"on an ordinary posting makes it indistinguishable from a correction",
			e.EntryID, e.Reason)
	}

	return e.checkBalanced()
}

// checkBalanced enforces the invariant that makes a ledger a ledger.
//
// Balance is checked per asset, not across the entry as one sum. A buy converts cash into
// a position, so the two legs are denominated in different assets and adding them together
// is meaningless. Requiring the sum of debits to equal the sum of credits *within each
// asset* is the invariant that actually holds, and it is the one that catches a mistyped
// amount: a clearing leg of 3000000 against a cash leg of 3000000 in the same asset no
// longer balances.
func (e Entry) checkBalanced() error {
	debits := map[string]contracts.Decimal{}
	credits := map[string]contracts.Decimal{}
	assets := map[string]bool{}

	for _, line := range e.Lines {
		assets[line.Asset] = true
		side := credits
		if line.Direction == Debit {
			side = debits
		}
		// Absent assets start at zero rather than at the unset Decimal, because the unset
		// zero is a construction error and would turn every single-asset entry into a
		// failure of the arithmetic rather than of the entry.
		if _, ok := side[line.Asset]; !ok {
			side[line.Asset] = contracts.Zero()
		}
		sum, err := side[line.Asset].Add(line.Amount)
		if err != nil {
			return fmt.Errorf("summing %s amounts in %s: %w", line.Direction, line.Asset, err)
		}
		side[line.Asset] = sum
	}

	names := make([]string, 0, len(assets))
	for asset := range assets {
		names = append(names, asset)
	}
	// Sorted so the error names the same asset on every run. A balance error that names a
	// different asset each time is close to useless when triaging a production posting
	// failure across several instances.
	sort.Strings(names)

	for _, asset := range names {
		dr, okD := debits[asset]
		cr, okC := credits[asset]
		if !okD {
			dr = contracts.Zero()
		}
		if !okC {
			cr = contracts.Zero()
		}
		cmp, err := dr.Cmp(cr)
		if err != nil {
			return fmt.Errorf("comparing %s totals: %w", asset, err)
		}
		if cmp != 0 {
			difference, err := dr.Sub(cr)
			if err != nil {
				return fmt.Errorf("computing the %s imbalance: %w", asset, err)
			}
			return fmt.Errorf("entry does not balance in %s: debits %s, credits %s; an "+
				"unbalanced entry means %s of %s has no counterpart and will not be "+
				"explainable by a later reconciliation", asset, dr, cr, difference, asset)
		}
	}
	return nil
}

// reversedLines returns the lines of the compensating entry that would undo this entry:
// the same lines with every direction flipped. Exported through Compensate rather than
// used directly, so that a caller cannot construct a half-reversed entry by hand.
func (e Entry) reversedLines() []Line {
	out := make([]Line, len(e.Lines))
	for i, line := range e.Lines {
		out[i] = line
		out[i].Direction = line.Direction.Opposite()
	}
	return out
}

// Assets returns the distinct assets the entry touches, sorted.
func (e Entry) Assets() []string {
	seen := map[string]bool{}
	for _, line := range e.Lines {
		seen[line.Asset] = true
	}
	out := make([]string, 0, len(seen))
	for a := range seen {
		out = append(out, a)
	}
	sort.Strings(out)
	return out
}

// Net returns the signed total for one account and asset. A positive value is a debit
// balance, which for a cash or position account is an asset we hold.
func (e Entry) Net(account AccountKind, asset string) (contracts.Decimal, error) {
	total := contracts.Zero()
	found := false
	for _, line := range e.Lines {
		if line.Account != account || line.Asset != asset {
			continue
		}
		found = true
		sum, err := total.Add(line.signed())
		if err != nil {
			return contracts.Decimal{}, fmt.Errorf("summing %s in %s: %w", account, asset, err)
		}
		total = sum
	}
	if !found {
		return contracts.Decimal{}, fmt.Errorf("entry %s does not touch account %s in %s",
			e.EntryID, account, asset)
	}
	return total, nil
}

func (e Entry) String() string {
	return fmt.Sprintf("Entry{seq=%d id=%s src=%s corr=%s lines=%d%s}",
		e.Sequence, e.EntryID, e.SourceCommandID, e.CorrelationID, len(e.Lines),
		correctionSuffix(e))
}

func correctionSuffix(e Entry) string {
	if !e.IsCompensation() {
		return ""
	}
	return fmt.Sprintf(" corrects=%s reason=%q", e.CorrectsEntryID, e.Reason)
}
