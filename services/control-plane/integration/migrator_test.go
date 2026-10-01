//go:build integration

package integration

import (
	"context"
	"database/sql"
	"io/fs"
	"os"
	"path/filepath"
	"testing"

	"github.com/danarprastika/web-trade/services/control-plane/migrate"
)

// migrationFS returns the repository's real migration set.
//
// Read from the working directory rather than embedded, so the test exercises the files CI
// would actually apply. If the path is wrong the test fails rather than quietly testing an
// empty set, which would make every assertion below vacuous.
func migrationFS(t *testing.T) fs.FS {
	t.Helper()

	// Three levels up from services/control-plane/integration is the repository root, where
	// db/migrations lives. The walk upwards rather than a fixed depth, because `go test` runs
	// each package in its own directory and a hardcoded relative path silently becomes wrong
	// the moment the package moves.
	dir := "."
	for i := 0; i < 6; i++ {
		candidate := filepath.Join(dir, "db", "migrations", "0001_ledger.sql")
		if _, err := os.Stat(candidate); err == nil {
			return os.DirFS(filepath.Join(dir, "db", "migrations"))
		}
		dir = filepath.Join(dir, "..")
	}
	t.Fatal("could not locate db/migrations from the test working directory")
	return nil
}

// The migrator applies the whole real set to a live database, reverts it to a clean catalog,
// and applies it again.
//
// This is the property the Python rehearsal proves, and it is reproduced here through the Go
// store because the rehearsal deliberately does not exercise Go code. Running both is the
// point: the rehearsal covers the SQL, and this covers the transaction discipline around it.
//
// It connects through openDestructive rather than open, because this is the one test in the
// package that runs an unbounded down run: two of them, against the real bodies, which drop
// schema ledger CASCADE along with the audit, authz and model_registry tables. Against
// DATABASE_URL pointing at a real database that is four schemas of somebody's data, deleted
// because a developer typed a DSN and ran the suite. openDestructive refuses such a target
// before any statement runs, and refuses it by failing rather than by skipping.
func TestMigratorAppliesRevertsAndReappliesTheRealSet(t *testing.T) {
	db := openDestructive(t)
	ctx := ctxFor(t)

	set, err := migrate.Parse(migrationFS(t))
	if err != nil {
		t.Fatalf("parsing the migration set: %v", err)
	}
	if len(set.Applied) == 0 {
		t.Fatal("parsed an empty migration set; every assertion below would be vacuous")
	}
	t.Logf("parsed %d migrations", len(set.Applied))

	// Start from a known-empty state. The applied-set table has to exist before the first read,
	// because the down run reads it to decide what to revert; a fresh database has neither the
	// table nor any migrations, so a down run against it is a no-op by definition.
	store := migrate.NewSQLStore(db)
	if err := store.Ensure(ctx); err != nil {
		t.Fatalf("ensuring the applied-set table: %v", err)
	}

	reset := &migrate.Runner{Set: set, Store: store, Out: os.Stderr}
	// Unbounded, and destructive by construction: every applied migration is reverted whatever
	// the DSN turned out to name. openDestructive above is what makes that acceptable here.
	if _, err := reset.Run(ctx, migrate.Down); err != nil {
		t.Fatalf("resetting the catalog to empty: %v", err)
	}

	// Up.
	up := &migrate.Runner{Set: set, Store: store, Out: os.Stderr}
	result, err := up.Run(ctx, migrate.Up)
	if err != nil {
		t.Fatalf("applying the set: %v", err)
	}
	if len(result.Applied) != len(set.Applied) {
		t.Fatalf("applied %d migrations, expected %d", len(result.Applied), len(set.Applied))
	}

	// Every migration must be recorded, and the record must match the parsed digest. A body
	// that committed without its record would leave the next run planning to reapply it.
	applied, err := store.Applied(ctx)
	if err != nil {
		t.Fatalf("reading the applied set: %v", err)
	}
	if len(applied) != len(set.Applied) {
		t.Fatalf("applied set holds %d records, expected %d", len(applied), len(set.Applied))
	}
	for _, m := range set.Applied {
		digest, ok := applied[m.Version]
		if !ok {
			t.Errorf("migration %d (%s) is missing from the applied set", m.Version, m.Name)
			continue
		}
		if digest != m.Digest {
			t.Errorf("migration %d (%s) recorded digest %q, parsed %q",
				m.Version, m.Name, digest, m.Digest)
		}
	}

	// The schema the Go store needs must exist after an up run. Naming a real object is what
	// turns "exit 0" into evidence: a runner that committed nothing would still exit 0.
	if !relationExists(ctx, t, db, "public", "model_registry") {
		t.Error("public.model_registry does not exist after the up run")
	}
	if !relationExists(ctx, t, db, "ledger", "entry") {
		t.Error("ledger.entry does not exist after the up run")
	}

	// A second up run must be a no-op: the runner reads its own record and plans nothing.
	// This is the idempotence property that makes a redeploy safe.
	again, err := up.Run(ctx, migrate.Up)
	if err != nil {
		t.Fatalf("second up run: %v", err)
	}
	if len(again.Applied) != 0 {
		t.Errorf("second up run applied %v, expected nothing", again.Applied)
	}

	// Down, to a clean catalog.
	down := &migrate.Runner{Set: set, Store: store, Out: os.Stderr}
	downResult, err := down.Run(ctx, migrate.Down)
	if err != nil {
		t.Fatalf("reverting the set: %v", err)
	}
	if len(downResult.Reverted) != len(set.Applied) {
		t.Errorf("reverted %d migrations, expected %d", len(downResult.Reverted), len(set.Applied))
	}

	if relationExists(ctx, t, db, "public", "model_registry") {
		t.Error("public.model_registry survived the down run")
	}

	afterDown, err := store.Applied(ctx)
	if err != nil {
		t.Fatalf("reading the applied set after reverting: %v", err)
	}
	if len(afterDown) != 0 {
		t.Errorf("applied set holds %d records after reverting, expected 0: %v",
			len(afterDown), afterDown)
	}

	// Up again, leaving the database migrated for the tests that follow.
	final, err := up.Run(ctx, migrate.Up)
	if err != nil {
		t.Fatalf("reapplying the set: %v", err)
	}
	if len(final.Applied) != len(set.Applied) {
		t.Errorf("reapplied %d migrations, expected %d", len(final.Applied), len(set.Applied))
	}
	if !relationExists(ctx, t, db, "public", "audit_records") {
		t.Error("public.audit_records does not exist after the reapplied up run")
	}
}

func relationExists(ctx context.Context, t *testing.T, db *sql.DB, schema, name string) bool {
	t.Helper()

	var present bool
	err := db.QueryRowContext(ctx, `
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = $2
        );`, schema, name).Scan(&present)
	if err != nil {
		t.Fatalf("checking for %s.%s: %v", schema, name, err)
	}
	return present
}
