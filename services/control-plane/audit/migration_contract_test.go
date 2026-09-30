package audit

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
)

// These tests keep the Go package and the SQL migration from drifting apart.
//
// The audit chain deliberately states the same rules in two places: the Go package
// refuses an invalid record, and the migration refuses it again so that a second writer
// bypassing the package cannot store anything. That redundancy is the point, and it is
// also a hazard: the two copies can agree today and disagree tomorrow, and a disagreement
// in a closed set means the database accepts records the platform considers invalid.
//
// The tests below read the migration and assert it still says what the Go code says.
// They are a text-level check, not an execution check; the authoritative proof that the
// database enforces these rules is db/tests/0002_audit_verify.sql, which runs them
// against a real PostgreSQL.

// migrationPath returns the path to the audit migration, relative to this package.
func migrationPath(t *testing.T) string {
	t.Helper()
	// The test runs with the package directory as its working directory, so the
	// migration is four levels up.
	path := filepath.Join("..", "..", "..", "db", "migrations", "0002_audit.sql")
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("cannot read the audit migration at %s: %v", path, err)
	}
	return path
}

func migrationText(t *testing.T) string {
	t.Helper()
	raw, err := os.ReadFile(migrationPath(t))
	if err != nil {
		t.Fatalf("reading the migration: %v", err)
	}
	return string(raw)
}

// everyActorType renders the Go closed set so it can be matched in the SQL.
func everyActorType() []string {
	var out []string
	for _, a := range []ActorType{ActorHuman, ActorService, ActorAgent, ActorStrategy, ActorSystem, ActorBreakGlass} {
		if !a.Valid() {
			// A value the Go side does not consider valid must never reach the SQL.
			panic("actor type " + string(a) + " is not in the Go closed set")
		}
		out = append(out, string(a))
	}
	return out
}

func everyResult() []string {
	var out []string
	for _, r := range []Result{ResultSucceeded, ResultRefused, ResultFailed, ResultPartial, ResultUnknown} {
		if !r.IsValid() {
			panic("result " + string(r) + " is not in the Go closed set")
		}
		out = append(out, string(r))
	}
	return out
}

func TestTheSQLClosedSetMatchesTheGoClosedSet(t *testing.T) {
	sql := migrationText(t)

	for _, actor := range everyActorType() {
		if !strings.Contains(sql, "'"+actor+"'") {
			t.Errorf("the migration does not list actor type %q; the Go closed set and the SQL have drifted", actor)
		}
	}
	for _, result := range everyResult() {
		if !strings.Contains(sql, "'"+result+"'") {
			t.Errorf("the migration does not list result %q; the Go closed set and the SQL have drifted", result)
		}
	}
}

// The schema version is part of the hashed payload, so a record written under a different
// version must not be accepted alongside current ones. Both sides must agree on it.
func TestTheSchemaVersionMatchesTheMigration(t *testing.T) {
	sql := migrationText(t)
	if !strings.Contains(sql, "audit_records_schema_version CHECK (schema_version = "+itoa64(int64(SchemaVersion))+")") {
		t.Errorf("the migration does not pin schema_version to the Go constant %d", SchemaVersion)
	}
	if !strings.Contains(sql, "audit_checkpoints_schema_version CHECK (schema_version = "+itoa64(int64(SchemaVersion))+")") {
		t.Errorf("the migration does not pin the checkpoint schema_version to the Go constant %d", SchemaVersion)
	}
}

// The hash width is fixed by the algorithm and is asserted on both sides. A mismatch
// would mean the Go verifier and the database disagree about what a hash is.
func TestTheHashWidthMatchesTheMigration(t *testing.T) {
	sql := migrationText(t)
	if HashLength != 32 {
		t.Fatalf("the Go hash length is %d, which is not SHA-256", HashLength)
	}
	for _, constraint := range []string{
		"audit_records_hash_length CHECK (length(record_hash) = 32)",
		"audit_records_previous_hash_length CHECK (length(previous_hash) = 32)",
		"audit_checkpoints_first_hash_length CHECK (length(first_hash) = 32)",
		"audit_checkpoints_last_hash_length CHECK (length(last_hash) = 32)",
	} {
		if !strings.Contains(sql, constraint) {
			t.Errorf("the migration is missing the hash-width constraint %q", constraint)
		}
	}
}

// Appending must be the only write. This is the property the whole package exists to
// make mechanical, and it is worth asserting against the migration text directly because
// a row-level trigger alone does not cover TRUNCATE.
func TestTheMigrationRefusesEveryDestructiveStatement(t *testing.T) {
	sql := migrationText(t)

	// The operation lives in the "BEFORE <op> ON <table>" clause, not in the trigger
	// name, so it is extracted from there. A trigger may cover more than one operation,
	// which is why "UPDATE OR DELETE" is matched as a unit and then split.
	triggers := regexp.MustCompile(`CREATE TRIGGER\s+(\w+)([\s\S]*?)EXECUTE FUNCTION audit_refuse_mutation\(\)`).
		FindAllStringSubmatch(sql, -1)
	if len(triggers) == 0 {
		t.Fatal("the migration declares no append-only triggers")
	}

	found := map[string]bool{}
	for _, match := range triggers {
		op := regexp.MustCompile(`BEFORE\s+([A-Z ]+?)\s+ON`).FindStringSubmatch(match[2])
		if op == nil {
			t.Errorf("trigger %s does not declare a BEFORE clause", match[1])
			continue
		}
		for _, part := range strings.Fields(op[1]) {
			found[part] = true
		}
	}

	for _, op := range []string{"UPDATE", "DELETE", "TRUNCATE"} {
		if !found[op] {
			t.Errorf("no append-only trigger refuses %s; a destructive statement could rewrite the evidence", op)
		}
	}
}

// The chain-link guard and the checkpoint-coverage guard are what make the stored data
// verifiable rather than merely append-only.
func TestTheMigrationEnforcesChainLinkageAndCheckpointCoverage(t *testing.T) {
	sql := migrationText(t)
	for _, fn := range []string{
		"CREATE FUNCTION audit_check_chain_link()",
		"CREATE CONSTRAINT TRIGGER audit_records_chain_link",
		"CREATE FUNCTION audit_check_checkpoint_coverage()",
		"CREATE CONSTRAINT TRIGGER audit_checkpoints_coverage",
	} {
		if !strings.Contains(sql, fn) {
			t.Errorf("the migration is missing %q", fn)
		}
	}
}

// The chain-link and coverage guards are constraint triggers, so they must be deferrable;
// otherwise a batch written in one transaction would be checked before its predecessors
// exist and could never be written at all.
func TestTheIntegrityTriggersAreDeferrable(t *testing.T) {
	sql := migrationText(t)
	for _, name := range []string{"audit_records_chain_link", "audit_checkpoints_coverage"} {
		re := regexp.MustCompile(`CREATE CONSTRAINT TRIGGER ` + name + `([\s\S]*?);`)
		match := re.FindStringSubmatch(sql)
		if match == nil {
			t.Errorf("could not find the declaration of %s", name)
			continue
		}
		if !strings.Contains(match[1], "DEFERRABLE INITIALLY DEFERRED") {
			t.Errorf("%s is not deferrable; a batch written in one transaction could never commit", name)
		}
	}
}
