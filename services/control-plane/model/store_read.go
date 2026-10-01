package model

import (
	"context"
	"database/sql"
	"fmt"
	"sort"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// Snapshot is everything the registry durably knows, in the shape a restart needs it.
//
// It exists because Store is write-only, and a write-only store means a process that restarts
// has no memory of which models exist, what state they reached, or which idempotency keys
// have already been spent. The third of those is the dangerous one: without the idempotency
// ledger a retried transition is not recognised as a retry, so a caller that retries after a
// restart gets a second execution of an operation that already committed. Snapshot therefore
// carries the ledger, not just the registry.
type Snapshot struct {
	// Models is every registered model in every lifecycle state.
	Models []ModelSnapshot
	// Idempotency is every recorded transition, keyed by scope and key by the loader.
	Idempotency []AppliedEntry
}

// ModelSnapshot is one model's durable row, with the audit record that established it.
type ModelSnapshot struct {
	Record       Record
	State        State
	AuditID      string
	UpdatedBy    string
	At           time.Time
	RegisteredAt time.Time
}

// AppliedEntry is one spent idempotency key and what it resolved to.
//
// Fingerprint is carried because the retry check needs it: a repeat of the same key carrying
// a different request is a conflict, not a retry, and that is only knowable if the original
// fingerprint survived.
type AppliedEntry struct {
	Scope       string
	Key         string
	Fingerprint Digest
	ModelID     contracts.Identifier
	From        State
	To          State
	AuditID     string
	At          time.Time
}

// SnapshotReader is the read side that Store deliberately is not.
//
// Split for the reason audit.Split Chain from Sink: a Store that could read as well as write
// would be reachable from code whose job is only to load, and the write guards in 0004 would
// no longer be the whole story. Keeping them apart also means a caller that only reads cannot
// be handed a half-implemented writer.
type SnapshotReader interface {
	// LoadSnapshot returns the whole durable registry.
	//
	// Whole, not filtered. A caller that asked for the models it cared about would get a
	// registry whose terminal states had been silently dropped, and a retired model that
	// looks unregistered is a model that can be registered again.
	LoadSnapshot(ctx context.Context) (Snapshot, error)
}

// LoadSnapshot returns the in-memory registry as a snapshot.
//
// It takes the lock, so a snapshot is a consistent cut rather than a walk over maps that a
// concurrent writer is mutating.
func (m *MemoryStore) LoadSnapshot(_ context.Context) (Snapshot, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failRead != nil {
		return Snapshot{}, m.failRead
	}
	snap := Snapshot{
		Models:      make([]ModelSnapshot, 0, len(m.models)),
		Idempotency: make([]AppliedEntry, 0, len(m.transitions)),
	}
	for _, entry := range m.models {
		registered := entry.RegisteredAt
		if registered.IsZero() {
			registered = entry.At
		}
		snap.Models = append(snap.Models, ModelSnapshot{
			Record:       entry.Record,
			State:        entry.State,
			AuditID:      entry.AuditID,
			UpdatedBy:    entry.UpdatedBy,
			At:           entry.At,
			RegisteredAt: registered,
		})
	}
	for _, t := range m.transitions {
		snap.Idempotency = append(snap.Idempotency, AppliedEntry{
			Scope:       t.Scope,
			Key:         t.Key,
			Fingerprint: t.Fingerprint,
			ModelID:     t.ModelID,
			From:        t.From,
			To:          t.To,
			AuditID:     t.AuditID,
			At:          t.At,
		})
	}
	sortSnapshot(&snap)
	return snap, nil
}

// sortSnapshot puts both lists in a stable order.
//
// A snapshot loaded from PostgreSQL arrives in model_id order and the ledger in whatever order
// the query returns; a snapshot from MemoryStore arrives in map order, which Go randomises
// between runs. Two runs restoring the same durable state must produce the same journal, or
// nothing built on top of it can be compared, and a flaky comparison is one nobody trusts.
func sortSnapshot(s *Snapshot) {
	sort.Slice(s.Models, func(i, j int) bool {
		if s.Models[i].Record.ModelID.String() != s.Models[j].Record.ModelID.String() {
			return s.Models[i].Record.ModelID.String() < s.Models[j].Record.ModelID.String()
		}
		return s.Models[i].Record.Version < s.Models[j].Record.Version
	})
	sort.Slice(s.Idempotency, func(i, j int) bool {
		if s.Idempotency[i].Scope != s.Idempotency[j].Scope {
			return s.Idempotency[i].Scope < s.Idempotency[j].Scope
		}
		return s.Idempotency[i].Key < s.Idempotency[j].Key
	})
}

// SQLSnapshotQuerier is the subset of the generated accessors the snapshot reader uses.
//
// ListAllModels rather than ListActiveModels, deliberately: the active set is blind to
// retired and quarantined models, which are exactly the rows a restart must remember. The
// ledger is read in one query for the same reason: rehydration restores every model, so a
// per-model read made startup cost one round trip per registered model, strictly sequential.
type SQLSnapshotQuerier interface {
	ListAllModels(ctx context.Context) ([]dbgen.ModelRegistry, error)
	ListAllIdempotency(ctx context.Context) ([]dbgen.ModelTransitionIdempotency, error)
}

// SQLSnapshotReader is a SnapshotReader over the generated accessors.
type SQLSnapshotReader struct {
	q SQLSnapshotQuerier
}

// NewSQLSnapshotReader returns a reader over db.
//
// It imports database/sql and the generated accessors and nothing else, matching SQLStore, so
// it introduces no driver dependency - which matters for the reason EV-046 records.
func NewSQLSnapshotReader(db *sql.DB) (*SQLSnapshotReader, error) {
	if db == nil {
		return nil, fmt.Errorf("a sql-backed snapshot reader requires a database handle; " +
			"constructing one here would hide the pool from the caller's shutdown sequence")
	}
	return &SQLSnapshotReader{q: dbgen.New(db)}, nil
}

// NewSQLSnapshotReaderInTx returns a reader whose reads join a transaction the caller owns.
func NewSQLSnapshotReaderInTx(q SQLSnapshotQuerier) (*SQLSnapshotReader, error) {
	if q == nil {
		return nil, fmt.Errorf("a sql-backed snapshot reader requires a querier")
	}
	return &SQLSnapshotReader{q: q}, nil
}

// LoadSnapshot reads the whole registry and every spent idempotency key.
//
// Exactly two round trips, whatever the size of the registry. The ledger arrives in one piece
// and is grouped here, so a snapshot is one network conversation rather than one per registered
// model - the cost of a restart then depends on how much history there is, not on how many
// models happen to be registered.
//
// Rows are attributed to a model only when that model is in the registry, which is what the
// per-model form did by construction: it could only ever ask about a model it had already read.
// A ledger row naming a model the registry does not contain is therefore dropped rather than
// reported, exactly as before. That is worth naming rather than quietly fixing here, because
// dropping it means such a key is not reconstructed as spent, so a retry of it would be applied
// a second time. Restore refuses a snapshot that names an unknown model, so the inconsistency
// is not silent once the row is in the snapshot at all - but whether the reader should hand such
// a row over for Restore to reject is a separate question from how many queries to make, and it
// is not answered by this change.
func (r *SQLSnapshotReader) LoadSnapshot(ctx context.Context) (Snapshot, error) {
	rows, err := r.q.ListAllModels(ctx)
	if err != nil {
		return Snapshot{}, fmt.Errorf("listing every model in the registry: %w", err)
	}
	ledger, err := r.q.ListAllIdempotency(ctx)
	if err != nil {
		return Snapshot{}, fmt.Errorf("listing the applied-transition ledger: %w", err)
	}

	// The registry's own row set, so a ledger row can be attributed without a second pass over
	// the models. Built before either list is consumed because a model registered with no
	// transitions still contributes an entry to Models.
	registered := make(map[string]struct{}, len(rows))
	snap := Snapshot{
		Models:      make([]ModelSnapshot, 0, len(rows)),
		Idempotency: make([]AppliedEntry, 0, len(ledger)),
	}
	for _, row := range rows {
		model, err := snapshotFrom(row)
		if err != nil {
			return Snapshot{}, err
		}
		registered[row.ModelID] = struct{}{}
		snap.Models = append(snap.Models, model)
	}

	for _, entry := range ledger {
		if _, ok := registered[entry.ModelID]; !ok {
			continue
		}
		id, err := contracts.ParseIdentifier(entry.ModelID)
		if err != nil {
			return Snapshot{}, fmt.Errorf("idempotency entry %s/%s names model %q, which "+
				"is not an identifier: %w", entry.IdempotencyScope, entry.IdempotencyKey,
				entry.ModelID, err)
		}
		snap.Idempotency = append(snap.Idempotency, AppliedEntry{
			Scope:       entry.IdempotencyScope,
			Key:         entry.IdempotencyKey,
			Fingerprint: Digest(entry.RequestFingerprint),
			ModelID:     id,
			From:        State(entry.FromState),
			To:          State(entry.ToState),
			AuditID:     entry.AuditID,
			At:          entry.AppliedAtUtc,
		})
	}
	sortSnapshot(&snap)
	return snap, nil
}

// snapshotFrom maps a registry row back onto a ModelSnapshot.
//
// The inverse of SQLStore.InsertModel, written field by field for the reason recordFrom is:
// a field silently dropped here produces a model whose record is quietly incomplete, and a
// declaration record is the document that has to describe the model for the rest of its life.
func snapshotFrom(row dbgen.ModelRegistry) (ModelSnapshot, error) {
	modelID, err := contracts.ParseIdentifier(row.ModelID)
	if err != nil {
		return ModelSnapshot{}, fmt.Errorf("registry row names model %q, which is not an "+
			"identifier: %w", row.ModelID, err)
	}
	return ModelSnapshot{
		Record: Record{
			ModelID:                    modelID,
			Version:                    row.Version,
			Owner:                      row.Owner,
			Author:                     row.Author,
			TrainingDatasetFingerprint: Digest(row.TrainingDatasetFingerprint),
			CodeRevision:               row.CodeRevision,
			FeatureSpecification:       row.FeatureSpecification,
			EvaluationResults:          Digest(row.EvaluationResults),
			Limitations:                row.Limitations,
			ApprovalRecord:             Digest(row.ApprovalRecord),
			DeploymentScope:            row.DeploymentScope,
			MonitoringPolicy:           row.MonitoringPolicy,
			RollbackArtifact:           Digest(row.RollbackArtifact),
		},
		State:        State(row.State),
		AuditID:      row.LastAuditID,
		UpdatedBy:    row.UpdatedBy,
		At:           row.UpdatedAtUtc,
		RegisteredAt: row.RegisteredAtUtc,
	}, nil
}
