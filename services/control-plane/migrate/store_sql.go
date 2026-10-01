package migrate

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"fmt"
	"regexp"
	"time"
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

// Status returns the applied set for a read-only report.
//
// It is deliberately not Applied. Applied reports a missing applied-set table as an error, and
// for a report that is the wrong answer: a database nobody has migrated yet has no applied set,
// and "no migrations applied" is precisely what an operator needs to hear about one. A status
// query against an uninitialised catalog is a normal state, not a failure.
//
// The catalog probe is what makes the whole path read-only. It is tempting to have Status call
// Ensure first so that Applied always finds a table, and that is exactly the bug: a status run
// would then issue CREATE SCHEMA and CREATE TABLE against a database it was asked to inspect,
// which fails on a replica or a read-only connection with an error that says nothing about the
// migrations. Probing pg_catalog cannot fail that way and changes nothing.
func (s *SQLStore) Status(ctx context.Context) (map[int]string, error) {
	var exists bool
	if err := s.db.QueryRowContext(ctx, appliedSetExistsSQL).Scan(&exists); err != nil {
		return nil, fmt.Errorf("%w: asking the catalog whether the applied set exists: %v",
			ErrStore, err)
	}
	if !exists {
		return map[int]string{}, nil
	}
	return s.Applied(ctx)
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

// advisoryLockKey is the key every instance of this runner locks on.
//
// An arbitrary constant that must never change, not a hash of anything. A key derived from the
// database, the set, or the working directory is a key two instances can compute differently,
// and a lock two instances compute differently serialises nothing while looking like it works.
// PostgreSQL scopes advisory locks per database, so this cannot collide with the migrations of
// some other database on the same server.
const advisoryLockKey int64 = 0x7765627472616465 // "webtrade"

const lockRunSQL = `SELECT pg_advisory_lock($1);`
const unlockRunSQL = `SELECT pg_advisory_unlock($1);`

// LockRun takes a session-level advisory lock that covers the whole run.
//
// Session-level (pg_advisory_lock) rather than transaction-level (pg_advisory_xact_lock)
// because a run is not one transaction and must not become one. The plan is computed from a
// read of the applied set, and then each migration commits in its own transaction along with
// its own record. A transaction-level lock would have to be held in a transaction wrapping all
// of that, which is the single long transaction this package refuses to open: one migration
// failing would then roll back the records of the migrations that had already succeeded, and
// the database would disagree with the repository with nothing to reconcile them.
//
// The race this prevents is two runners -- an operator and CI, or two operators -- reading the
// same applied set, planning the same steps, and both executing them. The loser dies partway
// through a set whose bodies are not idempotent: CREATE SEQUENCE in 0001 has no IF NOT
// EXISTS, so the second instance fails on a non-idempotent statement and leaves a catalog that
// is neither the old schema nor the new one, with a ledger that describes neither.
//
// A crashed run cannot leave this lock held, which is the property a transaction-level lock
// gets for free and a session-level one has to earn. PostgreSQL releases a session-level
// advisory lock the moment the session ends, so a killed process, an OOM kill, or a dropped
// connection all return the lock without a line of this package running. What the code does
// have to guarantee is the ordinary paths -- an error, and a panic inside a migration body --
// and both are covered by the deferred unlock in Runner.Run, which runs while the panic is
// still unwinding.
func (s *SQLStore) LockRun(ctx context.Context) (RunLock, error) {
	// A dedicated connection, because the lock belongs to a session and database/sql hands out
	// pooled connections that other goroutines will reuse. Locking on one and releasing on
	// another is unlocking someone else's lock, which PostgreSQL answers with a warning and no
	// change.
	conn, err := s.db.Conn(ctx)
	if err != nil {
		return nil, fmt.Errorf("%w: taking a connection to hold the migration lock on: %v",
			ErrStore, err)
	}
	if _, err := conn.ExecContext(ctx, lockRunSQL, advisoryLockKey); err != nil {
		// Nothing is locked, but the connection is already out of the pool and has to go back.
		_ = conn.Close()
		return nil, fmt.Errorf("%w: waiting for the migration lock: %v", ErrStore, err)
	}
	return &sqlRunLock{conn: conn}, nil
}

// sqlRunLock is a session-level advisory lock held on one connection.
type sqlRunLock struct {
	conn *sql.Conn
}

// Unlock releases the lock and returns the connection to the pool.
func (l *sqlRunLock) Unlock(ctx context.Context) error {
	if _, err := l.conn.ExecContext(ctx, unlockRunSQL, advisoryLockKey); err != nil {
		// Returning a connection to the pool that still holds the lock would hand the lock to
		// whichever caller gets that session next, and no other session can release it: every
		// later run would block until its own timeout, with nothing in the logs but a wait.
		// Marking the connection bad makes database/sql close the socket, and PostgreSQL
		// drops the session-level lock the instant the session ends -- so the failure mode is
		// one lost connection rather than a wedged database.
		_ = l.conn.Raw(func(any) error { return driver.ErrBadConn })
		return fmt.Errorf("%w: releasing the migration lock; the connection was dropped "+
			"rather than pooled, so the lock is released with the session: %v", ErrStore, err)
	}
	return l.conn.Close()
}

// unlockTimeout bounds the release of the run lock.
//
// The unlock runs on a path that has already failed or already succeeded, so it must not be
// able to hang: a release that never completes would hold a pooled connection forever. This is
// generous because releasing a lock is one round trip.
const unlockTimeout = 10 * time.Second

// compile-time proof that the store offers the run lock the runner looks for.
var _ interface {
	LockRun(context.Context) (RunLock, error)
} = (*SQLStore)(nil)
