package main

import (
	"bytes"
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"slices"
	"strings"
	"testing"
	"time"

	// The driver is imported for its side effect so the assertions below can read the
	// catalog the command left behind.
	_ "github.com/lib/pq"
)

// These tests run the command, not a refactored function with the flags stubbed out.
//
// The exit codes are a contract with an operator and with CI: 0 means the direction completed,
// 1 means the run failed, 2 means the command could not run. A claim about that contract
// proved against anything other than the real process is a claim about the test. So each case
// re-executes this test binary with the command's own arguments and reads the exit code and
// the two streams, which is the same evidence an operator or a CI job would collect.

// reexecEnv marks the child process, so TestMain runs the command instead of the tests.
const reexecEnv = "WEBTRADE_MIGRATE_CLI_CHILD"

func TestMain(m *testing.M) {
	if os.Getenv(reexecEnv) == "1" {
		os.Exit(run())
	}
	os.Exit(m.Run())
}

// cliResult is what running the command produced.
type cliResult struct {
	code   int
	stdout string
	stderr string
}

func runCLI(t *testing.T, env []string, args ...string) cliResult {
	t.Helper()

	cmd := exec.Command(os.Args[0], args...)
	cmd.Env = append(withoutEnv(os.Environ(), reexecEnv), env...)
	cmd.Env = append(cmd.Env, reexecEnv+"=1")

	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr

	result := cliResult{}
	if err := cmd.Run(); err != nil {
		var exit *exec.ExitError
		if !errors.As(err, &exit) {
			t.Fatalf("running the command %v: %v", args, err)
		}
		result.code = exit.ExitCode()
	}
	result.stdout, result.stderr = stdout.String(), stderr.String()
	return result
}

// withoutEnv drops a variable from an environment.
//
// Appending a duplicate would be enough on POSIX and not on Windows, where the earlier value
// is the one that survives -- so a test that meant to point the command at a disposable
// database would silently keep pointing it at the shared one.
func withoutEnv(env []string, names ...string) []string {
	out := make([]string, 0, len(env))
	for _, kv := range env {
		key, _, _ := strings.Cut(kv, "=")
		if slices.Contains(names, key) {
			continue
		}
		out = append(out, kv)
	}
	return out
}

// disposableDSN creates a database for one test and returns its DSN, dropping it afterwards.
//
// Every down run is destructive by construction -- the real down bodies drop the ledger and
// the authz tables CASCADE -- so a down test that ran against the shared DATABASE_URL would
// destroy the state every other suite in the repository depends on. A database of its own is
// the only isolation that survives that, because the objects live at database scope.
func disposableDSN(t *testing.T) string {
	t.Helper()

	base := strings.TrimSpace(os.Getenv("DATABASE_URL"))
	if base == "" {
		t.Skip("DATABASE_URL is not set; skipping live-database tests")
	}
	adminURL, err := url.Parse(base)
	if err != nil {
		t.Fatalf("DATABASE_URL must be a URL this test can rewrite to name a disposable "+
			"database; got %q: %v", base, err)
	}
	// CREATE DATABASE cannot run from inside the database it creates, so the maintenance
	// database does the creating and the dropping.
	adminURL.Path = "/postgres"

	admin, err := sql.Open("postgres", adminURL.String())
	if err != nil {
		t.Fatalf("opening the maintenance database: %v", err)
	}
	// Registered first so it runs last: the cleanup below still needs this handle.
	t.Cleanup(func() { _ = admin.Close() })

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := admin.PingContext(ctx); err != nil {
		t.Fatalf("DATABASE_URL=%q is set but not reachable: %v", base, err)
	}

	name := fmt.Sprintf("migrate_cli_%d_%x", os.Getpid(), time.Now().UnixNano())
	if _, err := admin.ExecContext(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatalf("creating the disposable database %s: %v", name, err)
	}
	t.Cleanup(func() {
		dropCtx, dropCancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer dropCancel()
		// A session the run left behind would keep the database from being dropped.
		_, _ = admin.ExecContext(dropCtx,
			`SELECT pg_terminate_backend(pid) FROM pg_stat_activity
			 WHERE datname = $1 AND pid <> pg_backend_pid()`, name)
		if _, err := admin.ExecContext(dropCtx, "DROP DATABASE IF EXISTS "+name); err != nil {
			t.Logf("dropping the disposable database %s: %v", name, err)
		}
	})

	target := *adminURL
	target.Path = "/" + name
	return target.String()
}

// catalog reads the applied set and the existence of two named tables, which together say
// both what the ledger claims and whether the objects are actually there. The ledger alone is
// not enough: a run that recorded a revert without running the body would report an applied
// set that does not describe the database.
func catalog(t *testing.T, dsn string) (versions []int, authzTable, registryTable bool) {
	t.Helper()

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatalf("opening %s: %v", dsn, err)
	}
	defer db.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	rows, err := db.QueryContext(ctx,
		`SELECT version FROM migrate.applied_set ORDER BY version`)
	if err != nil {
		t.Fatalf("reading the applied set: %v", err)
	}
	defer rows.Close()
	for rows.Next() {
		var v int
		if err := rows.Scan(&v); err != nil {
			t.Fatalf("reading a row of the applied set: %v", err)
		}
		versions = append(versions, v)
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("the applied-set scan ended early: %v", err)
	}

	// authz_decisions is created by 0003 and model_registry by 0004, so each one tells us
	// whether that migration is still in place whatever its ledger row says. Neither
	// migration creates a schema, so both live in public.
	for _, probe := range []struct {
		table string
		out   *bool
	}{
		{"public.authz_decisions", &authzTable},
		{"public.model_registry", &registryTable},
	} {
		var exists bool
		err := db.QueryRowContext(ctx,
			`SELECT to_regclass($1) IS NOT NULL`, probe.table).Scan(&exists)
		if err != nil {
			t.Fatalf("checking %s: %v", probe.table, err)
		}
		*probe.out = exists
	}
	return versions, authzTable, registryTable
}

// The status direction is a question. On a database that has never been migrated it has to
// answer "no migrations applied", exit 0, and leave the catalog exactly as it found it --
// otherwise the read-only direction cannot be pointed at a replica, and asking what state a
// database is in changes that state.
func TestStatusIsReadOnlyAndSucceedsOnAnUninitialisedDatabase(t *testing.T) {
	dsn := disposableDSN(t)

	got := runCLI(t, []string{"DATABASE_URL=" + dsn}, "-direction", "status")
	if got.code != 0 {
		t.Fatalf("status on an uninitialised database must exit 0, got %d\nstderr: %s",
			got.code, got.stderr)
	}
	if !strings.Contains(got.stdout, "no migrations applied") {
		t.Fatalf("expected the empty applied set to be reported, got %q", got.stdout)
	}

	// Nothing may have been created. This is the assertion the old ordering could not pass:
	// Ensure ran first and created both the schema and the table.
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatalf("opening %s: %v", dsn, err)
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

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

// Status still reports a real applied set, so the empty answer above is a decision about an
// uninitialised catalog rather than a stub that always says nothing.
func TestStatusReportsWhatIsApplied(t *testing.T) {
	dsn := disposableDSN(t)
	env := []string{"DATABASE_URL=" + dsn}

	if got := runCLI(t, env, "-direction", "up"); got.code != 0 {
		t.Fatalf("up must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}
	got := runCLI(t, env, "-direction", "status")
	if got.code != 0 {
		t.Fatalf("status must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}
	if !strings.Contains(got.stdout, "migration(s) applied") {
		t.Fatalf("expected the applied set to be reported, got %q", got.stdout)
	}
}

// -to is the difference between reverting one bad migration and dropping the database. The
// bounded run must revert exactly the suffix above the target and leave everything at or below
// it applied, in the ledger and in the catalog.
func TestABoundedRevertStopsAtTheTarget(t *testing.T) {
	dsn := disposableDSN(t)
	env := []string{"DATABASE_URL=" + dsn}

	if got := runCLI(t, env, "-direction", "up"); got.code != 0 {
		t.Fatalf("up must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}
	versions, authz, registry := catalog(t, dsn)
	if len(versions) == 0 || !authz || !registry {
		t.Fatalf("the whole set should be applied before the revert; ledger=%v authz=%v registry=%v",
			versions, authz, registry)
	}
	newest := versions[len(versions)-1]

	got := runCLI(t, env, "-direction", "down", "-to", fmt.Sprint(newest-1))
	if got.code != 0 {
		t.Fatalf("a bounded revert must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}

	versions, authz, registry = catalog(t, dsn)
	if len(versions) < 2 {
		t.Fatalf("expected the migrations below the target to survive, got %v", versions)
	}
	if versions[len(versions)-1] != newest-1 {
		t.Fatalf("the ledger should end at %06d, got %v", newest-1, versions)
	}
	if slices.Contains(versions, newest) {
		t.Fatalf("migration %06d was asked to be reverted and is still applied: %v", newest, versions)
	}
	if !authz {
		t.Fatal("the authz table is gone; the revert went past its target")
	}
	if registry {
		t.Fatal("the model registry survived; the newest migration was not reverted")
	}
}

// The default is unchanged: no -to reverts the whole applied set, which is the release-gate
// rehearsal. An operator who never passes the flag must get the run they got before it
// existed, on a database of their own.
func TestAnUnboundedRevertStillRevertsEverything(t *testing.T) {
	dsn := disposableDSN(t)
	env := []string{"DATABASE_URL=" + dsn}

	if got := runCLI(t, env, "-direction", "up"); got.code != 0 {
		t.Fatalf("up must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}
	if got := runCLI(t, env, "-direction", "down"); got.code != 0 {
		t.Fatalf("an unbounded revert must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}

	versions, authz, registry := catalog(t, dsn)
	if len(versions) != 0 {
		t.Fatalf("an unbounded revert must empty the ledger, got %v", versions)
	}
	if authz || registry {
		t.Fatalf("an unbounded revert must drop every object; authz=%v registry=%v", authz, registry)
	}
}

// A target the database is not applied to is refused. Accepting it would revert more than the
// operator asked for, which is the one outcome a rollback must never produce, so this exits 2
// and changes nothing.
func TestARevertToAVersionThatIsNotAppliedIsRefused(t *testing.T) {
	dsn := disposableDSN(t)
	env := []string{"DATABASE_URL=" + dsn}

	if got := runCLI(t, env, "-direction", "up"); got.code != 0 {
		t.Fatalf("up must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}
	// Down to 2 leaves the ledger at {1, 2}, so 4 is in the repository and not in the applied
	// set: the exact case that must be refused rather than rounded to a nearby version.
	if got := runCLI(t, env, "-direction", "down", "-to", "2"); got.code != 0 {
		t.Fatalf("the first bounded revert must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}
	before, _, _ := catalog(t, dsn)

	got := runCLI(t, env, "-direction", "down", "-to", "4")
	if got.code != 2 {
		t.Fatalf("a target outside the applied set must exit 2, got %d\nstdout: %s\nstderr: %s",
			got.code, got.stdout, got.stderr)
	}
	if !strings.Contains(got.stderr, "000004") {
		t.Fatalf("the refusal must name the version, got %q", got.stderr)
	}
	after, _, _ := catalog(t, dsn)
	if !slices.Equal(before, after) {
		t.Fatalf("a refused revert changed the database: %v became %v", before, after)
	}
}

// A target that names no migration is a typo, and it is refused by the same rule.
func TestARevertToAnUnknownVersionIsRefused(t *testing.T) {
	dsn := disposableDSN(t)
	env := []string{"DATABASE_URL=" + dsn}

	if got := runCLI(t, env, "-direction", "up"); got.code != 0 {
		t.Fatalf("up must exit 0, got %d\nstderr: %s", got.code, got.stderr)
	}
	before, _, _ := catalog(t, dsn)

	got := runCLI(t, env, "-direction", "down", "-to", "424242")
	if got.code != 2 {
		t.Fatalf("an unknown target must exit 2, got %d\nstderr: %s", got.code, got.stderr)
	}
	if !strings.Contains(got.stderr, "424242") {
		t.Fatalf("the refusal must name the version, got %q", got.stderr)
	}
	after, _, _ := catalog(t, dsn)
	if !slices.Equal(before, after) {
		t.Fatalf("a refused revert changed the database: %v became %v", before, after)
	}
}

// A bound on a direction that cannot use it is a typo, reported before the database is
// touched. Requiring a reachable database to be told that a flag cannot mean anything is the
// kind of help that arrives too late to be useful.
func TestToIsRefusedOnADirectionThatCannotUseIt(t *testing.T) {
	for _, direction := range []string{"up", "status"} {
		got := runCLI(t, []string{"DATABASE_URL="}, "-direction", direction, "-to", "2")
		if got.code != 2 {
			t.Fatalf("-to with -direction %s must exit 2, got %d\nstderr: %s",
				direction, got.code, got.stderr)
		}
		if !strings.Contains(got.stderr, "-to") {
			t.Fatalf("the refusal must name the flag, got %q", got.stderr)
		}
	}
}

// Versions are positive, so a bound of zero or less is not a request to revert everything. It
// is a request to name a version that cannot exist.
func TestANonPositiveToIsRefused(t *testing.T) {
	for _, v := range []string{"0", "-1"} {
		got := runCLI(t, []string{"DATABASE_URL="}, "-direction", "down", "-to", v)
		if got.code != 2 {
			t.Fatalf("-to %s must exit 2, got %d\nstderr: %s", v, got.code, got.stderr)
		}
		if !strings.Contains(got.stderr, "positive") {
			t.Fatalf("the refusal must explain why, got %q", got.stderr)
		}
	}
}

// An unknown direction keeps its own exit code, unchanged by any of this.
func TestAnUnknownDirectionIsRefused(t *testing.T) {
	got := runCLI(t, []string{"DATABASE_URL="}, "-direction", "sideways")
	if got.code != 2 {
		t.Fatalf("an unknown direction must exit 2, got %d\nstderr: %s", got.code, got.stderr)
	}
	if !strings.Contains(got.stderr, "sideways") {
		t.Fatalf("the refusal must name the direction, got %q", got.stderr)
	}
}

// The dry run answers "what would this do" without a database, and that has to keep holding
// when a bound is passed: the bound is validated before the connection is opened either way.
func TestABoundedDryRunNeedsNoDatabase(t *testing.T) {
	got := runCLI(t, []string{"DATABASE_URL="}, "-direction", "down", "-to", "2", "-dry-run")
	if got.code != 0 {
		t.Fatalf("a dry run must exit 0 with no database, got %d\nstderr: %s", got.code, got.stderr)
	}
	if !strings.Contains(got.stdout, "dry run") {
		t.Fatalf("expected the dry-run banner, got %q", got.stdout)
	}
}
