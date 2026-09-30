package ledger

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// The migration and the Go package declare the same closed sets: the account list, the
// identifier prefixes, and the rule that a reason belongs only to a correction. They are
// two implementations of one contract, and a divergence between them is a defect that only
// shows up in production, when the database refuses a posting the application considered
// valid.
//
// scripts/verify_ledger_db.py proves the database enforces its own side. These tests prove
// the two sides agree, and they run without Docker, so the drift is caught on a machine that
// cannot start PostgreSQL.

func migrationSQL(t *testing.T) string {
	t.Helper()
	// The test lives in services/control-plane/ledger, so the repository root is four
	// levels up.
	root := filepath.Join("..", "..", "..")
	path := filepath.Join(root, "db", "migrations", "0001_ledger.sql")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("cannot read the ledger migration at %s: %v; without it these tests "+
			"cannot confirm the two sides agree", path, err)
	}
	return string(data)
}

// TestTheMigrationAndThePackageDeclareTheSameAccounts is the drift check that matters most:
// an account the code can post to but the schema refuses would fail every posting in
// production, and an account the schema accepts but the code never posts would be a promise
// the books do not keep.
func TestTheMigrationAndThePackageDeclareTheSameAccounts(t *testing.T) {
	sql := migrationSQL(t)

	// The account list as it appears in the CHECK constraint.
	pattern := regexp.MustCompile(`account IN \(([^)]*)\)`)
	match := pattern.FindStringSubmatch(sql)
	if match == nil {
		t.Fatal("no closed account set found in the migration; the CHECK constraint is gone " +
			"or renamed, and the schema no longer pins the account set")
	}

	inSQL := map[AccountKind]bool{}
	for _, literal := range strings.Split(match[1], ",") {
		name := strings.Trim(strings.TrimSpace(literal), "'")
		if name != "" {
			inSQL[AccountKind(name)] = true
		}
	}

	inGo := map[AccountKind]bool{}
	for account := range accountKinds {
		inGo[account] = true
	}

	for account := range inGo {
		if !inSQL[account] {
			t.Errorf("account %s is postable by the Go package but refused by the migration; "+
				"every posting using it would fail in production", account)
		}
	}
	for account := range inSQL {
		if !inGo[account] {
			t.Errorf("the migration accepts account %s but the Go package has no such "+
				"account; the schema permits a posting the application can never make",
				account)
		}
	}
}

// TestTheMigrationAndThePackageUseTheSameDirectionSet.
func TestTheMigrationAndThePackageUseTheSameDirectionSet(t *testing.T) {
	sql := migrationSQL(t)
	pattern := regexp.MustCompile(`direction IN \(([^)]*)\)`)
	match := pattern.FindStringSubmatch(sql)
	if match == nil {
		t.Fatal("no closed direction set found in the migration")
	}
	inSQL := map[string]bool{}
	for _, literal := range strings.Split(match[1], ",") {
		inSQL[strings.Trim(strings.TrimSpace(literal), "'")] = true
	}
	for _, direction := range []string{string(Debit), string(Credit)} {
		if !inSQL[direction] {
			t.Errorf("the migration does not accept direction %s, but the Go package posts it",
				direction)
		}
	}
	if len(inSQL) != 2 {
		t.Errorf("the migration accepts %d directions, want 2: %v", len(inSQL), inSQL)
	}
}

// TestTheMigrationEnforcesTheCorrectionRuleThePackageEnforces. The reason rule is the one
// that keeps an ordinary posting distinguishable from a correction, and it is expressed in
// both places.
func TestTheMigrationEnforcesTheCorrectionRuleThePackageEnforces(t *testing.T) {
	sql := migrationSQL(t)
	if !strings.Contains(sql, "correction_has_reason") {
		t.Error("the migration no longer has the correction_has_reason constraint; an entry " +
			"could be a correction with no explanation, or look like one without being one")
	}
	if !strings.Contains(sql, "corrects_entry_id IS NULL AND reason IS NULL") {
		t.Error("the migration's correction rule no longer forbids a reason on a " +
			"non-correction, which is what keeps the two distinguishable in the history")
	}
}

// TestTheMigrationEnforcesTheIdentifierPrefixesThePackageRequires.
func TestTheMigrationEnforcesTheIdentifierPrefixesThePackageRequires(t *testing.T) {
	sql := migrationSQL(t)
	for _, want := range []string{
		"entry_id LIKE 'led\\_%'",
		"source_command_id LIKE 'cmd\\_%'",
	} {
		if !strings.Contains(sql, want) {
			t.Errorf("the migration does not enforce %s; a posting from another domain "+
				"would be accepted", want)
		}
	}
}

// TestTheMigrationEnforcesPositiveAmounts, because a signed amount would make a posting's
// meaning depend on which encoding a reader found.
func TestTheMigrationEnforcesPositiveAmounts(t *testing.T) {
	sql := migrationSQL(t)
	if !strings.Contains(sql, "line_amount_positive CHECK (amount > 0)") {
		t.Error("the migration does not enforce amount > 0; a negative amount would pass the " +
			"balance check while inverting a posting's direction")
	}
}

// TestTheMigrationEnforcesThePositionAssetRule.
func TestTheMigrationEnforcesThePositionAssetRule(t *testing.T) {
	sql := migrationSQL(t)
	if !strings.Contains(sql, "position_asset_matches_subject") {
		t.Error("the migration does not enforce that a position's subject and asset agree")
	}
}

// TestTheMigrationEnforcesIdempotencyOnTheCommandAndKeyTogether. A unique index on the key
// alone would collapse two different commands into one posting, which loses a financial
// fact; this is the case where the two sides could most plausibly drift.
func TestTheMigrationEnforcesIdempotencyOnTheCommandAndKeyTogether(t *testing.T) {
	sql := migrationSQL(t)
	pattern := regexp.MustCompile(`(?s)CREATE UNIQUE INDEX entry_idempotency_uniq\s+ON ledger\.entry \(([^)]*)\)`)
	match := pattern.FindStringSubmatch(sql)
	if match == nil {
		t.Fatal("no entry_idempotency_uniq index found in the migration; the database is not " +
			"enforcing replay safety, so idempotency is a Go convention only")
	}
	columns := strings.Join(strings.Fields(match[1]), " ")
	if columns != "source_command_id, idempotency_key" {
		t.Errorf("the idempotency index covers (%s); it must cover the source command and "+
			"the key together, or two different commands sharing a key would collide and "+
			"one posting would be silently lost", columns)
	}
}

// TestTheMigrationRefusesEveryDestructiveOperation, including TRUNCATE.
//
// TRUNCATE is the one that is easy to miss: it is a statement operation, so a row-level
// BEFORE UPDATE OR DELETE trigger does not fire, and the whole history can be erased in one
// statement with nothing to stop it.
func TestTheMigrationRefusesEveryDestructiveOperation(t *testing.T) {
	sql := migrationSQL(t)
	for _, want := range []string{
		"BEFORE UPDATE OR DELETE ON ledger.entry",
		"BEFORE UPDATE OR DELETE ON ledger.line",
		"BEFORE TRUNCATE ON ledger.entry",
		"BEFORE TRUNCATE ON ledger.line",
	} {
		if !strings.Contains(sql, want) {
			t.Errorf("the migration has no %q trigger; a %s could modify the ledger "+
				"without the append-only rule firing", want, firstWords(want))
		}
	}
}

func firstWords(s string) string {
	fields := strings.Fields(s)
	if len(fields) > 3 {
		fields = fields[:3]
	}
	return strings.Join(fields, " ")
}

// TestTheGoAccountNamesAreSortedForStableOutput guards the sorted output that both Balances
// and Rebuild depend on being deterministic.
func TestTheGoAccountNamesAreSortedForStableOutput(t *testing.T) {
	ids := newIDs(t)
	s := newStore()
	postFill(t, s, ids, 1, validFill(t, ids, 1))
	balances, err := Balances(s)
	if err != nil {
		t.Fatalf("Balances: %v", err)
	}
	if len(balances) == 0 {
		t.Fatal("expected some balances")
	}
	rendered := make([]string, 0, len(balances))
	for _, b := range balances {
		rendered = append(rendered, b.String())
	}
	if !sort.StringsAreSorted(rendered) {
		t.Errorf("the balance output is not sorted: %v", rendered)
	}
}
