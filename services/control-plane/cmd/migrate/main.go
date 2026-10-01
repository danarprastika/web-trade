// Command migrate applies the repository's migrations to PostgreSQL in either direction.
//
// This is the command .github/workflows/ci.yml runs as the migration rehearsal gate, and the
// command an operator runs to revert. It is deliberately thin: the ordering, the drift check,
// and the reversibility rules live in the migrate package, where they are tested without a
// database, and this file only wires flags to them.
//
// The database handle is opened through database/sql with github.com/lib/pq, which is the driver
// EV-060 established satisfies the repository's pinning gate. The earlier version of this file
// used pgxpool and was parked rather than run, on the belief that no Go driver could be admitted;
// that belief was wrong and the reason it was wrong is recorded rather than quietly dropped.
//
// Exit codes:
//
//	0  the requested direction completed, or a dry run found nothing to refuse
//	1  the run failed, or the database disagrees with the repository
//	2  the command could not run (no DATABASE_URL, missing migrations, unusable --to,
//	   unknown direction, database unreachable)
//
// `-direction status` is read-only. It reports the applied set, or reports that nothing is
// applied, and on a database that has never been migrated it says so without creating
// anything -- which is also why it is the direction that works against a replica or a
// read-only connection.
//
// `-direction down` reverts the whole applied set unless `-to` bounds it. The unbounded form
// is the release-gate rehearsal and is unchanged; `-to <version>` reverts only the applied
// migrations above that version, which is what an operator wants after a bad deploy when the
// alternative is dropping the ledger CASCADE.
package main

import (
	"context"
	"database/sql"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/migrate"

	// The driver is imported for its side effect: registering "postgres" with database/sql is
	// what lets sql.Open("postgres", ...) below find an implementation. It is not referenced by
	// name anywhere else in this file, and a named import would be a reference to nothing.
	_ "github.com/lib/pq"
)

func main() { os.Exit(run()) }

func run() int {
	direction := flag.String("direction", string(migrate.Up),
		"which way to apply the set: up, down, or status")
	dir := flag.String("dir", "", "migrations directory (default: found by walking up from the "+
		"working directory to locate db/migrations)")
	dryRun := flag.Bool("dry-run", false, "print the plan without touching the database")
	timeout := flag.Duration("timeout", 5*time.Minute,
		"how long the whole run may take before it is abandoned")
	to := flag.Int("to", 0, "for -direction down: revert only the applied migrations above "+
		"this version, leaving everything at or below it applied; default 0 means the whole "+
		"applied set")
	flag.Parse()

	parsed := migrate.Direction(*direction)
	if !parsed.Valid() {
		fmt.Fprintf(os.Stderr, "unknown direction %q; use up, down, or status\n", *direction)
		return 2
	}

	// Whether -to was given is tracked apart from its value, because the zero value is also
	// the unbounded default: an explicit "-to 0" names a version that cannot exist, and it is
	// refused rather than being indistinguishable from leaving the flag off.
	givenTo := false
	flag.Visit(func(f *flag.Flag) {
		if f.Name == "to" {
			givenTo = true
		}
	})

	// The bound is checked before the database is touched, because a bound that cannot mean
	// anything on this direction is a typo and reporting a typo should not require a reachable
	// database. The migrate package refuses the same thing again while planning, so the rule
	// holds for any caller and not only for this one.
	if givenTo {
		switch {
		case *to < 1:
			fmt.Fprintf(os.Stderr, "-to %d is not a migration version; versions are positive\n", *to)
			return 2
		case parsed != migrate.Down:
			fmt.Fprintf(os.Stderr, "-to applies to -direction down, not to %s\n", parsed)
			return 2
		}
	}

	root, err := findMigrations(*dir)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}

	set, err := migrate.Parse(os.DirFS(root))
	if err != nil {
		fmt.Fprintf(os.Stderr, "reading %s: %v\n", root, err)
		return 2
	}

	// A dry run stops here, before a connection is opened. It is the answer to "what would
	// this do", and making it require a reachable database would make it useless precisely
	// when a migration is suspected of being the thing that is broken.
	if *dryRun {
		fmt.Printf("dry run: %s\n", set.Describe())
		return 0
	}

	databaseURL := os.Getenv("DATABASE_URL")
	if databaseURL == "" {
		fmt.Fprintln(os.Stderr, "DATABASE_URL is not set; refusing to guess a database")
		return 2
	}

	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()

	// sql.Open validates nothing and connects to nothing, so a malformed DSN is only
	// discovered by the Ping below. Reporting that as "could not run" rather than "the run
	// failed" keeps the two categories the exit codes describe distinct.
	db, err := sql.Open("postgres", databaseURL)
	if err != nil {
		fmt.Fprintf(os.Stderr, "connecting to the database: %v\n", err)
		return 2
	}
	defer db.Close()

	if err := db.PingContext(ctx); err != nil {
		fmt.Fprintf(os.Stderr, "connecting to the database: %v\n", err)
		return 2
	}

	store := migrate.NewSQLStore(db)

	// Status comes before Ensure, and not for tidiness. Ensure is DDL -- CREATE SCHEMA and
	// CREATE TABLE -- and a status run is a question, not a change: called first, it made the
	// read-only direction mutate the database it was asked to inspect and fail with exit 2 on
	// a replica or a read-only connection, reporting "could not run" about a run that had
	// asked for nothing.
	if parsed == migrate.Status {
		// Status rather than Applied: a database nobody has migrated yet has no applied-set
		// table, and "no migrations applied" is the true answer for one rather than an error.
		applied, err := store.Status(ctx)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		fmt.Print(migrate.DescribeApplied(applied))
		return 0
	}

	if err := store.Ensure(ctx); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}

	runner := &migrate.Runner{Set: set, Store: store, Out: os.Stdout, To: *to}

	result, err := runner.Run(ctx, parsed)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		// A drift error is a disagreement about the schema, which is the one failure an
		// operator must resolve by hand rather than by retrying. It gets its own line so it
		// is not read as a transient connection problem.
		var driftErr migrate.ErrDrift
		if errors.As(err, &driftErr) {
			fmt.Fprintln(os.Stderr, "resolve the drift before running any migration; "+
				"re-running will not make the two records agree")
		}
		// A revert target the database cannot be reverted to is an unusable invocation rather
		// than a failed run, so it exits 2 with the rest of the ways this command cannot run.
		if errors.Is(err, migrate.ErrTarget) {
			return 2
		}
		// Whatever got applied before the failure did, and the operator needs to know how
		// much of the set is now in place.
		if len(result.Applied) > 0 || len(result.Reverted) > 0 {
			fmt.Fprintf(os.Stderr, "applied before the failure: %d; reverted: %d\n",
				len(result.Applied), len(result.Reverted))
		}
		return 1
	}

	switch {
	case len(result.Applied) > 0:
		fmt.Printf("applied %d migration(s)\n", len(result.Applied))
	case len(result.Reverted) > 0:
		fmt.Printf("reverted %d migration(s)\n", len(result.Reverted))
	default:
		fmt.Println("nothing to do")
	}
	return 0
}

// findMigrations locates the migrations directory.
//
// The default walks up from the working directory rather than hardcoding a relative path,
// because this binary is run by CI from the repository root and by an operator from wherever
// they happen to be, and a migration tool that only works from one directory is a tool that
// fails at the moment it is most needed.
func findMigrations(explicit string) (string, error) {
	if explicit != "" {
		if info, err := os.Stat(explicit); err != nil || !info.IsDir() {
			return "", fmt.Errorf("--dir %s is not a directory", explicit)
		}
		return explicit, nil
	}
	dir, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("determining the working directory: %w", err)
	}
	for {
		candidate := filepath.Join(dir, "db", "migrations")
		if info, err := os.Stat(candidate); err == nil && info.IsDir() {
			return candidate, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return "", errors.New("could not find db/migrations in this directory or any " +
				"parent; pass --dir")
		}
		dir = parent
	}
}
