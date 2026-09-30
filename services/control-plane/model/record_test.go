package model

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// TestARecordWithEveryRequiredFieldIsAccepted is the positive control for the record
// tests. Without it, a suite that cleared every field in turn would also pass against a
// Validate that rejected everything.
func TestARecordWithEveryRequiredFieldIsAccepted(t *testing.T) {
	if err := setID(t, validRecord()).Validate(); err != nil {
		t.Fatalf("a complete model record was refused: %v", err)
	}
}

// TestEveryRequiredFieldIsEnforced walks the fields docs/07 lists and clears each one in
// turn. The specification names eleven; this is the mechanical form of that list, and the
// test is written as a table so that adding a field to the record without adding a case
// here is visible as a coverage gap rather than as a silently unenforced requirement.
func TestEveryRequiredFieldIsEnforced(t *testing.T) {
	cases := map[string]func(*Record){
		"owner":                        func(r *Record) { r.Owner = "" },
		"version":                      func(r *Record) { r.Version = "" },
		"training_dataset_fingerprint": func(r *Record) { r.TrainingDatasetFingerprint = "" },
		"code_revision":                func(r *Record) { r.CodeRevision = "" },
		"feature_specification":        func(r *Record) { r.FeatureSpecification = "" },
		"evaluation_results":           func(r *Record) { r.EvaluationResults = "" },
		"limitations":                  func(r *Record) { r.Limitations = "" },
		"deployment_scope":             func(r *Record) { r.DeploymentScope = "" },
		"monitoring_policy":            func(r *Record) { r.MonitoringPolicy = "" },
		"rollback_artifact":            func(r *Record) { r.RollbackArtifact = "" },
		"author":                       func(r *Record) { r.Author = "" },
	}
	if len(cases) != 11 {
		t.Errorf("the table covers %d fields; docs/07 lists eleven required record fields "+
			"plus the author this package also requires", len(cases))
	}
	for name, mutate := range cases {
		rec := validRecord()
		mutate(&rec)
		err := setID(t, rec).Validate()
		if err == nil {
			t.Errorf("a record with no %s was accepted", name)
			continue
		}
		// The message must name the field, because the operator fixing a registration
		// reads the error and not this table.
		if !strings.Contains(err.Error(), strings.ReplaceAll(name, "_", " ")) &&
			!strings.Contains(err.Error(), name) {
			t.Errorf("the refusal for a missing %s does not name the field: %v", name, err)
		}
	}
}

// TestApprovalRecordMayBeEmptyBeforeApproval: it is the one required field that is
// legitimately absent at registration. Treating it as required at registration would make
// the record unmovable, and treating it as optional at APPROVED would reopen the gap
// docs/07 closes with it.
func TestApprovalRecordMayBeEmptyBeforeApproval(t *testing.T) {
	rec := validRecord()
	if rec.ApprovalRecord != "" {
		t.Fatal("test setup: the record should carry no approval digest")
	}
	if err := setID(t, rec).Validate(); err != nil {
		t.Errorf("a pre-approval record with no approval digest was refused: %v", err)
	}

	// When present it must be a real digest.
	rec.ApprovalRecord = "truncated"
	if err := setID(t, rec).Validate(); err == nil {
		t.Error("a record with a malformed approval digest was accepted")
	}
}

// TestMalformedDigestsAreRejectedDistinctlyFromMissingOnes: a truncated fingerprint is a
// different failure from an absent one, and conflating them would let a truncated digest
// pass as a recorded one.
func TestMalformedDigestsAreRejectedDistinctlyFromMissingOnes(t *testing.T) {
	for name, mutate := range map[string]func(*Record){
		"dataset":  func(r *Record) { r.TrainingDatasetFingerprint = "truncated" },
		"eval":     func(r *Record) { r.EvaluationResults = "XYZ" },
		"rollback": func(r *Record) { r.RollbackArtifact = Digest(string(digestRollback)[:63]) },
		"uppercase is not hex": func(r *Record) {
			r.EvaluationResults = Digest(strings.ToUpper(string(digestEval)))
		},
	} {
		rec := validRecord()
		mutate(&rec)
		err := setID(t, rec).Validate()
		if err == nil {
			t.Errorf("a record with a malformed %s digest was accepted", name)
			continue
		}
		if !strings.Contains(err.Error(), "sha-256") {
			t.Errorf("the refusal for a malformed %s digest does not explain the problem: %v",
				name, err)
		}
	}
}

// TestModelIdMustCarryTheModelPrefix: a record that identifies itself as something else
// cannot be promoted, audited, or rolled back as a model.
func TestModelIdMustCarryTheModelPrefix(t *testing.T) {
	strategy, err := contracts.ParseIdentifier("str_" + modelBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	rec := validRecord()
	rec.ModelID = strategy
	if err := rec.Validate(); err == nil {
		t.Error("a record carrying a strategy identifier was accepted")
	}
}

// TestWhitespaceOnlyFieldsCountAsAbsent: a field of spaces satisfies a non-empty check
// written with != "" and produces a record that looks complete and is not.
func TestWhitespaceOnlyFieldsCountAsAbsent(t *testing.T) {
	for name, mutate := range map[string]func(*Record){
		"owner":             func(r *Record) { r.Owner = "   " },
		"limitations":       func(r *Record) { r.Limitations = "\t\n " },
		"deployment scope":  func(r *Record) { r.DeploymentScope = " " },
		"monitoring policy": func(r *Record) { r.MonitoringPolicy = "  " },
		"code revision":     func(r *Record) { r.CodeRevision = " " },
		"feature spec":      func(r *Record) { r.FeatureSpecification = " " },
	} {
		rec := validRecord()
		mutate(&rec)
		if err := setID(t, rec).Validate(); err == nil {
			t.Errorf("a record with a whitespace-only %s was accepted", name)
		}
	}
}

// TestLimitationsMustBeRecordedNotEmptyByDefault: a model with no recorded limitations has
// not been assessed, so an empty string is refused rather than defaulted to "none known".
func TestLimitationsMustBeRecordedNotEmptyByDefault(t *testing.T) {
	rec := validRecord()
	rec.Limitations = ""
	err := setID(t, rec).Validate()
	if err == nil {
		t.Fatal("a record with no limitations was accepted")
	}
	if !strings.Contains(err.Error(), "limitations") {
		t.Errorf("the refusal does not name limitations: %v", err)
	}
}

// TestDigestValidation: the shape rule itself, so a change to it is visible.
func TestDigestValidation(t *testing.T) {
	cases := map[string]struct {
		digest Digest
		valid  bool
	}{
		"64 hex":          {Digest(strings.Repeat("a", 64)), true},
		"63 hex":          {Digest(strings.Repeat("a", 63)), false},
		"65 hex":          {Digest(strings.Repeat("a", 65)), false},
		"uppercase":       {Digest(strings.Repeat("A", 64)), false},
		"non hex":         {Digest(strings.Repeat("g", 64)), false},
		"empty":           {Digest(""), false},
		"with whitespace": {Digest(" " + strings.Repeat("a", 63)), false},
	}
	for name, tc := range cases {
		if got := tc.digest.Valid(); got != tc.valid {
			t.Errorf("%s: Valid() = %t, want %t", name, got, tc.valid)
		}
	}
}
