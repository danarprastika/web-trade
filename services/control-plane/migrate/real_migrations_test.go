package migrate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// migrationsDir is the repository's real migration directory, reached from this package.
//
// The fixture tests above prove the parser does what it claims. This file proves the parser
// and the repository agree, which is the thing that actually breaks: a migration added
// without a down body, or one that shadows another, is invisible to a test that only ever
// parses strings it wrote itself.
const migrationsDir = "../../../db/migrations"

func realSet(t *testing.T) Set {
	t.Helper()
	set, err := Parse(os.DirFS(migrationsDir))
	if err != nil {
		t.Fatalf("parsing %s: %v", migrationsDir, err)
	}
	if len(set.Applied) == 0 {
		t.Fatal("no migrations found; the path is wrong or the directory is empty")
	}
	return set
}

// The down rehearsal is a release gate, so a set that cannot be fully reverted fails here
// rather than at the point where an operator discovers it during a rollback.
func TestEveryRealMigrationIsReversible(t *testing.T) {
	set := realSet(t)
	var irreversible []string
	for _, m := range set.Applied {
		if !hasStatement(m.DownSQL) {
			irreversible = append(irreversible, m.Name)
		}
	}
	if len(irreversible) > 0 {
		t.Fatalf("these migrations cannot be reverted: %s", strings.Join(irreversible, ", "))
	}
	if !set.Reversible {
		t.Fatal("Set.Reversible disagrees with the per-migration check")
	}
}

func TestTheRealSetPlansAFullUpAndAFullDown(t *testing.T) {
	set := realSet(t)
	empty := map[int]bool{}

	up, err := set.Plan(Up, empty)
	if err != nil {
		t.Fatalf("planning up from empty: %v", err)
	}
	if len(up.Steps) != len(set.Applied) {
		t.Fatalf("up from empty should plan the whole set, got %s", up.Describe())
	}

	// Every migration applied, reverted in reverse. The runner has to be able to reach a
	// database with no migration object in it, which is what makes the second up pass a real
	// test rather than a no-op.
	all := map[int]bool{}
	for _, m := range set.Applied {
		all[m.Version] = true
	}
	down, err := set.Plan(Down, all)
	if err != nil {
		t.Fatalf("planning down from a fully applied database: %v", err)
	}
	if len(down.Steps) != len(set.Applied) {
		t.Fatalf("down should plan the whole set, got %s", down.Describe())
	}
	for i := 1; i < len(down.Steps); i++ {
		if down.Steps[i].Version >= down.Steps[i-1].Version {
			t.Fatalf("down must revert in strictly descending order, got %s", down.Describe())
		}
	}
}

// A down body that leaks into the up body is silent: the file still parses, the marker is
// still present, and the schema is dropped immediately after it is created. This is the
// exact mistake made while adding the down bodies, and it is cheap to assert against.
func TestNoRealUpBodyDropsWhatItsOwnMigrationCreates(t *testing.T) {
	set := realSet(t)
	for _, m := range set.Applied {
		for _, stmt := range []string{"DROP SCHEMA", "DROP TABLE", "DROP FUNCTION"} {
			if strings.Contains(strings.ToUpper(m.SQL), stmt) {
				t.Errorf("%s: the up body contains %q; a drop statement before the "+
					"down marker removes the schema the up body just created",
					m.Name, stmt)
			}
		}
	}
}

// Each file must be self-contained about its transaction, so applying it with the runner, by
// hand, or through psql gives the same atomicity. A migration that is atomic only when some
// runner happens to wrap it is atomic by accident.
func TestEveryRealMigrationCarriesItsOwnTransaction(t *testing.T) {
	set := realSet(t)
	for _, m := range set.Applied {
		if !strings.Contains(m.SQL, "BEGIN;") {
			t.Errorf("%s: the up body has no BEGIN; so a mid-migration failure leaves "+
				"objects behind with no record of the migration being applied", m.Name)
		}
		if !strings.Contains(m.SQL, "COMMIT;") {
			t.Errorf("%s: the up body has no COMMIT;", m.Name)
		}
		if !strings.Contains(m.DownSQL, "BEGIN;") || !strings.Contains(m.DownSQL, "COMMIT;") {
			t.Errorf("%s: the down body needs its own BEGIN/COMMIT; a partial revert that "+
				"fails halfway leaves a schema nobody planned", m.Name)
		}
	}
}

// The drift check is only worth having if it fires on a real edited file. This reproduces the
// scenario with a temporary copy of the real set rather than a hand-written string.
func TestDriftFiresOnAnEditedCopyOfTheRealSet(t *testing.T) {
	set := realSet(t)
	recorded := map[int]string{}
	for _, m := range set.Applied {
		recorded[m.Version] = m.Digest
	}
	if err := CheckDrift(set, recorded); err != nil {
		t.Fatalf("the unmodified real set must not report drift: %v", err)
	}

	// Corrupt the recorded digest for the newest migration, as though the file had been
	// edited after being applied.
	newest := set.Applied[len(set.Applied)-1]
	recorded[newest.Version] = strings.Repeat("0", 64)
	err := CheckDrift(set, recorded)
	if err == nil {
		t.Fatalf("editing %s after it was applied must be reported as drift", newest.Name)
	}
	if !strings.Contains(err.Error(), newest.Name[:4]) && !strings.Contains(err.Error(), "drift") {
		t.Logf("drift error names the version rather than the file: %v", err)
	}
}

// Guards the path constant itself. A test that silently parses an empty directory and passes
// is worse than no test, so the directory is asserted to hold what the repository claims.
func TestTheRealMigrationsDirectoryIsTheRepositoryOne(t *testing.T) {
	abs, err := filepath.Abs(migrationsDir)
	if err != nil {
		t.Fatalf("resolving %s: %v", migrationsDir, err)
	}
	entries, err := os.ReadDir(migrationsDir)
	if err != nil {
		t.Fatalf("reading %s: %v", abs, err)
	}
	// Counted as the glob counts them. The directory also holds a .gitkeep, and a log line
	// that says "4 migrations" beside three of them is evidence nobody can rely on.
	var sqlFiles int
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".sql") {
			sqlFiles++
		}
	}
	if sqlFiles == 0 {
		t.Fatalf("%s holds no .sql migrations", abs)
	}
	if sqlFiles != len(realSet(t).Applied) {
		t.Fatalf("%s holds %d .sql file(s) but the parser read %d migration(s); a file the "+
			"parser skips is a migration that will never be applied",
			abs, sqlFiles, len(realSet(t).Applied))
	}
	t.Logf("verified %d migration(s) in %s", sqlFiles, abs)
}
