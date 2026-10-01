package model

import (
	"context"
	"sync"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Store is where the journal's writes go.
//
// It exists because the journal held its registry, its idempotency ledger, and nothing
// durable behind them, so a restart lost all three together. That gap was recorded against
// EV-037 through EV-040 and it got worse with each of them: EV-040 widened containment to
// every workload serving a compromised model version, which multiplies the number of
// revocations that a restart erases. A revocation that does not survive a process boundary
// is not a revocation, and the widening made that sentence apply to more state than before.
//
// The interface is deliberately two methods rather than a general repository. The journal
// performs exactly two kinds of durable write - register a model, and apply a transition -
// and a wider interface would invite a third that the migration's guards do not cover. What
// the interface does not have is as load-bearing as what it does: there is no read, no
// delete, and no update-by-model-id.
//
// The missing read is a real limitation and is called out rather than papered over. Reads
// still come from the journal's maps, so this store is a durable record of what was decided
// rather than the source the process recovers from. Restoring from it is blocked on the audit
// chain, which is still in-memory: a restarted journal would allocate sequence numbers from
// an empty chain while the persisted records for the same partition already occupy 1..n, and
// the next append would collide with a record that exists. See EV-042.
//
// ApplyTransition takes the state change and the idempotency entry as one call rather than
// two. Splitting them would leave a window in which a model has advanced but its transition
// is unrecorded, so a retry would see an unrecorded key, re-check the state, and refuse with
// a stale-state error - or worse, find the state already moved and treat a fresh request as
// a retry. A store that can only do these separately cannot close that window, so the port
// does not offer the option.
type Store interface {
	// InsertModel durably records a newly registered model and its initial state.
	//
	// The audit identifier is a parameter, not something the store derives. The migration
	// refuses a registration whose last_audit_id is empty, which is what stops a model from
	// existing in the registry without appearing in the audit chain.
	InsertModel(ctx context.Context, entry RegistryEntry) error

	// ApplyTransition durably advances a model's lifecycle state and records the
	// transition as applied, atomically with respect to one another.
	//
	// Either both land or neither does. The migration's guards already refuse a state
	// change citing no audit record and refuse an amended or deleted idempotency entry, so
	// a store that wrote only one of the two would be stopped by the database rather than
	// silently corrupting the registry - but being stopped by a constraint is a worse
	// design than not offering the partial write at all.
	ApplyTransition(ctx context.Context, entry TransitionEntry) error

	// Close releases the store's resources. It exists so the sql-backed implementation can
	// close its pool without the caller needing to know which implementation it holds, and
	// so a test can assert that a store was closed rather than assuming one was.
	Close() error
}

// RegistryEntry is one model's durable row.
type RegistryEntry struct {
	Record Record
	// State is the lifecycle state this write establishes.
	State State
	// AuditID is the audit record that caused this state. It is empty only for a
	// registration, where there is no prior event to be caused by; the database requires
	// it to be present on any state change.
	AuditID string
	// UpdatedBy names the identity that performed the write.
	UpdatedBy string
	// At is the write's time, from the journal's injected clock rather than the wall clock,
	// so a test cannot pass by accident because time moved.
	At time.Time
	// RegisteredAt is when the model entered the registry. It is separate from At because
	// the two differ for every write after registration, and a single timestamp column
	// would have to be rewritten on each transition - which the immutability guard on the
	// model record forbids.
	RegisteredAt time.Time
}

// TransitionEntry is one applied transition's durable row.
type TransitionEntry struct {
	// Scope and Key together are the caller's idempotency coordinates.
	Scope string
	Key   string
	// Fingerprint digests the request that produced this transition. A retry carrying a
	// different fingerprint under the same coordinates is a conflict, not a retry, and the
	// primary key on (scope, key) is what makes that a conflict rather than an overwrite.
	Fingerprint Digest
	ModelID     contracts.Identifier
	From        State
	To          State
	// AuditID is the record that caused the transition. It is the same identifier the
	// registry row carries, so an investigator starting from either store reaches the
	// same audit record.
	AuditID string
	At      time.Time
}

// MemoryStore is a Store that keeps everything in memory.
//
// It is the default rather than a test double. The journal's 122 existing tests exercise
// lifecycle and audit behaviour that has nothing to do with durability, and forcing each of
// them to stand up a database would trade a real cost - slow, flaky, and harder to read -
// for a property they do not assert. What this implementation does guarantee is that it
// obeys the same ordering contract as the durable one, so a test that passes against it is
// not accidentally testing behaviour the durable store does not have.
//
// The mutex here is separate from the journal's. A Store handed to two journals would
// otherwise be shared state with no protection, and the lock each journal holds does not
// compose.
type MemoryStore struct {
	mu          sync.Mutex
	models      map[string]RegistryEntry
	transitions map[string]TransitionEntry
	// writes counts successful durable writes, so a test can assert that a refused
	// transition wrote nothing durable rather than merely reporting an error.
	writes int
	// failWrite, when set, makes the next durable write fail. It exists so a test can
	// prove the journal does not advance its in-memory state on a store failure, which is
	// the property that separates a durable write from a best-effort one.
	failWrite error
	// failRead, when set, makes every snapshot read fail until it is cleared. The write path
	// had a seam already; the read path needed its own because a restore that cannot fail is a
	// restore nobody has tested against failure.
	failRead error
	closed   bool
}

// NewMemoryStore returns an in-memory Store.
func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		models:      make(map[string]RegistryEntry),
		transitions: make(map[string]TransitionEntry),
	}
}

// FailReads makes every snapshot read return err until it is cleared with nil.
//
// Persistent rather than single-shot, unlike FailNextWrite, because the property worth
// proving here is different: a caller whose restore fails must not have applied a partial
// snapshot, and that is a statement about what happens on every subsequent attempt rather
// than about recovery on the next one.
func (m *MemoryStore) FailReads(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failRead = err
}

// FailNextWrite makes the next durable write return err, once.
//
// It is deliberately a single-shot. A permanent failure would let a test pass without
// proving that the journal recovered on a later attempt, and the recovery is the part worth
// checking.
func (m *MemoryStore) FailNextWrite(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failWrite = err
}

// Writes counts the durable writes performed, so a test can assert that a refused
// transition wrote nothing durable rather than merely reporting an error.
func (m *MemoryStore) Writes() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.writes
}

func (m *MemoryStore) InsertModel(_ context.Context, entry RegistryEntry) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failWrite != nil {
		err := m.failWrite
		m.failWrite = nil
		return err
	}
	m.models[entry.Record.ModelID.String()] = entry
	m.writes++
	return nil
}

func (m *MemoryStore) ApplyTransition(_ context.Context, entry TransitionEntry) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failWrite != nil {
		err := m.failWrite
		m.failWrite = nil
		return err
	}
	// The transition row and the state it establishes are one unit, as they are in SQLStore
	// and as the Store contract says. Recording only the transition would leave the stored
	// model pinned at the state it was registered in, so a snapshot read would report a model
	// as REGISTERED for the life of the process while its own spent idempotency entries
	// asserted it had been advanced - and a restore built from that snapshot would bring back
	// a model contradicting its own ledger.
	if existing, ok := m.models[entry.ModelID.String()]; ok {
		existing.State = entry.To
		existing.AuditID = entry.AuditID
		existing.UpdatedBy = "journal"
		existing.At = entry.At
		m.models[entry.ModelID.String()] = existing
	}
	m.transitions[entry.Scope+"\x1f"+entry.Key] = entry
	m.writes++
	return nil
}

// Close marks the store closed and refuses further writes.
func (m *MemoryStore) Close() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.closed = true
	return nil
}

// Closed reports whether Close has been called.
func (m *MemoryStore) Closed() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.closed
}
