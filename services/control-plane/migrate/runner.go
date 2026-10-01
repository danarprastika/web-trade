package migrate

import (
	"context"
	"fmt"
	"io"
)

// Runner applies a migration set against a store.
//
// The order of the checks is the design. Drift is checked before anything is planned, so an
// edited migration stops the run before it can compound; reversibility is checked by Plan
// before a single step runs, so a set that cannot be fully reverted never half-reverts; and
// the plan is computed in full before the first step executes, so a dry run and a real run
// report the same work.
type Runner struct {
	Set   Set
	Store Store
	Out   io.Writer

	// To bounds a down run to the applied migrations above this version. Zero means no bound,
	// which is the whole applied set.
	//
	// It exists because an unbounded down run on the real set drops the ledger, the audit
	// records, and every authz table CASCADE. That is the right cost for a release gate
	// rehearsing the reverse of everything, and the wrong cost for an operator who has just
	// shipped one bad migration and wants that migration back.
	To int
}

// Result is what a run did.
type Result struct {
	// Plan is what was going to be done, which is also what was done unless a step failed.
	Plan Plan
	// Applied names the migrations actually applied, in order.
	Applied []string
	// Reverted names the migrations actually reverted, in order.
	Reverted []string
}

// Run executes the plan.
//
// It stops at the first failure and says which step failed, because a migration set applied
// out of order is the failure this whole package exists to prevent. Continuing past a
// failure would apply later migrations against a schema that skipped an earlier one.
//
// The run lock is taken before the applied set is read and released after the last step, so
// the read, the plan, and the writes are one critical section. Without that, two runners read
// the same state and plan the same steps, and the loser fails partway through a set of
// non-idempotent bodies.
func (r *Runner) Run(ctx context.Context, direction Direction) (Result, error) {
	if r.Out == nil {
		r.Out = io.Discard
	}

	unlock, err := lockRun(ctx, r.Store)
	if err != nil {
		return Result{}, err
	}
	defer releaseRun(r.Out, unlock)

	appliedDigests, err := r.Store.Applied(ctx)
	if err != nil {
		return Result{}, err
	}

	if err := CheckDrift(r.Set, appliedDigests); err != nil {
		return Result{}, err
	}

	appliedVersions := make(map[int]bool, len(appliedDigests))
	for v := range appliedDigests {
		appliedVersions[v] = true
	}

	plan, err := r.Set.Plan(direction, appliedVersions, DownTo(r.To))
	if err != nil {
		return Result{}, err
	}

	fmt.Fprintln(r.Out, plan.Describe())
	result := Result{Plan: plan}

	for _, m := range plan.Steps {
		switch direction {
		case Down:
			if err := r.revert(ctx, m); err != nil {
				return result, err
			}
			result.Reverted = append(result.Reverted, m.Name)
		default:
			if err := r.apply(ctx, m); err != nil {
				return result, err
			}
			result.Applied = append(result.Applied, m.Name)
		}
	}
	return result, nil
}

func (r *Runner) apply(ctx context.Context, m Migration) error {
	exec, ok := r.Store.(interface {
		Exec(context.Context, Migration, string) error
	})
	if !ok {
		return fmt.Errorf("%w: the store cannot execute a migration body", ErrStore)
	}
	return exec.Exec(ctx, m, m.SQL)
}

func (r *Runner) revert(ctx context.Context, m Migration) error {
	undo, ok := r.Store.(interface {
		Undo(context.Context, Migration) error
	})
	if !ok {
		return fmt.Errorf("%w: the store cannot revert a migration", ErrStore)
	}
	return undo.Undo(ctx, m)
}

// lockRun takes the store's run lock if it offers one, and returns the function that releases
// it.
//
// A store without the capability yields a nil release and no error. That is the pure stores
// this package tests its planning against: they hold a Go mutex or no lock at all, and refusing
// to run against them would make the ordering untestable without a database.
func lockRun(ctx context.Context, store Store) (func(context.Context) error, error) {
	locker, ok := store.(interface {
		LockRun(context.Context) (RunLock, error)
	})
	if !ok {
		return nil, nil
	}
	lock, err := locker.LockRun(ctx)
	if err != nil {
		return nil, err
	}
	return lock.Unlock, nil
}

// releaseRun releases the lock, if one was taken.
//
// Deferred by Run, which is what makes a panicking migration body safe: a deferred call runs
// while the panic is still unwinding, so a migration that panics releases the lock instead of
// wedging every later run behind a session nobody will ever close.
//
// The release gets a context detached from the run's own. The common reasons to be here are a
// failed run and a timed-out run, and in both the run's context is already cancelled -- which
// would cancel the unlock and leave the lock held. The remaining failure mode is a release
// that cannot complete at all, which is why it is bounded.
//
// A failed release is reported on the output stream rather than returned. By the time it runs
// the run's own result is decided, and turning a successful run into a failed one because the
// lock could not be handed back cleanly would misreport the database's state. The store's own
// failure path already drops the connection, which returns the lock with the session.
func releaseRun(out io.Writer, unlock func(context.Context) error) {
	if unlock == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.WithoutCancel(context.Background()), unlockTimeout)
	defer cancel()
	if err := unlock(ctx); err != nil {
		fmt.Fprintf(out, "warning: %v\n", err)
	}
}

// Describe renders the applied set for a human.
func DescribeApplied(digests map[int]string) string {
	if len(digests) == 0 {
		return "no migrations applied"
	}
	out := fmt.Sprintf("%d migration(s) applied:\n", len(digests))
	for _, v := range sortedVersions(digests) {
		out += fmt.Sprintf("  %06d  %s\n", v, digests[v][:min(12, len(digests[v]))])
	}
	return out
}

func sortedVersions(digests map[int]string) []int {
	versions := make([]int, 0, len(digests))
	for v := range digests {
		versions = append(versions, v)
	}
	for i := 1; i < len(versions); i++ {
		for j := i; j > 0 && versions[j] < versions[j-1]; j-- {
			versions[j], versions[j-1] = versions[j-1], versions[j]
		}
	}
	return versions
}
