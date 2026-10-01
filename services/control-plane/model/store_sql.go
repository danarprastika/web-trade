package model

import (
	"context"
	"database/sql"
	"errors"
	"fmt"

	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// SQLStore is the durable Store, backed by the generated accessors over PostgreSQL.
//
// It takes a *sql.DB rather than constructing a pool, because a pool built here would be
// invisible to the process's shutdown sequence and would outlive the thing it pools. The
// driver is likewise the caller's: this file imports database/sql and the generated
// accessors and nothing else, so no driver dependency is introduced here. That is also why
// a DSN is not a constructor parameter - the connection string is a deployment concern and
// this type has no opinion about which of them is correct.
type SQLStore struct {
	// q is the narrow querier this store uses outside a transaction.
	q SQLQuerier
	// begin runs fn with a transaction-scoped querier, committing when fn returns nil.
	//
	// It is a field rather than an inline BeginTx so that ApplyTransition can be tested
	// without a database, and so that a caller already holding a transaction can supply
	// one. An inline BeginTx would make the two-statement atomicity of ApplyTransition the
	// one property in this file that could only be checked against a live PostgreSQL.
	begin func(ctx context.Context, fn func(SQLQuerier) error) error
	// close releases the caller's pool. It is nil when the store did not create one.
	close func() error
}

// SQLQuerier is the subset of the generated accessors this store uses.
//
// It is declared here rather than depending on dbgen.Querier wholesale, for the same reason
// the repository's other ports are narrow: a store that can reach every generated query can
// be asked to do something the 0004 guards do not cover, and the type system will not stop
// it. Narrowing the surface means a future query has to be added here deliberately.
type SQLQuerier interface {
	InsertModel(ctx context.Context, arg dbgen.InsertModelParams) (dbgen.ModelRegistry, error)
	SetModelState(ctx context.Context, arg dbgen.SetModelStateParams) (dbgen.ModelRegistry, error)
	RecordTransitionIdempotency(
		ctx context.Context, arg dbgen.RecordTransitionIdempotencyParams,
	) (dbgen.ModelTransitionIdempotency, error)
}

// NewSQLStore returns a SQLStore that opens its own transaction per ApplyTransition.
func NewSQLStore(db *sql.DB) (*SQLStore, error) {
	if db == nil {
		return nil, errors.New("a sql-backed model store requires a database handle; " +
			"constructing one here would hide the pool from the caller's shutdown sequence")
	}
	q := dbgen.New(db)
	return &SQLStore{
		q:     q,
		close: db.Close,
		begin: beginTx[SQLQuerier](db, func(tx *sql.Tx) SQLQuerier { return dbgen.New(tx) }),
	}, nil
}

// beginTx returns a function that runs fn inside a transaction it owns, committing when fn
// returns nil and rolling back otherwise.
//
// It is generic over the querier interface so that SQLStore and SQLIdentityStore share one
// implementation. That matters more than it looks: "these statements happen together or not
// at all" is a property each store claims in its own doc comment, and two hand-written
// transaction wrappers are two opportunities for them to mean subtly different things.
//
// newQuerier is passed in rather than assumed, because *dbgen.Queries satisfies every
// generated querier interface at once and so cannot be converted to the one being
// parameterised.
func beginTx[Q any](
	db *sql.DB,
	newQuerier func(*sql.Tx) Q,
) func(context.Context, func(Q) error) error {
	return func(ctx context.Context, fn func(Q) error) error {
		tx, err := db.BeginTx(ctx, nil)
		if err != nil {
			return fmt.Errorf("beginning the transaction: %w", err)
		}
		// The rollback error is deliberately discarded. After a successful Commit it
		// returns sql.ErrTxDone, and reporting that would turn a committed write into a
		// failure at the caller. A rollback that genuinely fails means the transaction
		// aborted, and that case is already reported by fn or by Commit.
		defer func() { _ = tx.Rollback() }()

		if err := fn(newQuerier(tx)); err != nil {
			return err
		}
		if err := tx.Commit(); err != nil {
			return fmt.Errorf("committing the transaction: %w", err)
		}
		return nil
	}
}

// NewSQLStoreInTx returns a SQLStore whose writes run inside a transaction the caller
// already owns, using an already-scoped querier.
//
// The transaction is the caller's, so this store will not commit or roll it back: a refusal
// here rolls back only if the caller does. That is the arrangement for a caller that must
// commit several models in one unit, and it is named separately from NewSQLStore precisely
// because the difference is who owns the commit - a mistake there means a store that
// silently never persists.
func NewSQLStoreInTx(q SQLQuerier) (*SQLStore, error) {
	if q == nil {
		return nil, errors.New("a sql-backed model store requires a querier")
	}
	return &SQLStore{
		q:     q,
		close: func() error { return nil },
		begin: func(_ context.Context, fn func(SQLQuerier) error) error {
			return fn(q)
		},
	}, nil
}

// InsertModel records a newly registered model.
//
// State, LastAuditID, UpdatedBy, and both timestamps are written from the entry rather than
// defaulted by the database, because the journal's clock is injected and a database default
// of now() would write a different time than the audit record describing the same event.
func (s *SQLStore) InsertModel(ctx context.Context, entry RegistryEntry) error {
	registered := entry.At
	if !entry.RegisteredAt.IsZero() {
		registered = entry.RegisteredAt
	}
	_, err := s.q.InsertModel(ctx, dbgen.InsertModelParams{
		ModelID:                    entry.Record.ModelID.String(),
		Version:                    entry.Record.Version,
		Owner:                      entry.Record.Owner,
		Author:                     entry.Record.Author,
		TrainingDatasetFingerprint: string(entry.Record.TrainingDatasetFingerprint),
		CodeRevision:               entry.Record.CodeRevision,
		FeatureSpecification:       entry.Record.FeatureSpecification,
		EvaluationResults:          string(entry.Record.EvaluationResults),
		Limitations:                entry.Record.Limitations,
		ApprovalRecord:             string(entry.Record.ApprovalRecord),
		DeploymentScope:            entry.Record.DeploymentScope,
		MonitoringPolicy:           entry.Record.MonitoringPolicy,
		RollbackArtifact:           string(entry.Record.RollbackArtifact),
		State:                      string(entry.State),
		RegisteredAtUtc:            registered,
		LastAuditID:                entry.AuditID,
		UpdatedBy:                  entry.UpdatedBy,
		UpdatedAtUtc:               entry.At,
	})
	if err != nil {
		return fmt.Errorf("recording model %s in the registry: %w", entry.Record.ModelID, err)
	}
	return nil
}

// ApplyTransition advances the lifecycle state and records the transition, atomically.
//
// These are two statements against two tables, and running them separately would leave a
// window in which a model has advanced but its transition is unrecorded. The consequence
// would be worse than a lost write: the idempotency lookup misses, the state check finds
// the model already moved, and the caller's retry is refused as a stale-state conflict - so
// the transition happened but has become unreplayable and unattributable.
//
// The order inside the transaction is state first, then the idempotency entry. The reverse
// order would record the transition before making it, so a constraint failure on the state
// write would leave an idempotency entry claiming a transition that never happened, and a
// retry would return that fabricated outcome as though it were real.
func (s *SQLStore) ApplyTransition(ctx context.Context, entry TransitionEntry) error {
	return s.begin(ctx, func(q SQLQuerier) error {
		if _, err := q.SetModelState(ctx, dbgen.SetModelStateParams{
			ModelID:      entry.ModelID.String(),
			State:        string(entry.To),
			LastAuditID:  entry.AuditID,
			UpdatedBy:    "journal",
			UpdatedAtUtc: entry.At,
		}); err != nil {
			return fmt.Errorf("recording model %s in state %s: %w", entry.ModelID, entry.To, err)
		}

		if _, err := q.RecordTransitionIdempotency(ctx, dbgen.RecordTransitionIdempotencyParams{
			IdempotencyScope:   entry.Scope,
			IdempotencyKey:     entry.Key,
			RequestFingerprint: string(entry.Fingerprint),
			ModelID:            entry.ModelID.String(),
			FromState:          string(entry.From),
			ToState:            string(entry.To),
			AuditID:            entry.AuditID,
			AppliedAtUtc:       entry.At,
		}); err != nil {
			return fmt.Errorf("recording the applied transition in scope %s: %w", entry.Scope, err)
		}
		return nil
	})
}

// Close releases the underlying pool, when this store was given one.
func (s *SQLStore) Close() error {
	if s.close == nil {
		return nil
	}
	return s.close()
}

// compile-time assertion that the narrow interface above is satisfied by the generated
// querier. Without this, a rename of a generated accessor would surface as a runtime failure
// in a deployment rather than as a build failure here.
var _ SQLQuerier = (dbgen.Querier)(nil)
