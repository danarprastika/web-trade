package migrate

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
)

// The lock contract is tested against a fake that counts, because what can go wrong here is
// entirely about ordering -- the lock is taken before the plan is read and released after the
// last step -- and ordering is exactly what a real advisory lock cannot demonstrate without a
// second process to observe. The live tests in live_test.go then prove the same sequence
// against PostgreSQL itself.

// lockedStore is a Store that offers a run lock and records when it is held.
type lockedStore struct {
	applied map[int]string
	execErr error
	onExec  func()

	mu       sync.Mutex
	takes    int
	releases int
	held     bool
}

func (s *lockedStore) Ensure(context.Context) error { return nil }

// Applied honours a dead context the way a real query does, so the cancelled-context test
// exercises a run that genuinely failed rather than one that sailed past a cancelled context.
func (s *lockedStore) Applied(ctx context.Context) (map[int]string, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return s.applied, nil
}

func (s *lockedStore) Record(context.Context, Migration) error { return nil }
func (s *lockedStore) Forget(context.Context, Migration) error { return nil }

func (s *lockedStore) LockRun(context.Context) (RunLock, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.takes++
	s.held = true
	return fakeRunLock{s}, nil
}

func (s *lockedStore) Exec(context.Context, Migration, string) error {
	if s.onExec != nil {
		s.onExec()
	}
	return s.execErr
}

func (s *lockedStore) Undo(context.Context, Migration) error { return nil }

func (s *lockedStore) state() (takes, releases int, held bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.takes, s.releases, s.held
}

// fakeRunLock releases by telling the store it was released.
type fakeRunLock struct{ s *lockedStore }

func (l fakeRunLock) Unlock(context.Context) error {
	l.s.mu.Lock()
	defer l.s.mu.Unlock()
	l.s.releases++
	l.s.held = false
	return nil
}

// unlockedStore is the same store with the capability removed, which is what every store in the
// pure half of this package looks like.
type unlockedStore struct{ *lockedStore }

// The lock must be held while a migration body runs, and released once. Taking it after the
// applied set is read, or releasing it before the last step, leaves exactly the window this
// lock exists to close.
func TestTheRunLockIsHeldWhileEveryStepExecutes(t *testing.T) {
	store := &lockedStore{}
	var heldDuring []bool
	store.onExec = func() {
		_, _, held := store.state()
		heldDuring = append(heldDuring, held)
	}

	r := &Runner{
		Set:   fiveMigrations(t),
		Store: store,
		Out:   io.Discard,
	}
	if _, err := r.Run(context.Background(), Up); err != nil {
		t.Fatalf("Run: %v", err)
	}

	takes, releases, held := store.state()
	if takes != 1 {
		t.Fatalf("the run must take the lock exactly once, took %d", takes)
	}
	if releases != 1 {
		t.Fatalf("the run must release the lock exactly once, released %d", releases)
	}
	if held {
		t.Fatal("the lock is still held after the run returned")
	}
	if len(heldDuring) != len(r.Set.Applied) {
		t.Fatalf("expected %d executions, saw %d", len(r.Set.Applied), len(heldDuring))
	}
	for i, held := range heldDuring {
		if !held {
			t.Fatalf("migration %d executed with no lock held", i+1)
		}
	}
}

// A failing run releases the lock, or the one failure is followed by a database where every
// later run waits until it times out.
func TestTheRunLockIsReleasedWhenAStepFails(t *testing.T) {
	store := &lockedStore{execErr: errors.New("the body failed")}
	r := &Runner{Set: fiveMigrations(t), Store: store, Out: io.Discard}

	if _, err := r.Run(context.Background(), Up); err == nil {
		t.Fatal("a failing step must be reported")
	}
	if _, releases, held := store.state(); releases != 1 || held {
		t.Fatalf("a failed run must release the lock; releases=%d held=%v", releases, held)
	}
}

// A migration body that panics must release the lock too. This is the case a plain defer is
// easy to get wrong: recovering above the run, or releasing on the error return only, would
// leave a session holding the lock that nothing will ever close, and every future migration
// run would block on it forever.
func TestAPanickingMigrationBodyStillReleasesTheRunLock(t *testing.T) {
	store := &lockedStore{}
	store.onExec = func() { panic("the body panicked") }
	r := &Runner{Set: fiveMigrations(t), Store: store, Out: io.Discard}

	mustPanic(t, "Run with a panicking body", func() {
		_, _ = r.Run(context.Background(), Up)
	})

	if _, releases, held := store.state(); releases != 1 || held {
		t.Fatalf("a panicking run must release the lock; releases=%d held=%v", releases, held)
	}
}

// The lock is released even when the run's own context is dead, which is the state the unlock
// is most likely to be in: a run that timed out is exactly the run whose lock must not be
// left behind.
func TestTheRunLockIsReleasedWhenTheRunsContextIsAlreadyCancelled(t *testing.T) {
	store := &lockedStore{}
	r := &Runner{Set: fiveMigrations(t), Store: store, Out: io.Discard}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := r.Run(ctx, Up); err == nil {
		t.Fatal("a cancelled run must not report success")
	}

	if _, releases, held := store.state(); releases != 1 || held {
		t.Fatalf("a cancelled run must release the lock; releases=%d held=%v", releases, held)
	}
}

// A store with no run lock still runs. The capability is discovered by type assertion for the
// same reason Exec and Undo are: the pure stores this package plans against hold no
// PostgreSQL lock, and refusing to run against them would make the ordering untestable.
func TestAStoreWithoutTheRunLockIsStillRunnable(t *testing.T) {
	store := &unlockedStore{&lockedStore{}}
	r := &Runner{Set: fiveMigrations(t), Store: store, Out: io.Discard}

	result, err := r.Run(context.Background(), Up)
	if err != nil {
		t.Fatalf("a store with no run lock must still run: %v", err)
	}
	if len(result.Applied) != len(r.Set.Applied) {
		t.Fatalf("expected %d applied, got %d", len(r.Set.Applied), len(result.Applied))
	}
}

// A release that fails is reported rather than swallowed. It is not returned as a run failure
// because by then the run's result is decided, but an operator who cannot see that the lock
// was not handed back cleanly has no way to know the next run might block.
func TestAFailedLockReleaseIsReportedOnTheOutput(t *testing.T) {
	store := &failingReleaseStore{lockedStore: &lockedStore{}}
	var out strings.Builder
	r := &Runner{Set: fiveMigrations(t), Store: store, Out: &out}

	result, err := r.Run(context.Background(), Up)
	if err != nil {
		t.Fatalf("a failed release must not turn a successful run into a failed one: %v", err)
	}
	if len(result.Applied) == 0 {
		t.Fatal("the run should still have applied the set")
	}
	if !strings.Contains(out.String(), "warning") {
		t.Fatalf("a failed release must be reported, got %q", out.String())
	}
}

// failingReleaseStore releases badly, the way a broken connection would.
type failingReleaseStore struct{ *lockedStore }

func (s *failingReleaseStore) LockRun(ctx context.Context) (RunLock, error) {
	if _, err := s.lockedStore.LockRun(ctx); err != nil {
		return nil, err
	}
	return failingReleaseLock{s.lockedStore}, nil
}

type failingReleaseLock struct{ s *lockedStore }

func (l failingReleaseLock) Unlock(context.Context) error {
	l.s.mu.Lock()
	defer l.s.mu.Unlock()
	l.s.releases++
	return fmt.Errorf("%w: releasing the migration lock: simulated", ErrStore)
}

// The read-only report must issue nothing that writes. This is asserted against the statements
// themselves rather than against a run's behaviour, so it still holds on a database where a
// status run would fail: the read-only path has exactly two statements and neither of them may
// be DDL or a write, because the direction is documented as changing nothing.
func TestTheReadOnlyReportIssuesNothingThatWrites(t *testing.T) {
	for name, stmt := range map[string]string{
		"applied-set existence probe": appliedSetExistsSQL,
		"applied-set read":            selectAppliedSQL,
	} {
		upper := strings.ToUpper(stmt)
		for _, verb := range []string{
			"CREATE ", "ALTER ", "DROP ", "TRUNCATE", "GRANT ", "REVOKE ",
			"INSERT ", "UPDATE ", "DELETE ", "MERGE ",
		} {
			if strings.Contains(upper, verb) {
				t.Errorf("the status path's %s issues %q; -direction status is read-only:\n%s",
					name, strings.TrimSpace(verb), stmt)
			}
		}
	}
}

// mustPanic runs f and fails the test if it returns normally.
//
// The recover has to be here rather than inside the code under test: the point of the test is
// that the panic escapes Run and the lock is released on the way out, so swallowing it would
// assert nothing.
func mustPanic(t *testing.T, what string, f func()) {
	t.Helper()
	defer func() {
		if recover() == nil {
			t.Errorf("%s returned normally; the release on the panic path was not exercised", what)
		}
	}()
	f()
}
