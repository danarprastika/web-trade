//go:build integration

// The destructive-reset guard, tested without a database.
//
// Every assertion here runs against the pure decision function, so the rule that decides
// whether four schemas may be dropped is verified even when there is no server to drop them
// from. A guard tested only by trying it against a live disposable database would pass in a
// world where the guard did not exist, because the happy path looks identical either way.
//
// What is being defended, stated once so each test below is accountable to it:
//
//   - A destructive migration reset against a database that is not verifiably disposable is
//     refused, and the refusal names that database.
//   - The refusal is a failure, never a skip and never a warning.
//   - The opt-in is an exact string comparison, and it is the second of two requirements, not
//     a single switch.

package integration

import (
	"os"
	"strings"
	"testing"
)

// A local database named like a test database is allowed without any opt-in.
//
// The first case is CI's own DSN, verbatim from .github/workflows/ci.yml. If this case ever
// starts failing, the guard has broken the protected branch rather than protected it, and the
// fix belongs in the guard's naming rule, not in a new variable nobody sets.
func TestALocalDisposableDatabaseNeedsNoOptIn(t *testing.T) {
	cases := []struct {
		name string
		dsn  string
	}{
		{"ci integration service", "postgres://webtrade:webtrade@localhost:5432/webtrade_test?sslmode=disable"},
		{"ipv4 loopback", "postgres://webtrade:secret@127.0.0.1:55440/webtrade_test?sslmode=disable"},
		{"ipv6 loopback", "postgres://webtrade:secret@[::1]:55440/webtrade_test?sslmode=disable"},
		{"unix socket default", "postgres:///webtrade_test?sslmode=disable"},
		{"no host at all", "postgres://webtrade:secret@/webtrade_test?sslmode=disable"},
		{"it suffix", "postgres://webtrade:secret@localhost:55440/webtrade_it?sslmode=disable"},
		{"test prefix", "postgres://webtrade:secret@localhost:55440/test_webtrade?sslmode=disable"},
		{"upper case name", "postgres://webtrade:secret@localhost:55440/WEBTRADE_TEST?sslmode=disable"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			verdict := evaluateDestructiveTarget(tc.dsn, "")
			if !verdict.allowed {
				t.Fatalf("refused a disposable database with no opt-in: %s", destructiveRefusalMessage(verdict))
			}
			if verdict.overridden {
				t.Error("verdict reports an override for a target that needed no opt-in")
			}
		})
	}
}

// The refusal itself. Each case is a database that must not be dropped by accident, and the
// failure mode being guarded is precisely "the operator typed a DSN and did not look at it".
func TestDestructiveResetIsRefusedAgainstANonDisposableDatabase(t *testing.T) {
	cases := []struct {
		name        string
		dsn         string
		database    string
		wantInError string
	}{
		{
			name:        "production on a remote host",
			dsn:         "postgres://webtrade:hunter2@db.internal:5432/webtrade?sslmode=require",
			database:    "webtrade",
			wantInError: "webtrade",
		},
		{
			name:        "staging on a remote host",
			dsn:         "postgres://ops:hunter2@staging.internal:5432/webtrade_staging?sslmode=require",
			database:    "webtrade_staging",
			wantInError: "webtrade_staging",
		},
		{
			name:        "production on loopback, still a real database",
			dsn:         "postgres://postgres@localhost:5432/webtrade_prod?sslmode=disable",
			database:    "webtrade_prod",
			wantInError: "webtrade_prod",
		},
		{
			name:        "a plainly named local database",
			dsn:         "postgres://postgres@localhost:55440/webtrade?sslmode=disable",
			database:    "webtrade",
			wantInError: "webtrade",
		},
		{
			name:        "a remote database that merely looks disposable",
			dsn:         "postgres://webtrade:hunter2@shared.internal:5432/webtrade_test?sslmode=require",
			database:    "webtrade_test",
			wantInError: "webtrade_test",
		},
		{
			name:        "keyword value DSN, which the guard will not guess at",
			dsn:         "host=localhost dbname=webtrade user=webtrade password=hunter2",
			database:    "",
			wantInError: "DATABASE_URL",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			verdict := evaluateDestructiveTarget(tc.dsn, "")
			if verdict.allowed {
				t.Fatalf("allowed a destructive reset against %s with no opt-in", verdict.target)
			}
			if verdict.reason == "" {
				t.Error("refused without a reason; a refusal an operator cannot act on is a bug")
			}
			if tc.database != "" && verdict.target.database != tc.database {
				t.Errorf("refusal is about database %q, expected %q",
					verdict.target.database, tc.database)
			}
			// The operator has to be able to tell which database was protected.
			message := destructiveRefusalMessage(verdict)
			if !strings.Contains(message, tc.wantInError) {
				t.Errorf("refusal message does not name %q:\n%s", tc.wantInError, message)
			}
		})
	}
}

// The message names the database and the server, and does not carry the password out of the
// environment and into a build log.
func TestTheRefusalNamesTheProtectedDatabaseAndNeverThePassword(t *testing.T) {
	const (
		password = "sup3r-s3cret-do-not-log"
		dsn      = "postgres://webtrade:" + password + "@db.internal:5432/webtrade?sslmode=require"
	)

	verdict := evaluateDestructiveTarget(dsn, "")
	if verdict.allowed {
		t.Fatal("a production DSN was allowed; every other assertion here is vacuous")
	}
	message := destructiveRefusalMessage(verdict)

	if !strings.Contains(message, "db.internal:5432") {
		t.Errorf("refusal does not name the server:\n%s", message)
	}
	if !strings.Contains(message, "webtrade") {
		t.Errorf("refusal does not name the database:\n%s", message)
	}
	if strings.Contains(message, password) {
		t.Errorf("refusal leaked the password:\n%s", message)
	}
	if strings.Contains(verdict.target.String(), password) {
		t.Errorf("the rendered target leaked the password: %s", verdict.target)
	}
	// The user is kept: it identifies which connection was refused, and it is not a secret.
	if !strings.Contains(message, "webtrade@db.internal") {
		t.Errorf("refusal does not identify the connection:\n%s", message)
	}
}

// The opt-in is compared exactly, and an unset or malformed value refuses rather than skips.
//
// This is the property the whole guard rests on. A permissive parser, or a default-allow for
// the empty string, turns one exported variable into the difference between keeping and losing
// a database.
func TestTheOptInMustBeExactlyOneAndNeverSkips(t *testing.T) {
	const production = "postgres://webtrade:hunter2@db.internal:5432/webtrade?sslmode=require"

	for _, optIn := range []string{"", " ", "0", "true", "TRUE", "yes", "on", "1 ", " 1", "11", "2"} {
		t.Run("refuses "+strings.ReplaceAll(strings.TrimSpace(optIn), " ", "<space>"), func(t *testing.T) {
			verdict := evaluateDestructiveTarget(production, optIn)
			if verdict.allowed {
				t.Fatalf("opt-in value %q was accepted; the opt-in must be the exact string %q",
					optIn, destructiveOptInValue)
			}
			if verdict.reason == "" {
				t.Error("refused without a reason")
			}
		})
	}

	t.Run("accepts the exact value and says so", func(t *testing.T) {
		verdict := evaluateDestructiveTarget(production, destructiveOptInValue)
		if !verdict.allowed {
			t.Fatalf("the documented opt-in did not work: %s", destructiveRefusalMessage(verdict))
		}
		if !verdict.overridden {
			t.Error("an opt-in override was not recorded; the run log would not show it happened")
		}
	})

	t.Run("the opt-in does not authorise an unnamed database", func(t *testing.T) {
		// A DSN that names no database can be neither checked nor reported, so there is no value
		// of the variable that makes it safe. An override that can widen into "whatever this
		// string parses as" is how a guard becomes a formality.
		verdict := evaluateDestructiveTarget("postgres://webtrade:hunter2@db.internal:5432/", destructiveOptInValue)
		if verdict.allowed {
			t.Fatal("an unnamed database was allowed by the opt-in")
		}
		if !strings.Contains(verdict.reason, "no database") {
			t.Errorf("refusal does not explain the unnamed database: %s", verdict.reason)
		}
	})
}

// The guard cannot be turned back into a skip.
//
// This reads harness_test.go rather than exercising the guard, because the property is about
// which testing verb the guard uses, and the only way to observe that without a live server is
// to read it. CI once accepted seventeen skips as a pass; a destructive step that skips on a
// bad DSN is the same failure with a worse consequence, and this is the test that says so.
func TestTheDestructiveGuardCannotSkip(t *testing.T) {
	source, err := os.ReadFile("harness_test.go")
	if err != nil {
		t.Fatalf("reading the harness: %v", err)
	}
	text := string(source)

	guard := funcBody(t, text, "requireDisposableDestructiveTarget")
	if !strings.Contains(guard, "t.Fatal") {
		t.Error("the guard does not fail the test; refusing without failing is a warning")
	}
	if strings.Contains(guard, "t.Skip") {
		t.Error("the guard skips; a destructive step that skips reports the same ok a pass does")
	}

	connect := funcBody(t, text, "openDestructive")
	if !strings.Contains(connect, "requireDisposableDestructiveTarget") {
		t.Error("openDestructive does not consult the guard")
	}
	// The guard must run before the connection is handed back, because the connection is what
	// every statement in the test runs against.
	guardAt := strings.Index(connect, "requireDisposableDestructiveTarget")
	returnAt := strings.Index(connect, "return db")
	if returnAt < 0 || guardAt < 0 || guardAt > returnAt {
		t.Errorf("the guard does not run before the connection is returned:\n%s", connect)
	}

	// And the destructive test must actually go through it, or the rule above protects nothing.
	migrator, err := os.ReadFile("migrator_test.go")
	if err != nil {
		t.Fatalf("reading the migrator test: %v", err)
	}
	if !strings.Contains(string(migrator), "openDestructive(t)") {
		t.Error("the migrator test no longer connects through the guarded constructor")
	}
	if strings.Contains(string(migrator), "reset.Run(ctx, migrate.Down)") &&
		!strings.Contains(string(migrator), "openDestructive(t)") {
		t.Error("an unguarded down run is back in the migrator test")
	}
}

// funcBody returns the source of one function, from its declaration to the column-zero brace
// that closes it. Good enough for a test that reads a file it also owns.
func funcBody(t *testing.T, source, name string) string {
	t.Helper()

	start := strings.Index(source, "func "+name+"(")
	if start < 0 {
		t.Fatalf("no function %s in the harness", name)
	}
	rest := source[start:]
	end := strings.Index(rest, "\n}\n")
	if end < 0 {
		t.Fatalf("could not find the end of %s", name)
	}
	return rest[:end]
}

// The configured database satisfies the guard, judged the same way the destructive test judges
// it. Without this the guard's happy path is only asserted against DSNs invented in a table,
// and a real DSN shape could stop matching the rule without any test noticing.
//
// Skips on an unset DATABASE_URL, because there is then nothing to judge and the harness's
// existing rule already covers that case. When it is set and not disposable, this fails
// loudly, which is the correct answer: the destructive test in this package would refuse too.
func TestTheConfiguredDatabaseSatisfiesTheDestructiveGuard(t *testing.T) {
	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL is not set; there is no configured target to judge")
	}

	verdict := evaluateDestructiveTarget(dsn, os.Getenv(destructiveOptInEnv))
	if !verdict.allowed {
		t.Fatalf("the configured database is refused by the destructive guard, so "+
			"TestMigratorAppliesRevertsAndReappliesTheRealSet cannot run:\n%s",
			destructiveRefusalMessage(verdict))
	}
	t.Logf("destructive guard verdict for the configured target %s: allowed (overridden=%v)",
		verdict.target, verdict.overridden)
}
