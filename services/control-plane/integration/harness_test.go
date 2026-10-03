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
// tag locally without a database sees a skip instead of a false failure. That skip is the
// non-destructive half of the harness and is unchanged: CI enforces its own DSN is present
// before it runs this suite, because a skip there would otherwise report success having run
// nothing.
//
// The destructive half is guarded instead. Reverting the real migration set drops schema
// ledger CASCADE and takes the audit, authz and model_registry tables with it, so running that
// against whatever DATABASE_URL happens to name would delete a developer's or operator's data
// with no confirmation. A test that reverts migrations therefore connects through
// openDestructive, which refuses a target that is not verifiably disposable before a single
// statement runs. See requireDisposableDestructiveTarget for the rule and the override.
package integration

import (
	"context"
	"database/sql"
	"os"
	"testing"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/migrate"

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

// openDestructive connects for a test that reverts migrations, and refuses a database that is
// not verifiably disposable before any statement runs.
//
// The refusal is a Fatalf and never a Skip. A test that skips having destroyed nothing reports
// the same "ok" a passing run reports, and the destructive step is exactly the step whose
// absence must be visible: this harness already had seventeen skips read as a pass, and adding
// a second way to quietly not-run the most dangerous test in the package would repeat that.
func openDestructive(t *testing.T) *sql.DB {
	db := open(t)
	requireDisposableDestructiveTarget(t)
	return db
}

// The opt-in name and its one accepted value.
//
// The value is compared exactly, on purpose. A permissive parser (trim, case-insensitive,
// "true"/"yes" accepted) makes the guard weaker every time somebody decides to be helpful,
// and the only thing this variable is for is to make an operator state, in characters they had
// to choose deliberately, that they mean to drop the database. Empty, "0", "yes" and a typo are
// all refusals.

// The guard itself lives in the migrate package, next to the migrator it protects, because a
// protection that lives in a _test.go file protects nothing outside `go test`. cmd/migrate -direction
// down judges its target with the same code; only the policy differs, and DestructivePolicy says
// which way and why in one place.
//
// What follows is this package's wiring over that shared rule. The names are kept unexported and
// the signatures are kept short so the tests in destructive_guard_test.go read the way they were
// written.
const (
	destructiveOptInEnv   = migrate.IntegrationOptInEnv
	destructiveOptInValue = migrate.OptInValue
)

// harnessPolicy is deliberately the permissive one.
//
// The harness's DSN comes from a CI service definition this repository controls, and a developer's
// deliberate local reset is not an accident waiting to happen. So a database that announces itself
// disposable on this machine needs nothing, and anything else needs only the opt-in. The shipped
// command uses the opposite policy, where the opt-in is necessary and not sufficient.
//
// This calls migrate.IntegrationOptInPolicy rather than restating the literal it returns. The
// first version of this line built the struct here instead, field for field, and an independent
// review of that change set noticed the consequence: editing IntegrationOptInPolicy would leave
// the harness untouched, while migrate/destructive_test.go - which asserts on the function - would
// stay green. The two would have drifted with nothing reporting it. A wrapper that retypes the
// value it wraps is not a wrapper.
var harnessPolicy = migrate.IntegrationOptInPolicy()

// disposableDatabaseSuffixes is re-exported rather than re-declared. The guard test asserts on the
// suffix list directly, and a second copy here could drift from the one the rule uses - which
// would leave a test passing against a list that no longer decides anything.
var disposableDatabaseSuffixes = migrate.DisposableDatabaseSuffixes

type dsnTarget = migrate.DSNTarget

type destructiveVerdict = migrate.DestructiveVerdict

func parseDSNTarget(dsn string) (dsnTarget, error) { return migrate.ParseDSNTarget(dsn) }

func evaluateDestructiveTarget(dsn, optIn string) destructiveVerdict {
	return migrate.EvaluateDestructiveTarget(dsn, harnessPolicy, optIn)
}

func destructiveRefusalMessage(v destructiveVerdict) string {
	return v.RefusalMessage("go test -tags=integration ./integration/...")
}

// requireDisposableDestructiveTarget fails the test unless the configured database may be reset.
//
// It fails. It does not skip, and it does not downgrade to a warning, and there is no environment
// value that turns the refusal into a skip. That is the whole point of adding a new variable here
// at all: a guard that can be silenced by an unset variable is not a guard, and the harness already
// ships one quiet path (an unset DATABASE_URL skips) which CI has to police from outside. This one
// polices itself.
func requireDisposableDestructiveTarget(t *testing.T) {
	t.Helper()

	verdict := evaluateDestructiveTarget(os.Getenv("DATABASE_URL"), os.Getenv(destructiveOptInEnv))
	if !verdict.Allowed {
		t.Fatal(destructiveRefusalMessage(verdict))
	}
	if verdict.Overridden {
		// Not fatal: the operator asked for this and got it. Logged because a run that reset a
		// database whose name did not announce itself as disposable is the case somebody needs to
		// find in a log after the fact.
		t.Logf("DESTRUCTIVE MIGRATION RESET: %s does not look like a disposable database and was allowed by %s=%s; its schemas and data were dropped",
			verdict.Target, destructiveOptInEnv, destructiveOptInValue)
		return
	}
	t.Logf("destructive migration reset permitted against the disposable target %s", verdict.Target)
}
