package ledger

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Fixtures are built so that each test changes exactly one input from a valid baseline.
// Where a fixture is deliberately invalid it is built by a named mutation of the valid one
// rather than written out longhand, so the test states which single thing it is breaking.

const (
	fixtureInstrument = "BTC-USD"
	fixtureQuote      = "USD"
	fixturePortfolio  = "PORT-ALPHA"
	fixtureVenue      = "VENUE-X"
	fixtureActor      = "svc-order-gateway"
)

func id(t *testing.T, s string) contracts.Identifier {
	t.Helper()
	v, err := contracts.ParseIdentifier(s)
	if err != nil {
		t.Fatalf("fixture identifier %q is not canonical: %v", s, err)
	}
	return v
}

func dec(t *testing.T, s string) contracts.Decimal {
	t.Helper()
	v, err := contracts.ParseDecimal(s)
	if err != nil {
		t.Fatalf("fixture decimal %q is not canonical: %v", s, err)
	}
	return v
}

func ts(t *testing.T, s string) contracts.Timestamp {
	t.Helper()
	v, err := contracts.ParseTimestamp(s)
	if err != nil {
		t.Fatalf("fixture timestamp %q is not canonical: %v", s, err)
	}
	return v
}

// canonicalID mints a distinct valid identifier for a prefix.
//
// A canonical identifier is the prefix plus exactly 26 base32 characters, 30 in total, so
// the counter has 18 characters to work with after the fixed timestamp portion. Hand-writing
// these in fixtures is how tests end up sharing one identity and passing for the wrong
// reason, so they are minted from a counter instead.
func canonicalID(t *testing.T, prefix string, n int) contracts.Identifier {
	t.Helper()
	const alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
	// 8 fixed characters stand in for the timestamp; the remaining 18 hold the counter.
	var digits []byte
	for v := n; v > 0; v /= 32 {
		digits = append([]byte{alphabet[v%32]}, digits...)
	}
	if len(digits) > 18 {
		t.Fatalf("counter %d needs %d base32 digits, which exceeds the 18 available in a "+
			"canonical identifier", n, len(digits))
	}
	body := []byte("01jq7x5a")
	for len(body)+len(digits) < 26 {
		body = append(body, '0')
	}
	body = append(body, digits...)
	// The canonical payload alphabet is lowercase Crockford Base32.
	parsed, err := contracts.ParseIdentifier(prefix + strings.ToLower(string(body)))
	if err != nil {
		t.Fatalf("generated identifier %q is not canonical: %v", prefix+string(body), err)
	}
	return parsed
}
func newIDs(t *testing.T) *idGen { return &idGen{t: t} }

type idGen struct{ t *testing.T }

func (g *idGen) next(n int) contracts.Identifier {
	g.t.Helper()
	return canonicalID(g.t, contracts.PrefixLedger, n)
}

func (g *idGen) order(n int) contracts.Identifier {
	g.t.Helper()
	return canonicalID(g.t, contracts.PrefixOrder, n)
}

func (g *idGen) command(n int) contracts.Identifier {
	g.t.Helper()
	return canonicalID(g.t, contracts.PrefixCommand, n)
}

// correlation is the root command of the request chain an entry belongs to. It carries the
// command prefix because the canonical identifier set has no separate correlation prefix, and
// that is the right fit: a correlation is the command whose request started the chain.
func (g *idGen) correlation(n int) contracts.Identifier {
	g.t.Helper()
	// Offset into a high counter range so a correlation never coincides with the specific
	// command that posted the entry, even in a one-entry fixture.
	return canonicalID(g.t, contracts.PrefixCommand, 900000+n)
}

// validEntry is the baseline: two legs in one asset that balance exactly.
func validEntry(t *testing.T, ids *idGen, n int) Entry {
	t.Helper()
	return Entry{
		EntryID:         ids.next(n),
		PostedAt:        ts(t, "2026-09-28T10:00:00Z"),
		SourceCommandID: ids.command(n),
		CorrelationID:   ids.correlation(1),
		IdempotencyKey:  "baseline",
		Lines: []Line{
			{Account: AccountCash, Subject: fixturePortfolio, Asset: fixtureQuote,
				Direction: Debit, Amount: dec(t, "1000.00")},
			{Account: AccountClearing, Subject: fixtureVenue, Asset: fixtureQuote,
				Direction: Credit, Amount: dec(t, "1000.00")},
		},
	}
}

func newStore() *MemoryStore { return NewMemoryStore() }

// validFill is a buy of 2 BTC-USD at 30000 with a 1.00 USD fee.
func validFill(t *testing.T, ids *idGen, n int) Fill {
	t.Helper()
	return Fill{
		OrderID:         ids.order(n),
		Instrument:      fixtureInstrument,
		Side:            SideBuy,
		Quantity:        dec(t, "2"),
		Price:           dec(t, "30000"),
		QuoteCurrency:   fixtureQuote,
		Fee:             dec(t, "1.00"),
		FeeCurrency:     fixtureQuote,
		Portfolio:       fixturePortfolio,
		Venue:           fixtureVenue,
		VenueOrderRef:   "VEX-9931",
		ExecutedAt:      ts(t, "2026-09-28T10:00:00Z"),
		SourceCommandID: ids.command(n),
		CorrelationID:   ids.correlation(1),
		IdempotencyKey:  "fill-1",
	}
}

// postFill validates and appends the entries for a fill, failing the test on refusal.
func postFill(t *testing.T, s *MemoryStore, ids *idGen, n int, f Fill) Entry {
	t.Helper()
	entry, err := EntriesForFill(f, ids.next(n), ts(t, "2026-09-28T10:00:01Z"))
	if err != nil {
		t.Fatalf("building entries for fill %d: %v", n, err)
	}
	stored, err := s.Append(entry)
	if err != nil {
		t.Fatalf("appending entries for fill %d: %v", n, err)
	}
	return stored
}

func mustAppend(t *testing.T, s *MemoryStore, e Entry) Entry {
	t.Helper()
	stored, err := s.Append(e)
	if err != nil {
		t.Fatalf("appending %s: %v", e, err)
	}
	return stored
}
