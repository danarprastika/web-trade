package migrate

import (
	"errors"
	"fmt"
	"slices"
	"strings"
	"testing"
)

// The unbounded down plan is the release gate's rehearsal and must keep meaning what it meant
// before --to existed. An operator who never passes a bound has to get the same run they got
// last time, or the change is not backwards compatible in the only sense that matters.
func TestDownWithoutABoundStillRevertsTheWholeAppliedSet(t *testing.T) {
	set := fiveMigrations(t)
	plan, err := set.Plan(Down, map[int]bool{1: true, 2: true, 3: true, 4: true, 5: true})
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	if got := versionsOf(plan); !slices.Equal(got, []int{5, 4, 3, 2, 1}) {
		t.Fatalf("the default down plan must still be the whole applied set, got %v", got)
	}
}

// The bounded form reverts a suffix of the applied set and stops. Getting this wrong in the
// permissive direction is the failure that motivates the whole flag: reverting everything when
// the operator asked for one migration drops the ledger and the audit tables CASCADE.
func TestDownToBoundsTheRevertToTheSuffixAboveTheTarget(t *testing.T) {
	set := fiveMigrations(t)
	applied := map[int]bool{1: true, 2: true, 3: true, 4: true, 5: true}

	plan, err := set.Plan(Down, applied, DownTo(3))
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	if got := versionsOf(plan); !slices.Equal(got, []int{5, 4}) {
		t.Fatalf("-to 3 should revert 5 and 4 only, got %v", got)
	}
}

// The bound is a floor, not a starting point: the migrations at and below it stay applied and
// must not appear in the plan in either order.
func TestDownToLeavesEverythingAtOrBelowTheTargetAlone(t *testing.T) {
	set := fiveMigrations(t)
	applied := map[int]bool{1: true, 2: true, 3: true, 4: true, 5: true}

	plan, err := set.Plan(Down, applied, DownTo(2))
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	for _, v := range versionsOf(plan) {
		if v <= 2 {
			t.Fatalf("migration %d is at or below the target and must not be planned: %v",
				v, versionsOf(plan))
		}
	}
	if got := versionsOf(plan); !slices.Equal(got, []int{5, 4, 3}) {
		t.Fatalf("-to 2 should revert 5, 4 and 3, got %v", got)
	}
}

// Reverting to the newest applied version has nothing to do. That is an empty plan, not an
// error: the database is already at the state the operator asked for.
func TestDownToTheNewestAppliedVersionPlansNothing(t *testing.T) {
	set := fiveMigrations(t)
	plan, err := set.Plan(Down, map[int]bool{1: true, 2: true, 3: true}, DownTo(3))
	if err != nil {
		t.Fatalf("Plan: %v", err)
	}
	if len(plan.Steps) != 0 {
		t.Fatalf("expected no steps, got %s", plan.Describe())
	}
	if !strings.Contains(plan.Describe(), "nothing to revert") {
		t.Fatalf("an empty bounded plan should say so plainly, got %q", plan.Describe())
	}
}

// A target the repository has never heard of is a typo or a version from another branch.
// Rounding it to the nearest version that exists would revert a different number of
// migrations than the operator typed, so it is refused.
func TestDownToAVersionTheRepositoryDoesNotHaveIsRefused(t *testing.T) {
	set := fiveMigrations(t)
	_, err := set.Plan(Down, map[int]bool{1: true, 2: true, 3: true}, DownTo(9999))
	if err == nil {
		t.Fatal("a target that names no migration must be refused, not rounded to a nearby version")
	}
	if !errors.Is(err, ErrTarget) {
		t.Fatalf("expected ErrTarget so the command can exit 2, got %T: %v", err, err)
	}
	if !strings.Contains(err.Error(), "009999") {
		t.Fatalf("the error must name the version that was refused, got: %v", err)
	}
}

// A version the repository has but the database has not applied cannot be reverted to: it is
// already gone, or was never there. Silently ignoring it would revert more than was asked
// for, which is the outcome a rollback must never produce.
func TestDownToAVersionThatIsNotAppliedIsRefused(t *testing.T) {
	set := fiveMigrations(t)
	// 4 was reverted in an earlier run, so the database sits at {1, 2, 3} while the repository
	// still carries 4 and 5.
	_, err := set.Plan(Down, map[int]bool{1: true, 2: true, 3: true}, DownTo(4))
	if err == nil {
		t.Fatal("a target outside the applied set must be refused, not silently ignored")
	}
	if !errors.Is(err, ErrTarget) {
		t.Fatalf("expected ErrTarget, got %T: %v", err, err)
	}
	if !strings.Contains(err.Error(), "000004") {
		t.Fatalf("the error must name the version that was refused, got: %v", err)
	}
}

// A bound on an up or status run has no meaning, and silently ignoring it would leave the
// operator believing they had bounded something.
func TestABoundIsRefusedOnADirectionThatCannotUseIt(t *testing.T) {
	set := fiveMigrations(t)
	for _, d := range []Direction{Up, Status} {
		if _, err := set.Plan(d, map[int]bool{}, DownTo(2)); !errors.Is(err, ErrTarget) {
			t.Fatalf("%s with a bound must be refused with ErrTarget, got: %v", d, err)
		}
	}
}

// The bound does not excuse irreversibility. A bounded revert still refuses a suffix that
// contains a migration with no down body, because that suffix could not be fully undone.
func TestABoundedRevertIsStillRefusedWhenItsSuffixIsIrreversible(t *testing.T) {
	set := mustParse(t, map[string]string{
		"0001_a.sql": mig(1, up1, down1),
		"0002_b.sql": mig(2, "CREATE TABLE b (id int);\n", ""),
	})
	applied := map[int]bool{1: true, 2: true}

	if _, err := set.Plan(Down, applied, DownTo(1)); err == nil {
		t.Fatal("a bounded revert whose step has no down body must be refused")
	}
	// Bounded the other way, the irreversible migration is out of the plan entirely and the
	// run is legitimate: nothing below the target is being touched.
	if _, err := set.Plan(Down, map[int]bool{1: true}, DownTo(1)); err != nil {
		t.Fatalf("a revert that leaves the irreversible migration applied must be allowed: %v", err)
	}
}

// Version zero is the absence of a bound, because versions start at one. A caller that passes
// the zero value must get the whole applied set rather than "revert everything", which is the
// opposite of what a zero target would mean if it were taken literally.
func TestANonPositiveTargetMeansNoBound(t *testing.T) {
	set := fiveMigrations(t)
	applied := map[int]bool{1: true, 2: true, 3: true}

	for _, v := range []int{0, -1} {
		plan, err := set.Plan(Down, applied, DownTo(v))
		if err != nil {
			t.Fatalf("DownTo(%d): %v", v, err)
		}
		if got := versionsOf(plan); !slices.Equal(got, []int{3, 2, 1}) {
			t.Fatalf("DownTo(%d) must mean no bound, got %v", v, got)
		}
	}
}

// fiveMigrations is the smallest set long enough for a bound to be a suffix rather than the
// whole set.
func fiveMigrations(t *testing.T) Set {
	files := map[string]string{}
	for v := 1; v <= 5; v++ {
		name := fmt.Sprintf("%04d_t%d.sql", v, v)
		files[name] = mig(v,
			"CREATE TABLE "+name+" (id int PRIMARY KEY);\n",
			"DROP TABLE "+name+";\n")
	}
	return mustParse(t, files)
}

// versionsOf renders a plan's steps as versions, so a failed assertion can name the versions
// that were planned rather than only their count.
func versionsOf(p Plan) []int {
	out := make([]int, 0, len(p.Steps))
	for _, m := range p.Steps {
		out = append(out, m.Version)
	}
	return out
}
