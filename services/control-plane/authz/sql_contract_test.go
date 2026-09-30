package authz_test

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"testing"

	"github.com/danarprastika/web-trade/services/control-plane/authz"
)

// The SQL migration deliberately duplicates two sets of numbers that already exist in Go:
// the role-exclusion matrix and the session-class timeout table. The duplication is
// deliberate, because a database guard that is generated from Go would be unenforceable by
// anyone editing the bundle by hand, and a Go constant that is the only copy of a control
// is a comment.
//
// The cost of duplication is that the two copies drift, and a drift here is a control that
// exists in one layer and not the other. A session could be valid per the evaluator and
// expired per the trigger, or a policy rule could be refused by the database and accepted by
// the evaluator. Both are exactly the kind of defect that passes every test in one layer.
//
// So this file compares the two copies directly. It is the only test that can catch the
// drift, because it is the only test that can see both sides.

// migrationPath is the SQL migration that carries the duplicated tables.
const migrationPath = "../../../db/migrations/0003_authz.sql"

// loadMigration reads the migration once. A missing file is a hard failure rather than a
// skip: the migration is the other half of these tests, and a test that quietly stops
// checking it is a test that has stopped running.
func loadMigration(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.FromSlash(migrationPath))
	if err != nil {
		t.Fatalf("reading %s: %v", migrationPath, err)
	}
	return stripSQLComments(string(raw))
}

// stripSQLComments removes `--` line comments.
//
// This is load-bearing rather than cosmetic. The migration explains itself in prose, and
// that prose contains sentence-ending semicolons. A pattern like `VALUES(.*?);` matched
// against the raw file stops at the first semicolon it finds, which lands inside a comment
// above the first row, and the comparison then reports that every class is missing from a
// table that has all three of them seeded. A test that reports a missing table when the
// table is present is worse than no test, because it invites someone to "fix" the migration.
var sqlLineComment = regexp.MustCompile(`--[^\n]*`)

func stripSQLComments(sql string) string {
	return sqlLineComment.ReplaceAllString(sql, "")
}

// insertPairs extracts the (a, b) tuples of an INSERT ... VALUES block.
func insertPairs(t *testing.T, sql, statement string) [][2]string {
	t.Helper()
	block := regexp.MustCompile(
		regexp.QuoteMeta(statement) + `(?s)\s*VALUES(.*?);`,
	).FindStringSubmatch(sql)
	if block == nil {
		t.Fatalf("no %s VALUES block found in the migration", statement)
	}
	row := regexp.MustCompile(`\('([A-Z_]+)',\s*'([A-Z_]+)'\)`)
	var out [][2]string
	for _, m := range row.FindAllStringSubmatch(block[1], -1) {
		out = append(out, [2]string{m[1], m[2]})
	}
	return out
}

// The role-exclusion matrix must be identical in both layers.
//
// This is asserted as a set of exact pairs rather than as a count. A count would catch a
// missing row, which is the easy mistake, but it would not catch a row that is present in
// both layers and names the wrong action â€” and a wrong action is the failure that matters.
func TestTheSeededExclusionMatrixMatchesTheGoMatrix(t *testing.T) {
	sql := loadMigration(t)

	sqlPairs := map[string]bool{}
	for _, p := range insertPairs(t, sql, "INSERT INTO authz_role_action_exclusion (role, action)") {
		sqlPairs[p[0]+"/"+p[1]] = true
	}

	goPairs := map[string]bool{}
	for role, excluded := range authz.AllRoleExclusions() {
		for action := range excluded {
			goPairs[string(role)+"/"+string(action)] = true
		}
	}

	for pair := range goPairs {
		if !sqlPairs[pair] {
			t.Errorf("Go forbids %s but the SQL migration does not seed it; a policy rule granting it "+
				"would be refused by the evaluator and accepted by the database", pair)
		}
	}
	for pair := range sqlPairs {
		if !goPairs[pair] {
			t.Errorf("the SQL migration seeds the exclusion %s but Go does not forbid it; a policy rule "+
				"granting it would be accepted by the evaluator and refused by the database", pair)
		}
	}
	if len(goPairs) == 0 {
		t.Fatal("the Go exclusion matrix is empty; the test would pass trivially")
	}
	t.Logf("compared %d exclusion pairs across both layers", len(goPairs))
}

// The session-class timeouts must be identical in both layers.
//
// The database refuses a session created beyond its class absolute timeout, and the
// evaluator refuses one that has exceeded it. A session valid per one and expired per the
// other is a session whose lifetime depends on which layer happened to answer, which is not
// a property anyone can reason about.
func TestTheSeededSessionPolicyMatchesTheGoTable(t *testing.T) {
	sql := loadMigration(t)

	type row struct{ idle, absolute, stepUp int }
	byClass := map[string]row{}

	// The (?s) flag is load-bearing: the VALUES block spans several lines, and Go's regexp
	// does not let . match a newline without it. Without the flag the block simply is not
	// found and the test fails with "no block", which reads like a missing table rather
	// than a broken pattern.
	block := regexp.MustCompile(
		`(?s)INSERT INTO authz_session_policy\s*\([^)]*\)\s*VALUES(.*?);`,
	).FindStringSubmatch(sql)
	if block == nil {
		t.Fatal("no authz_session_policy VALUES block found in the migration")
	}
	tuple := regexp.MustCompile(
		`\('([A-Z_]+)',\s*(\d+),\s*(\d+),\s*(\d+)\)`,
	)
	for _, m := range tuple.FindAllStringSubmatch(block[1], -1) {
		idle, _ := strconv.Atoi(m[2])
		absolute, _ := strconv.Atoi(m[3])
		stepUp, _ := strconv.Atoi(m[4])
		byClass[m[1]] = row{idle, absolute, stepUp}
	}

	for _, class := range authz.AllSessionClasses() {
		policy, ok := authz.PolicyFor(class)
		if !ok {
			t.Errorf("Go has no policy for session class %s", class)
			continue
		}
		sqlRow, ok := byClass[string(class)]
		if !ok {
			t.Errorf("Go defines session class %s but the SQL migration does not seed it", class)
			continue
		}
		if int(policy.IdleTimeout.Seconds()) != sqlRow.idle {
			t.Errorf("session class %s: Go idle timeout is %s but the migration seeds %d seconds",
				class, policy.IdleTimeout, sqlRow.idle)
		}
		if int(policy.AbsoluteTimeout.Seconds()) != sqlRow.absolute {
			t.Errorf("session class %s: Go absolute timeout is %s but the migration seeds %d seconds",
				class, policy.AbsoluteTimeout, sqlRow.absolute)
		}
		if int(policy.StepUpFreshness.Seconds()) != sqlRow.stepUp {
			t.Errorf("session class %s: Go step-up freshness is %s but the migration seeds %d seconds",
				class, policy.StepUpFreshness, sqlRow.stepUp)
		}
	}
	if len(byClass) == 0 {
		t.Fatal("the session policy table parsed to nothing; the comparison would pass vacuously")
	}

	// The read-only class carries a longer step-up freshness than the privileged class. It
	// reads backwards, so it is asserted here rather than left to a future reader to
	// "correct": a uniform value would be a silent change to docs/21 section 3.
	if readOnly, privileged := byClass["READ_ONLY_OPERATOR"], byClass["PRIVILEGED_OPERATOR"]; readOnly.stepUp <= privileged.stepUp {
		t.Errorf("read-only step-up freshness (%d) should exceed the privileged one (%d); "+
			"docs/21 section 3 states this deliberately", readOnly.stepUp, privileged.stepUp)
	}
}

// The migration's own closed sets must match the Go closed sets, or a value Go accepts
// would be refused by the database and one Go refuses would be storable.
func TestTheActionAndRoleClosedSetsMatchTheMigration(t *testing.T) {
	sql := loadMigration(t)

	// Every action the Go package knows must appear in the migration's action closed set.
	actionNames := regexp.MustCompile(
		`(?s)authz_role_action_exclusion_action_closed CHECK \(action IN\s*\((.*?)\)\)`,
	).FindStringSubmatch(sql)
	if actionNames == nil {
		t.Fatal("no action closed set found in the migration")
	}
	sqlActions := csvSet(actionNames[1])

	goActions := authz.AllActions()
	if len(goActions) == 0 {
		t.Fatal("the Go action set is empty; the comparison would pass vacuously")
	}
	var missing []string
	for _, a := range goActions {
		if !sqlActions[a] {
			missing = append(missing, a)
		}
	}
	sort.Strings(missing)
	for _, a := range missing {
		t.Errorf("Go defines action %s but the migration's closed set does not admit it; "+
			"the evaluator could refuse a value the database never sees", a)
	}
}

// csvSet splits a comma-separated SQL literal list into a set.
func csvSet(s string) map[string]bool {
	out := map[string]bool{}
	for _, part := range regexp.MustCompile(`\s*,\s*`).Split(s, -1) {
		part = regexp.MustCompile(`['\s]`).ReplaceAllString(part, "")
		if part != "" {
			out[part] = true
		}
	}
	return out
}
