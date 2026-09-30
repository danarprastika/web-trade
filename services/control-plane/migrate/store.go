package migrate

import (
	"context"
	"errors"
	"time"
)

// AppliedRecord is one row of the database's record of what has been applied.
type AppliedRecord struct {
	Version   int
	Name      string
	Digest    string
	AppliedAt time.Time
}

// Store is the database's memory of which migrations have been applied.
//
// It is an interface because the part of this package worth testing is the ordering, the
// drift check, and the plan, all of which are pure and need no database. What remains is
// bookkeeping, and an interface keeps the pure half from acquiring a driver just to be tested.
type Store interface {
	// Ensure creates the applied-set table if it does not exist.
	//
	// This is bootstrapping rather than a migration, a deliberate exception to the rule that
	// schema changes are migrations: a migration that records itself needs the record to
	// already exist, so the first version of the table cannot be recorded by itself.
	Ensure(ctx context.Context) error

	// Applied returns the applied set as version -> digest.
	Applied(ctx context.Context) (map[int]string, error)

	// Record writes a migration as applied.
	Record(ctx context.Context, m Migration) error

	// Forget removes a migration's record, called only after it has been reverted.
	Forget(ctx context.Context, m Migration) error
}

// ErrStore is returned when the applied set cannot be read or written.
//
// It is distinct from a drift or plan error because it means the runner does not know the
// state of the database, which is more serious than knowing the state and disliking it.
// Reapplying something already applied is worse than refusing to run, so this never gets
// swallowed into a generic failure.
var ErrStore = errors.New("the applied-set record could not be read or written")

// createAppliedSetSQL creates the applied-set table.
//
// The digest column is what makes an edited migration detectable after the fact, which is
// the one condition a migration runner cannot otherwise recover from: the database and the
// repository both claim to be authoritative and neither can prove the other is right.
//
// This is not a migration and lives in its own `migrate` namespace so that it is never
// confused with the schema it is tracking.
const createAppliedSetSQL = `
CREATE SCHEMA IF NOT EXISTS migrate;

CREATE TABLE IF NOT EXISTS migrate.applied_set (
    version    integer     PRIMARY KEY,
    name       text        NOT NULL,
    digest     text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    direction  text        NOT NULL,
    CONSTRAINT applied_set_direction_closed CHECK (direction IN ('up', 'down'))
);
`

const selectAppliedSQL = `
SELECT version, digest FROM migrate.applied_set ORDER BY version;
`

// recordAppliedSQL is idempotent on version so that re-running a migration that was applied
// but whose record was lost writes the record rather than failing the run.
const recordAppliedSQL = `
INSERT INTO migrate.applied_set (version, name, digest, direction)
VALUES ($1, $2, $3, 'up')
ON CONFLICT (version) DO UPDATE
    SET name = EXCLUDED.name, digest = EXCLUDED.digest, applied_at = now();
`

const forgetAppliedSQL = `DELETE FROM migrate.applied_set WHERE version = $1;`
