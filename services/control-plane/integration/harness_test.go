//go:build integration

// Live-database tests for the migrator and the durable stores.
//
// These exist because the repository previously had no Go PostgreSQL driver, which meant the
// SQL behind SQLSink, SQLStore, SQLIdentityStore and SQLChainReader had never been executed
// by the code that calls it. Every other test of those paths runs against an in-memory fake,
// and a fake accepts whatever shape the Go code hands it, so a query that references a column
// the migration never creates would pass the whole suite and fail on first production use.
//
// Gated behind the `integration` build tag so `go test ./...` stays driver-free and fast. CI's
// integration job already passes -tags=integration and already provides a PostgreSQL service,
// so these run there on protected branches without a workflow change.
//
// Requires DATABASE_URL. Skips rather than fails when it is absent, so a developer running the
// tag locally without a database sees a skip instead of a false failure.
package integration

import (
	"context"
	"database/sql"
	"os"
	"testing"
	"time"

	_ "github.com/lib/pq"
)

// open connects to the test database or skips.
//
// The skip is deliberate and is not a way for a broken build to pass quietly: CI sets
// DATABASE_URL, so a skip there means the job lost its service and the run is already
// visibly wrong.
func open(t *testing.T) *sql.DB {
	t.Helper()

	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL is not set; skipping live-database tests")
	}

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatalf("opening the database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		// A single retry, because a container that was just recreated accepts the port
		// before it has finished initialising its own credentials. Without this, a local
		// run fails on the first attempt after a container restart for a reason that has
		// nothing to do with the code under test.
		//
		// The retry is bounded and does not loop: a genuinely wrong DSN still fails, and it
		// fails with the driver's own message rather than a swallowed one.
		if retryErr := db.PingContext(ctx); retryErr != nil {
			t.Fatalf("pinging the database: %v (retry also failed: %v)", err, retryErr)
		}
		t.Log("ping failed once and succeeded on retry; the server was still initialising")
	}
	return db
}

func ctxFor(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	t.Cleanup(cancel)
	return ctx
}
