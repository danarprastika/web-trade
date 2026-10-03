package migrate

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"path"
	"strings"
)

// A destructive migration is the only operation in this repository that can destroy a database
// rather than change it, and it is the only one an operator runs by hand against whatever
// DATABASE_URL happens to be exported. db/migrations/0002_audit.sql reverts to
// `DROP TABLE IF EXISTS audit_records CASCADE`, `DROP TABLE IF EXISTS audit_checkpoints CASCADE`
// and the rest of the tamper-evident audit schema, which is the evidence the platform's
// compliance story rests on. One command, no confirmation, and nothing between it and that
// schema.
//
// The guard against that lived in services/control-plane/integration/harness_test.go, which is a
// test file. The shipped command never executed a line of it. That is the shape this file exists
// to correct: a protection present in the repository and absent from the product is not a
// protection, and the commit that added the harness guard could honestly say it closed "a guard
// reporting that it had protected a database it never saw" only of the harness.
//
// So the rule moved here, next to the migrator it protects, and both callers use it. One
// implementation, two callers, one definition of what may be destroyed.

// DestructivePolicy is the rule a destructive run is judged against, plus what the refusal should
// tell the operator they are about to lose.
//
// The fields differ between callers deliberately, and the difference is the whole reason this is
// a struct rather than a constant.
type DestructivePolicy struct {
	// OptInEnv is the environment variable an operator sets to authorise a run the target check
	// would otherwise refuse, and OptInValue is the one value that counts.
	//
	// The comparison is exact and deliberately unforgiving: unset, empty, "0", "true" and " 1"
	// all refuse. A guard that accepts a family of spellings has to keep that family in step with
	// whatever a shell might produce, and the only value that cannot be produced by accident is
	// the one value that is written on purpose.
	OptInEnv   string
	OptInValue string

	// OptInOverrides decides whether the opt-in can stand in for the target check entirely.
	//
	// The integration harness sets it true. Its DSN comes from a CI service definition the
	// repository controls, a staging run is deliberate, and refusing a deliberate reset over
	// ceremony would only teach people to reach for the flag without reading it.
	//
	// The shipped command leaves it false, and that asymmetry is intentional rather than an
	// oversight: cmd/migrate runs against whatever the operator has exported, which is the
	// situation where the database on the other end is the one thing nobody wants to lose. There
	// the opt-in is necessary and not sufficient - the target must also announce itself as
	// disposable - so the worst case needs two deliberate acts rather than one. Raising this to
	// true for the command would make the flag sufficient on its own, which is precisely the
	// reading an operator most likely has while their finger is on the return key.
	OptInOverrides bool

	// Destroys names what the operation takes away, in the refusal. An operator who has been told
	// only that a command refused has learned nothing about whether to argue with it.
	Destroys string
}

// DSNTarget is the part of a DSN that identifies which database is about to be destroyed.
//
// It holds no password, and its String renders one only if the scheme happened to be given one.
// The refusal an operator reads has to name the database that was protected; it must never also
// hand the same log line the credentials that reach it.
type DSNTarget struct {
	Scheme   string
	Host     string // "host:port" as written; empty means lib/pq's local socket default
	User     string
	Database string
}

func (t DSNTarget) String() string {
	server := t.Server()
	database := t.Database
	if database == "" {
		database = "(no database in the DSN)"
	}
	if t.User != "" {
		return fmt.Sprintf("%s://%s@%s/%s", t.Scheme, t.User, server, database)
	}
	return fmt.Sprintf("%s://%s/%s", t.Scheme, server, database)
}

// Server returns host and port for the message, split so an operator can compare it against what
// they meant to type.
func (t DSNTarget) Server() string {
	if t.Host == "" {
		return "(local socket)"
	}
	return t.Host
}

// IsLoopback reports whether the DSN points at this machine.
//
// A remote host means somebody else's database, which is the case the guard exists for. The empty
// host is lib/pq's own default for a local unix socket, so it counts as local.
func (t DSNTarget) IsLoopback() bool {
	if t.Host == "" {
		return true
	}
	host := t.Host
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

// LooksDisposable reports whether the database announces itself as a test database.
func (t DSNTarget) LooksDisposable() bool {
	name := strings.ToLower(t.Database)
	if name == "" {
		return false
	}
	if strings.HasPrefix(name, "test_") {
		return true
	}
	for _, suffix := range DisposableDatabaseSuffixes {
		if strings.HasSuffix(name, suffix) {
			return true
		}
	}
	return false
}

// DisposableDatabaseSuffixes and the test_ prefix are what a database has to be called to be
// treated as disposable.
//
// This is a naming convention, not a proof, and the name of it says so rather than pretending
// otherwise: a staging database called webtrade_test would pass. It is still the difference
// between "typed any DSN" and "the DSN has to announce itself as a test database", which is the
// accident this guards.
var DisposableDatabaseSuffixes = []string{"_test", "_tests", "_it", "_ci"}

// The two opt-in variables, one per caller, kept here so the names are declared once.
//
// They are different on purpose. The integration harness predates the shipped command's guard and
// CI does not set either, so renaming one would silently change who is protected; keeping both
// means a change to either is a visible edit rather than a coincidence.
const (
	// IntegrationOptInEnv authorises a destructive integration reset. It is read by the harness
	// only, and no CI job sets it.
	IntegrationOptInEnv = "INTEGRATION_ALLOW_DESTRUCTIVE"

	// CommandOptInEnv authorises a destructive run of cmd/migrate. Read by the shipped command,
	// and not set by CI, which only ever migrates up.
	CommandOptInEnv = "MIGRATE_ALLOW_DESTRUCTIVE"

	// OptInValue is the single value that counts for either variable. The comparison is exact, so
	// unset, empty, "0", "true" and " 1" all refuse.
	//
	// Exported as a constant rather than read off a policy because callers use it in const
	// declarations and in message text, and a value that has to be fetched through a function to
	// print a variable name is a value that will eventually be retyped somewhere.
	OptInValue = "1"
)

// IntegrationOptInPolicy is the harness's rule, the permissive one. See DestructivePolicy.
func IntegrationOptInPolicy() DestructivePolicy {
	return DestructivePolicy{
		OptInEnv:       IntegrationOptInEnv,
		OptInValue:     OptInValue,
		OptInOverrides: true,
		Destroys:       "drops schema ledger CASCADE and the audit, authz and model_registry tables with it",
	}
}

// CommandOptInPolicy is cmd/migrate's rule, the strict one: the opt-in is necessary and not
// sufficient, so the worst case needs two deliberate acts rather than one.
//
// Exported so the tests can assert on the shipped policy rather than reconstructing it, which would
// let a test pass against a policy the command does not use.
func CommandOptInPolicy() DestructivePolicy {
	return DestructivePolicy{
		OptInEnv:       CommandOptInEnv,
		OptInValue:     OptInValue,
		OptInOverrides: false,
		Destroys: "reverts applied migrations, and 0002_audit.sql's down body drops the audit " +
			"schema - audit_records and audit_checkpoints - with CASCADE",
	}
}

// DestructiveVerdict is the guard's decision, and why it made it.
type DestructiveVerdict struct {
	// Allowed reports whether the destructive operation may proceed.
	Allowed bool
	// Reason is empty when allowed, and always names the database or explains why it could not
	// be named.
	Reason string
	// Target is what the guard read. Present even on a refusal, so the message can name the
	// database it protected.
	Target DSNTarget
	// Overridden is true when the target did not look disposable and the explicit opt-in allowed
	// it anyway. Callers log that, so a run record shows the reset was not the default-safe case.
	Overridden bool

	policy DestructivePolicy
}

// RefusalMessage renders a refusal for a human. The database is named twice on purpose: once in
// the target line and once in the verdict, because an operator reading a failed log has to be
// able to tell which database was protected without reconstructing it from what they typed
// earlier.
//
// example is the invocation that would authorise this exact target, supplied by the caller
// because only the caller knows whether it is a `go test` or a `go run`.
func (v DestructiveVerdict) RefusalMessage(example string) string {
	if v.Reason != "" && v.Target.Database == "" && v.Target.Host == "" {
		// The DSN could not be parsed into a target at all.
		return fmt.Sprintf(`refusing to run a destructive migration: DATABASE_URL could not be read (%s)
  this run %s
  no statement was executed and the database was not touched`, v.Reason, v.policy.Destroys)
	}

	var how string
	if v.policy.OptInOverrides {
		how = fmt.Sprintf("  to allow this exact target anyway, opt in explicitly:\n      %s=%s %s",
			v.policy.OptInEnv, v.policy.OptInValue, example)
	} else {
		how = fmt.Sprintf("  the opt-in is necessary but not sufficient here: this target must also be a\n"+
			"  loopback address whose database announces itself as disposable (suffix %s, or prefix\n"+
			"  test_), AND %s must be set to exactly %s:\n      %s=%s %s",
			strings.Join(DisposableDatabaseSuffixes, " / "),
			v.policy.OptInEnv, v.policy.OptInValue, v.policy.OptInEnv, v.policy.OptInValue, example)
	}

	return fmt.Sprintf(`refusing to run a destructive migration against %s
  this run %s
  refused because: %s
  the database named above was protected; no statement was executed against it
%s
  %s is compared exactly: unset, empty, "0" and any other value refuse the run`,
		v.Target, v.policy.Destroys, v.Reason, how, v.policy.OptInEnv)
}

// EvaluateDestructiveTarget decides whether a destructive migration may run against dsn. It is a
// pure function of the DSN, the opt-in value and the policy, so the rule is testable without a
// database and cannot be weakened by a connection that happens to succeed.
//
// The rule, in full:
//
//	policy.OptInOverrides:  allowed = local AND disposable-looking name
//	                          OR (the DSN names a database AND opt-in is exact)
//	otherwise:             allowed = local AND disposable-looking name AND opt-in is exact
//
// A DSN naming no database is refused either way: there is nothing to prove it is disposable and
// nothing to put in the refusal, and a guard that cannot say what it protected is not a guard.
func EvaluateDestructiveTarget(dsn string, policy DestructivePolicy, optIn string) DestructiveVerdict {
	target, err := ParseDSNTarget(dsn)
	if err != nil {
		return DestructiveVerdict{Reason: err.Error(), policy: policy}
	}
	if target.Database == "" {
		return DestructiveVerdict{
			Target: target,
			Reason: "the DSN names no database, so there is nothing to prove is disposable " +
				"and nothing to name in this refusal",
			policy: policy,
		}
	}

	disposable := target.LooksDisposable()
	local := target.IsLoopback()
	optedIn := optIn == policy.OptInValue
	targetOK := disposable && local

	// Three cases rather than one boolean, because the two policies are not the same rule with a
	// different threshold. Collapsing them into an expression such as
	// `targetOK && (optedIn || !OptInOverrides)` reads as though the permissive policy *requires*
	// the opt-in on a disposable target - which is the exact inversion, and the inversion is
	// silent in the dangerous direction: it lets the strict policy's command drop a local test
	// database with no opt-in at all.
	switch {
	case !policy.OptInOverrides:
		// Strict: the target must announce itself disposable on this machine AND the opt-in must
		// be exact. Neither alone is permission.
		if targetOK && optedIn {
			return DestructiveVerdict{Allowed: true, Target: target, policy: policy}
		}
	case targetOK:
		// Permissive: a DSN that announces itself disposable on this machine is the whole
		// permission. No opt-in, no ceremony, nothing to remember.
		return DestructiveVerdict{Allowed: true, Target: target, policy: policy}
	case optedIn:
		// Permissive only, and the case worth logging: a deliberate override of a target that did
		// not announce itself.
		return DestructiveVerdict{Allowed: true, Target: target, Overridden: true, policy: policy}
	}

	// The reasons are accumulated rather than returned at the first failure, so a refusal that
	// could be fixed by satisfying either of two conditions says so, instead of sending the
	// operator round the loop discovering the second one after they fix the first.
	var reasons []string
	if !local {
		reasons = append(reasons, fmt.Sprintf(
			"server %q is not on this machine, so the database belongs to something else", target.Host))
	}
	if !disposable {
		reasons = append(reasons, fmt.Sprintf(
			"database %q is not named like a disposable one (suffix %s, or prefix test_)",
			target.Database, strings.Join(DisposableDatabaseSuffixes, " / ")))
	}
	if !optedIn {
		reasons = append(reasons, fmt.Sprintf(
			"%s is not set to exactly %q", policy.OptInEnv, policy.OptInValue))
	}

	// Every path that arrives here has either the strict policy (so OptInOverrides is false) or
	// neither a disposable target nor an opt-in (so optedIn is false). An earlier version of this
	// function re-tested `policy.OptInOverrides && optedIn` here as a second override site. That
	// was unreachable in every case - the switch above already returns for both - so it read as a
	// deliberate second path rather than as the dead code it was, and an independent review of the
	// change set that introduced it flagged it. A rule that can never decide anything is worse
	// than no rule: it implies a second way in exists for an auditor to check, and there is not one.
	return DestructiveVerdict{Target: target, Reason: strings.Join(reasons, "; "), policy: policy}
}

// ParseDSNTarget extracts the identifying parts of a DSN.
//
// A keyword/value DSN ("host=... dbname=...") is refused rather than guessed at: this guard must
// not be the component that is wrong about a working DSN. lib/pq accepts that form, so a
// developer using it gets a clear error telling them what the guard could not read rather than a
// silent pass or a confusing partial parse.
//
// A query string that could redirect the connection is refused for the same reason. lib/pq reads
// the path first and then applies every query parameter into one option map, last write winning,
// so `webtrade_test?dbname=webtrade` connects to webtrade and `localhost/webtrade_test?host=prod`
// connects to prod. Both would otherwise pass a guard that only read the path - and both point the
// destructive run at a database whose name the guard never saw. The parameters are named rather
// than honoured because a guard that has to reimplement the driver's precedence rules is a second
// implementation of connection parsing, and a stale one is a bypass.
func ParseDSNTarget(dsn string) (DSNTarget, error) {
	raw := strings.TrimSpace(dsn)
	if raw == "" {
		return DSNTarget{}, errors.New("DATABASE_URL is empty")
	}
	if !strings.Contains(raw, "://") {
		return DSNTarget{}, errors.New(
			"DATABASE_URL is not a URL; the keyword/value DSN form is not accepted by this guard")
	}
	u, err := url.Parse(raw)
	if err != nil {
		return DSNTarget{}, fmt.Errorf("parsing DATABASE_URL: %w", err)
	}
	target := DSNTarget{
		Scheme:   u.Scheme,
		Host:     u.Host,
		Database: strings.TrimPrefix(path.Clean("/"+u.Path), "/"),
	}
	if u.User != nil {
		target.User = u.User.Username()
	}

	// A dbname that merely restates the path changes nothing, so it is allowed through; anything
	// else that could move the connection is refused by name.
	overrides := make([]string, 0, 4)
	for _, key := range []string{"dbname", "host", "port", "user"} {
		switch key {
		case "dbname":
			if v := u.Query().Get(key); v != "" && v != target.Database {
				overrides = append(overrides, key)
			}
		default:
			if u.Query().Get(key) != "" {
				overrides = append(overrides, key)
			}
		}
	}
	if len(overrides) > 0 {
		return DSNTarget{}, fmt.Errorf("DATABASE_URL carries %s in its query string, which "+
			"overrides the path this guard reads; refusing rather than risk resetting a database "+
			"the guard could not see", strings.Join(overrides, ", "))
	}
	return target, nil
}
