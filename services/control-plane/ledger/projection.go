package ledger

import (
	"fmt"
	"sort"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Position returns the net quantity held in an instrument.
//
// A negative value is a short position, which is a real position and not an error. It is
// returned as-is rather than clamped, because the difference between a flat position and a
// short one is precisely what a risk limit needs to see.
func Position(s Store, instrument string) (contracts.Decimal, error) {
	return accountTotal(s, AccountPosition, instrument, instrument)
}

// CashBalance returns the net cash held in a portfolio in one currency. A negative value is
// cash owed, which is a normal condition for a margin book and not an error.
func CashBalance(s Store, portfolio, currency string) (contracts.Decimal, error) {
	return accountTotal(s, AccountCash, portfolio, currency)
}

// VenueExposure returns the net amount owed to or by a venue across every asset, per asset.
//
// It is exposed on its own because the clearing account is the venue's running claim on this
// book. A clearing balance that does not settle is an operational signal long before it
// becomes a reconciliation case, and nothing else in the ledger surfaces it.
func VenueExposure(s Store, venue string) (map[string]contracts.Decimal, error) {
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		return nil, err
	}
	folded, err := balances(entries)
	if err != nil {
		return nil, err
	}
	out := map[string]contracts.Decimal{}
	for _, b := range folded {
		if b.Account != AccountClearing || b.Subject != venue || b.Amount.IsZero() {
			continue
		}
		out[b.Asset] = b.Amount
	}
	return out, nil
}

func accountTotal(s Store, account AccountKind, subject, asset string) (contracts.Decimal, error) {
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		return contracts.Decimal{}, err
	}
	folded, err := balances(entries)
	if err != nil {
		return contracts.Decimal{}, err
	}
	key := string(account) + "\x00" + subject + "\x00" + asset
	if b, ok := folded[key]; ok {
		return b.Amount, nil
	}
	// No postings at all is a flat position of zero, not an error. Distinguishing it from
	// an error would force every caller to handle a case that is not exceptional.
	return contracts.Zero(), nil
}

// Snapshot is a point-in-time view of the ledger, projected.
//
// It carries no authority. It is a value computed from entries, and deleting it changes
// nothing: Rebuild produces it again. The distinction is the reason a cached Snapshot may be
// served to a dashboard while the ledger may not be bypassed (docs/25 section 3, invariant
// 4, and docs/01 section 3, rule 7).
type Snapshot struct {
	// UpTo is the sequence this snapshot was built from. Every entry at or before this
	// sequence is included, so a snapshot is reproducible from its own field.
	UpTo int64
	// Balances are the folded account balances at that point.
	Balances []AccountBalance
	// EntryCount is how many entries were folded.
	EntryCount int
}

// Balance returns the projected balance for one account, subject, and asset, and whether
// the account was touched at all.
func (s Snapshot) Balance(account AccountKind, subject, asset string) (contracts.Decimal, bool) {
	for _, b := range s.Balances {
		if b.Account == account && b.Subject == subject && b.Asset == asset {
			return b.Amount, true
		}
	}
	return contracts.Zero(), false
}

// Position is the projected net quantity in an instrument.
func (s Snapshot) Position(instrument string) contracts.Decimal {
	v, _ := s.Balance(AccountPosition, instrument, instrument)
	return v
}

// String renders the snapshot for a log. Never parse it.
func (s Snapshot) String() string {
	parts := make([]string, 0, len(s.Balances))
	for _, b := range s.Balances {
		parts = append(parts, b.String())
	}
	return fmt.Sprintf("Snapshot{upTo=%d entries=%d %v}", s.UpTo, s.EntryCount, parts)
}

// Rebuild projects the ledger as of a sequence.
//
// It reads the entries and folds them; it does not consult any stored total, any cache, or
// any previously computed snapshot. That is the whole property: the output is a function of
// the entry history alone, so two rebuilds of the same history are equal and a stale
// snapshot cannot disagree with the ledger without the ledger being wrong.
func Rebuild(s Store, upTo int64) (Snapshot, error) {
	entries, err := s.Sequence(upTo)
	if err != nil {
		return Snapshot{}, err
	}
	folded, err := balances(entries)
	if err != nil {
		return Snapshot{}, err
	}
	out := make([]AccountBalance, 0, len(folded))
	for _, b := range folded {
		if b.Amount.IsZero() {
			continue
		}
		out = append(out, b)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Account != out[j].Account {
			return out[i].Account < out[j].Account
		}
		if out[i].Subject != out[j].Subject {
			return out[i].Subject < out[j].Subject
		}
		return out[i].Asset < out[j].Asset
	})

	last := int64(0)
	if len(entries) > 0 {
		last = entries[len(entries)-1].Sequence
	}
	return Snapshot{UpTo: last, Balances: out, EntryCount: len(entries)}, nil
}

// ReconcilePositions compares the projected position in each instrument against the
// quantity the OMS reports as validated, and returns every difference.
//
// This is the check docs/04 section 'Portfolio integrity' requires: positions are derived
// from validated fills, so the ledger's position and the OMS's validated quantity must agree
// exactly, in both instruments. A half-instrument difference is not a rounding artefact and
// is reported the same as a whole one.
//
// The expected map is keyed by instrument and holds signed net quantity.
func ReconcilePositions(s Store, expected map[string]contracts.Decimal) ([]Difference, error) {
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		return nil, err
	}
	folded, err := balances(entries)
	if err != nil {
		return nil, err
	}

	// Union the instruments on both sides. An instrument present in only one of them is
	// itself the difference, and iterating only the expected map would hide exactly the
	// case where the ledger holds a position nobody expected.
	instruments := map[string]bool{}
	for instrument := range expected {
		instruments[instrument] = true
	}
	for _, b := range folded {
		if b.Account == AccountPosition {
			instruments[b.Subject] = true
		}
	}

	names := make([]string, 0, len(instruments))
	for instrument := range instruments {
		names = append(names, instrument)
	}
	sort.Strings(names)

	var differences []Difference
	for _, instrument := range names {
		key := string(AccountPosition) + "\x00" + instrument + "\x00" + instrument
		actual := contracts.Zero()
		if b, ok := folded[key]; ok {
			actual = b.Amount
		}
		want, expectedHere := expected[instrument]
		if !expectedHere {
			want = contracts.Zero()
		}
		cmp, err := actual.Cmp(want)
		if err != nil {
			return nil, reject(contracts.CodeInternal,
				"comparing position in %s: %v", instrument, err)
		}
		if cmp != 0 {
			delta, err := actual.Sub(want)
			if err != nil {
				return nil, reject(contracts.CodeInternal,
					"computing the position difference in %s: %v", instrument, err)
			}
			differences = append(differences, Difference{
				Instrument: instrument,
				Kind:       "POSITION",
				Ledger:     actual,
				External:   want,
				Delta:      delta,
			})
		}
	}
	return differences, nil
}

// Difference is one reconciliation break.
type Difference struct {
	// Instrument is what the difference is about.
	Instrument string
	// Kind is what kind of thing differs, such as POSITION.
	Kind string
	// Ledger is what the ledger says.
	Ledger contracts.Decimal
	// External is what the other authority says.
	External contracts.Decimal
	// Delta is Ledger minus External, signed.
	Delta contracts.Decimal
}

func (d Difference) String() string {
	return fmt.Sprintf("%s %s: ledger %s, external %s, delta %s",
		d.Kind, d.Instrument, d.Ledger, d.External, d.Delta)
}

// Break is raised when a reconciliation finds differences that require a case.
type Break struct {
	Differences []Difference
}

func (b Break) Error() string {
	parts := make([]string, 0, len(b.Differences))
	for _, d := range b.Differences {
		parts = append(parts, d.String())
	}
	return fmt.Sprintf("reconciliation break: %d difference(s): %v", len(b.Differences), parts)
}

// Unwrap exposes the ledger sentinel so errors.Is works for a reconciliation break the same
// way it does for a refused posting.
func (b Break) Unwrap() error { return ErrInvalidEntry }

// RequireReconciled returns a Break when the reconciliation finds differences.
//
// docs/05 section 'Reconciliation' states that a material unresolved break blocks affected
// risk-increasing actions. This function is the detection half; enforcing that block is the
// Risk Engine's job, and duplicating a risk decision here would create a second financial
// authority, which docs/01 section 3 prohibits.
func RequireReconciled(differences []Difference) error {
	if len(differences) == 0 {
		return nil
	}
	return Break{Differences: differences}
}
