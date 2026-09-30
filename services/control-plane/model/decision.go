package model

import (
	"fmt"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ToolCall is one tool invocation made while producing a decision.
//
// docs/07 section 6 requires that "Prompts, model versions, tool calls, retrieved context
// identifiers, and generated decisions are recorded for material trading decisions." A tool
// call is recorded as an immutable fact about what happened: which tool, which arguments,
// which path, and what the control plane decided. It is not a record of the tool's output,
// because the output belongs to whatever consumed it and is reproduced by the artifact
// digest that produced it.
type ToolCall struct {
	// ToolName is the tool that was invoked.
	ToolName string
	// Classification is the class the tool was evaluated as. It is recorded rather than
	// looked up because the classification is what the decision depended on at the time,
	// and a later reclassification must not rewrite history.
	Classification Classification
	// Path is how the tool was reached, which is load-bearing for a financial call: it
	// records that the call did or did not pass the Go command path.
	Path ToolInvocationPath
	// ArgumentsDigest is the digest of the arguments. The arguments themselves are not
	// stored in the ledger because they may contain data classified above the ledger's
	// retention; the digest identifies them for the investigator who holds the artifact.
	ArgumentsDigest Digest
	// Authorized records whether the control plane permitted the call.
	Authorized bool
	// RefusalCode is the canonical error code when Authorized is false, so the reason for
	// a denial is reconstructable without re-running the authorization.
	RefusalCode contracts.ErrorCode
}

// RetrievedContext identifies one piece of context supplied to the model.
//
// docs/07 section 6 names "retrieved context identifiers" specifically rather than
// retrieved context, and the distinction is the point: the ledger stores the identifier so
// a decision can be traced to its inputs, while the content itself stays under whatever
// classification and retention govern it. Copying the content into the ledger would make
// the audit trail the least-protected copy of the most sensitive data in the system.
type RetrievedContext struct {
	// Identifier is the content identifier of the retrieved item.
	Identifier string
	// Digest is the digest of the content at the moment it was retrieved.
	Digest Digest
}

// Decision is one recorded decision.
//
// It is designed to answer, from the record alone and without consulting anything mutable:
// which model, at which version, trained on which dataset, built from which code, was told
// what, was allowed to call what, and did what. Every field needed for that answer is either
// present or required to be present.
type Decision struct {
	// DecisionID is the canonical decision identifier, carrying the "run_" prefix.
	DecisionID contracts.Identifier
	// ModelID is the deciding model.
	ModelID contracts.Identifier
	// ModelVersion is the model version that decided. Recorded separately from ModelID
	// because a model is versioned immutably and a decision must name which revision of it
	// acted.
	ModelVersion string
	// DatasetFingerprint is the training dataset the deciding model was built from. It is
	// copied from the record rather than referenced so that a decision is still explainable
	// if the registry entry is later quarantined or archived.
	DatasetFingerprint Digest
	// CodeRevision is the revision the model was built from.
	CodeRevision string
	// PromptDigests are the digests of the prompts used, in order. A digest and not the
	// text, for the reason given on RetrievedContext: the prompt may contain context the
	// ledger is not cleared to hold.
	PromptDigests []Digest
	// Contexts are the retrieved context identifiers supplied to the model.
	Contexts []RetrievedContext
	// ToolCalls are the tools invoked, in order.
	ToolCalls []ToolCall
	// ResultDigest is the digest of the decision output.
	ResultDigest Digest
}

// Validate checks that a decision entry is complete enough to be reconstructable.
//
// The rule this enforces is that a decision whose lineage has a hole is not recorded at all,
// rather than recorded partially. A partial lineage entry is worse than a missing one,
// because it will be read as though it described a decision with no tool calls, when in
// fact the tool calls were simply not captured.
func (d Decision) Validate() error {
	if d.DecisionID.IsZero() {
		return reject(contracts.CodeValidation, ErrIncompleteRecord, "decision id is required")
	}
	if d.DecisionID.Prefix() != contracts.PrefixRun {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"decision id must carry the %q prefix, got %q",
			contracts.PrefixRun, d.DecisionID.Prefix())
	}
	if d.ModelID.IsZero() || d.ModelID.Prefix() != contracts.PrefixModel {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"decision must name the model that made it, carrying the %q prefix",
			contracts.PrefixModel)
	}
	if strings.TrimSpace(d.ModelVersion) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"decision must record the model version; a decision attributable only to a "+
				"model id cannot be tied to an immutable revision")
	}
	if !d.DatasetFingerprint.Valid() {
		return reject(contracts.CodeValidation, ErrUnverifiedDigest,
			"decision dataset_fingerprint is not a valid sha-256 digest")
	}
	if strings.TrimSpace(d.CodeRevision) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"decision must record the code revision the model was built from")
	}
	if len(d.PromptDigests) == 0 {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"decision must record at least one prompt digest; a decision with no recorded "+
				"prompt cannot be reconstructed or challenged")
	}
	for i, p := range d.PromptDigests {
		if !p.Valid() {
			return reject(contracts.CodeValidation, ErrUnverifiedDigest,
				"prompt digest at index %d is not a valid sha-256 digest", i)
		}
	}
	for i, c := range d.Contexts {
		if strings.TrimSpace(c.Identifier) == "" {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"retrieved context at index %d has no identifier", i)
		}
		if !c.Digest.Valid() {
			return reject(contracts.CodeValidation, ErrUnverifiedDigest,
				"retrieved context %q digest is not a valid sha-256 digest", c.Identifier)
		}
	}
	for i, call := range d.ToolCalls {
		if strings.TrimSpace(call.ToolName) == "" {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"tool call at index %d has no tool name", i)
		}
		if !call.Classification.Valid() {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"tool call %q records unknown classification %q",
				call.ToolName, call.Classification)
		}
		if !call.Path.Valid() {
			return reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
				"tool call %q records unknown invocation path %q", call.ToolName, call.Path)
		}
		if !call.Authorized && call.RefusalCode == "" {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"tool call %q was refused but records no refusal code; a denial without a "+
					"reason is not reconstructable", call.ToolName)
		}
	}
	if !d.ResultDigest.Valid() {
		return reject(contracts.CodeValidation, ErrUnverifiedDigest,
			"decision result digest is not a valid sha-256 digest")
	}
	return nil
}

// AssertNoFinancialAuthority is a final check on a decision before it is recorded.
//
// It refuses a decision that records an authorized financial tool call which did not come
// through the Go command path, and it does so even though Authorize already refuses that
// combination at call time.
//
// The redundancy is intentional and is the only place in this package where a check exists
// purely as a second line. A decision entry is assembled from several records, possibly by a
// different component from the one that authorized the call, and the ledger is what an
// investigation reads. If the two disagree, the ledger must not be the one that is believed.
// A financial tool call appearing in a recorded decision without the command path would
// mean the two disagree, and the correct response is to refuse to record the decision rather
// than to record one that reads as though the control plane had approved an order.
func (d Decision) AssertNoFinancialAuthority() error {
	for i, call := range d.ToolCalls {
		if !call.Authorized {
			continue
		}
		if call.Classification == ClassFinancial && call.Path != PathGoCommand {
			return reject(contracts.CodeAuthorization, ErrToolNotPermitted,
				"decision %s records an authorized FINANCIAL tool call to %q on the %s path "+
					"at index %d; an authorized financial call must record the Go command path, "+
					"and a disagreement between the ledger and the authorization check is "+
					"refused rather than recorded",
				d.DecisionID, call.ToolName, call.Path, i)
		}
	}
	return nil
}

// AuthorizedFinancialCalls returns the financial tool calls in a decision that were
// authorized. It exists so a governance view can assert that every such call went through
// the command path without re-implementing the rule.
func (d Decision) AuthorizedFinancialCalls() []ToolCall {
	var out []ToolCall
	for _, c := range d.ToolCalls {
		if c.Authorized && c.Classification == ClassFinancial {
			out = append(out, c)
		}
	}
	return out
}

// Lineage is a reconstructable summary of what a decision was made from.
type Lineage struct {
	DecisionID         contracts.Identifier
	ModelID            contracts.Identifier
	ModelVersion       string
	DatasetFingerprint Digest
	CodeRevision       string
	PromptCount        int
	ContextCount       int
	ToolCallCount      int
	RefusedCallCount   int
	ResultDigest       Digest
}

// Lineage reduces a decision to its provenance, without the prompt and context contents.
//
// It is what a reviewer reads to answer "where did this come from" and what a rollback
// decision reads to answer "what else might this have influenced". It is derived rather
// than stored so that it cannot drift from the decision it summarizes.
func (d Decision) Lineage() Lineage {
	refused := 0
	for _, c := range d.ToolCalls {
		if !c.Authorized {
			refused++
		}
	}
	return Lineage{
		DecisionID:         d.DecisionID,
		ModelID:            d.ModelID,
		ModelVersion:       d.ModelVersion,
		DatasetFingerprint: d.DatasetFingerprint,
		CodeRevision:       d.CodeRevision,
		PromptCount:        len(d.PromptDigests),
		ContextCount:       len(d.Contexts),
		ToolCallCount:      len(d.ToolCalls),
		RefusedCallCount:   refused,
		ResultDigest:       d.ResultDigest,
	}
}

// String renders a lineage for an audit record.
func (l Lineage) String() string {
	return fmt.Sprintf(
		"decision %s by model %s@%s (dataset %s, revision %s, %d prompts, %d contexts, "+
			"%d tool calls of which %d refused, result %s)",
		l.DecisionID, l.ModelID, l.ModelVersion, l.DatasetFingerprint, l.CodeRevision,
		l.PromptCount, l.ContextCount, l.ToolCallCount, l.RefusedCallCount, l.ResultDigest)
}
