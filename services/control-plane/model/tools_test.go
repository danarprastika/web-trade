package model

import (
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

func toolRead(t *testing.T) Tool {
	t.Helper()
	return Tool{
		Name:           "market_data.read",
		Classification: ClassReadOnly,
		Description:    "Read normalized market data for the symbols in the current scope.",
	}
}

func toolState(t *testing.T) Tool {
	t.Helper()
	return Tool{
		Name:           "dataset.version.write",
		Classification: ClassStateChanging,
		Description:    "Register a new immutable dataset version.",
	}
}

func toolFinancial(t *testing.T) Tool {
	t.Helper()
	return Tool{
		Name:           "order.submit",
		Classification: ClassFinancial,
		Description:    "Submit an order to the OMS through the Go command path.",
	}
}

func mustAllowlist(t *testing.T, subject string, subjectType contracts.ActorType, tools ...Tool) *Allowlist {
	t.Helper()
	list, err := NewAllowlist(subject, subjectType, tools)
	if err != nil {
		t.Fatalf("NewAllowlist: %v", err)
	}
	return list
}

// TestFinancialToolIsRefusedOnTheDirectPath is the tool permission-denial half of
// acceptance criterion three, and the single most important behaviour in this file.
//
// docs/07 section 5: "Financial tools can only be invoked through the Go command path and
// therefore pass normal authorization and risk controls." The refusal is what makes the
// "therefore" true. If a financial tool could be reached directly, it would execute without
// either authorization or the risk veto, and the sentence in the specification would
// describe an intention rather than a mechanism.
func TestFinancialToolIsRefusedOnTheDirectPath(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, toolFinancial(t))

	for _, path := range []ToolInvocationPath{PathDirect} {
		_, err := Authorize(list, ToolRequest{
			SubjectID:       "agent-alpha",
			ToolName:        "order.submit",
			Path:            path,
			ArgumentsDigest: digestArgs,
		})
		if err == nil {
			t.Errorf("financial tool authorized on the %s path", path)
		}
	}

	// The same tool through the Go command path is permitted, and carries the risk veto.
	out, err := Authorize(list, ToolRequest{
		SubjectID:       "agent-alpha",
		ToolName:        "order.submit",
		Path:            PathGoCommand,
		ArgumentsDigest: digestArgs,
	})
	if err != nil {
		t.Fatalf("financial tool refused on the Go command path: %v", err)
	}
	if !out.RequiresRiskVeto {
		t.Error("an authorized financial tool call did not require the risk veto; the Go " +
			"command path is what subjects it to the Risk Engine, and dropping the flag " +
			"would drop the veto")
	}
}

// TestUnnamedToolsAreDenied is the explicit-allowlist property. Anything not named is
// denied, so a tool added to the system is inert until somebody grants it on purpose.
func TestUnnamedToolsAreDenied(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, toolRead(t))
	for _, name := range []string{"order.submit", "dataset.version.write", "anything.at.all"} {
		if _, err := Authorize(list, ToolRequest{
			SubjectID: "agent-alpha",
			ToolName:  name,
			Path:      PathGoCommand,
		}); err == nil {
			t.Errorf("tool %q was authorized but is not on the allowlist", name)
		}
	}
}

// TestAnEmptyAllowlistDeniesEverything: revocation is modelled as an empty list rather
// than a deleted one, so a revoked worker holds an empty allowlist and every call fails.
func TestAnEmptyAllowlistDeniesEverything(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent)
	if list.Permits("market_data.read") {
		t.Error("an empty allowlist permits a tool")
	}
	if _, err := Authorize(list, ToolRequest{
		SubjectID: "agent-alpha",
		ToolName:  "market_data.read",
		Path:      PathDirect,
	}); err == nil {
		t.Error("an empty allowlist authorized a read-only tool")
	}
}

// TestNilAllowlistDeniesEverything: a caller with no allowlist is not a caller with all
// permissions.
func TestNilAllowlistDeniesEverything(t *testing.T) {
	if _, err := Authorize(nil, ToolRequest{
		SubjectID: "agent-alpha",
		ToolName:  "market_data.read",
		Path:      PathDirect,
	}); err == nil {
		t.Error("a nil allowlist authorized a tool call")
	}
}

// TestAllowlistIsNotTransferableBetweenIdentities: an allowlist bound to one subject must
// not be usable by another, even with the same tools.
func TestAllowlistIsNotTransferableBetweenIdentities(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, toolRead(t))
	if _, err := Authorize(list, ToolRequest{
		SubjectID: "agent-beta",
		ToolName:  "market_data.read",
		Path:      PathDirect,
	}); err == nil {
		t.Error("agent-beta used agent-alpha's allowlist; permissions are bound to an identity")
	}
}

// TestReadOnlyToolsNeedNoRiskVeto: only a financial call through the command path obliges
// the veto, and asserting so keeps a future change from making every call risky, which
// would make the flag meaningless.
func TestReadOnlyToolsNeedNoRiskVeto(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, toolRead(t), toolState(t))
	for _, name := range []string{"market_data.read", "dataset.version.write"} {
		out, err := Authorize(list, ToolRequest{
			SubjectID: "agent-alpha",
			ToolName:  name,
			Path:      PathDirect,
		})
		if err != nil {
			t.Errorf("non-financial tool %q refused: %v", name, err)
			continue
		}
		if out.RequiresRiskVeto {
			t.Errorf("non-financial tool %q required the risk veto", name)
		}
	}
}

// TestStateChangingToolsAreInvokableDirectly: docs/07 classifies them as a middle class,
// and the rule is only that financial tools need the command path. Refusing them would be
// over-restrictive and would push the system toward routing everything through the command
// path, which is not what the specification says.
func TestStateChangingToolsAreInvokableDirectly(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, toolState(t))
	if _, err := Authorize(list, ToolRequest{
		SubjectID: "agent-alpha",
		ToolName:  "dataset.version.write",
		Path:      PathDirect,
	}); err != nil {
		t.Errorf("a state-changing tool was refused on the direct path: %v", err)
	}
}

// TestUnknownClassificationIsRejectedAtConstruction: an unrecognised class must not be
// treated as read-only, because that default would grant a tool authority nobody classified.
func TestUnknownClassificationIsRejectedAtConstruction(t *testing.T) {
	_, err := NewAllowlist("agent-alpha", contracts.ActorAgent, []Tool{{
		Name:           "mystery.tool",
		Classification: Classification("SEEMS_FINE"),
		Description:    "A tool nobody classified.",
	}})
	if err == nil {
		t.Error("a tool with an unknown classification was accepted; unknown classes are " +
			"unsupported, not treated as read-only")
	}
}

// TestConflictingDuplicateToolsAreRefused: a duplicate with a different classification is an
// authority conflict and must be refused rather than resolved by iteration order.
func TestConflictingDuplicateToolsAreRefused(t *testing.T) {
	// The two entries must share a name, or there is no conflict to detect. Building the
	// conflict from toolRead and toolFinancial would test nothing, because they are
	// different tools.
	read := toolRead(t)
	financial := toolFinancial(t)
	financial.Name = read.Name

	_, err := NewAllowlist("agent-alpha", contracts.ActorAgent, []Tool{read, financial})
	if err == nil {
		t.Error("a tool listed twice with conflicting classifications was accepted")
	}
	// An identical duplicate is harmless and is deduplicated.
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, read, read)
	if len(list.Tools) != 1 {
		t.Errorf("identical duplicate tools were not deduplicated: %d entries", len(list.Tools))
	}
}

// TestToolsWithoutDescriptionsAreRejected: an allowlist of bare names is not reviewable,
// and the allowlist is the artifact a reviewer reads.
func TestToolsWithoutDescriptionsAreRejected(t *testing.T) {
	_, err := NewAllowlist("agent-alpha", contracts.ActorAgent, []Tool{{
		Name:           "market_data.read",
		Classification: ClassReadOnly,
	}})
	if err == nil {
		t.Error("a tool with no description was accepted")
	}
}

// TestAnonymousAllowlistsAreRejected: an allowlist with no subject cannot be revoked.
func TestAnonymousAllowlistsAreRejected(t *testing.T) {
	for _, subject := range []string{"", "   "} {
		if _, err := NewAllowlist(subject, contracts.ActorAgent, nil); err == nil {
			t.Errorf("an allowlist with subject %q was accepted", subject)
		}
	}
}

// TestRevocationProducesAnEmptyAllowlistAndRequiresAReason: the reason requirement is what
// makes the revocation auditable, and the empty list is what makes it effective.
func TestRevocationProducesAnEmptyAllowlistAndRequiresAReason(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, toolRead(t), toolFinancial(t))
	if !list.PermitsFinancial() {
		t.Fatal("test setup: the allowlist should hold a financial tool")
	}

	if _, err := list.Revoke(""); err == nil {
		t.Error("a revocation with no reason was accepted; an unattributed revocation is " +
			"not auditable")
	}

	revoked, err := list.Revoke("workload identity suspected compromised")
	if err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	if revoked.PermitsFinancial() || revoked.Permits("market_data.read") {
		t.Error("a revoked allowlist still permits a tool")
	}
	if revoked.SubjectID != list.SubjectID {
		t.Error("revocation changed the subject; the identity must be retained so the " +
			"revocation is attributable")
	}
	if _, err := Authorize(revoked, ToolRequest{
		SubjectID: "agent-alpha",
		ToolName:  "market_data.read",
		Path:      PathGoCommand,
	}); err == nil {
		t.Error("a revoked allowlist authorized a tool call")
	}
}

// TestUnknownInvocationPathIsNotTreatedAsDirect: an unrecognised path must be refused
// rather than defaulted, because the default for a financial tool is the safe answer and
// the default for an unrecognised one is unknown.
func TestUnknownInvocationPathIsNotTreatedAsDirect(t *testing.T) {
	list := mustAllowlist(t, "agent-alpha", contracts.ActorAgent, toolRead(t))
	if _, err := Authorize(list, ToolRequest{
		SubjectID: "agent-alpha",
		ToolName:  "market_data.read",
		Path:      ToolInvocationPath("SOME_OTHER_PATH"),
	}); err == nil {
		t.Error("an unknown invocation path was accepted")
	}
}
