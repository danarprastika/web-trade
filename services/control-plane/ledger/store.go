package ledger

import (
	"fmt"
	"sort"
	"sync"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// AllSequences asks for every entry.
//
// It is -1 rather than 0 because 0 is the sequence of the very first entry. Using 0 as the
// "no upper bound" sentinel would silently make a snapshot as of the first entry identical
// to a full snapshot, which is a wrong answer rather than an error.
const AllSequences int64 = -1

// Store is the append-only ledger.
//
// The absence of an update and a delete method is the point of this interface, not an
// oversight. A ledger with an update method is a table, and a table that holds financial
// facts cannot be reconciled against a venue record, because there is no history to compare
// it to. Every durable ledger implementation behind this interface must therefore be
// append-only at the storage layer too, enforced by the database and not by convention
// (docs/25 section 4, persistence row: "Treating cache, event bus, or analytics store as
// source of truth" is the prohibited behaviour, and an updatable ledger is exactly that).
type Store interface {
	// Append records a validated entry and returns it with the sequence assigned.
	//
	// Appending an entry whose (SourceCommandID, IdempotencyKey) pair has already been
	// recorded is a no-op that returns the original entry. A replayed request must not
	// post twice, and it must not be an error either, because a retry after a timeout is
	// the normal case rather than a fault.
	Append(entry Entry) (Entry, error)

	// Get returns the entry with the given id.
	Get(id contracts.Identifier) (Entry, error)

	// Sequence returns every entry in ledger order up to and including a sequence, or every
	// entry when upTo is AllSequences. This is the input to a projection rebuild, so it
	// must return a copy: a caller that mutated the returned slice would be mutating the
	// ledger.
	Sequence(upTo int64) ([]Entry, error)

	// Len returns the number of entries.
	Len() (int, error)
}

// ErrNotFound is returned when an entry does not exist. It is a distinct sentinel so that
// "no such entry" and "the ledger is broken" are not the same event to a caller.
//
// It wraps ErrInvalidEntry, so a caller that only cares that the call failed can still match
// the general sentinel, while a caller triaging a correction can tell a missing target from
// a malformed request.
var ErrNotFound = fmt.Errorf("no such ledger entry: %w", ErrInvalidEntry)

// MemoryStore is an in-memory Store.
//
// It exists so the domain rules can be proven without a database, and so the balance,
// append-only, and idempotency properties can be tested against a real implementation rather
// than against a mock that cannot fail. It is not a production store: it holds nothing
// across a restart, which is a property a financial system may not have.
type MemoryStore struct {
	mu sync.RWMutex
	// byID indexes entries by identity for Get and for correction resolution.
	byID map[string]Entry
	// order is the authoritative total order. Appends go to the end and are never
	// reordered.
	order []Entry
	// byIdempotency indexes by source command and idempotency key together. Keying on the
	// idempotency key alone would let two different commands collide on a key and one would
	// silently disappear, which is the same class of defect as losing a fill.
	byIdempotency map[string]Entry
	// correctedBy records which entries already have a compensation, so a second
	// correction of the same entry is refused rather than applied twice.
	correctedBy  map[string]Entry
	nextSequence int64
}

// NewMemoryStore returns an empty store.
func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		byID:          map[string]Entry{},
		byIdempotency: map[string]Entry{},
		correctedBy:   map[string]Entry{},
	}
}

var _ Store = (*MemoryStore)(nil)

// Append implements Store.
//
// The lock is held across validation and insert. Validation reads the entry being corrected
// for a compensation, so validating outside the lock would let two concurrent corrections of
// the same entry both pass the "not already corrected" check and then both be written.
func (s *MemoryStore) Append(entry Entry) (Entry, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if err := entry.validate(); err != nil {
		return Entry{}, reject(contracts.CodeValidation,
			"entry %s is not postable: %v", entry.EntryID, err)
	}

	// A replay is a no-op, not a fault. Returning the stored entry rather than the
	// submitted one matters: the stored one carries the sequence, and a caller that
	// received a sequence-less copy could not tell a replay from a first post.
	if existing, ok := s.byIdempotency[idempotencyKey(entry)]; ok {
		return existing, nil
	}

	if _, exists := s.byID[entry.EntryID.String()]; exists {
		return Entry{}, reject(contracts.CodeConflict,
			"entry id %s is already recorded at sequence %d; a canonical identity is "+
				"minted once and never reused", entry.EntryID, existingSequence(s, entry))
	}

	if entry.IsCompensation() {
		if err := s.checkCorrectionAllowed(entry); err != nil {
			return Entry{}, err
		}
	}

	entry.Sequence = s.nextSequence
	s.nextSequence++

	s.byID[entry.EntryID.String()] = entry
	s.order = append(s.order, entry)
	s.byIdempotency[idempotencyKey(entry)] = entry
	if entry.IsCompensation() {
		s.correctedBy[entry.CorrectsEntryID.String()] = entry
	}
	return entry, nil
}

// checkCorrectionAllowed enforces that a correction is a real correction: of an entry that
// exists, that is not already corrected, and whose lines this entry genuinely reverses.
func (s *MemoryStore) checkCorrectionAllowed(entry Entry) error {
	target, ok := s.byID[entry.CorrectsEntryID.String()]
	if !ok {
		return reject(contracts.CodeConflict,
			"entry %s corrects %s, which is not in the ledger; a correction that reverses "+
				"nothing is indistinguishable from a fabricated fact",
			entry.EntryID, entry.CorrectsEntryID)
	}
	if target.IsCompensation() {
		return reject(contracts.CodeConflict,
			"entry %s corrects %s, which is itself a correction of %s; a correction of a "+
				"correction reverses history instead of cancelling an error, and the "+
				"original error is reversed by the first correction",
			entry.EntryID, target.EntryID, target.CorrectsEntryID)
	}
	if first, already := s.correctedBy[entry.CorrectsEntryID.String()]; already {
		return reject(contracts.CodeConflict,
			"entry %s corrects %s, which was already corrected by %s; a second correction "+
				"of the same entry would net to something other than the original balance",
			entry.EntryID, entry.CorrectsEntryID, first.EntryID)
	}
	// The compensation must actually reverse the target. Without this check a caller could
	// post a "correction" with the same direction as the original, which would pass the
	// balance check while doubling the posting.
	if !mirrors(entry, target) {
		return reject(contracts.CodeValidation,
			"entry %s does not reverse %s line for line; a compensation must carry the same "+
				"lines with opposite directions, otherwise it is a new fact rather than a "+
				"correction", entry.EntryID, target.EntryID)
	}
	return nil
}

// mirrors reports whether correction is target with every direction reversed.
//
// It compares the two as multisets rather than by keying on account, subject, and asset.
// A fill posts two lines to the same clearing account in the same currency: one for the
// notional and one for the fee. Keyed on account and asset alone, the second overwrites the
// first and every later comparison is against the wrong line, which would reject a correct
// compensation. Including the direction and the amount in the signature keeps duplicate
// postings distinct, and sorting makes the comparison independent of line order so a caller
// need not reproduce the original's ordering.
func mirrors(correction, target Entry) bool {
	if len(correction.Lines) != len(target.Lines) {
		return false
	}
	wanted := make([]string, 0, len(target.Lines))
	for _, line := range target.Lines {
		wanted = append(wanted, lineSignature(line.Account, line.Subject, line.Asset,
			line.Direction.Opposite(), line.Amount))
	}
	got := make([]string, 0, len(correction.Lines))
	for _, line := range correction.Lines {
		got = append(got, lineSignature(line.Account, line.Subject, line.Asset,
			line.Direction, line.Amount))
	}
	sort.Strings(wanted)
	sort.Strings(got)
	for i := range wanted {
		if wanted[i] != got[i] {
			return false
		}
	}
	return true
}

// lineSignature is a full, unambiguous fingerprint of one posting. The amount is rendered
// canonically so two postings of equal value at different scales are the same posting, which
// is what a compensation must reproduce.
func lineSignature(account AccountKind, subject, asset string, direction Direction, amount contracts.Decimal) string {
	return string(account) + "|" + subject + "|" + asset + "|" + string(direction) + "|" + amount.String()
}

func idempotencyKey(e Entry) string {
	return e.SourceCommandID.String() + "|" + e.IdempotencyKey
}

func existingSequence(s *MemoryStore, e Entry) int64 {
	return s.byID[e.EntryID.String()].Sequence
}

// Get implements Store.
func (s *MemoryStore) Get(id contracts.Identifier) (Entry, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	entry, ok := s.byID[id.String()]
	if !ok {
		return Entry{}, Rejection{
			Code:   contracts.CodeConflict,
			Cause:  ErrNotFound,
			Reason: fmt.Sprintf("no ledger entry with id %s", id),
		}
	}
	return entry, nil
}

// Sequence implements Store.
func (s *MemoryStore) Sequence(upTo int64) ([]Entry, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]Entry, 0, len(s.order))
	for _, entry := range s.order {
		if upTo != AllSequences && entry.Sequence > upTo {
			break
		}
		// A copy of the struct, but the Lines slice is shared. The entry is treated as
		// immutable by convention and the lines are validated on append, so a caller
		// reaching in and editing a line would be violating the contract the type
		// documents. The slice header is copied so appending to the result cannot disturb
		// the ledger's own slice.
		entry.Lines = append([]Line(nil), entry.Lines...)
		out = append(out, entry)
	}
	return out, nil
}

// Len implements Store.
func (s *MemoryStore) Len() (int, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.order), nil
}

// Compensate builds and appends the correcting entry for an existing one.
//
// The compensating entry is constructed here rather than assembled by the caller, because a
// hand-built correction is exactly the thing this package exists to prevent: it is easy to
// copy the lines and forget to flip one direction, and the result still balances, so it
// posts successfully and doubles half the entry.
//
// The new entry needs its own identity, its own idempotency key, and its own reason. A
// caller supplies the reason because a correction without one cannot be reviewed later, and
// nobody but the correcting party knows why.
func Compensate(s Store, corrects contracts.Identifier, newID contracts.Identifier, req CompensationRequest) (Entry, error) {
	target, err := s.Get(corrects)
	if err != nil {
		return Entry{}, err
	}
	entry := Entry{
		EntryID:         newID,
		PostedAt:        req.PostedAt,
		Lines:           target.reversedLines(),
		SourceCommandID: req.SourceCommandID,
		CorrelationID:   req.CorrelationID,
		CorrectsEntryID: corrects,
		Reason:          req.Reason,
		IdempotencyKey:  req.IdempotencyKey,
	}
	return s.Append(entry)
}

// CompensationRequest is what a caller must supply to post a correction.
type CompensationRequest struct {
	// PostedAt is the time of the correction, not the time of the original. A correction
	// that inherited the original's timestamp would sort as if it happened first, and the
	// ledger order would stop matching what actually happened.
	PostedAt contracts.Timestamp
	// SourceCommandID is the command that caused the correction. It is not the original's
	// command: that command is the reason the entry exists, and reusing it would file the
	// correction under the original decision and hide the second decision entirely.
	SourceCommandID contracts.Identifier
	// CorrelationID ties the correction to the request that caused it.
	CorrelationID contracts.Identifier
	// Reason explains what was wrong. Required.
	Reason string
	// IdempotencyKey makes a replayed correction a no-op.
	IdempotencyKey string
}

// VerifyBalances re-checks every entry's balance invariant over the whole ledger.
//
// It exists because the invariant is enforced on append, and a store that can be reached by
// something other than Append (a migration, a restore, a future writer) would not be covered
// by that enforcement. Running it over the recorded history is the check a reviewer can run
// against a real database dump.
func VerifyBalances(s Store) error {
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if err := entry.checkBalanced(); err != nil {
			return reject(contracts.CodeInternal,
				"ledger entry %d (%s) does not balance: %v", entry.Sequence, entry.EntryID, err)
		}
	}
	return nil
}

// VerifyAppendOnly checks that the sequence is dense, strictly increasing, and free of
// duplicate identities, which are the three ways an append-only store can be quietly wrong
// without any entry being individually invalid.
func VerifyAppendOnly(s Store) error {
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		return err
	}
	seen := map[string]bool{}
	for i, entry := range entries {
		if entry.Sequence != int64(i) {
			return reject(contracts.CodeInternal,
				"ledger sequence is not dense: position %d holds sequence %d; a gap or a "+
					"reorder means the total order is not the order things were posted in",
				i, entry.Sequence)
		}
		if seen[entry.EntryID.String()] {
			return reject(contracts.CodeInternal,
				"ledger entry id %s appears at more than one sequence", entry.EntryID)
		}
		seen[entry.EntryID.String()] = true
	}
	return nil
}

// AccountBalance is the net balance of one account in one asset, summed over the ledger.
type AccountBalance struct {
	Account AccountKind
	Subject string
	Asset   string
	// Amount is signed: positive is a debit balance, which for cash and position accounts
	// is an asset held.
	Amount contracts.Decimal
}

func (b AccountBalance) String() string {
	return fmt.Sprintf("%s[%s] %s %s", b.Account, b.Subject, b.Amount, b.Asset)
}

// balances folds the entries into a map keyed by account, subject, and asset. The key is
// built with a separator that cannot appear in a subject, so two different postings cannot
// be folded into one key.
func balances(entries []Entry) (map[string]AccountBalance, error) {
	out := map[string]AccountBalance{}
	for _, entry := range entries {
		for _, line := range entry.Lines {
			key := string(line.Account) + "\x00" + line.Subject + "\x00" + line.Asset
			existing, ok := out[key]
			if !ok {
				existing = AccountBalance{
					Account: line.Account, Subject: line.Subject, Asset: line.Asset,
					Amount: contracts.Zero(),
				}
			}
			sum, err := existing.Amount.Add(line.signed())
			if err != nil {
				return nil, reject(contracts.CodeInternal,
					"folding %s[%s] in %s: %v", line.Account, line.Subject, line.Asset, err)
			}
			existing.Amount = sum
			out[key] = existing
		}
	}
	return out, nil
}

// Balances returns every account balance in the ledger, sorted for stable output.
func Balances(s Store) ([]AccountBalance, error) {
	entries, err := s.Sequence(AllSequences)
	if err != nil {
		return nil, err
	}
	folded, err := balances(entries)
	if err != nil {
		return nil, err
	}
	out := make([]AccountBalance, 0, len(folded))
	for _, b := range folded {
		// A balance that nets to zero is not worth reporting. Zero here means the account
		// was opened and closed, which is a fact about the entry history and not about the
		// current position.
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
	return out, nil
}
