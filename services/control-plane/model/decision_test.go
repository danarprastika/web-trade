package model

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// validDecision builds a complete decision entry so a test can clear exactly one field and
// attribute the refusal to that field.
func validDecision(t *testing.T) Decision {
	t.Helper()
	return Decision{
		DecisionID:         mustRunID(t),
		ModelID:            mustModelID(t),
		ModelVersion:       "3.2.1",
		DatasetFingerprint: digestDataset,
		CodeRevision:       "9f3c1a7e5b2d8046af13c9e2b7d05f84a6c3e1d97b2a4f6c8e0d2b4a6f8c0e1d",
		PromptDigests:      []Digest{digestPrompt},
		Contexts:           []RetrievedContext{{Identifier: "ctx/feature-snapshot-41", Digest: digestContext}},
		ToolCalls: []ToolCall{{
			ToolName:        "market_data.read",
			Classification:  ClassReadOnly,
			Path:            PathDirect,
			ArgumentsDigest: digestArgs,
			Authorized:      true,
		}},
		ResultDigest: digestResult,
	}
}

// TestLineageIsReconstructable is the lineage half of acceptance criterion three.
//
// The property is that a decision explains itself from the record alone. Every field
// Validate requires is one an investigator would otherwise have to reconstruct from a
// mutable store, and the test clears each one in turn to prove that a decision with a hole
// in its lineage is refused rather than recorded partially.
func TestLineageIsReconstructable(t *testing.T) {
	if err := validDecision(t).Validate(); err != nil {
		t.Fatalf("a complete decision was refused: %v", err)
	}

	cases := map[string]func(*Decision){
		"no decision id":     func(d *Decision) { d.DecisionID = contracts.Identifier{} },
		"no model":           func(d *Decision) { d.ModelID = contracts.Identifier{} },
		"no model version":   func(d *Decision) { d.ModelVersion = "" },
		"no code revision":   func(d *Decision) { d.CodeRevision = "" },
		"no prompts":         func(d *Decision) { d.PromptDigests = nil },
		"no result digest":   func(d *Decision) { d.ResultDigest = "" },
		"bad dataset digest": func(d *Decision) { d.DatasetFingerprint = "not-a-digest" },
		"bad prompt digest": func(d *Decision) {
			d.PromptDigests = []Digest{"truncated"}
		},
		"context without identifier": func(d *Decision) {
			d.Contexts = []RetrievedContext{{Digest: digestContext}}
		},
		"context without digest": func(d *Decision) {
			d.Contexts = []RetrievedContext{{Identifier: "ctx/1"}}
		},
		"tool call without a name": func(d *Decision) {
			d.ToolCalls = []ToolCall{{Classification: ClassReadOnly, Path: PathDirect}}
		},
		"tool call with unknown classification": func(d *Decision) {
			d.ToolCalls = []ToolCall{{
				ToolName:       "x",
				Classification: Classification("MYSTERY"),
				Path:           PathDirect,
			}}
		},
		"refused call with no reason": func(d *Decision) {
			d.ToolCalls = []ToolCall{{
				ToolName:       "market_data.read",
				Classification: ClassReadOnly,
				Path:           PathDirect,
				Authorized:     false,
			}}
		},
	}
	for name, mutate := range cases {
		d := validDecision(t)
		mutate(&d)
		if err := d.Validate(); err == nil {
			t.Errorf("a decision with %s was accepted; a partial lineage entry is worse "+
				"than a missing one, because it reads as a decision with no tool calls "+
				"rather than as a decision whose tool calls were not captured", name)
		}
	}
}

// TestRefusedToolCallsAreRecordedWithTheirReason: a denial is a fact worth reconstructing,
// not an absence. The ledger must carry the canonical code so an investigator can see why
// the control plane said no without re-running the authorization.
func TestRefusedToolCallsAreRecordedWithTheirReason(t *testing.T) {
	d := validDecision(t)
	d.ToolCalls = append(d.ToolCalls, ToolCall{
		ToolName:        "order.submit",
		Classification:  ClassFinancial,
		Path:            PathDirect,
		ArgumentsDigest: digestArgs,
		Authorized:      false,
		RefusalCode:     contracts.CodeAuthorization,
	})
	if err := d.Validate(); err != nil {
		t.Fatalf("a decision recording a refused financial call was refused: %v", err)
	}
	if got := d.Lineage().RefusedCallCount; got != 1 {
		t.Errorf("lineage reports %d refused calls, want 1", got)
	}
}

// TestDecisionRejectsAnAuthorizedFinancialCallOffTheCommandPath is the second line of
// defence on the tool rule.
//
// Authorize already refuses a financial call on the direct path, so this is redundant by
// construction. It is here because a decision entry is assembled from several records,
// possibly by a component other than the one that authorized the call, and the ledger is
// what an investigation reads. If the two disagree, the ledger must not be the one believed.
func TestDecisionRejectsAnAuthorizedFinancialCallOffTheCommandPath(t *testing.T) {
	d := validDecision(t)
	d.ToolCalls = append(d.ToolCalls, ToolCall{
		ToolName:        "order.submit",
		Classification:  ClassFinancial,
		Path:            PathDirect,
		ArgumentsDigest: digestArgs,
		Authorized:      true,
	})
	if err := d.AssertNoFinancialAuthority(); err == nil {
		t.Error("a decision recording an authorized FINANCIAL call on the direct path was " +
			"accepted; the ledger and the authorization check disagree, and the refusal is " +
			"the correct response")
	}

	// The same call through the command path is fine and is reported as financial.
	d = validDecision(t)
	d.ToolCalls = append(d.ToolCalls, ToolCall{
		ToolName:        "order.submit",
		Classification:  ClassFinancial,
		Path:            PathGoCommand,
		ArgumentsDigest: digestArgs,
		Authorized:      true,
	})
	if err := d.AssertNoFinancialAuthority(); err != nil {
		t.Errorf("a decision recording an authorized financial call on the Go command path "+
			"was refused: %v", err)
	}
	if got := len(d.AuthorizedFinancialCalls()); got != 1 {
		t.Errorf("AuthorizedFinancialCalls returned %d, want 1", got)
	}
}

// TestRefusedFinancialCallsDoNotTripTheAuthorityAssertion: a denial is exactly what should
// happen, so recording one must not be treated as a contradiction.
func TestRefusedFinancialCallsDoNotTripTheAuthorityAssertion(t *testing.T) {
	d := validDecision(t)
	d.ToolCalls = append(d.ToolCalls, ToolCall{
		ToolName:        "order.submit",
		Classification:  ClassFinancial,
		Path:            PathDirect,
		ArgumentsDigest: digestArgs,
		Authorized:      false,
		RefusalCode:     contracts.CodeAuthorization,
	})
	if err := d.AssertNoFinancialAuthority(); err != nil {
		t.Errorf("a recorded refusal was treated as a contradiction: %v", err)
	}
	if got := len(d.AuthorizedFinancialCalls()); got != 0 {
		t.Errorf("a refused call was counted as an authorized financial call: %d", got)
	}
}

// TestLineageIsDerivedNotStored checks that Lineage summarizes the decision rather than
// restating it, so it cannot drift from what it describes.
func TestLineageIsDerivedNotStored(t *testing.T) {
	d := validDecision(t)
	before := d.Lineage()
	d.ToolCalls = append(d.ToolCalls, ToolCall{
		ToolName:        "market_data.read",
		Classification:  ClassReadOnly,
		Path:            PathDirect,
		ArgumentsDigest: digestArgs,
		Authorized:      true,
	})
	after := d.Lineage()
	if before.ToolCallCount != 1 || after.ToolCallCount != 2 {
		t.Errorf("lineage did not follow the decision: %d then %d tool calls",
			before.ToolCallCount, after.ToolCallCount)
	}
	if before.DecisionID != after.DecisionID {
		t.Error("lineage identity changed with the decision body")
	}
}

// TestLineageStringNamesItsProvenance: the rendered form is what an audit record carries,
// so it must mention the model, the dataset, the revision, and the call counts. A lineage
// that renders as an empty or truncated string is unreadable at exactly the moment it is
// needed.
func TestLineageStringNamesItsProvenance(t *testing.T) {
	s := validDecision(t).Lineage().String()
	for _, want := range []string{"run_", "mdl_", "3.2.1", string(digestDataset), "tool calls", "result"} {
		if !strings.Contains(s, want) {
			t.Errorf("lineage string omits %q: %s", want, s)
		}
	}
}

// TestDecisionMustNameAModelCarryingTheModelPrefix: a decision attributed to a strategy or
// an order is not a model decision, and the prefix is what distinguishes them.
func TestDecisionMustNameAModelCarryingTheModelPrefix(t *testing.T) {
	strategy, err := contracts.ParseIdentifier("str_" + modelBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	d := validDecision(t)
	d.ModelID = strategy
	if err := d.Validate(); err == nil {
		t.Error("a decision naming a non-model identifier was accepted")
	}
}

// TestDecisionIdMustCarryTheRunPrefix.
func TestDecisionIdMustCarryTheRunPrefix(t *testing.T) {
	d := validDecision(t)
	order, err := contracts.ParseIdentifier("ord_" + runBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	d.DecisionID = order
	if err := d.Validate(); err == nil {
		t.Error("a decision carrying an order identifier was accepted")
	}
}
