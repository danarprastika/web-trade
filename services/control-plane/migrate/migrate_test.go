package migrate

import (
	"errors"
	"strings"
	"testing"
	"testing/fstest"
)

// The pure half of the runner is tested without a database, because everything here is a
// decision about which SQL to run and running the wrong SQL is the failure that matters.
// A database-backed test of this logic would prove the driver works, not that the ordering
// is right.

func fsWith(files map[string]string) fstest.MapFS {
	out := fstest.MapFS{}
	for name, body := range files {
		out[name] = &fstest.MapFile{Data: []byte(body)}
	}
	return out
}

const up1 = "CREATE TABLE a (id int PRIMARY KEY);\n"
const down1 = "DROP TABLE a;\n"

func mig(version int, up, down string) string {
	var b strings.Builder
	for i := 1; i < version; i++ {
		b.WriteString(up)
	}
	b.WriteString(up)
	if down != "" {
		b.WriteString("\n" + downMarker + "\n" + down)
	}
	return b.String()
}

// --- Ordering -----------------------------------------------------------------

// Lexical ordering puts 00010 before 0002. A runner that sorts filenames as strings will
// apply the tenth migration before the second, against a database that reached ten.
func TestVersionsOrderNumericallyNotLexically(t *testing.T) {
	set, err := Parse(fsWith(map[string]string{
		"0010_ten.sql":  mig(10, "CREATE TABLE ten (id int);\n", "DROP TABLE ten;\n"),
		"0002_two.sql":  mig(2, "CREATE TABLE two (id int);\n", "DROP TABLE two;\n"),
		"0009_nine.sql": mig(9, "CREATE TABLE nine (id int);\n", "DROP TABLE nine;\n"),
	}))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	var got []int
	for _, m := range set.Applied {
		got = append(got, m.Version)
	}
	want := []int{2, 9, 10}
	if len(got) != len(want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("expected %v, got %v", want, got)
		}
	}
}

// Two files claiming the same version means one of them silently never runs.
func TestADuplicateVersionIsRefused(t *testing.T) {
	_, err := Parse(fsWith(map[string]string{
		"0001_one.sql":  mig(1, "CREATE TABLE a (id int);\n", "DROP TABLE a;\n"),
		"0001_also.sql": mig(1, "CREATE TABLE b (id int);\n", "DROP TABLE b;\n"),
	}))
	if err == nil {
		t.Fatal("two migrations with the same version must be refused")
	}
	if !strings.Contains(err.Error(), "renumber") {
		t.Fatalf("the error should say how to fix it, got: %v", err)
	}
}

func TestAMalformedFilenameIsRefused(t *testing.T) {
	for _, name := range []string{"nodigits_name.sql", "_leading.sql", "abc_name.sql"} {
		if _, err := Parse(fsWith(map[string]string{name: up1})); err == nil {
			t.Fatalf("migration %q must be refused for lacking a numeric version prefix", name)
		}
	}
}

func TestAVersionMustBePositive(t *testing.T) {
	if _, err := Parse(fsWith(map[string]string{"0000_zero.sql": up1})); err == nil {
		t.Fatal("version 0 must be refused")
	}
}

// --- Up and down bodies -------------------------------------------------------

func TestTheDownBodyIsSeparatedByTheMarker(t *testing.T) {
	set, err := Parse(fsWith(map[string]string{
		"0001_a.sql": up1 + "\n" + downMarker + "\n" + down1,
	}))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	m := set.Applied[0]
	if !strings.Contains(m.SQL, "CREATE TABLE a") {
		t.Fatalf("the up body lost its statement: %q", m.SQL)
	}
	if strings.Contains(m.SQL, "DROP TABLE a") {
		t.Fatal("the down statement leaked into the up body")
	}
	if !strings.Contains(m.DownSQL, "DROP TABLE a") {
		t.Fatalf("the down body was not captured: %q", m.DownSQL)
	}
}

func TestAMigrationWithNoDownBodyIsMarkedIrreversible(t *testing.T) {
	set, err := Parse(fsWith(map[string]string{
		"0001_a.sql": mig(1, up1, ""),
		"0002_b.sql": mig(2, "CREATE TABLE b (id int);\n", "DROP TABLE b;\n"),
	}))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if set.Reversible {
		t.Fatal("a set containing a migration with no down body is not reversible")
	}
}

// A down body that is only a comment is not a down body. This is the case that makes a
// migration look reversible in a diff and revert nothing at runtime.
func TestACommentOnlyDownBodyDoesNotCountAsReversible(t *testing.T) {
	set, err := Parse(fsWith(map[string]string{
		"0001_a.sql": up1 + "\n" + downMarker + "\n-- nothing to do here\n",
	}))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	plan, err := set.Plan(Down, map[int]bool{1: true})
	if err == nil {
		t.Fatalf("a comment-only down body must not satisfy the down rehearsal, got plan: %s", plan.Describe())
	}
}

// --- Planning -----------------------------------------------------------------

func TestUpAppliesOnlyPendingMigrationsInOrder(t *testing.T) {
	set := mustParse(t, map[string]string{
		"0001_a.sql": mig(1, "CREATE TABLE a (id int);\n", "DROP TABLE a;\n"),
		"0002_b.sql": mig(2, "CREATE TABLE b (id int);\n", "DROP TABLE b;\n"),
		"0003_c.sql": mig(3, "CREATE TABLE c (id int);\n", "DROP TABLE c;\n"),
	})
	plan, err := set.Plan(Up, map[int]bool{1: true, 2: true})
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	if len(plan.Steps) != 1 || plan.Steps[0].Version != 3 {
		t.Fatalf("expected only migration 3, got %s", plan.Describe())
	}
}

func TestDownRevertsNewestFirst(t *testing.T) {
	set := mustParse(t, map[string]string{
		"0001_a.sql": mig(1, "CREATE TABLE a (id int);\n", "DROP TABLE a;\n"),
		"0002_b.sql": mig(2, "CREATE TABLE b (id int);\n", "DROP TABLE b;\n"),
	})
	plan, err := set.Plan(Down, map[int]bool{1: true, 2: true})
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	if len(plan.Steps) != 2 || plan.Steps[0].Version != 2 {
		t.Fatalf("down must revert newest first, got %s", plan.Describe())
	}
}

// Reverting three of four and stopping looks like success in a log while leaving the schema
// in a state no release ever planned. The whole plan is refused instead.
func TestDownIsRefusedWhenAnyStepIsIrreversible(t *testing.T) {
	set := mustParse(t, map[string]string{
		"0001_a.sql": mig(1, "CREATE TABLE a (id int);\n", "DROP TABLE a;\n"),
		"0002_b.sql": mig(2, "CREATE TABLE b (id int);\n", ""),
	})
	_, err := set.Plan(Down, map[int]bool{1: true, 2: true})
	if err == nil {
		t.Fatal("a partially reversible set must not produce a down plan")
	}
	if !strings.Contains(err.Error(), "0002_b.sql") {
		t.Fatalf("the error should name the irreversible migration, got: %v", err)
	}
}

func TestAnUpToDateDatabasePlansNothing(t *testing.T) {
	set := mustParse(t, map[string]string{"0001_a.sql": mig(1, up1, down1)})
	plan, err := set.Plan(Up, map[int]bool{1: true})
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	if len(plan.Steps) != 0 {
		t.Fatalf("expected no steps, got %s", plan.Describe())
	}
	if !strings.Contains(plan.Describe(), "nothing to apply") {
		t.Fatalf("an empty plan should say so plainly, got %q", plan.Describe())
	}
}

func TestAnUnknownDirectionIsRefused(t *testing.T) {
	set := mustParse(t, map[string]string{"0001_a.sql": mig(1, up1, down1)})
	if Direction("sideways").Valid() {
		t.Fatal("an unknown direction must not validate")
	}
	if _, err := set.Plan(Direction("sideways"), nil); err == nil {
		t.Fatal("an unknown direction must produce an error rather than an empty plan")
	}
}

// --- Drift --------------------------------------------------------------------

// Editing a migration that has already been applied leaves the database and the repository
// disagreeing about what the schema is. The only symptom otherwise is a query that should
// work and does not, weeks later.
func TestAnEditedAppliedMigrationIsDetected(t *testing.T) {
	set := mustParse(t, map[string]string{"0001_a.sql": mig(1, up1, down1)})
	original := set.Applied[0].Digest

	err := CheckDrift(set, map[int]string{1: original})
	if err != nil {
		t.Fatalf("an unedited migration must not report drift: %v", err)
	}

	// The same version, a different body.
	edited := mustParse(t, map[string]string{
		"0001_a.sql": mig(1, "CREATE TABLE a (id int, extra text);\n", down1),
	})
	err = CheckDrift(edited, map[int]string{1: original})
	if err == nil {
		t.Fatal("an edited applied migration must be reported as drift")
	}
	var drift ErrDrift
	if !errors.As(err, &drift) {
		t.Fatalf("expected an ErrDrift, got %T: %v", err, err)
	}
	if drift.Version != 1 {
		t.Fatalf("drift should name the version, got %d", drift.Version)
	}
	if !strings.Contains(err.Error(), "add a new migration") {
		t.Fatalf("the error should say what to do instead, got: %v", err)
	}
}

// A database migrated from another branch has applied a version this branch has never
// heard of. Applying on top of that would be building on an unknown state.
func TestAMigrationRecordedButAbsentIsRefused(t *testing.T) {
	set := mustParse(t, map[string]string{"0001_a.sql": mig(1, up1, down1)})
	err := CheckDrift(set, map[int]string{
		1:     set.Applied[0].Digest,
		99999: "deadbeef",
	})
	if err == nil {
		t.Fatal("a migration recorded in the database but absent from the repository must be refused")
	}
	if !strings.Contains(err.Error(), "not this one") {
		t.Fatalf("the error should explain the likely cause, got: %v", err)
	}
}

// The digest must cover only the up body. A down script gaining a comment is an ordinary
// later change, and refusing to start a database over it would make the drift check
// something people disable.
func TestEditingOnlyTheDownBodyIsNotDrift(t *testing.T) {
	before := mustParse(t, map[string]string{
		"0001_a.sql": up1 + "\n" + downMarker + "\n" + down1,
	})
	after := mustParse(t, map[string]string{
		"0001_a.sql": up1 + "\n" + downMarker + "\n" + down1 + "\n-- clarified\n",
	})
	if before.Applied[0].Digest != after.Applied[0].Digest {
		t.Fatal("the digest must cover the up body only")
	}
	if err := CheckDrift(after, map[int]string{1: before.Applied[0].Digest}); err != nil {
		t.Fatalf("a down-body edit must not be reported as drift: %v", err)
	}
}

// --- Helpers ------------------------------------------------------------------

func mustParse(t *testing.T, files map[string]string) Set {
	t.Helper()
	set, err := Parse(fsWith(files))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	return set
}
