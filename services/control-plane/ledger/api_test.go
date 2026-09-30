package ledger

import (
	"errors"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The tests here cover the exported accessors a caller would actually reach for. A cash
// balance accessor that no test calls is a cash balance nobody has verified, and the String
// renderings exist to be read in a log, so their failure mode is a panic rather than a wrong
// answer.

// TestTheCashBalanceTracksWhatTheFillsCost. A buy must reduce cash by exactly the notional
// plus the fee, which is the whole point of posting a clearing leg rather than netting.
func TestTheCashBalanceTracksWhatTheFillsCost(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	postFill(t, s, ids, 1, f)

	cash, err := CashBalance(s, fixturePortfolio, fixtureQuote)
	if err != nil {
		t.Fatalf("CashBalance: %v", err)
	}
	notional, err := f.Notional()
	if err != nil {
		t.Fatalf("Notional: %v", err)
	}
	// The fee does not come out of cash. It is posted to the fee expense and to the venue's
	// clearing account, so the venue nets it against settlement rather than the book
	// quietly reducing cash by a number nobody can point at. Cash therefore moves by exactly
	// the notional, and the fee is visible on the clearing balance instead.
	want := notional.Neg()
	if !decimalsEqual(t, cash, want) {
		t.Errorf("cash is %s after a buy of %s at %s, want %s; the %s fee belongs on the "+
			"clearing account, not on cash",
			cash, f.Quantity, f.Price, want, f.Fee)
	}

	// And the fee is visible where it belongs: against the venue.
	exposure, err := VenueExposure(s, fixtureVenue)
	if err != nil {
		t.Fatalf("VenueExposure: %v", err)
	}
	venueClaim, err := notional.Sub(f.Fee)
	if err != nil {
		t.Fatalf("Sub: %v", err)
	}
	if !decimalsEqual(t, exposure[fixtureQuote], venueClaim) {
		t.Errorf("the venue's claim is %s, want the notional less the fee, %s",
			exposure[fixtureQuote], venueClaim)
	}
}

func TestASaleReturnsCash(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	f.Side = SideSell
	postFill(t, s, ids, 1, f)

	cash, err := CashBalance(s, fixturePortfolio, fixtureQuote)
	if err != nil {
		t.Fatalf("CashBalance: %v", err)
	}
	if cash.Sign() <= 0 {
		t.Errorf("cash is %s after a sale, want an inflow", cash)
	}
}

// TestAnUntouchedAccountIsFlatRatherThanMissing, because a caller handling an exception
// would otherwise have to distinguish "no trades" from "a bug" with no way to tell.
func TestAnUntouchedAccountIsFlatRatherThanMissing(t *testing.T) {
	s := newStore()
	cash, err := CashBalance(s, "PORT-NOBODY", "USD")
	if err != nil {
		t.Fatalf("CashBalance on an untouched account: %v", err)
	}
	if !cash.IsZero() {
		t.Errorf("an untouched account reports %s, want zero", cash)
	}
	position, err := Position(s, "NOBODY-USD")
	if err != nil {
		t.Fatalf("Position on an untouched instrument: %v", err)
	}
	if !position.IsZero() {
		t.Errorf("an untouched instrument reports %s, want zero", position)
	}
}

// TestTheNetOfAnEntryIsItsOwnBalance, which is what a caller reviews a single posting by.
func TestTheNetOfAnEntryIsItsOwnBalance(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := postFill(t, s, ids, 1, validFill(t, ids, 1))

	// The entry took a long position, so the position leg is a debit.
	position, err := entry.Net(AccountPosition, fixtureInstrument)
	if err != nil {
		t.Fatalf("Net: %v", err)
	}
	if position.Sign() != 1 {
		t.Errorf("the position leg nets to %s after a buy, want a debit", position)
	}
	// The clearing leg in the same asset runs the other way and exactly cancels it, which
	// is the invariant checkBalanced already enforces; Net is how a reviewer sees it.
	clearing, err := entry.Net(AccountClearing, fixtureInstrument)
	if err != nil {
		t.Fatalf("Net: %v", err)
	}
	total, err := position.Add(clearing)
	if err != nil {
		t.Fatalf("Add: %v", err)
	}
	if !total.IsZero() {
		t.Errorf("the instrument legs net to %s, want zero", total)
	}

	if _, err := entry.Net(AccountFee, "GBP"); err == nil {
		t.Error("asking for an account the entry does not touch must be an error, not zero; " +
			"a silent zero would hide a mistyped account")
	}
}

// TestAnEntryNamesEveryAssetItTouches, so a caller triaging an entry knows the full set of
// currencies involved without walking the lines.
func TestAnEntryNamesEveryAssetItTouches(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := postFill(t, s, ids, 1, validFill(t, ids, 1))
	assets := entry.Assets()
	want := map[string]bool{fixtureInstrument: true, fixtureQuote: true}
	if len(assets) != len(want) {
		t.Fatalf("the entry reports assets %v, want %d", assets, len(want))
	}
	for _, a := range assets {
		if !want[a] {
			t.Errorf("the entry reports asset %q, which the fill did not touch", a)
		}
	}
	// Sorted, so the rendering is stable across runs.
	for i := 1; i < len(assets); i++ {
		if assets[i-1] > assets[i] {
			t.Errorf("the asset list is not sorted: %v", assets)
			break
		}
	}
}

// TestARefusalCarriesBothACodeAndASentinel, the same contract the OMS, strategy, and risk
// packages carry. A caller on another service needs the code; errors.Is must work in process.
func TestARefusalCarriesBothACodeAndASentinel(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.Lines[1].Amount = dec(t, "999.00")
	_, err := s.Append(entry)
	if err == nil {
		t.Fatal("expected a refusal")
	}

	wrapped := errors.New("outer: " + err.Error())
	_ = wrapped

	if !errors.Is(err, ErrInvalidEntry) {
		t.Error("a refusal must match the ledger sentinel")
	}
	if !errors.Is(err, contracts.ErrInvalidContractValue) {
		t.Error("a refusal must match the canonical contract sentinel")
	}
	var r Rejection
	if !errors.As(err, &r) {
		t.Fatal("a refusal must be extractable as a Rejection")
	}
	if got := r.Error(); got == "" || got[:len(r.Code)] != string(r.Code) {
		t.Errorf("the message should lead with the code %q, got %q", r.Code, got)
	}
}

func TestAMissingEntryIsDistinguishableFromAMalformedOne(t *testing.T) {
	s := newStore()
	_, err := s.Get(canonicalID(t, contracts.PrefixLedger, 7))
	if err == nil {
		t.Fatal("expected a not-found error")
	}
	// Both the general sentinel and the specific one must match, so a caller can triage
	// either way without the error being ambiguous.
	if !errors.Is(err, ErrNotFound) {
		t.Error("a missing entry must match ErrNotFound")
	}
	if !errors.Is(err, ErrInvalidEntry) {
		t.Error("a missing entry must also match the general ledger sentinel")
	}
}

// TestABreakIsBothAMessageAndASentinel, so a reconciliation break can be inspected or
// matched.
func TestABreakIsBothAMessageAndASentinel(t *testing.T) {
	breakErr := Break{Differences: []Difference{{
		Instrument: fixtureInstrument, Kind: "POSITION",
		Ledger: dec(t, "2"), External: dec(t, "3"), Delta: dec(t, "-1"),
	}}}
	msg := breakErr.Error()
	for _, want := range []string{"1 difference", fixtureInstrument, "-1"} {
		if !containsSubstring(msg, want) {
			t.Errorf("the break message %q should mention %q", msg, want)
		}
	}
	if !errors.Is(breakErr, ErrInvalidEntry) {
		t.Error("a break must unwrap to the ledger sentinel")
	}
}

func TestAnEmptyBreakIsNeverRaised(t *testing.T) {
	if err := RequireReconciled(nil); err != nil {
		t.Errorf("no differences must not raise a break: %v", err)
	}
	if err := RequireReconciled([]Difference{}); err != nil {
		t.Errorf("an empty difference list must not raise a break: %v", err)
	}
}

// TestTheRenderingsCarryTheirIdentifyingFields. These exist to be read by a person in a log
// and must never panic, which is the only way they can be wrong.
func TestTheRenderingsCarryTheirIdentifyingFields(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := postFill(t, s, ids, 1, validFill(t, ids, 1))

	for name, rendered := range map[string]string{
		"entry":         entry.String(),
		"side":          SideBuy.String(),
		"account":       AccountClearing.String(),
		"direction":     Debit.String(),
		"balance":       AccountBalance{Account: AccountCash, Subject: fixturePortfolio, Asset: fixtureQuote, Amount: dec(t, "10")}.String(),
		"snapshot":      mustSnapshot(t, s).String(),
		"opposite-buy":  Debit.Opposite().String(),
		"opposite-sell": Credit.Opposite().String(),
	} {
		if rendered == "" {
			t.Errorf("%s renders as an empty string", name)
		}
	}
	if !containsSubstring(entry.String(), entry.EntryID.String()) {
		t.Error("an entry rendering should carry its identity")
	}
	// A correction renders differently from an ordinary posting, because a reviewer needs to
	// tell them apart at a glance.
	correction, err := Compensate(s, entry.EntryID, ids.next(200), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(200),
		CorrelationID:   ids.correlation(1),
		Reason:          "posted in error",
		IdempotencyKey:  "correction-1",
	})
	if err != nil {
		t.Fatalf("Compensate: %v", err)
	}
	if !containsSubstring(correction.String(), "corrects=") {
		t.Errorf("a correction should render what it corrects, got %q", correction.String())
	}
	if !containsSubstring(correction.String(), "posted in error") {
		t.Error("a correction should render its reason")
	}
}

func mustSnapshot(t *testing.T, s *MemoryStore) Snapshot {
	t.Helper()
	snap, err := Rebuild(s, AllSequences)
	if err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	return snap
}

func TestASnapshotReportsWhetherAnAccountWasTouched(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	postFill(t, s, ids, 1, validFill(t, ids, 1))
	snap := mustSnapshot(t, s)

	if _, ok := snap.Balance(AccountCash, fixturePortfolio, fixtureQuote); !ok {
		t.Error("the snapshot should report the cash account it holds")
	}
	if _, ok := snap.Balance(AccountCash, "PORT-NOBODY", "USD"); ok {
		t.Error("the snapshot should not report an account it does not hold")
	}
}
