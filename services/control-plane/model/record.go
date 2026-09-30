// Package model implements the model registry, its lifecycle, tool permissions, and the
// decision ledger required by gate G5.
//
// The package exists because docs/07 places model governance in the same authority class as
// the rest of the trading core: a model is a versioned object with an owner, a lineage, an
// approval, and a rollback, and every one of those is authoritative state. The research worker
// produces the artifacts; it does not decide what is registered, approved, or permitted. That
// boundary is the same one docs/01 section 5 draws for AI generally, and this package is where
// it is enforced for models rather than assumed of them.
//
// Three properties carry the design, and each is mechanical rather than procedural:
//
//  1. No model may authorize its own execution. A model is registered, evaluated, and
//     approved by actors who are not the model and not the author who built it. The lifecycle
//     in lifecycle.go makes this structural: the APPROVED and PROMOTED transitions accept only
//     human actors, and Approve additionally refuses an approval whose reviewer matches the
//     record's owner or author. docs/07 says research authors cannot self-approve for live
//     use; this package refuses more than that, because an approval signed by the author is
//     also refused, and the refusal is a property of the request rather than a review step.
//
//  2. Financial authority is never reachable from this package. A tool classified financial
//     can only be invoked through the Go command path, which is the deterministic path where
//     authorization and the Risk Engine veto apply. Nothing here places, amends, or cancels
//     an order, and the import test in structure_test.go enforces that by failing the build if
//     this package ever gains a dependency on the order or ledger packages.
//
//  3. Every decision is reconstructable from the record alone. A decision entry carries the
//     model id and version, the dataset fingerprint and code revision it was produced from,
//     the prompts, tool calls, and retrieved context identifiers that fed it, and the
//     content digests of all of them. A reader must never have to consult a mutable store to
//     learn what a model was told and what it did with that, because that is exactly the
//     information an investigation needs and exactly the information that decays.
//
// The lifecycle is a closed state machine taken verbatim from docs/07:
// REGISTERED -> EVALUATED -> VALIDATED -> APPROVED -> PAPER -> SHADOW -> PROMOTED ->
// MONITORED -> RETIRED.
package model

import (
	"errors"
	"fmt"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Digest is a content digest. It is a distinct type rather than a bare string so that a
// digest cannot be passed where a reference is expected, or vice versa, without a compile
// error. The distinction matters because lineage is only meaningful if a digest and a
// human-readable reference are not interchangeable: a digest proves what the bytes were, and
// a reference says where to find them.
type Digest string

// Valid reports whether the digest is a well-formed lowercase hex SHA-256.
func (d Digest) Valid() bool {
	if len(d) != 64 {
		return false
	}
	for i := 0; i < len(d); i++ {
		c := d[i]
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') {
			return false
		}
	}
	return true
}

// Sentinel errors. Each is wrapped by a Rejection so that errors.Is keeps working for
// in-process checks while the wire-facing error code stays machine-readable.
var (
	// ErrIncompleteRecord means a required field of the model record is absent.
	ErrIncompleteRecord = errors.New("model record is incomplete")
	// ErrSelfAuthorization means the approval or promotion actor is the party it
	// certifies, which separation of duties forbids.
	ErrSelfAuthorization = errors.New("actor may not authorize its own model")
	// ErrToolNotPermitted means a tool is outside the allowlist or is being invoked
	// through a path its class forbids.
	ErrToolNotPermitted = errors.New("tool invocation not permitted")
	// ErrUnverifiedDigest means a lineage field is not a well-formed content digest.
	ErrUnverifiedDigest = errors.New("lineage field is not a valid sha-256 digest")
	// ErrCompromised means the model or its producing workload has been marked
	// compromised and every promotion path is closed until it is cleared.
	ErrCompromised = errors.New("model is quarantined; promotion is blocked")
)

// Classification is a tool's authority class, from docs/07: "Tools are classified read-only,
// state-changing, or financial."
//
// The three are not a spectrum of convenience; they are three different blast radii, and the
// difference between state-changing and financial is the difference between changing the
// system's own bookkeeping and moving money.
type Classification string

// The closed set of tool classifications.
const (
	// ClassReadOnly observes state and changes nothing. It may be invoked by an agent
	// directly, because observing cannot cause a financial outcome.
	ClassReadOnly Classification = "READ_ONLY"
	// ClassStateChanging mutates internal state that is not itself financial: a dataset
	// version, a monitoring threshold, a registry entry.
	ClassStateChanging Classification = "STATE_CHANGING"
	// ClassFinancial can place, amend, or cancel an order, or otherwise move money or
	// exposure. It is invokable only through the Go command path.
	ClassFinancial Classification = "FINANCIAL"
)

var allClassifications = []Classification{
	ClassReadOnly, ClassStateChanging, ClassFinancial,
}

// Valid reports whether the classification is in the closed set.
func (c Classification) Valid() bool {
	for _, k := range allClassifications {
		if k == c {
			return true
		}
	}
	return false
}

// String satisfies fmt.Stringer.
func (c Classification) String() string { return string(c) }

// AllClassifications returns the closed set, ordered least to most authority. The order is
// the blast-radius order and is used to present an operator with a summary of what a given
// agent is permitted to touch.
func AllClassifications() []Classification {
	out := make([]Classification, len(allClassifications))
	copy(out, allClassifications)
	return out
}

// Record is the required model record from docs/07: "Every model has owner, version,
// training dataset fingerprint, code revision, feature specification, evaluation results,
// limitations, approval record, deployment scope, monitoring policy, and rollback artifact."
//
// Every field is required. There is deliberately no notion of a partial record, because a
// registry that accepts one is a registry that cannot answer whether a model is promotable,
// and "we did not record that" must fail loudly at registration rather than at the moment an
// operator is trying to promote a model that has been trading.
type Record struct {
	// ModelID is the canonical model identifier, which must carry the "mdl_" prefix.
	ModelID contracts.Identifier
	// Version is the immutable version string for this revision of the model. Two records
	// with the same ID and different versions are different models and must both be
	// retained; an in-place edit of a registered model is not a version.
	Version string
	// Owner is the human accountable for the model. Approval by this identity is refused.
	Owner string
	// Author is the identity that produced the model, which is a pipeline rather than a
	// person in normal operation. Approval by this identity is refused as self-approval.
	Author string
	// TrainingDatasetFingerprint is the content digest of the dataset the model was
	// trained on. It is what makes a model reproducible: without it, the same code revision
	// and the same weights are not the same model.
	TrainingDatasetFingerprint Digest
	// CodeRevision is the repository revision the model was built from.
	CodeRevision string
	// FeatureSpecification names the feature contract the model consumes. It is a name
	// rather than a document body so that the record stays a pointer to an immutable
	// artifact instead of a second copy that can drift from it.
	FeatureSpecification string
	// EvaluationResults is the digest of the evaluation report.
	EvaluationResults Digest
	// Limitations is the recorded statement of what the model does not do well. It is
	// required and may not be empty because a model with no recorded limitations has not
	// been assessed, and an unassessed model is one whose failure modes are unknown.
	Limitations string
	// ApprovalRecord is the digest of the approval artifact. It is empty until the model
	// reaches APPROVED, and non-empty afterwards; the lifecycle in lifecycle.go is what
	// requires it before that state may be entered.
	ApprovalRecord Digest
	// DeploymentScope bounds where the model may run. An empty scope would be an
	// unbounded deployment, so an empty value is rejected rather than defaulted.
	DeploymentScope string
	// MonitoringPolicy names the drift and degradation policy applied while the model is
	// live.
	MonitoringPolicy string
	// RollbackArtifact is the digest of the artifact that restores the prior known-good
	// state. A model that cannot be rolled back is a model that cannot be promoted, and
	// this is why the field is required at registration rather than at deployment.
	RollbackArtifact Digest
}

// requiredFields names the record fields that must be non-empty, in the order docs/07 lists
// them. The order is the document's, so a validation message reads in the same sequence a
// reader of the spec will find.
var requiredFields = []struct {
	name  string
	empty func(Record) bool
}{
	{"owner", func(r Record) bool { return strings.TrimSpace(r.Owner) == "" }},
	{"version", func(r Record) bool { return strings.TrimSpace(r.Version) == "" }},
	{"training_dataset_fingerprint", func(r Record) bool { return r.TrainingDatasetFingerprint == "" }},
	{"code_revision", func(r Record) bool { return strings.TrimSpace(r.CodeRevision) == "" }},
	{"feature_specification", func(r Record) bool { return strings.TrimSpace(r.FeatureSpecification) == "" }},
	{"evaluation_results", func(r Record) bool { return r.EvaluationResults == "" }},
	{"limitations", func(r Record) bool { return strings.TrimSpace(r.Limitations) == "" }},
	{"deployment_scope", func(r Record) bool { return strings.TrimSpace(r.DeploymentScope) == "" }},
	{"monitoring_policy", func(r Record) bool { return strings.TrimSpace(r.MonitoringPolicy) == "" }},
	{"rollback_artifact", func(r Record) bool { return r.RollbackArtifact == "" }},
}

// Validate checks that every required field of the required model record is present and
// well-formed.
//
// It returns the first problem it finds rather than collecting all of them, because a
// registration failure is fixed one field at a time and a list would only obscure which one
// is blocking.
func (r Record) Validate() error {
	if r.ModelID.IsZero() {
		return reject(contracts.CodeValidation, ErrIncompleteRecord, "model id is required")
	}
	if r.ModelID.Prefix() != contracts.PrefixModel {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"model id must carry the %q prefix, got %q",
			contracts.PrefixModel, r.ModelID.Prefix())
	}
	if strings.TrimSpace(r.Author) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord, "author is required")
	}
	for _, f := range requiredFields {
		if f.empty(r) {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"required model record field %q is empty; docs/07 requires owner, version, "+
					"training dataset fingerprint, code revision, feature specification, "+
					"evaluation results, limitations, approval record, deployment scope, "+
					"monitoring policy, and rollback artifact", f.name)
		}
	}
	// A digest that is present but malformed is a different failure from a digest that is
	// absent, and conflating them would let a truncated fingerprint pass as a recorded
	// one. Lineage is only evidence if the digest actually identifies bytes.
	for _, d := range []struct {
		name  string
		value Digest
	}{
		{"training_dataset_fingerprint", r.TrainingDatasetFingerprint},
		{"evaluation_results", r.EvaluationResults},
		{"rollback_artifact", r.RollbackArtifact},
	} {
		if !d.value.Valid() {
			return reject(contracts.CodeValidation, ErrUnverifiedDigest,
				"%s is not a valid sha-256 digest", d.name)
		}
	}
	// approval_record is excluded from the loop above because it is legitimately empty
	// before APPROVED. When it is present it must still be a real digest.
	if r.ApprovalRecord != "" && !r.ApprovalRecord.Valid() {
		return reject(contracts.CodeValidation, ErrUnverifiedDigest,
			"approval_record is not a valid sha-256 digest")
	}
	return nil
}

// Rejection is a refused registry operation.
//
// It carries two things that a single fmt.Errorf cannot. The canonical ErrorCode is the wire
// contract: a caller on another service needs to see AUTHORIZATION_ERROR rather than prose,
// and it is what the closed taxonomy in docs/03 requires. The wrapped sentinel is the local
// cause, so errors.Is keeps working for in-process checks.
type Rejection struct {
	// Code is the canonical error code from docs/03.
	Code contracts.ErrorCode
	// Cause is the local sentinel, reachable through errors.Is.
	Cause error
	// Reason is the human-facing explanation. Never parsed.
	Reason string
}

// Error satisfies error, leading with the code so a log consumer that pattern-matches on the
// stable part stays correct if the wording changes.
func (r Rejection) Error() string {
	return fmt.Sprintf("%s: %s", r.Code, r.Reason)
}

// Unwrap exposes the local sentinel to errors.Is and errors.As.
func (r Rejection) Unwrap() error { return r.Cause }

// reject builds a Rejection with a formatted reason.
func reject(code contracts.ErrorCode, cause error, format string, args ...any) Rejection {
	return Rejection{Code: code, Cause: cause, Reason: fmt.Sprintf(format, args...)}
}
