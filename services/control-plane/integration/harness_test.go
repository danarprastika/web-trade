//go:build integration

// Live-database tests for the migrator and the durable stores.
//
// These exist because the repository previously had no Go PostgreSQL driver, which meant the
// SQL behind SQLSink, SQLStore, SQLIdentityStore and SQLChainReader had never been executed
// by the code that calls it. Every other test of those paths runs against an in-memory fake,
// and a fake accepts whatever shape the Go code hands it, so a query that references a column
// the migration never creates would pass the whole suite and fail on first production use.
//
// Gated behind the `integration` build tag so `go test ./...` stays driver-free and fast. CI's
// integration job already passes -tags=integration and already provides a PostgreSQL service,
// so these run there on protected branches without a workflow change.
//
// Requires DATABASE_URL. Skips rather than fails when it is absent, so a developer running the
// tag locally without a database sees a skip instead of a false failure. That skip is the
// non-destructive half of the harness and is unchanged: CI enforces its own DSN is present
// before it runs this suite, because a skip there would otherwise report success having run
// nothing.
//
// The destructive half is guarded instead. Reverting the real migration set drops schema
// ledger CASCADE and takes the audit, authz and model_registry tables with it, so running that
// against whatever DATABASE_URL happens to name would delete a developer's or operator's data
// with no confirmation. A test that reverts migrations therefore connects through
// openDestructive, which refuses a target that is not verifiably disposable before a single
// statement runs. See requireDisposableDestructiveTarget for the rule and the override.
package integration

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path"
	"strings"
	"testing"
	"time"

	_ "github.com/lib/pq"
)

// open connects to the test database or skips.
//
// The skip is deliberate and is not a way for a broken build to pass quietly: CI sets
// DATABASE_URL, so a skip there means the job lost its service and the run is already
// visibly wrong.
func open(t *testing.T) *sql.DB {
	t.Helper()

	dsn := os.Getenv("DATABASE_URL")
	if dsn == "" {
		t.Skip("DATABASE_URL is not set; skipping live-database tests")
	}

	db, err := sql.Open("postgres", dsn)
	if err != nil {
		t.Fatalf("opening the database: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		// A single retry, because a container that was just recreated accepts the port
		// before it has finished initialising its own credentials. Without this, a local
		// run fails on the first attempt after a container restart for a reason that has
		// nothing to do with the code under test.
		//
		// The retry is bounded and does not loop: a genuinely wrong DSN still fails, and it
		// fails with the driver's own message rather than a swallowed one.
		if retryErr := db.PingContext(ctx); retryErr != nil {
			t.Fatalf("pinging the database: %v (retry also failed: %v)", err, retryErr)
		}
		t.Log("ping failed once and succeeded on retry; the server was still initialising")
	}
	return db
}

func ctxFor(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// openDestructive connects for a test that reverts migrations, and refuses a database that is
// not verifiably disposable before any statement runs.
//
// The refusal is a Fatalf and never a Skip. A test that skips having destroyed nothing reports
// the same "ok" a passing run reports, and the destructive step is exactly the step whose
// absence must be visible: this harness already had seventeen skips read as a pass, and adding
// a second way to quietly not-run the most dangerous test in the package would repeat that.
func openDestructive(t *testing.T) *sql.DB {
	db := open(t)
	requireDisposableDestructiveTarget(t)
	return db
}

// The opt-in name and its one accepted value.
//
// The value is compared exactly, on purpose. A permissive parser (trim, case-insensitive,
// "true"/"yes" accepted) makes the guard weaker every time somebody decides to be helpful,
// and the only thing this variable is for is to make an operator state, in characters they had
// to choose deliberately, that they mean to drop the database. Empty, "0", "yes" and a typo are
// all refusals.
const (
	destructiveOptInEnv   = "INTEGRATION_ALLOW_DESTRUCTIVE"
	destructiveOptInValue = "1"
)

// disposableDatabaseSuffixes and the test_ prefix are what a database has to be called to be
// treated as disposable without the opt-in.
//
// This is a naming convention, not a proof, and the comment says so rather than pretending
// otherwise: a staging database called webtrade_test would pass. It is still the difference
// between "typed any DSN" and "the DSN has to announce itself as a test database", which is the
// accident this guards. Anything that does not announce itself has to opt in, and the opt-in
// is the second of two independent requirements, so neither one alone opens the door.
var disposableDatabaseSuffixes = []string{"_test", "_tests", "_it", "_ci"}

// dsnTarget is the part of a DSN that identifies which database is about to be destroyed.
//
// It holds no password, and its String renders one only if the scheme happened to be given
// one. The refusal message an operator reads has to name the database that was protected; it
// must never also hand the same log line the credentials that reach it.
type dsnTarget struct {
	scheme   string
	host     string // "host:port" as written; empty means lib/pq's local socket default
	user     string
	database string
}

func (t dsnTarget) String() string {
	server := t.host
	if server == "" {
		server = "(local socket)"
	}
	database := t.database
	if database == "" {
		database = "(no database in the DSN)"
	}
	if t.user != "" {
		return fmt.Sprintf("%s://%s@%s/%s", t.scheme, t.user, server, database)
	}
	return fmt.Sprintf("%s://%s/%s", t.scheme, server, database)
}

// server returns host and port for the message, split so an operator can compare it against
// what they meant to type.
func (t dsnTarget) server() string {
	if t.host == "" {
		return "(local socket)"
	}
	return t.host
}

// isLoopback reports whether the DSN points at this machine.
//
// A remote host means somebody else's database, which is the case this guard exists for. The
// empty host is lib/pq's own default for a local unix socket, so it counts as local.
func (t dsnTarget) isLoopback() bool {
	if t.host == "" {
		return true
	}
	host := t.host
	if h, _, err := net.SplitHostPort(host); err == nil {
		host = h
	}
	host = strings.Trim(host, "[]")
	if strings.EqualFold(host, "localhost") {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// looksDisposable reports whether the database announces itself as a test database.
func (t dsnTarget) looksDisposable() bool {
	name := strings.ToLower(t.database)
	if name == "" {
		return false
	}
	if strings.HasPrefix(name, "test_") {
		return true
	}
	for _, suffix := range disposableDatabaseSuffixes {
		if strings.HasSuffix(name, suffix) {
			return true
		}
	}
	return false
}

// destructiveVerdict is the guard's decision, and why it made it.
type destructiveVerdict struct {
	allowed bool
	// reason is empty when allowed, and always names the database or explains why it could not
	// be named.
	reason string
	target dsnTarget
	// overridden is true when the database did not look disposable and the explicit opt-in
	// allowed it anyway. The caller logs that, so the run record shows the reset was not the
	// default-safe case.
	overridden bool
}

// evaluateDestructiveTarget decides whether a destructive migration reset may run. It is a
// pure function of the DSN and the opt-in value, so the rule is tested without a database and
// cannot be weakened by a connection that happens to succeed.
//
// The rule, in full:
//
//	allowed = local host AND a disposable-looking database name
//	         OR (non-empty database name AND opt-in == "1")
//
// Both halves matter. The first means the common case, CI's own service database, needs no
// ceremony at all. The second means a deliberate operator is not blocked, but only by naming
// the variable and its exact value. A database the DSN does not name is refused either way:
// there is nothing to prove it is disposable and nothing to put in the refusal message, and a
// guard that cannot say what it protected is not a guard.
func evaluateDestructiveTarget(dsn, optIn string) destructiveVerdict {
	target, err := parseDSNTarget(dsn)
	if err != nil {
		return destructiveVerdict{reason: err.Error()}
	}
	if target.database == "" {
		return destructiveVerdict{
			target: target,
			reason: "the DSN names no database, so there is nothing to prove is disposable " +
				"and nothing to name in this refusal",
		}
	}

	disposable := target.looksDisposable()
	local := target.isLoopback()
	if disposable && local {
		return destructiveVerdict{allowed: true, target: target}
	}

	var reasons []string
	if !local {
		reasons = append(reasons, fmt.Sprintf(
			"server %q is not on this machine, so the database belongs to something else", target.host))
	}
	if !disposable {
		reasons = append(reasons, fmt.Sprintf(
			"database %q is not named like a disposable one (suffix %s, or prefix test_)",
			target.database, strings.Join(disposableDatabaseSuffixes, " / ")))
	}
	if optIn != destructiveOptInValue {
		return destructiveVerdict{target: target, reason: strings.Join(reasons, "; ")}
	}
	return destructiveVerdict{allowed: true, target: target, overridden: true}
}

// destructiveRefusalMessage renders a refusal for a human. The database is named twice on
// purpose: once in the target line and once in the verdict, because an operator reading a
// failed CI log has to be able to tell which database was protected without reconstructing it
// from what they typed earlier.
func destructiveRefusalMessage(v destructiveVerdict) string {
	target := v.target.String()
	if v.reason != "" && v.target.database == "" && v.target.host == "" {
		// The DSN could not be parsed into a target at all.
		return fmt.Sprintf(`refusing to run a destructive migration reset: DATABASE_URL could not be read (%s)
  this reset drops schema ledger CASCADE and the audit, authz and model_registry tables with it
  no statement was executed and the database was not touched`, v.reason)
	}
	return fmt.Sprintf(`refusing to run a destructive migration reset against %s
  this reset drops schema ledger CASCADE and the audit, authz and model_registry tables with it
  refused because: %s
  the database named above was protected; no statement was executed against it
  to allow this exact target anyway, opt in explicitly:
      %s=%s DATABASE_URL=... go test -tags=integration ./integration/...
  %s is compared exactly: unset, empty, "0" and any other value refuse the run rather than skip it`,
		target, v.reason, destructiveOptInEnv, destructiveOptInValue, destructiveOptInEnv)
}

// parseDSNTarget extracts the identifying parts of a DSN.
//
// A keyword/value DSN ("host=... dbname=...") is refused rather than guessed at: this guard
// must not be the component that is wrong about a working DSN. lib/pq accepts that form, so a
// developer using it gets a clear error telling them what the guard could not read rather than
// a silent pass or a confusing partial parse.
func parseDSNTarget(dsn string) (dsnTarget, error) {
	raw := strings.TrimSpace(dsn)
	if raw == "" {
		return dsnTarget{}, errors.New("DATABASE_URL is empty")
	}
	if !strings.Contains(raw, "://") {
		return dsnTarget{}, errors.New(
			"DATABASE_URL is not a URL; the keyword/value DSN form is not accepted by this guard")
	}
	u, err := url.Parse(raw)
	if err != nil {
		return dsnTarget{}, fmt.Errorf("parsing DATABASE_URL: %w", err)
	}
	target := dsnTarget{
		scheme:   u.Scheme,
		host:     u.Host,
		database: strings.TrimPrefix(path.Clean("/"+u.Path), "/"),
	}
	if u.User != nil {
		target.user = u.User.Username()
	}
	return target, nil
}

// requireDisposableDestructiveTarget fails the test unless the configured database may be
// reset.
//
// It fails. It does not skip, and it does not downgrade to a warning, and there is no
// environment value that turns the refusal into a skip. That is the whole point of adding a
// new variable here at all: a guard that can be silenced by an unset variable is not a guard,
// and the harness already ships one quiet path (an unset DATABASE_URL skips) which CI has to
// police from outside. This one polices itself.
func requireDisposableDestructiveTarget(t *testing.T) {
	t.Helper()

	verdict := evaluateDestructiveTarget(
		os.Getenv("DATABASE_URL"),
		os.Getenv(destructiveOptInEnv),
	)
	if !verdict.allowed {
		t.Fatal(destructiveRefusalMessage(verdict))
	}
	if verdict.overridden {
		// Not fatal: the operator asked for this and got it. Logged because a run that reset a
		// database whose name did not announce itself as disposable is the case somebody needs
		// to find in a log after the fact.
		t.Logf("DESTRUCTIVE MIGRATION RESET: %s does not look like a disposable database and was allowed by %s=%s; its schemas and data were dropped",
			verdict.target, destructiveOptInEnv, destructiveOptInValue)
		return
	}
	t.Logf("destructive migration reset permitted against the disposable target %s", verdict.target)
}
