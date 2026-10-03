package migrate

import (
	"context"
	"database/sql"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	// The driver is imported for its side effect, exactly as cmd/migrate does. Without it
	// sql.Open("postgres", ...) has no implementation and every test below fails at the
	// first query with a message about a missing driver rather than about the code.
	_ "github.com/lib/pq"
)

// The tests in this file are the only ones that prove the two claims this package now makes
// about PostgreSQL rather than about logic: that a status run issues no DDL, and that two
// concurrent runs cannot both plan the same steps. Both need a real server to be worth
// anything -- a fake cannot hold an advisory lock, and a fake cannot prove that a query left
// the catalog alone.
//
// They skip when DATABASE_URL is absent rather than failing, which is the same trade the
// integration harness makes: CI sets it, so a skip there means the job lost its service and
// the run is already visibly wrong, and a developer without a database gets a skip instead of
// a false failure.

// testDatabaseURL is the DSN the live tests connect to, or a skip.
func testDatabaseURL(t *testing.T) string {
	t.Helper()
	dsn := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if dsn == "" {
		t.Skip("DATABASE_URL is not set; skipping live-database tests")
	}
	return dsn
}

// disposableDB creates a database that belongs to one test and drops it afterwards.
//
// Isolation has to be a database rather than a schema here. The migrations create objects in
// the ledger, audit, and authz schemas at database scope, and a down body drops them CASCADE,
// so a test that reverts anything against the shared DATABASE_URL destroys the state every
// other suite in this repository is using. A database of its own is the only isolation that
// survives a down body.
func disposableDB(t *testing.T) *sql.DB {
	t.Helper()
	base := testDatabaseURL(t)

	adminURL, err := url.Parse(base)
	if err != nil {
		t.Fatalf("DATABASE_URL must be a URL this test can rewrite to name a disposable "+
			"database; got %q: %v", base, err)
	}
	// CREATE DATABASE cannot run from inside the database being dropped, so the maintenance
	// database does the creating and the dropping.
	adminURL.Path = "/postgres"

	admin, err := sql.Open("postgres", adminURL.String())
	if err != nil {
		t.Fatalf("opening the maintenance database: %v", err)
	}
	t.Cleanup(func() { _ = admin.Close() })

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := admin.PingContext(ctx); err != nil {
		t.Fatalf("DATABASE_URL=%q is set but not reachable: %v", base, err)
	}

	name := fmt.Sprintf("migrate_live_%d_%x", os.Getpid(), time.Now().UnixNano())
	// The name is generated here and interpolated rather than bound, because PostgreSQL will
	// not accept a bound parameter in place of a database name. There is nothing to quote
	// because nothing but this format string can reach it.
	if _, err := admin.ExecContext(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatalf("creating the disposable database %s: %v", name, err)
	}
	// Registered before the test's own handle, so reverse-order cleanup closes that handle
	// first and the drop below does not fail on a database still in use.
	t.Cleanup(func() { dropDisposable(t, admin, name) })

	target := *adminURL
	target.Path = "/" + name
	db, err := sql.Open("postgres", target.String())
	if err != nil {
		t.Fatalf("opening the disposable database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

func dropDisposable(t *testing.T, admin *sql.DB, name string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	// A session the test left behind keeps the database from being dropped, and a leftover
	// disposable database is the kind of litter nobody notices until the disk fills.
	_, _ = admin.ExecContext(ctx,
		`SELECT pg_terminate_backend(pid) FROM pg_stat_activity
		 WHERE datname = $1 AND pid <> pg_backend_pid()`, name)
	if _, err := admin.ExecContext(ctx, "DROP DATABASE IF EXISTS "+name); err != nil {
		t.Logf("dropping the disposable database %s: %v", name, err)
	}
}

func liveCtx(t *testing.T, d time.Duration) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), d)
	t.Cleanup(cancel)
	return ctx
}

// handMigration builds a migration without a file, because the properties under test here --
// a body slow enough to be observed from another connection, a body that fails, a body that
// panics -- cannot be requested of the repository's real migrations on demand.
func handMigration(version int, body, down string) Migration {
	return Migration{
		Version: version,
		Name:    fmt.Sprintf("%04d_hand.sql", version),
		SQL:     body,
		DownSQL: down,
		Digest:  fmt.Sprintf("digest%04d", version),
	}
}

// The status path must be a question, not a change. Asserting that Applied fails on this same
// database is what makes the Status assertion meaningful: the catalog genuinely has no
// applied-set table, so Status did not find one, it decided there was nothing applied.
func TestStatusOnAnUninitialisedDatabaseReportsNothingAndCreatesNothing(t *testing.T) {
	db := disposableDB(t)
	ctx := liveCtx(t, 30*time.Second)
	store := NewSQLStore(db)

	if _, err := store.Applied(ctx); err == nil {
		t.Fatal("the applied-set table is not expected to exist yet; if it does, this " +
			"test is not running against an uninitialised database")
	}

	applied, err := store.Status(ctx)
	if err != nil {
		t.Fatalf("status against an uninitialised catalog must succeed, got: %v", err)
	}
	if len(applied) != 0 {
		t.Fatalf("expected an empty applied set, got %v", applied)
	}

	// The whole point: no schema, no table, nothing. A status run that creates the catalog it
	// was asked to read is the bug this test exists to prevent.
	var exists bool
	err = db.QueryRowContext(ctx,
		`SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = 'migrate')`,
	).Scan(&exists)
	if err != nil {
		t.Fatalf("checking the catalog: %v", err)
	}
	if exists {
		t.Fatal("a status run created the migrate schema; the read-only direction must not " +
			"issue DDL against the database it inspects")
	}
}

// Status reads the applied set when there is one, so the empty result above is a decision
// rather than a stub.
func TestStatusReportsTheAppliedSetOnceThereIsOne(t *testing.T) {
	db := disposableDB(t)
	ctx := liveCtx(t, 30*time.Second)
	store := NewSQLStore(db)

	set := Set{Applied: []Migration{
		handMigration(1, "CREATE TABLE one (id int PRIMARY KEY);", "DROP TABLE one;"),
		handMigration(2, "CREATE TABLE two (id int PRIMARY KEY);", "DROP TABLE two;"),
	}, Reversible: true}

	if err := store.Ensure(ctx); err != nil {
		t.Fatalf("Ensure: %v", err)
	}
	if _, err := (&Runner{Set: set, Store: store, Out: io.Discard}).Run(ctx, Up); err != nil {
		t.Fatalf("applying the set: %v", err)
	}

	applied, err := store.Status(ctx)
	if err != nil {
		t.Fatalf("Status: %v", err)
	}
	if len(applied) != 2 || applied[1] == "" || applied[2] == "" {
		t.Fatalf("expected both migrations reported, got %v", applied)
	}
}

// The failure the advisory lock exists to prevent: two runners read the same applied set, plan
// the same steps, and both execute them. The bodies here are not idempotent -- CREATE TABLE
// has no IF NOT EXISTS -- so a race ends with one runner failing on a statement the other
// already executed. The first runner holds the lock for the length of a pg_sleep, which is
// long enough for the second to be inside its lock wait rather than merely slow.
func TestTwoConcurrentRunsSerialiseOnTheAdvisoryLock(t *testing.T) {
	db := disposableDB(t)
	ctx := liveCtx(t, 120*time.Second)

	set := Set{Applied: []Migration{
		handMigration(1,
			"CREATE TABLE raced (id int PRIMARY KEY);\nSELECT pg_sleep(3);\n",
			"DROP TABLE raced;"),
	}, Reversible: true}

	// The command calls Ensure before the runner does, because a run that records itself
	// needs the ledger to exist. Both runners start from the same bootstrapped catalog, which
	// is what makes the only remaining difference between them the lock.
	if err := NewSQLStore(db).Ensure(ctx); err != nil {
		t.Fatalf("Ensure: %v", err)
	}

	first := &Runner{Set: set, Store: NewSQLStore(db), Out: io.Discard}
	second := &Runner{Set: set, Store: NewSQLStore(db), Out: io.Discard}

	firstDone := make(chan error, 1)
	go func() {
		_, err := first.Run(ctx, Up)
		firstDone <- err
	}()
	waitForAdvisoryLock(t, db)

	// Results travel through a channel rather than being asserted in the goroutine, because a
	// test that fails while its runners are still in flight leaves a session holding the lock
	// and the cleanup dropping the database underneath it.
	type outcome struct {
		result Result
		err    error
	}
	secondDone := make(chan outcome, 1)
	go func() {
		result, err := second.Run(ctx, Up)
		secondDone <- outcome{result, err}
	}()

	// The second run must not come back while the first still holds the lock. If it does, it
	// read the applied set before the first committed and is about to plan the same step.
	//
	// This used to be a bare `select` over both channels, and that was wrong for a reason worth
	// recording: when both runners are ready at once - which is what happens when the first
	// finishes while the test sits between selects - Go picks between the two channels at
	// random. Choosing `secondDone` there proves nothing about the lock, because both runs are
	// simply done, yet the message read it as proof of a concurrent run. "While the first still
	// held the lock" only means something if the first really is still running, so that is now
	// checked directly instead of inferred from which channel the select happened to choose.
	//
	// That change is correct but it was not the cause. WI-176 was an unscoped pg_locks query in
	// waitForAdvisoryLock; see advisoryLocksInThisDatabase for the actual defect. What this test
	// gained along the way is diagnosability: every failure below reports elapsed time, whether
	// the first runner finished, and how many sessions hold the lock in this database. The
	// root cause above was found in one run because of those fields - two hours of guessing at
	// a one-line message had not found it.
	started := time.Now()
	elapsed := func() string { return time.Since(started).Round(time.Millisecond).String() }

	// lockHolders counts sessions holding an advisory lock *in this database*, so a failure can
	// distinguish "the lock was never taken" from "the lock was taken and ignored". It uses the
	// same scoped query as waitForAdvisoryLock: an unscoped count would report other tests' locks
	// and make this diagnostic actively misleading.
	lockHolders := func() string {
		var n int
		dctx, dcancel := context.WithTimeout(ctx, 5*time.Second)
		defer dcancel()
		if err := db.QueryRowContext(dctx, advisoryLocksInThisDatabase).Scan(&n); err != nil {
			return "unknown (" + err.Error() + ")"
		}
		return fmt.Sprintf("%d", n)
	}

	var got outcome
	secondReturned := false
	firstFinished := false
	var firstErr error
	select {
	case got = <-secondDone:
		secondReturned = true
		select {
		case firstErr = <-firstDone:
			firstFinished = true
			if firstErr != nil {
				t.Fatalf("the first run failed after %s with %s advisory lock holder(s): %v",
					elapsed(), lockHolders(), firstErr)
			}
		default:
			t.Fatalf("the second run returned while the first still held the lock, after %s "+
				"with %s advisory lock holder(s): second err=%v second applied=%v first finished=%t",
				elapsed(), lockHolders(), got.err, got.result.Applied, firstFinished)
		}
	case firstErr = <-firstDone:
		firstFinished = true
		if firstErr != nil {
			t.Fatalf("the first run failed after %s with %s advisory lock holder(s): %v",
				elapsed(), lockHolders(), firstErr)
		}
	}

	if !secondReturned {
		select {
		case got = <-secondDone:
		case <-time.After(30 * time.Second):
			t.Fatalf("the second run never acquired the lock after %s; %s advisory lock "+
				"holder(s) remain and the first finished with err=%v",
				elapsed(), lockHolders(), firstErr)
		}
	}
	if got.err != nil {
		t.Fatalf("the second run failed instead of waiting for the lock, after %s with %s "+
			"advisory lock holder(s): %v", elapsed(), lockHolders(), got.err)
	}
	if len(got.result.Applied) != 0 {
		t.Fatalf("the second run applied %v after %s with %s advisory lock holder(s); it should "+
			"have observed the completed set and planned nothing",
			got.result.Applied, elapsed(), lockHolders())
	}

	var rows int
	if err := db.QueryRowContext(ctx, `SELECT count(*) FROM raced`).Scan(&rows); err != nil {
		t.Fatalf("reading the created table: %v", err)
	}
	if rows != 0 {
		t.Fatalf("expected an empty table from the migration, found %d row(s)", rows)
	}
}

// waitForAdvisoryLock polls until some session holds an advisory lock.
//
// Any advisory lock in a freshly created disposable database belongs to the test, so the count
// is the whole signal; there is no other migration tool on this server that could hold one.
func waitForAdvisoryLock(t *testing.T, db *sql.DB) {
	t.Helper()
	ctx := liveCtx(t, 20*time.Second)
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		var held int
		if err := db.QueryRowContext(ctx, advisoryLocksInThisDatabase).Scan(&held); err != nil {
			t.Fatalf("reading pg_locks: %v", err)
		}
		if held > 0 {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("the first run never took the advisory lock, so nothing was actually serialised")
}

// advisoryLocksInThisDatabase counts session-level advisory locks held in the *current*
// database, which is the only scope in which "this test's first runner holds the lock" can be
// concluded from a lock count.
//
// This is scoped to the database and that scoping is load-bearing, not tidiness. `pg_locks` is
// cluster-wide, and every test in this package locks on the same key against one shared
// PostgreSQL instance. An unscoped count is therefore satisfied by *any other concurrently
// running test's* lock, so the wait returned before this test's first runner had locked
// anything. The second runner then started unblocked, won the race for the real lock, and
// applied the migration itself - which is exactly what the assertions caught:
//
//	the second run returned while the first still held the lock, after 3.099s with
//	2 advisory lock holder(s): second err=<nil> second applied=[0001_hand.sql] first finished=false
//
// The old comment here claimed that "any advisory lock in a freshly created disposable database
// belongs to the test", which is true of the *database* and false of the *cluster*. The two were
// confused, and the confusion only showed up when other packages were testing at the same time.
const advisoryLocksInThisDatabase = `
SELECT count(*) FROM pg_locks
WHERE locktype = 'advisory'
  AND database = (SELECT oid FROM pg_database WHERE datname = current_database())`

// A run that fails releases the lock. If it did not, the next run would block on it until its
// own timeout and report a lock wait rather than a migration error, and every run after that
// would do the same.
func TestAFailedRunReleasesTheAdvisoryLock(t *testing.T) {
	db := disposableDB(t)
	if err := NewSQLStore(db).Ensure(liveCtx(t, 30*time.Second)); err != nil {
		t.Fatalf("Ensure: %v", err)
	}

	broken := Set{Applied: []Migration{
		handMigration(1,
			"CREATE TABLE half_done (id int);\nSELECT 1 / 0;\n",
			"DROP TABLE half_done;"),
	}, Reversible: true}
	failing := &Runner{Set: broken, Store: NewSQLStore(db), Out: io.Discard}
	if _, err := failing.Run(liveCtx(t, 30*time.Second), Up); err == nil {
		t.Fatal("a body that divides by zero must fail the run")
	}

	// Bounded, because the failure mode being guarded against is a lock that is never
	// released: this second run must acquire it, not wait for the deadline and report that.
	after := Set{Applied: []Migration{
		handMigration(2, "CREATE TABLE after_failure (id int);", "DROP TABLE after_failure;"),
	}, Reversible: true}
	next := &Runner{Set: after, Store: NewSQLStore(db), Out: io.Discard}
	if _, err := next.Run(liveCtx(t, 15*time.Second), Up); err != nil {
		t.Fatalf("the run after a failed run could not take the lock: %v", err)
	}
}

// The requirement that makes a session-level lock defensible: a panicking migration body must
// not wedge every future run. The panic is raised by a store that otherwise uses the real
// PostgreSQL lock, so this asserts the property against the lock that would actually wedge,
// not against a fake that cannot.
func TestAPanickingMigrationBodyLeavesTheAdvisoryLockFree(t *testing.T) {
	db := disposableDB(t)
	if err := NewSQLStore(db).Ensure(liveCtx(t, 30*time.Second)); err != nil {
		t.Fatalf("Ensure: %v", err)
	}

	panicking := Set{Applied: []Migration{
		handMigration(1, "CREATE TABLE never (id int);", "DROP TABLE never;"),
	}, Reversible: true}
	boom := &Runner{Set: panicking, Store: &panickingSQLStore{SQLStore: NewSQLStore(db)}, Out: io.Discard}
	mustPanic(t, "Run with a panicking body", func() {
		_, _ = boom.Run(liveCtx(t, 30*time.Second), Up)
	})

	after := Set{Applied: []Migration{
		handMigration(2, "CREATE TABLE after_panic (id int);", "DROP TABLE after_panic;"),
	}, Reversible: true}
	next := &Runner{Set: after, Store: NewSQLStore(db), Out: io.Discard}
	if _, err := next.Run(liveCtx(t, 15*time.Second), Up); err != nil {
		t.Fatalf("the run after a panicking body could not take the lock: %v", err)
	}
}

// panickingSQLStore is a real store with a body that panics instead of executing. Everything
// else, the lock included, is the real thing.
type panickingSQLStore struct{ *SQLStore }

func (p *panickingSQLStore) Exec(context.Context, Migration, string) error {
	panic("the migration body panicked")
}
