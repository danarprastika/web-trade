package migrate

import (
	"context"
	"database/sql"
	"fmt"
	"regexp"
)

// SQLStore is the Store backed by a real PostgreSQL database.
//
// Ported from the pgx-backed store parked during WI-106, which could not be built because
// pgx pulls github.com/jackc/pgservicefile, whose only available versions are pseudo-versions
// and which scripts/verify_toolchain.py refuses as unpinned. github.com/lib/pq v1.10.9
// satisfies the same gate unweakened and has no transitive dependencies at all.
//
// The design is unchanged from the parked original and its reasoning is preserved verbatim
// where the reasoning did not depend on the driver: each body is committed together with the
// record of itself, the deferred rollback exists so a panic cannot hold locks, and the applied
// scan is checked after iteration rather than trusted. Only the call surface changed, from
// pgxpool to database/sql, which is also what sqlc generates against.
type SQLStore struct {
	db *sql.DB
}

// NewSQLStore wraps a database handle.
func NewSQLStore(db *sql.DB) *SQLStore { return &SQLStore{db: db} }

// Ensure creates the applied-set table.
//
// Committed on its own rather than folded into the first migration's transaction: if it were
// part of that transaction, a rollback of the migration would also roll back the record of
// which migrations exist, and the next run would have nothing to compare against.
func (s *SQLStore) Ensure(ctx context.Context) error {
	if _, err := s.db.ExecContext(ctx, createAppliedSetSQL); err != nil {
		return fmt.Errorf("%w: creating the applied-set table: %v", ErrStore, err)
	}
	return nil
}

// Applied returns the applied set as version -> digest.
func (s *SQLStore) Applied(ctx context.Context) (map[int]string, error) {
	rows, err := s.db.QueryContext(ctx, selectAppliedSQL)
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
func (s *SQLStore) Record(ctx context.Context, m Migration) error {
	if _, err := s.db.ExecContext(ctx, recordAppliedSQL, m.Version, m.Name, m.Digest); err != nil {
		return fmt.Errorf("%w: recording %s: %v", ErrStore, m.Name, err)
	}
	return nil
}

// Forget removes a migration's record after it has been reverted.
//
// The record is removed rather than marked reverted so that a following up run reapplies the
// migration, which is what an operator reverting one expects to happen next.
func (s *SQLStore) Forget(ctx context.Context, m Migration) error {
	if _, err := s.db.ExecContext(ctx, forgetAppliedSQL, m.Version); err != nil {
		return fmt.Errorf("%w: forgetting %s: %v", ErrStore, m.Name, err)
	}
	return nil
}

// Exec runs a migration body and records it, in one transaction.
//
// The body and the record are committed together on purpose. Committing the body and then
// failing to write the record leaves a database whose schema is ahead of its own record of
// itself, and the next run would reapply the migration to a schema that already has it.
// txControlPattern matches the transaction control statements a migration body carries.
//
// Every migration in db/migrations wraps its own body in BEGIN and COMMIT, which is correct
// when the body is handed to psql directly. It is wrong here, because this store's design
// requires that the body and the record of the body commit together: if the body's own COMMIT
// runs first, the transaction this method opened is already closed before the record is
// written, and the write fails with "unexpected transaction status idle". The failure is loud,
// but it is also a false negative about a design that is otherwise correct.
//
// So the control statements are removed and this method owns the transaction. A body's
// BEGIN/COMMIT and the store's are redundant, never in conflict once one of them is dropped,
// and keeping only the outer one is what preserves the atomicity the store promises.
var txControlPattern = regexp.MustCompile(`(?im)^[ \t]*(BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION)\s*;`)

// stripTxControl removes transaction control from a body, leaving the statements to run.
func stripTxControl(body string) string {
	return txControlPattern.ReplaceAllString(body, "")
}

func (s *SQLStore) Exec(ctx context.Context, m Migration, body string) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("%w: beginning the transaction: %v", ErrStore, err)
	}
	// Deferred so that a panic does not leave the transaction open holding locks. A migration
	// that panics is a bug, and a bug that blocks every other connection is a much worse
	// version of the same bug.
	defer func() { _ = tx.Rollback() }()

	if _, err := tx.ExecContext(ctx, stripTxControl(body)); err != nil {
		return fmt.Errorf("%s failed and was rolled back: %w", m.Name, err)
	}

	if _, err := tx.ExecContext(ctx, recordAppliedSQL, m.Version, m.Name, m.Digest); err != nil {
		return fmt.Errorf("%w: recording %s in the same transaction as its body: %v",
			ErrStore, m.Name, err)
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("%s ran but the commit failed, so the database state is unknown: %w",
			m.Name, err)
	}
	return nil
}

// Undo reverts a migration and forgets it, in one transaction.
func (s *SQLStore) Undo(ctx context.Context, m Migration) error {
	if !hasStatement(m.DownSQL) {
		return fmt.Errorf("cannot revert %s: it declares no %s body", m.Name, downMarker)
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return fmt.Errorf("%w: beginning the transaction: %v", ErrStore, err)
	}
	defer func() { _ = tx.Rollback() }()

	if _, err := tx.ExecContext(ctx, stripTxControl(m.DownSQL)); err != nil {
		return fmt.Errorf("reverting %s failed and was rolled back: %w", m.Name, err)
	}
	if _, err := tx.ExecContext(ctx, forgetAppliedSQL, m.Version); err != nil {
		return fmt.Errorf("%w: forgetting %s: %v", ErrStore, m.Name, err)
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("%s was reverted but the commit failed, so the database state is "+
			"unknown: %w", m.Name, err)
	}
	return nil
}

// compile-time proof that the store satisfies the interface the runner consumes.
var _ Store = (*SQLStore)(nil)
