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
func (r *Runner) Run(ctx context.Context, direction Direction) (Result, error) {
	if r.Out == nil {
		r.Out = io.Discard
	}

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

	plan, err := r.Set.Plan(direction, appliedVersions)
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
