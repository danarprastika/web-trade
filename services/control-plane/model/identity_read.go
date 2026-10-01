package model

import (
	"context"
	"database/sql"
	"fmt"
	"sort"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// IdentitySnapshot is every workload identity issued and every revocation recorded.
//
// Both halves are in one type because they are only safe together. The registry's refusal to
// re-mint a revoked identity is a lookup in its revocation map, so a snapshot carrying
// identities without revocations restores a registry that will happily re-issue an identity
// whose compromise was recorded - the failure the check was written to prevent, arriving
// through the maintenance path rather than the attack path.
type IdentitySnapshot struct {
	Identities  []WorkloadIdentity
	Revocations []Revocation
}

// IdentitySnapshotReader is the read side that IdentityStore deliberately is not.
//
// IdentityStore's own comment says the durable store is "a record of what happened, not the
// source the process recovers from". That is a reasonable position only if the registry can
// be recovered from somewhere else, and before this interface existed it could not: with no
// read, the claim was true by necessity rather than by design. A read-only interface keeps
// the write port narrow - still no delete, so the record of an issuance cannot be destroyed -
// while letting the registry be reconstructed from the record of what happened.
type IdentitySnapshotReader interface {
	LoadIdentitySnapshot(ctx context.Context) (IdentitySnapshot, error)
}

// LoadIdentitySnapshot returns the in-memory record of issuances and revocations.
func (m *MemoryIdentityStore) LoadIdentitySnapshot(_ context.Context) (IdentitySnapshot, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failRead != nil {
		return IdentitySnapshot{}, m.failRead
	}
	snap := IdentitySnapshot{
		Identities:  make([]WorkloadIdentity, 0, len(m.identities)),
		Revocations: make([]Revocation, 0, len(m.revocations)),
	}
	for _, w := range m.identities {
		snap.Identities = append(snap.Identities, w)
	}
	for _, rev := range m.revocations {
		snap.Revocations = append(snap.Revocations, rev)
	}
	sortIdentitySnapshot(&snap)
	return snap, nil
}

// sortIdentitySnapshot puts both lists in a stable order.
//
// MemoryStore iterates maps, whose order Go randomises between runs. A restore that produced a
// different registry from the same durable state would make any comparison of the two a
// coin flip.
func sortIdentitySnapshot(s *IdentitySnapshot) {
	sort.Slice(s.Identities, func(i, j int) bool {
		return s.Identities[i].Identity < s.Identities[j].Identity
	})
	sort.Slice(s.Revocations, func(i, j int) bool {
		if s.Revocations[i].RevokedAt.Equal(s.Revocations[j].RevokedAt) {
			return s.Revocations[i].Identity < s.Revocations[j].Identity
		}
		return s.Revocations[i].RevokedAt.Before(s.Revocations[j].RevokedAt)
	})
}

// SQLIdentitySnapshotQuerier is the subset of the generated accessors this reader uses.
//
// Both reads are unfiltered. ListValidIdentitiesForModelVersion would be the wrong read for a
// restore for the same reason ListActiveModels was the wrong read for the registry: it drops
// exactly the rows a restore must not drop.
type SQLIdentitySnapshotQuerier interface {
	ListAllWorkloadIdentities(ctx context.Context) ([]dbgen.WorkloadIdentity, error)
	ListAllWorkloadRevocations(ctx context.Context) ([]dbgen.WorkloadRevocation, error)
}

// SQLIdentitySnapshotReader is an IdentitySnapshotReader over the generated accessors.
type SQLIdentitySnapshotReader struct {
	q SQLIdentitySnapshotQuerier
}

// NewSQLIdentitySnapshotReader returns a reader over db.
//
// It imports database/sql and the generated accessors and nothing else, matching
// SQLIdentityStore, so it introduces no driver dependency.
func NewSQLIdentitySnapshotReader(db *sql.DB) (*SQLIdentitySnapshotReader, error) {
	if db == nil {
		return nil, fmt.Errorf("a sql-backed identity snapshot reader requires a database " +
			"handle; constructing one here would hide the pool from the caller's shutdown sequence")
	}
	return &SQLIdentitySnapshotReader{q: dbgen.New(db)}, nil
}

// NewSQLIdentitySnapshotReaderInTx returns a reader whose reads join a transaction the caller owns.
func NewSQLIdentitySnapshotReaderInTx(q SQLIdentitySnapshotQuerier) (*SQLIdentitySnapshotReader, error) {
	if q == nil {
		return nil, fmt.Errorf("a sql-backed identity snapshot reader requires a querier")
	}
	return &SQLIdentitySnapshotReader{q: q}, nil
}

// LoadIdentitySnapshot reads every issuance and every revocation.
func (r *SQLIdentitySnapshotReader) LoadIdentitySnapshot(ctx context.Context) (IdentitySnapshot, error) {
	identities, err := r.q.ListAllWorkloadIdentities(ctx)
	if err != nil {
		return IdentitySnapshot{}, fmt.Errorf("listing every workload identity: %w", err)
	}
	revocations, err := r.q.ListAllWorkloadRevocations(ctx)
	if err != nil {
		return IdentitySnapshot{}, fmt.Errorf("listing every workload revocation: %w", err)
	}
	snap := IdentitySnapshot{
		Identities:  make([]WorkloadIdentity, 0, len(identities)),
		Revocations: make([]Revocation, 0, len(revocations)),
	}
	for _, row := range identities {
		w, err := workloadFrom(row)
		if err != nil {
			return IdentitySnapshot{}, err
		}
		snap.Identities = append(snap.Identities, w)
	}
	for _, row := range revocations {
		rev, err := revocationFrom(row)
		if err != nil {
			return IdentitySnapshot{}, err
		}
		snap.Revocations = append(snap.Revocations, rev)
	}
	sortIdentitySnapshot(&snap)
	return snap, nil
}

// workloadFrom maps an issuance row back onto a WorkloadIdentity.
func workloadFrom(row dbgen.WorkloadIdentity) (WorkloadIdentity, error) {
	modelID, err := contracts.ParseIdentifier(row.ModelID)
	if err != nil {
		return WorkloadIdentity{}, fmt.Errorf("identity %q is bound to model %q, which is not "+
			"an identifier: %w", row.Identity, row.ModelID, err)
	}
	return WorkloadIdentity{
		Identity:     row.Identity,
		ModelID:      modelID,
		ModelVersion: row.ModelVersion,
		Scope:        WorkloadScope(row.Scope),
		IssuedAt:     row.IssuedAtUtc,
		ExpiresAt:    row.ExpiresAtUtc,
	}, nil
}

// revocationFrom maps a revocation row back onto a Revocation.
//
// revoked_by is read and discarded, and that is the same decision the write side makes when
// it writes a constant. The responder is recorded in the audit chain, and carrying a second
// copy here would give two places to disagree about who responded to a compromise.
func revocationFrom(row dbgen.WorkloadRevocation) (Revocation, error) {
	modelID, err := contracts.ParseIdentifier(row.ModelID)
	if err != nil {
		return Revocation{}, fmt.Errorf("revocation of %q names model %q, which is not an "+
			"identifier: %w", row.Identity, row.ModelID, err)
	}
	return Revocation{
		Identity:     row.Identity,
		ModelID:      modelID,
		ModelVersion: row.ModelVersion,
		RevokedAt:    row.RevokedAtUtc,
		Reason:       row.Reason,
		EvidenceRef:  row.EvidenceRef,
	}, nil
}
