package migrate

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

// PgStore is the Store backed by a real PostgreSQL database.
type PgStore struct {
	pool *pgxpool.Pool
}

// NewPgStore wraps a connection pool.
func NewPgStore(pool *pgxpool.Pool) *PgStore { return &PgStore{pool: pool} }

// Ensure creates the applied-set table.
//
// Committed on its own rather than folded into the first migration's transaction: if it were
// part of that transaction, a rollback of the migration would also roll back the record of
// which migrations exist, and the next run would have nothing to compare against.
func (s *PgStore) Ensure(ctx context.Context) error {
	if _, err := s.pool.Exec(ctx, createAppliedSetSQL); err != nil {
		return fmt.Errorf("%w: creating the applied-set table: %v", ErrStore, err)
	}
	return nil
}

// Applied returns the applied set as version -> digest.
func (s *PgStore) Applied(ctx context.Context) (map[int]string, error) {
	rows, err := s.pool.Query(ctx, selectAppliedSQL)
	if err != nil {
		return nil, fmt.Errorf("%w: reading the applied set: %v", ErrStore, err)
	}
	defer rows.Close()

	applied := map[int]string{}
	for rows.Next() {
		var version int
		var digest string
		if err := rows.Scan(&version, &digest); err != nil {
			return nil, fmt.Errorf("%w: reading a row of the applied set: %v", ErrStore, err)
		}
		applied[version] = digest
	}
	// Checked after the loop rather than trusted to be nil: a connection that dies mid-scan
	// ends the iteration early, and a short map would make the runner plan migrations that
	// are already applied.
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("%w: the applied-set scan ended early: %v", ErrStore, err)
	}
	return applied, nil
}

// Record writes a migration as applied.
func (s *PgStore) Record(ctx context.Context, m Migration) error {
	if _, err := s.pool.Exec(ctx, recordAppliedSQL, m.Version, m.Name, m.Digest); err != nil {
		return fmt.Errorf("%w: recording %s: %v", ErrStore, m.Name, err)
	}
	return nil
}

// Forget removes a migration's record after it has been reverted.
//
// The record is removed rather than marked reverted so that a following up run reapplies the
// migration, which is what an operator reverting one expects to happen next.
func (s *PgStore) Forget(ctx context.Context, m Migration) error {
	if _, err := s.pool.Exec(ctx, forgetAppliedSQL, m.Version); err != nil {
		return fmt.Errorf("%w: forgetting %s: %v", ErrStore, m.Name, err)
	}
	return nil
}

// Exec runs a migration body and records it, in one transaction.
//
// The body and the record are committed together on purpose. Committing the body and then
// failing to write the record leaves a database whose schema is ahead of its own record of
// itself, and the next run would reapply the migration to a schema that already has it.
func (s *PgStore) Exec(ctx context.Context, m Migration, body string) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("%w: beginning the transaction: %v", ErrStore, err)
	}
	// Deferred so that a panic does not leave the transaction open holding locks. A migration
	// that panics is a bug, and a bug that blocks every other connection is a much worse
	// version of the same bug.
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, body); err != nil {
		return fmt.Errorf("%s failed and was rolled back: %w", m.Name, err)
	}

	if _, err := tx.Exec(ctx, recordAppliedSQL, m.Version, m.Name, m.Digest); err != nil {
		return fmt.Errorf("%w: recording %s in the same transaction as its body: %v",
			ErrStore, m.Name, err)
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("%s ran but the commit failed, so the database state is unknown: %w",
			m.Name, err)
	}
	return nil
}

// Undo reverts a migration and forgets it, in one transaction.
func (s *PgStore) Undo(ctx context.Context, m Migration) error {
	if !hasStatement(m.DownSQL) {
		return fmt.Errorf("cannot revert %s: it declares no %s body", m.Name, downMarker)
	}
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return fmt.Errorf("%w: beginning the transaction: %v", ErrStore, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err := tx.Exec(ctx, m.DownSQL); err != nil {
		return fmt.Errorf("reverting %s failed and was rolled back: %w", m.Name, err)
	}
	if _, err := tx.Exec(ctx, forgetAppliedSQL, m.Version); err != nil {
		return fmt.Errorf("%w: forgetting %s: %v", ErrStore, m.Name, err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("%s was reverted but the commit failed, so the database state is "+
			"unknown: %w", m.Name, err)
	}
	return nil
}

// compile-time proof that the store satisfies the interface the runner consumes.
var _ Store = (*PgStore)(nil)
