package model

import (
	"sort"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ToolInvocationPath is how a tool is being reached. It is a parameter of authorization
// rather than an incident-report detail, because the same tool is permitted or refused
// depending on which path reaches it.
type ToolInvocationPath string

// The closed set of invocation paths.
const (
	// PathDirect is an agent or UI calling the tool in-process. This is the only path
	// available to anything outside the Go command path.
	PathDirect ToolInvocationPath = "DIRECT"
	// PathGoCommand is the deterministic Go command path, where the caller's
	// authorization and the Risk Engine veto are both evaluated before the tool runs.
	PathGoCommand ToolInvocationPath = "GO_COMMAND"
)

var allPaths = []ToolInvocationPath{PathDirect, PathGoCommand}

// Valid reports whether the path is in the closed set.
func (p ToolInvocationPath) Valid() bool {
	for _, k := range allPaths {
		if k == p {
			return true
		}
	}
	return false
}

// Tool is a named capability an agent may be granted.
type Tool struct {
	// Name is the stable tool identifier, used in the allowlist and in the decision ledger.
	Name string
	// Classification is the authority class from docs/07 section 5.
	Classification Classification
	// Description is a human-facing summary recorded in the audit trail. It is required
	// because an allowlist of bare names is unreadable during an incident, and the reader
	// at that moment is usually a human who did not write it.
	Description string
}

// Allowlist is the explicit set of tools an agent or workload may invoke.
//
// docs/07 section 5: "AI agents use an explicit tool allowlist." The word explicit is load-
// bearing and is why this is a list rather than a classification or a default: anything not
// named here is denied, and a new tool class added to the system is denied until somebody
// writes it into somebody's allowlist on purpose.
type Allowlist struct {
	// SubjectID is the agent or workload the list binds. It is part of the allowlist
	// because an allowlist without an owner is a list nobody can revoke.
	SubjectID string
	// SubjectType is the kind of identity, which decides whether the list may contain
	// financial tools at all.
	SubjectType contracts.ActorType
	// Tools is the permitted set, deduplicated by name on construction.
	Tools []Tool
}

// NewAllowlist builds an allowlist, rejecting a subject that is empty and deduplicating
// tools by name.
//
// A nil or empty tool set is valid and means the subject may invoke nothing. That is a
// meaningful state, not an error: a worker whose permissions have been revoked holds an
// empty allowlist rather than having the allowlist deleted, so the revocation is
// represented in the audit trail as a transition rather than as an absence.
func NewAllowlist(subjectID string, subjectType contracts.ActorType, tools []Tool) (*Allowlist, error) {
	if strings.TrimSpace(subjectID) == "" {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"allowlist subject_id is required; an allowlist with no subject cannot be revoked")
	}
	if subjectType == "" {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"allowlist subject_type is required")
	}
	for _, t := range tools {
		if strings.TrimSpace(t.Name) == "" {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"allowlist for %s contains a tool with no name", subjectID)
		}
		if !t.Classification.Valid() {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"tool %q declares unknown classification %q; unknown classes are unsupported, "+
					"not treated as read-only", t.Name, t.Classification)
		}
		if strings.TrimSpace(t.Description) == "" {
			return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
				"tool %q has no description; an allowlist of bare names is not reviewable", t.Name)
		}
	}

	byName := make(map[string]Tool, len(tools))
	order := make([]string, 0, len(tools))
	for _, t := range tools {
		if _, exists := byName[t.Name]; exists {
			// A duplicate with a different classification is a real conflict and is
			// refused rather than resolved, because silently taking one of the two would
			// decide an authority question by iteration order.
			if byName[t.Name].Classification != t.Classification {
				return nil, reject(contracts.CodeAuthorization, ErrToolNotPermitted,
					"tool %q appears twice in the allowlist for %s with conflicting "+
						"classifications %s and %s", t.Name, subjectID,
					byName[t.Name].Classification, t.Classification)
			}
			continue
		}
		byName[t.Name] = t
		order = append(order, t.Name)
	}
	sort.Strings(order)
	out := make([]Tool, 0, len(order))
	for _, n := range order {
		out = append(out, byName[n])
	}
	return &Allowlist{SubjectID: subjectID, SubjectType: subjectType, Tools: out}, nil
}

// Permits reports whether the allowlist names the tool, without considering the path.
func (a *Allowlist) Permits(name string) bool {
	for _, t := range a.Tools {
		if t.Name == name {
			return true
		}
	}
	return false
}

// Lookup returns the named tool if the allowlist carries it.
func (a *Allowlist) Lookup(name string) (Tool, bool) {
	for _, t := range a.Tools {
		if t.Name == name {
			return t, true
		}
	}
	return Tool{}, false
}

// ToolRequest is a proposed tool invocation.
type ToolRequest struct {
	// SubjectID is the agent or workload attempting the call. It must equal the
	// allowlist's subject; a list is not transferable between identities.
	SubjectID string
	// ToolName is the tool being invoked.
	ToolName string
	// Path is how the tool is being reached.
	Path ToolInvocationPath
	// ArgumentsDigest is a digest of the call arguments, recorded in the decision ledger.
	// The arguments themselves are not required here; the ledger entry carries them.
	ArgumentsDigest Digest
}

// Authorization is the outcome of evaluating a tool request.
type Authorization struct {
	// Tool is the authorized tool, when permitted.
	Tool Tool
	// RequiresRiskVeto reports whether the invocation must additionally clear the
	// deterministic Risk Engine before it executes. It is true exactly for a financial
	// tool reached through the Go command path, and it is the only circumstance in which
	// this package asserts anything about risk.
	RequiresRiskVeto bool
	// Path is the authorized path.
	Path ToolInvocationPath
}

// Authorize evaluates a tool request against an allowlist.
//
// docs/07 section 5 states the rule this implements: "Financial tools can only be invoked
// through the Go command path and therefore pass normal authorization and risk controls."
// The word "therefore" is the whole point. The Go command path is not a formality that
// financial tools are routed through as a formality; it is what causes authorization and
// the Risk Engine veto to apply, so a financial tool reached any other way has, by
// definition, reached execution without them.
//
// The two refusals below are therefore distinct and both necessary:
//
//   - a financial tool on PathDirect is refused, because nothing evaluated authorization
//     or risk on the way in;
//   - a tool absent from the allowlist is refused regardless of path, because the allowlist
//     is explicit and an unnamed tool is denied.
//
// The order matters. A financial tool reached directly by a subject that does not have it
// on its list is refused for not being on the list, which is the more fundamental of the
// two reasons and the one whose fix is the same in either case: do not grant it.
func Authorize(list *Allowlist, req ToolRequest) (Authorization, error) {
	if list == nil {
		return Authorization{}, reject(contracts.CodeAuthorization, ErrToolNotPermitted,
			"no allowlist for subject %q; every tool is denied without an explicit grant",
			req.SubjectID)
	}
	if strings.TrimSpace(req.SubjectID) == "" {
		return Authorization{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"subject_id is required on a tool request")
	}
	if list.SubjectID != req.SubjectID {
		return Authorization{}, reject(contracts.CodeAuthorization, ErrToolNotPermitted,
			"allowlist belongs to %q but the request is from %q; an allowlist is not "+
				"transferable between identities", list.SubjectID, req.SubjectID)
	}
	if !req.Path.Valid() {
		return Authorization{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"invocation path %q is not one of %s; an unknown path is not treated as direct",
			req.Path, describePaths())
	}

	tool, ok := list.Lookup(req.ToolName)
	if !ok {
		return Authorization{}, reject(contracts.CodeAuthorization, ErrToolNotPermitted,
			"tool %q is not on the allowlist for %s; the allowlist is explicit and an "+
				"unnamed tool is denied", req.ToolName, list.SubjectID)
	}

	if tool.Classification == ClassFinancial && req.Path != PathGoCommand {
		return Authorization{}, reject(contracts.CodeAuthorization, ErrToolNotPermitted,
			"tool %q is FINANCIAL and was invoked on the %s path; financial tools may only be "+
				"invoked through the Go command path, which is what subjects them to "+
				"authorization and the risk veto (docs/07)",
			tool.Name, req.Path)
	}

	return Authorization{
		Tool:             tool,
		RequiresRiskVeto: tool.Classification == ClassFinancial && req.Path == PathGoCommand,
		Path:             req.Path,
	}, nil
}

// PermitsFinancial reports whether the allowlist grants any financial tool. It exists so a
// governance view can answer "does this subject hold financial authority" without
// reconstructing it from the tool list.
func (a *Allowlist) PermitsFinancial() bool {
	for _, t := range a.Tools {
		if t.Classification == ClassFinancial {
			return true
		}
	}
	return false
}

// Revoke returns an empty allowlist for the same subject.
//
// Revocation is modelled as a new empty allowlist rather than as a nil one, so that the
// decision ledger and the audit chain both carry a record that a permission was removed and
// when. A deleted allowlist is indistinguishable from one that never existed, and the
// question an investigation asks is when the permission went away.
func (a *Allowlist) Revoke(reason string) (*Allowlist, error) {
	if strings.TrimSpace(reason) == "" {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"a revocation requires a reason; an unattributed revocation is not auditable")
	}
	return &Allowlist{SubjectID: a.SubjectID, SubjectType: a.SubjectType, Tools: []Tool{}}, nil
}

func describePaths() string {
	parts := make([]string, 0, len(allPaths))
	for _, p := range allPaths {
		parts = append(parts, string(p))
	}
	return strings.Join(parts, ", ")
}
