package main

import (
	"os"
	"strings"
	"testing"
)

// `-direction down` with no -to reverts the whole applied set, and 0002_audit.sql's down body is
// `DROP TABLE IF EXISTS audit_records CASCADE` followed by the rest of the audit schema. That is
// the tamper-evident chain the platform's compliance story rests on, destroyed by one flag against
// whatever DATABASE_URL is exported.
//
// The guard that prevents it used to exist only in
// services/control-plane/integration/harness_test.go, a test file this command never executes. A
// protection present in the repository and absent from the product is not a protection, and the
// harness guard could not have helped here: it was the same defect one layer out.
//
// These tests drive the real command, through the same re-execution harness the rest of this file
// uses, so the thing being tested is the binary an operator runs rather than a function with the
// flags stubbed out. The DSNs name deliberately unreachable hosts: the guard is required to refuse
// *before* it connects, and an unreachable host is what makes that observable - a guard that
// connected first would report a connection failure instead, and the two are trivially
// distinguishable in the output.

// productionDSN names a remote database whose name announces nothing disposable. Nothing connects
// to it: the guard must refuse before any connection is attempted.
const productionDSN = "postgres://webtrade:hunter2@db.internal.invalid:5432/webtrade"

// disposableDSN-shaped target that is loopback and disposable-looking but not listening, so a
// permitted run fails at the connection rather than anywhere earlier.
const localDisposableDSN = "postgres://webtrade:hunter2@127.0.0.1:1/webtrade_test"

const optInEnv = "MIGRATE_ALLOW_DESTRUCTIVE"

const refusalMarker = "refusing to run a destructive migration"

// The core property. The unbounded revert is refused against a production target, the refusal
// names the database, and it never reaches a connection attempt.
func TestAnUnboundedRevertAgainstAProductionDatabaseIsRefused(t *testing.T) {
	got := runCLI(t,
		// The opt-in is deliberately absent here and set in the next test, so the two halves of
		// the strict policy are proved separately rather than assumed together.
		[]string{"DATABASE_URL=" + productionDSN},
		"-direction", "down", "-timeout", "10s")

	if got.code != 2 {
		t.Fatalf("exit code %d, expected 2: a refused destructive run is a way the command cannot "+
			"run, not a run that failed. stdout: %s stderr: %s", got.code, got.stdout, got.stderr)
	}
	if !strings.Contains(got.stderr, refusalMarker) {
		t.Fatalf("the command did not refuse: %s", got.stderr)
	}
	if !strings.Contains(got.stderr, "webtrade") || !strings.Contains(got.stderr, "db.internal.invalid") {
		t.Errorf("the refusal must name the database it protected: %s", got.stderr)
	}
	if strings.Contains(got.stderr, "hunter2") {
		t.Errorf("the refusal leaked the password into the log: %s", got.stderr)
	}
	// A connection attempt is distinguishable from a refusal: this one says the server is
	// unreachable, the other never gets that far.
	if strings.Contains(got.stderr, "connecting to the database") {
		t.Errorf("the guard ran after the connection was opened, so the database was contacted "+
			"before anything decided whether it could be destroyed: %s", got.stderr)
	}
}

// The strict policy's whole point: the opt-in alone is not permission. This is the case that
// separates cmd/migrate's rule from the integration harness's, and it is the one that would
// destroy a production audit schema from a single deliberate act.
func TestTheOptInAloneDoesNotAuthoriseAnUnboundedRevert(t *testing.T) {
	got := runCLI(t,
		[]string{"DATABASE_URL=" + productionDSN, optInEnv + "=1"},
		"-direction", "down", "-timeout", "10s")

	if got.code != 2 {
		t.Fatalf("exit code %d, expected 2: %s=1 must not by itself authorise dropping a "+
			"production database. stderr: %s", got.code, optInEnv, got.stderr)
	}
	if !strings.Contains(got.stderr, refusalMarker) {
		t.Fatalf("the command did not refuse even with the opt-in set: %s", got.stderr)
	}
	if !strings.Contains(got.stderr, "not sufficient") {
		t.Errorf("the refusal must say the opt-in is not sufficient on its own, or it reads as a "+
			"missing step rather than as the policy: %s", got.stderr)
	}
}

// A local disposable target with the opt-in is permitted, and says so. Without this the guard
// could pass every test above by refusing everything, which is the other way a safety check lies.
func TestALocalDisposableTargetWithTheOptInIsPermitted(t *testing.T) {
	got := runCLI(t,
		[]string{"DATABASE_URL=" + localDisposableDSN, optInEnv + "=1"},
		"-direction", "down", "-timeout", "10s")

	if strings.Contains(got.stderr, refusalMarker) {
		t.Fatalf("a local disposable target with the opt-in was refused: %s", got.stderr)
	}
	if !strings.Contains(got.stderr, "destructive migration permitted") {
		t.Fatalf("a permitted destructive run must announce itself, so the record shows it was "+
			"not the default-safe case: %s", got.stderr)
	}
	// Nothing is listening on port 1, so the run then fails to connect. That is the point: it
	// proves the guard let the run past and the connection is a separate, later step.
	if !strings.Contains(got.stderr, "connecting to the database") {
		t.Errorf("after the guard permits, the command should reach the connection; got: %s", got.stderr)
	}
}

// A local disposable target with no opt-in is still refused, because cmd/migrate always requires
// it. This is what separates the shipped policy from the harness's, and it is the reason the
// policy is a struct rather than a constant.
func TestALocalDisposableTargetStillNeedsTheOptIn(t *testing.T) {
	got := runCLI(t,
		[]string{"DATABASE_URL=" + localDisposableDSN},
		"-direction", "down", "-timeout", "10s")

	if !strings.Contains(got.stderr, refusalMarker) {
		t.Fatalf("a local disposable target with no opt-in was not refused: %s", got.stderr)
	}
	if !strings.Contains(got.stderr, optInEnv) {
		t.Errorf("the refusal must name the variable that would allow this target: %s", got.stderr)
	}
}

// The guard must not over-block. `up` and `status` are how a database is first reached, and
// requiring an opt-in to create or inspect one would make the tool unusable for its normal job.
func TestTheGuardDoesNotApplyToUpOrStatus(t *testing.T) {
	for _, direction := range []string{"up", "status"} {
		t.Run(direction, func(t *testing.T) {
			got := runCLI(t,
				[]string{"DATABASE_URL=" + productionDSN},
				"-direction", direction, "-timeout", "10s")
			if strings.Contains(got.stderr, refusalMarker) {
				t.Fatalf("-direction %s must not be guarded as destructive: %s", direction, got.stderr)
			}
		})
	}
}

// A bounded revert is guarded too, and this test is the one that establishes why.
//
// An earlier version of this file asserted the opposite - that a bounded revert must NOT be
// guarded - and cited the same reasoning the command's comment used: that `-to <version>`
// "reverts above a bound and does not take the ledger or the audit schema with it". That
// sentence was false, and the asymmetry built on it was a hole straight through the guard.
//
// `migrate.DownTo` reverts the applied migrations *above* the bound, newest first. On the real
// set that is 0001_ledger, 0002_audit, 0003_authz, 0004_model_registry, so `-to 1` plans
// versions 4, 3, 2 - and 0002_audit.sql's down body is
// `DROP TABLE IF EXISTS audit_records CASCADE`, `audit_checkpoints`, and
// `audit_deletion_events`. The bound below 0002 does not spare the audit schema; it is the one
// case that destroys it while looking bounded. An unbounded down destroys exactly the same
// tables. The bound chooses how much is reverted. It has no bearing on whether a destructive
// down body runs, so it cannot be the thing that decides whether the guard applies.
//
// `-to 1` is used here rather than a bound that would have been harmless, because a test that
// only exercised `-to 4` would pass under both the correct rule and the wrong one.
func TestABoundedRevertIsGuardedToo(t *testing.T) {
	got := runCLI(t,
		[]string{"DATABASE_URL=" + productionDSN},
		"-direction", "down", "-to", "1", "-timeout", "10s")

	if !strings.Contains(got.stderr, refusalMarker) {
		t.Fatalf("a bounded revert to version 1 reverts 0002_audit.sql, whose down body drops "+
			"audit_records, so it must be refused the same way an unbounded revert is: %s", got.stderr)
	}
	if !strings.Contains(got.stderr, optInEnv) {
		t.Errorf("the refusal must name the variable that would allow this target: %s", got.stderr)
	}
}

// The F6 shape, asserted directly. The guard can be perfect in the migrate package and worth
// nothing if the command stops consulting it, and the only evidence that catches that is a test
// that reads the command. This is deliberately a source check rather than a behaviour one, and the
// division of labour is deliberate:
//
//   - This test owns "the call is still here". Every behavioural test in this file would stay green
//     if the guard were deleted outright, because each refusal test then sees a connection failure
//     and every other test sees the same - all of them exit 2, which is what the refusal tests
//     assert. A deleted guard and a working guard are indistinguishable through the exit code.
//
//   - The behavioural tests own the ordering, that is, that the guard runs before the connection.
//     TestAnUnboundedRevertAgainstAProductionDatabaseIsRefused asserts stderr contains no
//     "connecting to the database", which a source check cannot honestly establish: it was tried,
//     and matching a string's position in a file only proves where a name appears, not whether
//     anything is executed first. An earlier version of this test made that ordering claim and a
//     mutation gate proved it false - inserting a second, redundant guard evaluation after
//     sql.Open satisfied a first-occurrence index check while changing no behaviour whatsoever.
func TestTheCommandActuallyConsultsTheDestructiveGuard(t *testing.T) {
	source, err := os.ReadFile("main.go")
	if err != nil {
		t.Fatalf("reading main.go: %v", err)
	}
	text := string(source)

	for _, needle := range []string{
		"migrate.CommandOptInPolicy()",
		"migrate.EvaluateDestructiveTarget(",
		"parsed == migrate.Down",
	} {
		if !strings.Contains(text, needle) {
			t.Errorf("main.go no longer contains %q, so the command may no longer consult the "+
				"destructive guard. The guard existing in the migrate package is worth nothing if "+
				"the binary does not call it, which is the defect WI-171 was raised for", needle)
		}
	}

	// The guard condition must be the bare direction test. An independent review of this change
	// set found the command guarding `parsed == migrate.Down && *to == 0 && !givenTo`, on the
	// stated reasoning that a bounded revert does not take the audit schema with it. It does:
	// DownTo reverts the migrations above the bound, so `-to 1` runs 0002_audit.sql's down body
	// and drops audit_records. This assertion is here so that the narrowing cannot come back on
	// the strength of a plausible-sounding comment.
	if !strings.Contains(text, "if parsed == migrate.Down {") {
		t.Error("the destructive guard's condition is no longer the bare down test. A bound on " +
			"`down` reverts the migrations above it, including 0002_audit.sql, so a condition " +
			"that exempts `-to` exempts the one case that destroys the audit schema while " +
			"looking bounded")
	}
}
