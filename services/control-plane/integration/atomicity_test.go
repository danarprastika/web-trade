//go:build integration

package integration

import (
	"context"
	"database/sql"
	"strings"
	"testing"

	"github.com/danarprastika/web-trade/services/control-plane/migrate"
)

// A migration body that fails must leave nothing behind: no partial schema, and no record
// claiming it was applied.
//
// This is the property the store's whole design exists to provide, and it is the one thing a
// fake store cannot check. The parked original asserted it in a comment; here it is executed.
// The failure is injected as a body whose first statement succeeds and whose second does not,
// because a body that fails on its first statement would leave nothing to roll back and would
// pass even with the transaction removed.
func TestAFailedMigrationCommitsNeitherSchemaNorRecord(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	if err := dropIfExists(ctx, db, "public", "probe_partial"); err != nil {
		t.Fatalf("clearing the probe table: %v", err)
	}
	if err := clearApplied(ctx, db, 900001); err != nil {
		t.Fatalf("clearing the probe record: %v", err)
	}

	store := migrate.NewSQLStore(db)
	if err := store.Ensure(ctx); err != nil {
		t.Fatalf("ensuring the applied-set table: %v", err)
	}

	// First statement succeeds and creates a real object. Second references a column that does
	// not exist, so the transaction must abort with the table still uncommitted.
	body := strings.Join([]string{
		"BEGIN;",
		"CREATE TABLE public.probe_partial (id integer PRIMARY KEY);",
		"INSERT INTO public.probe_partial (id, no_such_column) VALUES (1, 2);",
		"COMMIT;",
	}, "\n")

	m := migrate.Migration{
		Version: 900001,
		Name:    "900001_probe_partial.sql",
		SQL:     body,
		// Any well-formed digest: the store records what it is given, and this test is about
		// atomicity, not about digest computation.
		Digest: strings.Repeat("a", 64),
	}

	err := store.Exec(ctx, m, body)
	if err == nil {
		t.Fatal("a body with an invalid column was accepted; the store is not enforcing anything")
	}
	t.Logf("injected failure surfaced as: %v", err)

	if relationExists(ctx, t, db, "public", "probe_partial") {
		t.Error("probe_partial survived a failed migration; the transaction did not roll back")
	}

	applied, readErr := store.Applied(ctx)
	if readErr != nil {
		t.Fatalf("reading the applied set: %v", readErr)
	}
	if _, recorded := applied[900001]; recorded {
		t.Error("a failed migration was recorded as applied; the body and record are not atomic")
	}
}

// The same, for a revert: a down body that fails must not forget the migration, or the next
// run would believe the schema is gone when it is not.
func TestAFailedRevertKeepsTheRecordAndTheSchema(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)

	store := migrate.NewSQLStore(db)
	if err := store.Ensure(ctx); err != nil {
		t.Fatalf("ensuring the applied-set table: %v", err)
	}

	// Apply a real, minimal migration so there is a schema and a record to protect.
	if err := dropIfExists(ctx, db, "public", "probe_revert"); err != nil {
		t.Fatalf("clearing the probe table: %v", err)
	}
	if err := clearApplied(ctx, db, 900002); err != nil {
		t.Fatalf("clearing the probe record: %v", err)
	}

	m := migrate.Migration{
		Version: 900002,
		Name:    "900002_probe_revert.sql",
		SQL:     "BEGIN;\nCREATE TABLE public.probe_revert (id integer PRIMARY KEY);\nCOMMIT;",
		Digest:  strings.Repeat("b", 64),
	}
	if err := store.Exec(ctx, m, m.SQL); err != nil {
		t.Fatalf("applying the probe migration: %v", err)
	}
	if !relationExists(ctx, t, db, "public", "probe_revert") {
		t.Fatal("probe_revert does not exist after a successful apply")
	}

	// A down body that drops the table and then fails. The drop must be rolled back.
	badDown := strings.Join([]string{
		"BEGIN;",
		"DROP TABLE public.probe_revert;",
		"SELECT no_such_function() ;",
		"COMMIT;",
	}, "\n")
	m.DownSQL = badDown

	if err := store.Undo(ctx, m); err == nil {
		t.Fatal("a down body with an invalid function was accepted")
	}

	if !relationExists(ctx, t, db, "public", "probe_revert") {
		t.Error("probe_revert is gone after a failed revert; the drop was not rolled back")
	}
	applied, err := store.Applied(ctx)
	if err != nil {
		t.Fatalf("reading the applied set: %v", err)
	}
	if _, recorded := applied[900002]; !recorded {
		t.Error("a failed revert forgot the migration; the next run would plan it wrongly")
	}

	// Leave the database as found.
	dropIfExists(ctx, db, "public", "probe_revert")
	clearApplied(ctx, db, 900002)
}

func dropIfExists(ctx context.Context, db *sql.DB, schema, name string) error {
	_, err := db.ExecContext(ctx, `DROP TABLE IF EXISTS `+schema+`.`+name+`;`)
	return err
}

// clearApplied removes a probe record, creating the applied-set table first if it is absent.
//
// The table is created by whichever test runs the migrator first, and Go runs tests in file
// order within a package, so an atomicity test cannot assume it exists. Ensuring it here is
// idempotent and keeps each test independent of the order the package happens to use.
func clearApplied(ctx context.Context, db *sql.DB, version int) error {
	if err := migrate.NewSQLStore(db).Ensure(ctx); err != nil {
		return err
	}
	_, err := db.ExecContext(ctx, `DELETE FROM migrate.applied_set WHERE version = $1;`, version)
	return err
}
