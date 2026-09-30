// Command migrate applies the repository's migrations to PostgreSQL in either direction.
//
// This is the command .github/workflows/ci.yml runs as the migration rehearsal gate, and the
// command an operator runs to revert. It is deliberately thin: the ordering, the drift check,
// and the reversibility rules live in the migrate package, where they are tested without a
// database, and this file only wires flags to them.
//
// Exit codes:
//
//	0  the requested direction completed, or a dry run found nothing to refuse
//	1  the run failed, or the database disagrees with the repository
//	2  the command could not run (no DATABASE_URL, missing migrations, database unreachable)
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/danarprastika/web-trade/services/control-plane/migrate"
	"github.com/jackc/pgx/v5/pgxpool"
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
	flag.Parse()

	parsed := migrate.Direction(*direction)
	if !parsed.Valid() {
		fmt.Fprintf(os.Stderr, "unknown direction %q; use up, down, or status\n", *direction)
		return 2
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

	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		fmt.Fprintf(os.Stderr, "connecting to the database: %v\n", err)
		return 2
	}
	defer pool.Close()

	store := migrate.NewPgStore(pool)
	if err := store.Ensure(ctx); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}

	runner := &migrate.Runner{Set: set, Store: store, Out: os.Stdout}

	if parsed == migrate.Status {
		applied, err := store.Applied(ctx)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		fmt.Print(migrate.DescribeApplied(applied))
		return 0
	}

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
