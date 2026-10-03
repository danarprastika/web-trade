package migrate

import (
	"strings"
	"testing"
)

// The guard moved here from services/control-plane/integration/harness_test.go, and the reason it
// moved is that it was in a test file. cmd/migrate -direction down reverts the whole applied set,
// and 0002_audit.sql's down body is `DROP TABLE IF EXISTS audit_records CASCADE`, so the unbounded
// revert destroys the tamper-evident audit schema against whatever DATABASE_URL is exported. The
// harness guard could not help there: `go run ./services/control-plane/cmd/migrate` never executes
// a line of a _test.go file.
//
// So the tests below are the ones that matter most, and they are table-driven over the policy
// rather than over a connection, because a rule that needs a database to check is a rule that is
// never checked.

// The shipped policy must be the strict one. If this fails, someone has made the command's opt-in
// sufficient on its own, which is the single most consequential change this file could contain:
// MIGRATE_ALLOW_DESTRUCTIVE=1 against a production DSN would then destroy the audit schema from one
// deliberate act instead of two.
func TestTheCommandPolicyDoesNotLetTheOptInStandAlone(t *testing.T) {
	policy := CommandOptInPolicy()
	if policy.OptInOverrides {
		t.Fatal("cmd/migrate must not allow the opt-in to override the target check; the command " +
			"runs against whatever DATABASE_URL the operator has exported")
	}
	if policy.OptInValue != "1" {
		t.Fatalf("the opt-in value is %q, expected \"1\"; a guard that accepts a family of "+
			"spellings has to keep that family in step with whatever a shell produces", policy.OptInValue)
	}
	if policy.Destroys == "" {
		t.Fatal("the policy must name what the run destroys, or the refusal tells an operator " +
			"nothing about whether to argue with it")
	}
}

// The strict policy in full, as a table. Each row is a case where the answer has to be known, and
// the opt-in column is the half of the rule that the harness policy does not require.
func TestTheStrictPolicyRequiresBothTheTargetAndTheOptIn(t *testing.T) {
	policy := CommandOptInPolicy()
	const production = "postgres://webtrade:hunter2@db.internal:5432/webtrade"

	cases := []struct {
		name    string
		dsn     string
		optIn   string
		allowed bool
		why     string
	}{
		{
			name:  "production host, no opt-in",
			dsn:   production,
			optIn: "",
			why:   "neither the target nor the opt-in is satisfied",
		},
		{
			name:  "opt-in alone is not enough",
			dsn:   production,
			optIn: "1",
			why: "the opt-in is necessary but not sufficient; the database does not announce " +
				"itself disposable and the server is not this machine",
		},
		{
			name:  "a disposable-looking name on a remote host is still refused",
			dsn:   "postgres://webtrade:hunter2@db.internal:5432/webtrade_test",
			optIn: "1",
			why:   "a remote server is somebody else's database whatever it is called",
		},
		{
			name:  "a local disposable target with no opt-in is refused",
			dsn:   "postgres://webtrade:hunter2@127.0.0.1:5432/webtrade_test",
			optIn: "",
			why:   "cmd/migrate always requires the opt-in, so the worst case is never one act",
		},
		{
			name:    "a local disposable target with the opt-in",
			dsn:     "postgres://webtrade:hunter2@127.0.0.1:5432/webtrade_test",
			optIn:   "1",
			allowed: true,
			why:     "both requirements met",
		},
		{
			name:  "a local database whose name does not announce itself is refused",
			dsn:   "postgres://webtrade:hunter2@localhost:5432/webtrade",
			optIn: "1",
			why:   "loopback alone is not permission to drop a database called webtrade",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			verdict := EvaluateDestructiveTarget(tc.dsn, policy, tc.optIn)
			if verdict.Allowed != tc.allowed {
				t.Fatalf("allowed = %v, expected %v: %s", verdict.Allowed, tc.allowed, tc.why)
			}
			if tc.allowed {
				if verdict.Overridden {
					t.Fatal("the strict policy has no override, so a permitted run is never " +
						"reported as overridden")
				}
				return
			}
			if verdict.Reason == "" {
				t.Fatal("a refusal with no reason is a refusal an operator cannot act on")
			}
			if !strings.Contains(verdict.Reason, policy.OptInEnv) &&
				!strings.Contains(verdict.Reason, "disposable") &&
				!strings.Contains(verdict.Reason, "this machine") {
				t.Fatalf("the refusal must say which requirement was unmet, got: %s", verdict.Reason)
			}
		})
	}
}

// The exactness of the opt-in is the property that makes it deliberate. Every near miss refuses,
// and each refusal names the database - so the operator learns what was protected rather than only
// that something stopped.
func TestTheOptInIsComparedExactly(t *testing.T) {
	policy := CommandOptInPolicy()
	const dsn = "postgres://webtrade:hunter2@127.0.0.1:5432/webtrade_test"

	for _, value := range []string{"", " ", "0", "true", "yes", "01", " 1", "1 ", "1\n", "on"} {
		verdict := EvaluateDestructiveTarget(dsn, policy, value)
		if verdict.Allowed {
			t.Errorf("the opt-in value %q was accepted; only %q authorises a destructive run",
				value, policy.OptInValue)
		}
	}

	if verdict := EvaluateDestructiveTarget(dsn, policy, "1"); !verdict.Allowed {
		t.Fatalf("the documented opt-in was refused: %s", verdict.Reason)
	}
}

// A DSN naming no database is refused under either policy, even with the opt-in, because there is
// nothing to name in the refusal. A guard that cannot say what it protected is not a guard, and a
// guard that cannot say what it is protecting is in a strictly worse position.
func TestAnUnnamedDatabaseIsRefusedEvenWithTheOptIn(t *testing.T) {
	for name, policy := range map[string]DestructivePolicy{
		"harness": IntegrationOptInPolicy(),
		"command": CommandOptInPolicy(),
	} {
		t.Run(name, func(t *testing.T) {
			verdict := EvaluateDestructiveTarget(
				"postgres://webtrade:hunter2@db.internal:5432/", policy, "1")
			if verdict.Allowed {
				t.Fatal("a DSN naming no database must be refused even with the opt-in")
			}
			if !strings.Contains(verdict.Reason, "no database") {
				t.Fatalf("the refusal must explain that there is no database to name, got: %s",
					verdict.Reason)
			}
		})
	}
}

// The refusal is the operator's only evidence of what the guard saw, so it has to name the
// database and must not hand over the password that reaches it.
func TestTheRefusalNamesTheDatabaseAndNotThePassword(t *testing.T) {
	const password = "hunter2"
	verdict := EvaluateDestructiveTarget(
		"postgres://webtrade:"+password+"@db.internal:5432/webtrade",
		CommandOptInPolicy(), "")

	if verdict.Allowed {
		t.Fatal("a production DSN was allowed")
	}
	message := verdict.RefusalMessage("go run ./services/control-plane/cmd/migrate -direction down")

	if !strings.Contains(message, "db.internal:5432") {
		t.Errorf("the refusal must name the server it refused: %s", message)
	}
	if !strings.Contains(message, "webtrade") {
		t.Errorf("the refusal must name the database it protected: %s", message)
	}
	if strings.Contains(message, password) {
		t.Errorf("the refusal leaked the password into a log line: %s", message)
	}
	// The opt-in is named, and stated as insufficient on its own, because the strict policy's whole
	// distinguishing feature is that it is not the only key.
	if !strings.Contains(message, CommandOptInEnv) {
		t.Errorf("the refusal must name the variable that would allow this target: %s", message)
	}
	if !strings.Contains(message, "not sufficient") {
		t.Errorf("the refusal must say the opt-in is not sufficient by itself, or the strict "+
			"policy reads like the permissive one: %s", message)
	}
}

// The redirect check is the subtlest of the guards, because the DSN the guard reads and the
// database lib/pq connects to are the same string read two different ways. These two are the
// bypasses: a query parameter that moves the connection to a database the guard never saw.
func TestAQueryStringCannotRedirectTheGuardToAnotherDatabase(t *testing.T) {
	for _, dsn := range []string{
		"postgres://webtrade:pw@127.0.0.1:5432/webtrade_test?dbname=webtrade",
		"postgres://webtrade:pw@127.0.0.1:5432/webtrade_test?host=prod.internal",
		"postgres://webtrade:pw@127.0.0.1:5432/webtrade_test?port=5433",
		"postgres://webtrade:pw@127.0.0.1:5432/webtrade_test?user=postgres",
	} {
		verdict := EvaluateDestructiveTarget(dsn, CommandOptInPolicy(), "1")
		if verdict.Allowed {
			t.Errorf("a DSN redirecting the connection was allowed: %s", dsn)
		}
	}

	// A dbname that merely restates the path moves nothing, and refusing it would break a working
	// DSN for no gain.
	if _, err := ParseDSNTarget(
		"postgres://webtrade:pw@127.0.0.1:5432/webtrade_test?dbname=webtrade_test&sslmode=disable"); err != nil {
		t.Fatalf("a harmless query string was refused: %v", err)
	}
}

// The harness keeps the permissive policy it was built with, because CI does not set the opt-in
// and a stricter rule there would break the protected branch rather than protect it. This asserts
// that asymmetry deliberately, so a future edit to either policy has to be noticed.
func TestTheHarnessAndCommandPoliciesDifferOnPurpose(t *testing.T) {
	harness := IntegrationOptInPolicy()
	command := CommandOptInPolicy()

	if !harness.OptInOverrides {
		t.Fatal("the integration harness must keep the opt-in as an override: CI does not set it, " +
			"so a stricter rule would refuse the disposable target CI's own DSN names")
	}
	if command.OptInOverrides {
		t.Fatal("the shipped command must not treat the opt-in as an override")
	}
	if harness.OptInEnv == command.OptInEnv {
		t.Fatalf("both policies read %s, so setting it for one would silently authorise the other",
			harness.OptInEnv)
	}
}
