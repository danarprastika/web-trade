package ledger

import (
	"errors"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// AC1: "Ledger records financial facts through append-only entries only."
// AC2: "Corrections are compensating entries, never in-place mutation."
// AC3: "Projections and caches are rebuildable and carry no financial authority."
// AC4: "Positions reconcile to validated fills."
//
// Each test below names the criterion it covers. The structural absence of an update or
// delete method is asserted separately, in structure_test.go, by reading the interface.

// ---------------------------------------------------------------------------
// AC1: append-only
// ---------------------------------------------------------------------------

// TestTheStoreHasNoUpdateAndNoDelete is the direct check for AC1. An append-only store that
// merely documents the rule is still updatable, so the rule is enforced by the interface
// having no method to violate it.
func TestTheStoreHasNoUpdateAndNoDelete(t *testing.T) {
	// The interface is the contract. If someone adds Update or Delete to Store, this
	// reflection over its method set fails, which is the alarm.
	forbidden := map[string]bool{
		"Update": true, "Delete": true, "Remove": true, "Mutate": true,
		"Set": true, "Put": true, "Patch": true, "Overwrite": true, "Rewrite": true,
		"Truncate": true, "Purge": true, "Reset": true, "Upsert": true,
	}
	storeType := reflectTypeOfStore()
	for i := 0; i < storeType.NumMethod(); i++ {
		name := storeType.Method(i).Name
		if forbidden[name] {
			t.Errorf("Store declares %s; an updatable or deletable ledger is a table, and "+
				"a table of financial facts cannot be reconciled because it has no history",
				name)
		}
	}

	// The concrete store is checked too, because an interface can be satisfied by a type
	// that offers more than the interface does. A caller holding a *MemoryStore could
	// reach a mutating method the interface never mentions.
	concrete := reflectTypeOfMemoryStore()
	for i := 0; i < concrete.NumMethod(); i++ {
		name := concrete.Method(i).Name
		if forbidden[name] {
			t.Errorf("*MemoryStore exposes %s even though Store does not; a mutation "+
				"reachable on the concrete type defeats append-only just as effectively", name)
		}
	}
}

// TestAnEntryCannotBeMutatedThroughTheStore covers the other way a store leaks authority:
// handing back a pointer into its own state.
func TestAnEntryCannotBeMutatedThroughTheStore(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	stored := mustAppend(t, s, validEntry(t, ids, 1))

	// Editing the returned entry must not change what the store holds. If Sequence handed
	// back the live slice, this would corrupt the ledger and nothing would notice until a
	// balance check failed much later.
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		t.Fatalf("Sequence: %v", err)
	}
	entries[0].Lines[0].Amount = dec(t, "999999.00")
	entries[0].Sequence = 4242

	again, err := s.Get(stored.EntryID)
	if err != nil {
		t.Fatalf("Get: %v", err)
	}
	if again.Sequence != stored.Sequence {
		t.Errorf("sequence became %d after the caller edited its copy, want %d",
			again.Sequence, stored.Sequence)
	}
	if cmp, _ := again.Lines[0].Amount.Cmp(dec(t, "1000.00")); cmp != 0 {
		t.Errorf("the stored amount became %s after the caller edited its copy, want 1000.00",
			again.Lines[0].Amount)
	}
}

// TestAppendedEntriesKeepTheirOrder pins the total order, since sequence is the ledger's
// only ordering authority.
func TestAppendedEntriesKeepTheirOrder(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	for n := 1; n <= 5; n++ {
		entry := validEntry(t, ids, n)
		entry.IdempotencyKey = "key-" + string(rune('a'+n-1))
		stored := mustAppend(t, s, entry)
		if stored.Sequence != int64(n-1) {
			t.Errorf("entry %d got sequence %d, want %d", n, stored.Sequence, n-1)
		}
	}
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		t.Fatalf("Sequence: %v", err)
	}
	for i, entry := range entries {
		if entry.Sequence != int64(i) {
			t.Errorf("position %d holds sequence %d", i, entry.Sequence)
		}
	}
	if err := VerifyAppendOnly(s); err != nil {
		t.Errorf("VerifyAppendOnly: %v", err)
	}
}

// TestAReplayedPostingIsANoOp covers the idempotency half of AC1. A retried request after a
// timeout is normal, and posting it twice would double a financial fact.
func TestAReplayedPostingIsANoOp(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	first := mustAppend(t, s, validEntry(t, ids, 1))

	replay := validEntry(t, ids, 1) // same id, same command, same key
	second, err := s.Append(replay)
	if err != nil {
		t.Fatalf("a replayed posting must be a no-op, not an error: %v", err)
	}
	if second.Sequence != first.Sequence {
		t.Errorf("a replay returned sequence %d, want the original %d",
			second.Sequence, first.Sequence)
	}
	if n, _ := s.Len(); n != 1 {
		t.Errorf("the ledger holds %d entries after a replay, want 1", n)
	}
}

// TestTheSameKeyFromADifferentCommandIsADifferentPosting prevents idempotency from becoming
// a way to lose a fact: two distinct commands must never collapse into one.
func TestTheSameKeyFromADifferentCommandIsADifferentPosting(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	first := validEntry(t, ids, 1)
	mustAppend(t, s, first)

	second := validEntry(t, ids, 2) // different entry id and command, same key
	second.IdempotencyKey = first.IdempotencyKey
	stored := mustAppend(t, s, second)

	if stored.Sequence == first.Sequence {
		t.Fatal("two different commands collapsed into one posting")
	}
	if n, _ := s.Len(); n != 2 {
		t.Errorf("the ledger holds %d entries, want 2", n)
	}
}

// TestAReusedEntryIdentityIsRefused covers the canonical-identity half of AC1.
func TestAReusedEntryIdentityIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	first := validEntry(t, ids, 1)
	mustAppend(t, s, first)

	// Same identity, different content and a different idempotency key, so the idempotency
	// check does not catch it first.
	clash := first
	clash.IdempotencyKey = "different"
	clash.Lines = append([]Line(nil), first.Lines...)
	clash.Lines[0].Amount = dec(t, "2000.00")
	clash.Lines[1].Amount = dec(t, "2000.00")

	if _, err := s.Append(clash); err == nil {
		t.Fatal("reusing a canonical entry identity must be refused")
	} else {
		var r Rejection
		if !errors.As(err, &r) || r.Code != contracts.CodeConflict {
			t.Errorf("a reused identity should be a CONFLICT, got %v", err)
		}
	}
}

// TestAnEntryWithNoSourceCommandIsRefused covers traceability, which docs/05 requires of
// every entry.
func TestAnEntryWithNoSourceCommandIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.SourceCommandID = contracts.Identifier{}
	if _, err := s.Append(entry); err == nil {
		t.Error("an entry with no source command must be refused; docs/05 requires every " +
			"entry to reference the command that caused it")
	}
}

func TestAnEntryWithNoCorrelationIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.CorrelationID = contracts.Identifier{}
	if _, err := s.Append(entry); err == nil {
		t.Error("an entry with no correlation id must be refused")
	}
}

func TestAnEntryWithNoIdempotencyKeyIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.IdempotencyKey = ""
	if _, err := s.Append(entry); err == nil {
		t.Error("an entry with no idempotency key must be refused, or a replayed request " +
			"would post a second time")
	}
}

// ---------------------------------------------------------------------------
// Balance, which is what makes the entries financial facts rather than notes
// ---------------------------------------------------------------------------

// TestAnUnbalancedEntryIsRefused is the core invariant of AC1: a posting with no
// counterpart creates or destroys value and is not a fact about anything.
func TestAnUnbalancedEntryIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	// Keep both lines in the same asset and the same direction class, so the only thing
	// wrong is the amount. This isolates the balance check from every other validation.
	entry.Lines[1].Amount = dec(t, "900.00")

	_, err := s.Append(entry)
	if err == nil {
		t.Fatal("an unbalanced entry must be refused")
	}
	if n, _ := s.Len(); n != 0 {
		t.Errorf("the refused entry was stored anyway; the ledger holds %d entries", n)
	}
	var r Rejection
	if !errors.As(err, &r) || r.Code != contracts.CodeValidation {
		t.Errorf("an unbalanced entry should be a VALIDATION_ERROR, got %v", err)
	}
	// The reason must name the asset and the imbalance, because this is the message an
	// operator triages a production posting failure from.
	for _, want := range []string{fixtureQuote, "does not balance"} {
		if !containsSubstring(err.Error(), want) {
			t.Errorf("the refusal %q should mention %q", err, want)
		}
	}
}

// TestABalanceAcrossDifferentAssetsIsNotATotal proves balance is per asset. A buy's two
// legs are in different assets and must not be added together.
func TestABalanceAcrossDifferentAssetsIsNotATotal(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	// A buy is a position up in BTC and cash down in USD. Those are different assets and
	// are not supposed to sum to zero; the clearing legs are what make it balance.
	postFill(t, s, ids, 1, f)
}

// TestAnEntryOfOneLineIsRefused, because a single posting cannot have a counterpart.
func TestAnEntryOfOneLineIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.Lines = entry.Lines[:1]
	if _, err := s.Append(entry); err == nil {
		t.Error("a one-line entry must be refused; it cannot balance")
	}
}

func TestANegativeAmountIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	// Amounts are positive and the direction carries the sign. A signed amount would make
	// a posting's meaning depend on which of two encodings a reader found.
	entry.Lines[0].Amount = dec(t, "-1000.00")
	entry.Lines[1].Amount = dec(t, "1000.00")
	if _, err := s.Append(entry); err == nil {
		t.Error("a negative amount must be refused")
	}
}

func TestAPositionLineWithMismatchedInstrumentIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.Lines = []Line{
		{Account: AccountPosition, Subject: "ETH-USD", Asset: "BTC-USD",
			Direction: Debit, Amount: dec(t, "1")},
		{Account: AccountClearing, Subject: fixtureVenue, Asset: "BTC-USD",
			Direction: Credit, Amount: dec(t, "1")},
	}
	if _, err := s.Append(entry); err == nil {
		t.Error("a position line whose subject and asset disagree must be refused")
	}
}

func TestAnEntryWithAnUnsetAmountIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.Lines[0].Amount = contracts.Decimal{}
	if _, err := s.Append(entry); err == nil {
		t.Error("a line with an unset amount must be refused; absent is not zero")
	}
}

func TestAnEntryWithAnUnrecognisedAccountIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.Lines[0].Account = AccountKind("SLUSH_FUND")
	if _, err := s.Append(entry); err == nil {
		t.Error("an account outside the closed set must be refused")
	}
}

func TestALedgerOfValidEntriesIsAlwaysBalanced(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	for n := 1; n <= 6; n++ {
		postFill(t, s, ids, n, validFill(t, ids, n))
	}
	if err := VerifyBalances(s); err != nil {
		t.Errorf("a ledger built only from balanced postings should verify: %v", err)
	}
}

// ---------------------------------------------------------------------------
// AC2: corrections are compensating entries
// ---------------------------------------------------------------------------

// TestACorrectionReversesTheEntryItCorrects is AC2 stated positively.
func TestACorrectionReversesTheEntryItCorrects(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))

	before, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	if before.IsZero() {
		t.Fatal("the fixture should have opened a position")
	}

	correction, err := Compensate(s, original.EntryID, ids.next(100), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "venue reported the execution as reversed; the fill was posted in error",
		IdempotencyKey:  "correction-1",
	})
	if err != nil {
		t.Fatalf("Compensate: %v", err)
	}

	after, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position after correction: %v", err)
	}
	if !after.IsZero() {
		t.Errorf("after correcting the only fill the position is %s, want exactly zero", after)
	}
	if len(correction.Lines) != len(original.Lines) {
		t.Fatalf("the correction has %d lines, the original has %d",
			len(correction.Lines), len(original.Lines))
	}
	for i, line := range correction.Lines {
		if line.Direction != original.Lines[i].Direction.Opposite() {
			t.Errorf("line %d has direction %s, want %s (the opposite of %s)",
				i, line.Direction, original.Lines[i].Direction.Opposite(), original.Lines[i].Direction)
		}
	}
	if correction.CorrectsEntryID != original.EntryID {
		t.Errorf("the correction references %s, want %s", correction.CorrectsEntryID, original.EntryID)
	}
}

// TestTheOriginalEntrySurvivesTheCorrection is the append-only half of AC2: a correction
// adds, it does not replace.
func TestTheOriginalEntrySurvivesTheCorrection(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))
	if _, err := Compensate(s, original.EntryID, ids.next(100), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "posted against the wrong portfolio",
		IdempotencyKey:  "correction-1",
	}); err != nil {
		t.Fatalf("Compensate: %v", err)
	}

	survived, err := s.Get(original.EntryID)
	if err != nil {
		t.Fatalf("the original entry disappeared after being corrected: %v", err)
	}
	if len(survived.Lines) != len(original.Lines) {
		t.Error("the original entry's lines were changed by the correction")
	}
	if n, _ := s.Len(); n != 2 {
		t.Errorf("the ledger holds %d entries, want 2: a correction appends, it does not "+
			"replace", n)
	}
}

// TestASecondCorrectionOfTheSameEntryIsRefused. Two corrections of one entry net to
// something other than the original, which is not what anybody meant.
func TestASecondCorrectionOfTheSameEntryIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))
	req := CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "first correction",
		IdempotencyKey:  "correction-1",
	}
	if _, err := Compensate(s, original.EntryID, ids.next(100), req); err != nil {
		t.Fatalf("the first correction should be allowed: %v", err)
	}
	req.Reason = "second correction"
	req.IdempotencyKey = "correction-2"
	if _, err := Compensate(s, original.EntryID, ids.next(101), req); err == nil {
		t.Fatal("a second correction of the same entry must be refused")
	}
}

func TestACorrectionOfAnEntryThatDoesNotExistIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	_, err := Compensate(s, ids.next(999), ids.next(100), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "correcting something that was never posted",
		IdempotencyKey:  "correction-1",
	})
	if err == nil {
		t.Fatal("correcting an entry that does not exist must be refused")
	}
}

// TestACorrectionOfACorrectionIsRefused stops history being rewritten. The original error is
// already reversed by the first correction.
func TestACorrectionOfACorrectionIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))
	correction, err := Compensate(s, original.EntryID, ids.next(100), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "posted in error",
		IdempotencyKey:  "correction-1",
	})
	if err != nil {
		t.Fatalf("Compensate: %v", err)
	}
	_, err = Compensate(s, correction.EntryID, ids.next(101), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T12:00:00Z"),
		SourceCommandID: ids.command(101),
		CorrelationID:   ids.correlation(1),
		Reason:          "correcting the correction",
		IdempotencyKey:  "correction-2",
	})
	if err == nil {
		t.Fatal("correcting a correction must be refused; the first correction already " +
			"reversed the original error")
	}
}

// TestACorrectionThatDoesNotReverseTheOriginalIsRefused. A "correction" with the same
// directions as the original still balances, so only this check stops it posting and
// doubling the entry.
func TestACorrectionThatDoesNotReverseTheOriginalIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))

	forged := original
	forged.EntryID = ids.next(100)
	forged.Sequence = 0
	forged.CorrectsEntryID = original.EntryID
	forged.Reason = "not actually a correction"
	forged.IdempotencyKey = "correction-1"
	forged.Lines = append([]Line(nil), original.Lines...) // same directions
	forged.PostedAt = ts(t, "2026-09-28T11:00:00Z")

	if _, err := s.Append(forged); err == nil {
		t.Fatal("a correction carrying the original's own directions must be refused; it " +
			"balances, so only this check stops it from doubling the entry")
	}
}

func TestACorrectionWithNoReasonIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))
	_, err := Compensate(s, original.EntryID, ids.next(100), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "   ",
		IdempotencyKey:  "correction-1",
	})
	if err == nil {
		t.Fatal("a correction with no reason must be refused; a correction nobody can " +
			"explain later is indistinguishable from a mistake")
	}
}

func TestAReasonOnAnOrdinaryPostingIsRefused(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	entry := validEntry(t, ids, 1)
	entry.Reason = "looks like a correction"
	if _, err := s.Append(entry); err == nil {
		t.Error("an ordinary posting carrying a correction reason must be refused, or the " +
			"two become indistinguishable when reviewing the history")
	}
}

// TestAReplayedCorrectionIsANoOp. Retrying a correction after a timeout must not double it.
func TestAReplayedCorrectionIsANoOp(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))
	req := CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "posted in error",
		IdempotencyKey:  "correction-1",
	}
	first, err := Compensate(s, original.EntryID, ids.next(100), req)
	if err != nil {
		t.Fatalf("Compensate: %v", err)
	}
	second, err := Compensate(s, original.EntryID, ids.next(100), req)
	if err != nil {
		t.Fatalf("a replayed correction must be a no-op: %v", err)
	}
	if first.Sequence != second.Sequence {
		t.Errorf("the replayed correction got sequence %d, want the original %d",
			second.Sequence, first.Sequence)
	}
	if n, _ := s.Len(); n != 2 {
		t.Errorf("the ledger holds %d entries after a replayed correction, want 2", n)
	}
}

// TestACorrectionIsPostedAfterTheOriginalItCorrects. A correction that inherits the
// original's time would sort as though it happened first.
func TestACorrectionIsPostedAfterTheOriginalItCorrects(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))
	correction, err := Compensate(s, original.EntryID, ids.next(100), CompensationRequest{
		PostedAt:        ts(t, "2026-09-27T09:00:00Z"), // earlier than the original
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "corrected with an earlier timestamp by mistake",
		IdempotencyKey:  "correction-1",
	})
	if err != nil {
		t.Fatalf("Compensate: %v", err)
	}
	if correction.Sequence <= original.Sequence {
		t.Error("a correction must be appended after the entry it corrects regardless of " +
			"the timestamps it carries; the sequence is the order things actually happened in")
	}
}

// ---------------------------------------------------------------------------
// AC3: projections are rebuildable and carry no authority
// ---------------------------------------------------------------------------

// TestAProjectionIsAFunctionOfTheEntries is AC3. Two rebuilds of the same history are
// equal, and the projection does not consult any stored total.
func TestAProjectionIsAFunctionOfTheEntries(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	for n := 1; n <= 4; n++ {
		f := validFill(t, ids, n)
		f.IdempotencyKey = "fill-" + string(rune('a'+n-1))
		postFill(t, s, ids, n, f)
	}

	first, err := Rebuild(s, AllSequences)
	if err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	second, err := Rebuild(s, AllSequences)
	if err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	if len(first.Balances) != len(second.Balances) {
		t.Fatalf("two rebuilds produced %d and %d balances", len(first.Balances), len(second.Balances))
	}
	for i := range first.Balances {
		a, b := first.Balances[i], second.Balances[i]
		// Compared field by field rather than with ==, because AccountBalance embeds a
		// contracts.Decimal, whose == is struct identity. Two decimals of equal value at
		// different scales are not the same struct, and treating them as different would
		// make this test fail for a reason that has nothing to do with rebuildability.
		if a.Account != b.Account || a.Subject != b.Subject || a.Asset != b.Asset {
			t.Errorf("balance %d differs between rebuilds: %s vs %s", i, a, b)
			continue
		}
		if !decimalsEqual(t, a.Amount, b.Amount) {
			t.Errorf("balance %d differs between rebuilds: %s vs %s", i, a, b)
		}
	}
}

// TestARebuildIgnoresEntriesPastItsSequence pins what UpTo means, which is what makes a
// snapshot reproducible.
func TestARebuildIgnoresEntriesPastItsSequence(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	first := postFill(t, s, ids, 1, f)
	postFill(t, s, ids, 2, validFill(t, ids, 2))

	full, err := Rebuild(s, AllSequences)
	if err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	asOfFirst, err := Rebuild(s, first.Sequence)
	if err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	if asOfFirst.UpTo != first.Sequence {
		t.Errorf("the snapshot reports UpTo %d, want %d", asOfFirst.UpTo, first.Sequence)
	}
	if !decimalsEqual(t, asOfFirst.Position(fixtureInstrument), f.Quantity) {
		t.Errorf("a snapshot as of the first entry holds %s, want exactly that first fill's %s",
			asOfFirst.Position(fixtureInstrument), f.Quantity)
	}
	if decimalsEqual(t, asOfFirst.Position(fixtureInstrument), full.Position(fixtureInstrument)) {
		t.Error("a snapshot as of the first entry should hold less than the full projection")
	}
}

// TestDiscardingAProjectionChangesNothing. A projection is a cache, so deleting it must be
// free. Here the projection is dropped on the floor and recomputed from the entries alone.
func TestDiscardingAProjectionChangesNothing(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	for n := 1; n <= 3; n++ {
		postFill(t, s, ids, n, validFill(t, ids, n))
	}

	before, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	// The projection is a value; dropping it and recomputing is what a cache eviction
	// looks like from the ledger's point of view.
	discarded, err := Rebuild(s, AllSequences)
	if err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	_ = discarded

	after, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	cmp, err := before.Cmp(after)
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if cmp != 0 {
		t.Errorf("the position changed from %s to %s after a rebuild; a projection holds "+
			"no authority and cannot move a balance", before, after)
	}

	rebuilt, err := Rebuild(s, AllSequences)
	if err != nil {
		t.Fatalf("Rebuild: %v", err)
	}
	if !decimalsEqual(t, rebuilt.Position(fixtureInstrument), before) {
		t.Error("the rebuilt projection does not match the ledger")
	}
}

// TestAProjectionCannotBeFedBackAsAFact. Handing a projected balance back as though it were
// a new posting would let a rounding difference become permanent.
func TestAProjectionCannotBeFedBackAsAFact(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	postFill(t, s, ids, 1, validFill(t, ids, 1))

	projected, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	// There is no function that turns a projection into an entry, and the balance-check
	// and store tests together show why: any such entry would have to balance against
	// something, and the only available counterpart would be the projection itself.
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		t.Fatalf("Sequence: %v", err)
	}
	total := contracts.Zero()
	for _, e := range entries {
		for _, line := range e.Lines {
			if line.Account == AccountPosition && line.Asset == fixtureInstrument {
				sum, err := total.Add(line.signed())
				if err != nil {
					t.Fatalf("Add: %v", err)
				}
				total = sum
			}
		}
	}
	cmp, err := projected.Cmp(total)
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if cmp != 0 {
		t.Errorf("the projection is %s but the entries fold to %s; a projection must be "+
			"exactly the fold, or it has become a second source of truth", projected, total)
	}
}

// ---------------------------------------------------------------------------
// AC4: positions reconcile to validated fills
// ---------------------------------------------------------------------------

// TestAPositionIsTheSumOfTheValidatedFills is AC4 in its simplest form.
func TestAPositionIsTheSumOfTheValidatedFills(t *testing.T) {
	ids := newIDs(t)
	s := newStore()

	var want = contracts.Zero()
	for n := 1; n <= 3; n++ {
		f := validFill(t, ids, n)
		f.IdempotencyKey = "fill-" + string(rune('a'+n-1))
		postFill(t, s, ids, n, f)
		sum, err := want.Add(f.Quantity)
		if err != nil {
			t.Fatalf("Add: %v", err)
		}
		want = sum
	}

	got, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	cmp, err := got.Cmp(want)
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if cmp != 0 {
		t.Errorf("the ledger holds %s, the validated fills sum to %s", got, want)
	}
}

// TestASellReducesThePositionWithoutInvertingIt covers the short side, because a position
// that only ever grows is not a position.
func TestASellReducesThePositionWithoutInvertingIt(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	buy := validFill(t, ids, 1)
	postFill(t, s, ids, 1, buy)

	sell := validFill(t, ids, 2)
	sell.Side = SideSell
	sell.IdempotencyKey = "fill-b"
	postFill(t, s, ids, 2, sell)

	got, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	want, err := buy.Quantity.Sub(sell.Quantity)
	if err != nil {
		t.Fatalf("Sub: %v", err)
	}
	cmp, err := got.Cmp(want)
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if cmp != 0 {
		t.Errorf("the ledger holds %s, want %s", got, want)
	}
}

func TestAShortPositionIsARealPosition(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	sell := validFill(t, ids, 1)
	sell.Side = SideSell
	postFill(t, s, ids, 1, sell)

	got, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	if got.Sign() >= 0 {
		t.Errorf("a lone sell should leave a short position, got %s", got)
	}
}

// TestAReconciliationFindsAPositionDifference is AC4's detection half.
func TestAReconciliationFindsAPositionDifference(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	postFill(t, s, ids, 1, validFill(t, ids, 1))

	// The OMS reports three units, the ledger holds the fill's two.
	differences, err := ReconcilePositions(s, map[string]contracts.Decimal{
		fixtureInstrument: dec(t, "3"),
	})
	if err != nil {
		t.Fatalf("ReconcilePositions: %v", err)
	}
	if len(differences) != 1 {
		t.Fatalf("found %d differences, want 1", len(differences))
	}
	d := differences[0]
	if d.Instrument != fixtureInstrument {
		t.Errorf("the difference is about %s, want %s", d.Instrument, fixtureInstrument)
	}
	if d.Ledger.Sign() == 0 {
		t.Error("a difference of zero is not a difference")
	}
	if err := RequireReconciled(differences); err == nil {
		t.Error("a difference must raise a break, because docs/05 requires an unresolved " +
			"break to block affected risk-increasing actions")
	}
}

// TestAPositionNobodyExpectedIsADifference. Iterating only the expected set would hide
// exactly this case.
func TestAPositionNobodyExpectedIsADifference(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	postFill(t, s, ids, 1, validFill(t, ids, 1))

	differences, err := ReconcilePositions(s, map[string]contracts.Decimal{})
	if err != nil {
		t.Fatalf("ReconcilePositions: %v", err)
	}
	if len(differences) != 1 {
		t.Fatalf("found %d differences, want 1: a position the ledger holds and nobody "+
			"expected is the most important kind of break", len(differences))
	}
}

// TestAReconciledLedgerReportsNoDifferences, so the detector is not simply always reporting.
func TestAReconciledLedgerReportsNoDifferences(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	postFill(t, s, ids, 1, f)

	differences, err := ReconcilePositions(s, map[string]contracts.Decimal{
		fixtureInstrument: f.Quantity,
	})
	if err != nil {
		t.Fatalf("ReconcilePositions: %v", err)
	}
	if len(differences) != 0 {
		t.Errorf("a matching ledger reported %d differences: %v", len(differences), differences)
	}
	if err := RequireReconciled(differences); err != nil {
		t.Errorf("a reconciled ledger must not raise a break: %v", err)
	}
}

// TestACorrectedFillReconcilesToFlat proves the correction path reaches AC4 as well.
func TestACorrectedFillReconcilesToFlat(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	original := postFill(t, s, ids, 1, validFill(t, ids, 1))
	if _, err := Compensate(s, original.EntryID, ids.next(100), CompensationRequest{
		PostedAt:        ts(t, "2026-09-28T11:00:00Z"),
		SourceCommandID: ids.command(100),
		CorrelationID:   ids.correlation(1),
		Reason:          "the fill was never reported by the venue",
		IdempotencyKey:  "correction-1",
	}); err != nil {
		t.Fatalf("Compensate: %v", err)
	}

	differences, err := ReconcilePositions(s, map[string]contracts.Decimal{
		fixtureInstrument: contracts.Zero(),
	})
	if err != nil {
		t.Fatalf("ReconcilePositions: %v", err)
	}
	if len(differences) != 0 {
		t.Errorf("a corrected fill should reconcile to flat, got %v", differences)
	}
}

// ---------------------------------------------------------------------------
// Fill translation
// ---------------------------------------------------------------------------

// TestARepeatedVenueReportPostsOneFill covers the case that costs real money: a venue that
// reports the same execution twice.
func TestARepeatedVenueReportPostsOneFill(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	postFill(t, s, ids, 1, f)
	// Same fill, re-derived and re-posted, as a repeated report would be.
	postFill(t, s, ids, 1, f)

	if n, _ := s.Len(); n != 1 {
		t.Errorf("the ledger holds %d entries after a repeated venue report, want 1", n)
	}
	got, err := Position(s, fixtureInstrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	cmp, err := got.Cmp(f.Quantity)
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if cmp != 0 {
		t.Errorf("the position is %s after a repeated report, want %s", got, f.Quantity)
	}
}

func TestTheNotionalIsExact(t *testing.T) {
	ids := newIDs(t)
	f := validFill(t, ids, 1)
	f.Quantity = dec(t, "0.1")
	f.Price = dec(t, "0.2")
	f.Fee = contracts.Zero()
	notional, err := f.Notional()
	if err != nil {
		t.Fatalf("Notional: %v", err)
	}
	// 0.1 * 0.2 is 0.02 exactly. In binary floating point it is
	// 0.020000000000000004, and an order sized by that notional would exceed its limit.
	if cmp, _ := notional.Cmp(dec(t, "0.02")); cmp != 0 {
		t.Errorf("notional is %s, want exactly 0.02", notional)
	}
}

func TestAZeroFeeNeedsNoCurrency(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	f.Fee = contracts.Zero()
	f.FeeCurrency = ""
	postFill(t, s, ids, 1, f)

	// No fee lines were posted, so the fee account must not appear at all.
	balances, err := Balances(s)
	if err != nil {
		t.Fatalf("Balances: %v", err)
	}
	for _, b := range balances {
		if b.Account == AccountFee {
			t.Errorf("a fill with no fee posted a %s balance", b)
		}
	}
}

func TestAZeroFeeWithACurrencyIsRefused(t *testing.T) {
	ids := newIDs(t)
	f := validFill(t, ids, 1)
	f.Fee = contracts.Zero()
	// FeeCurrency left as the fixture's "USD" with a zero amount: a fee line that should
	// not exist.
	if _, err := EntriesForFill(f, ids.next(1), ts(t, "2026-09-28T10:00:01Z")); err == nil {
		t.Error("a zero fee that still names a currency must be refused")
	}
}

func TestANonZeroFeeWithNoCurrencyIsRefused(t *testing.T) {
	ids := newIDs(t)
	f := validFill(t, ids, 1)
	f.FeeCurrency = ""
	if _, err := EntriesForFill(f, ids.next(1), ts(t, "2026-09-28T10:00:01Z")); err == nil {
		t.Error("a non-zero fee with no currency must be refused")
	}
}

func TestAFillWithNoVenueCannotBalance(t *testing.T) {
	ids := newIDs(t)
	f := validFill(t, ids, 1)
	f.Venue = ""
	if _, err := EntriesForFill(f, ids.next(1), ts(t, "2026-09-28T10:00:01Z")); err == nil {
		t.Error("a fill with no venue must be refused; the trade has no counterparty")
	}
}

func TestAFillWithNoExecutionTimeIsRefused(t *testing.T) {
	ids := newIDs(t)
	f := validFill(t, ids, 1)
	f.ExecutedAt = contracts.Timestamp{}
	if _, err := EntriesForFill(f, ids.next(1), ts(t, "2026-09-28T10:00:01Z")); err == nil {
		t.Error("a fill with no execution time must be refused")
	}
}

func TestAFillWithNoIdempotencyKeyIsRefused(t *testing.T) {
	ids := newIDs(t)
	f := validFill(t, ids, 1)
	f.IdempotencyKey = ""
	if _, err := EntriesForFill(f, ids.next(1), ts(t, "2026-09-28T10:00:01Z")); err == nil {
		t.Error("a fill with no idempotency key must be refused; venues repeat reports")
	}
}

func TestAVenueReferenceIsNeverTheIdentity(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	f.VenueOrderRef = "VEX-9931"
	entry := postFill(t, s, ids, 1, f)
	if entry.EntryID.Prefix() != contracts.PrefixLedger {
		t.Errorf("the entry identity is %s, want a canonical ledger identity", entry.EntryID)
	}
	if entry.EntryID.String() == f.VenueOrderRef {
		t.Error("the venue's reference became the ledger identity")
	}
}

// TestTheVenueClearingBalanceTracksWhatIsOwed is the operational signal the clearing
// account exists to carry.
func TestTheVenueClearingBalanceTracksWhatIsOwed(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	f := validFill(t, ids, 1)
	postFill(t, s, ids, 1, f)

	exposure, err := VenueExposure(s, fixtureVenue)
	if err != nil {
		t.Fatalf("VenueExposure: %v", err)
	}
	notional, err := f.Notional()
	if err != nil {
		t.Fatalf("Notional: %v", err)
	}
	// A buy leaves us owing the venue the cash we have not yet paid, less the fee, which
	// the fixture also posts against the clearing account. The net claim is therefore the
	// notional minus the fee, and anything else here would be a sign error.
	usd := exposure[fixtureQuote]
	if usd.Sign() != 1 {
		t.Errorf("the venue's USD claim is %s after a buy, want a debit balance", usd)
	}
	want, err := notional.Sub(f.Fee)
	if err != nil {
		t.Fatalf("Sub: %v", err)
	}
	if !decimalsEqual(t, usd, want) {
		t.Errorf("the venue's USD claim is %s, want the notional %s less the fee %s, "+
			"which is %s", usd, notional, f.Fee, want)
	}
}
