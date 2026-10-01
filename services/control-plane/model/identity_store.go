package model

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sync"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// IdentityStore is where workload identity issuance and revocation are recorded durably.
//
// It is a separate port from Store rather than two more methods on it, because the registry
// that holds identities does not need to reach the model registry, and a journal that could
// insert a revocation would be a journal that could revoke a workload. The two are joined by
// the model version they both name, not by sharing a write path.
//
// The port has no read for the same reason Store has none: reads come from the registry's
// own state, and adding a read here would make it look like the store were the recovery
// source when it is not. See EV-042 on why restoring is blocked.
//
// What it deliberately does not have is a delete, and that absence is the point of the type.
// The registry removes a revoked identity from its live map, because a revoked identity is
// no longer something the registry answers "yes" to. A durable store that mirrored that by
// deleting the row would destroy the record of what was issued - which is precisely the
// evidence an investigation needs, since the revocation's reason and the forensic reference
// only mean something next to the identity they were issued against. So the durable record
// keeps the row and adds a revocation beside it, and the two together are what a responder
// reads. There is no query that removes a row, and the migration refuses one.
type IdentityStore interface {
	// InsertIdentity durably records a newly issued workload identity.
	//
	// The expiry is the registry's computed value, not a database default. The registry
	// bounds the lifetime to WorkloadTTL and the migration bounds it again, and a
	// database-side now() would make the stored lifetime depend on insert latency.
	InsertIdentity(ctx context.Context, identity WorkloadIdentity) error

	// InsertRevocation durably records that an identity was revoked, and why.
	//
	// The identity row is left in place. Revocation is additive: it says something happened
	// on a given date, and removing what it happened to would leave a revocation citing a
	// subject that no longer exists anywhere.
	InsertRevocation(ctx context.Context, rev Revocation) error
}

// MemoryIdentityStore is an in-memory IdentityStore.
//
// As with MemoryStore it is the default rather than a test double: the registry's existing
// tests are about expiry, binding, and revocation semantics, and standing up a database for
// each would make them slower and no more informative. What it does guarantee is the same
// ordering contract as the durable one, so a test that passes here is not testing behaviour
// the durable store lacks.
//
// The mutex is its own because an IdentityStore may be handed to registries in different
// processes; the per-registry lock does not compose across them.
type MemoryIdentityStore struct {
	mu          sync.Mutex
	identities  map[string]WorkloadIdentity
	revocations map[string]Revocation
	// failWrite, when set, makes the next durable write fail once. It exists so a test can
	// prove the registry does not act on a revocation the store never recorded - the
	// failure mode being that a compromise response reports containment it did not achieve.
	failWrite error
	// failRead, when set, makes every snapshot read fail until it is cleared with nil. The
	// write path has its own seam already; this one exists because a restore that cannot fail
	// is a restore nobody has tested against failure.
	failRead error
	writes   int
}

// FailReads makes every snapshot read return err until it is cleared with nil.
//
// Persistent rather than single-shot, unlike FailNextWrite, because the property worth proving
// is different: a registry whose restore failed must be left empty rather than half-populated,
// and that has to hold on every attempt rather than only the first.
func (m *MemoryIdentityStore) FailReads(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failRead = err
}

// NewMemoryIdentityStore returns an in-memory IdentityStore.
func NewMemoryIdentityStore() *MemoryIdentityStore {
	return &MemoryIdentityStore{
		identities:  map[string]WorkloadIdentity{},
		revocations: map[string]Revocation{},
	}
}

// FailNextWrite makes the next durable write return err, once.
func (m *MemoryIdentityStore) FailNextWrite(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failWrite = err
}

// Writes counts successful durable writes.
func (m *MemoryIdentityStore) Writes() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.writes
}

// HasIdentity reports whether a row was durably recorded for an identity.
//
// It is a read on the concrete type rather than on the port, because the port must not offer
// reads. That is the arrangement the port comment describes: the durable store is a record of
// what happened, not the source the process recovers from, and a test that wants to check
// the record has to ask for it explicitly.
func (m *MemoryIdentityStore) HasIdentity(identity string) (WorkloadIdentity, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	w, ok := m.identities[identity]
	return w, ok
}

// Revocation records a revocation read back from the store.
func (m *MemoryIdentityStore) Revocation(identity string) (Revocation, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	rev, ok := m.revocations[identity]
	return rev, ok
}

func (m *MemoryIdentityStore) InsertIdentity(_ context.Context, identity WorkloadIdentity) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failWrite != nil {
		err := m.failWrite
		m.failWrite = nil
		return err
	}
	// The issued row is kept, not replaced-on-revoke. See the port comment.
	m.identities[identity.Identity] = identity
	m.writes++
	return nil
}

func (m *MemoryIdentityStore) InsertRevocation(_ context.Context, rev Revocation) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failWrite != nil {
		err := m.failWrite
		m.failWrite = nil
		return err
	}
	m.revocations[rev.Identity] = rev
	m.writes++
	return nil
}

// SQLIdentityStore is the durable IdentityStore, backed by the generated accessors.
//
// The transaction wrapper is shared with SQLStore's own by being a field on a shared
// embedded helper rather than duplicated: two implementations of "run these two statements
// or neither" that happen to agree today is one more thing to keep in step tomorrow.
type SQLIdentityStore struct {
	q     identityQuerier
	begin func(ctx context.Context, fn func(identityQuerier) error) error
	close func() error
}

// identityQuerier is the subset of the generated accessors this store uses.
//
// Two methods, neither of which can remove a row. The narrowing is not decoration: a store
// holding the full dbgen.Querier could be handed a query that deletes an identity, and the
// type system would not object.
type identityQuerier interface {
	InsertWorkloadIdentity(
		ctx context.Context, arg dbgen.InsertWorkloadIdentityParams,
	) (dbgen.WorkloadIdentity, error)
	InsertRevocation(ctx context.Context, arg dbgen.InsertRevocationParams) (dbgen.WorkloadRevocation, error)
}

// NewSQLIdentityStore returns a SQLIdentityStore over a database handle.
func NewSQLIdentityStore(db *sql.DB) (*SQLIdentityStore, error) {
	if db == nil {
		return nil, errors.New("a sql-backed identity store requires a database handle; " +
			"constructing one here would hide the pool from the caller's shutdown sequence")
	}
	return &SQLIdentityStore{
		q:     dbgen.New(db),
		close: db.Close,
		begin: beginTx[identityQuerier](db, func(tx *sql.Tx) identityQuerier { return dbgen.New(tx) }),
	}, nil
}

// Close releases the underlying pool.
func (s *SQLIdentityStore) Close() error {
	if s.close == nil {
		return nil
	}
	return s.close()
}

// InsertIdentity durably records a newly issued workload identity.
func (s *SQLIdentityStore) InsertIdentity(ctx context.Context, identity WorkloadIdentity) error {
	_, err := s.q.InsertWorkloadIdentity(ctx, dbgen.InsertWorkloadIdentityParams{
		Identity:     identity.Identity,
		ModelID:      identity.ModelID.String(),
		ModelVersion: identity.ModelVersion,
		Scope:        string(identity.Scope),
		IssuedAtUtc:  identity.IssuedAt,
		ExpiresAtUtc: identity.ExpiresAt,
	})
	if err != nil {
		return fmt.Errorf("recording workload identity %q: %w", identity.Identity, err)
	}
	return nil
}

// InsertRevocation durably records a revocation.
//
// It runs inside a transaction even though it is a single statement, and that is not
// ceremony. The statement is the last thing that makes a compromise response durable; if it
// is written outside the same unit as the in-memory state change, a failure between them
// leaves the registry believing a workload is revoked while nothing durable says so. Holding
// a transaction for one statement costs a round trip and buys a single, well-defined place
// where the answer changes.
//
// There is no delete of the identity row here, and the omission is deliberate: the row is
// what the revocation is evidence about.
func (s *SQLIdentityStore) InsertRevocation(ctx context.Context, rev Revocation) error {
	return s.begin(ctx, func(q identityQuerier) error {
		if _, err := q.InsertRevocation(ctx, dbgen.InsertRevocationParams{
			Identity:     rev.Identity,
			ModelID:      rev.ModelID.String(),
			ModelVersion: rev.ModelVersion,
			RevokedAtUtc: rev.RevokedAt,
			Reason:       rev.Reason,
			EvidenceRef:  rev.EvidenceRef,
			// revoked_by is the responder. The registry is not given an actor parameter
			// because the compromise response is the only caller and it already records the
			// responder in the audit chain; duplicating the column here would give two
			// places to disagree about who responded.
			RevokedBy: "control-plane",
		}); err != nil {
			return fmt.Errorf("recording the revocation of %q: %w", rev.Identity, err)
		}
		return nil
	})
}

// compile-time assertion that the narrow interface is satisfied by the generated querier, so
// a rename of a generated accessor is a build failure rather than a deployment surprise.
var _ identityQuerier = (dbgen.Querier)(nil)
