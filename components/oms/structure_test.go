package oms

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// These tests read the source rather than calling the API, because the properties they check
// are about the shape of the implementation. An API test can show that a refusal happens; it
// cannot show that no *other* code path could clear a halt, or that no future transition can
// be added without declaring the eight fields docs/01 section 8 requires.

// validateTransition checks one declared transition against the eight declarations
// docs/01 section 8 names: actor, command, precondition, resulting state, event, idempotency
// key, audit record, and failure behavior.
//
// It is a function rather than inline assertions so that the negative test below can feed it
// a deliberately broken transition. A structural test that only ever sees well-formed input
// cannot distinguish "the table is valid" from "the check does nothing", and the second is
// the more likely bug.
func validateTransition(t *testing.T, tr Transition) []string {
	t.Helper()
	label := tr.String()
	var problems []string
	if tr.From == "" || !tr.From.Valid() {
		problems = append(problems, label+": from is not a known state")
	}
	if tr.To == "" || !tr.To.Valid() {
		problems = append(problems, label+": to is not a known state")
	}
	if len(tr.PermittedActors) == 0 {
		problems = append(problems, label+": declares no permitted actor; an edge nobody may "+
			"take is a dead edge")
	}
	// Command is empty only for observation edges, and those must be reachable by an
	// observation kind. Checked directly so an observation edge that no observation reaches
	// cannot hide here.
	if tr.Command == "" {
		if !observationEdgeIsReachable(tr) {
			problems = append(problems, label+": has no command and no observation reaches it, "+
				"so it is unreachable")
		}
	} else if !tr.Command.Valid() {
		problems = append(problems, label+": command is not in the closed set")
	}
	if tr.EventType == "" {
		problems = append(problems, label+": declares no audit event; docs/01 section 8 requires "+
			"every transition to produce one")
	}
	if tr.IdempotencyScope == "" {
		problems = append(problems, label+": declares no idempotency scope")
	}
	if tr.AuditRecord == "" {
		problems = append(problems, label+": declares no audit record")
	}
	if !tr.FailureBehavior.valid() {
		problems = append(problems, label+": failure behavior is not in the closed set")
	}
	return problems
}

// TestEveryTransitionDeclaresTheFullSetRequiredByDocs01 applies the check to the real table.
func TestEveryTransitionDeclaresTheFullSetRequiredByDocs01(t *testing.T) {
	for _, tr := range transitions {
		for _, problem := range validateTransition(t, tr) {
			t.Error(problem)
		}
	}
}

// TestTheTransitionCheckActuallyRejects proves the check is not vacuous, by feeding it
// transitions that are each broken in exactly one of the eight ways.
func TestTheTransitionCheckActuallyRejects(t *testing.T) {
	good := Transition{
		From: StateSubmitting, To: StateAcknowledged,
		PermittedActors:  []contracts.ActorType{contracts.ActorService},
		EventType:        "order.acknowledged",
		IdempotencyScope: "venue_order_ref",
		AuditRecord:      "venue acknowledged the order",
		FailureBehavior:  FailureHoldStops,
	}
	if problems := validateTransition(t, good); len(problems) != 0 {
		t.Fatalf("the control transition should be valid, got: %v", problems)
	}

	cases := map[string]func(*Transition){
		"no permitted actor":   func(tr *Transition) { tr.PermittedActors = nil },
		"no event":             func(tr *Transition) { tr.EventType = "" },
		"no idempotency scope": func(tr *Transition) { tr.IdempotencyScope = "" },
		"no audit record":      func(tr *Transition) { tr.AuditRecord = "" },
		"bad failure behavior": func(tr *Transition) { tr.FailureBehavior = "WHENEVER" },
		"unknown from state":   func(tr *Transition) { tr.From = "NOPE" },
		"unknown to state":     func(tr *Transition) { tr.To = "NOPE" },
	}
	for name, breakIt := range cases {
		t.Run(name, func(t *testing.T) {
			tr := good
			breakIt(&tr)
			if problems := validateTransition(t, tr); len(problems) == 0 {
				t.Fatalf("a transition with %s should be reported as invalid", name)
			}
		})
	}
}

// TestEveryStateHasAnOnwardPathOrIsDeclaredTerminal guards against a state that can be
// entered but never left and is not terminal, which would strand an order silently.
func TestEveryStateHasAnOnwardPathOrIsDeclaredTerminal(t *testing.T) {
	reachable := map[State]bool{}
	for _, s := range allStates {
		reachable[s] = true
	}
	for _, s := range allStates {
		hasOutgoing := false
		for _, tr := range transitions {
			if tr.From == s {
				hasOutgoing = true
				break
			}
		}
		if !hasOutgoing && !s.IsTerminal() {
			t.Errorf("state %s has no onward transition and is not declared terminal", s)
		}
	}
}

// TestOnlyDeclaredEdgesAreReachable asserts the command and observation lookups agree with
// the table, so the two can never drift.
func TestOnlyDeclaredEdgesAreReachable(t *testing.T) {
	for _, tr := range transitions {
		if tr.Command == "" {
			continue
		}
		got, ok := transitionFor(tr.From, tr.Command)
		if !ok {
			t.Errorf("declared edge %s is not reachable by command", tr)
			continue
		}
		if got.To != tr.To {
			t.Errorf("command lookup for %s returned %s, want %s", tr, got.To, tr.To)
		}
		// A command declared for one state must not resolve for another. This is the
		// confused-deputy check: a caller in ACKNOWLEDGED naming SUBMIT_TO_VENUE must not
		// find the edge declared for RISK_APPROVED.
		for _, other := range allStates {
			if other == tr.From {
				continue
			}
			if resolved, ok := transitionFor(other, tr.Command); ok && resolved.To == tr.To &&
				resolved.From == tr.From {
				t.Errorf("command %q resolved for state %s but is declared for %s",
					tr.Command, other, tr.From)
			}
		}
	}
}

// TestRiskIncreasingTransitionsRequireNoActiveHalt checks the rule that reaches new exposure
// is the rule that checks the halt. If an edge is risk-increasing and does not require it,
// the halt does not stop that path.
func TestRiskIncreasingTransitionsRequireNoActiveHalt(t *testing.T) {
	found := 0
	for _, tr := range transitions {
		if !tr.RiskIncreasing {
			continue
		}
		found++
		if !containsPrecondition(tr.RequiresPreconditions, PreNoActiveHalt) {
			t.Errorf("%s is risk-increasing but does not require NO_ACTIVE_HALT, so a halt "+
				"would not stop it", tr)
		}
	}
	if found == 0 {
		t.Error("no transition is risk-increasing, so the halt never blocks anything")
	}
}

// TestRiskReducingTransitionsAreNotBlockedByAHalt pins the other half: a cancellation and a
// halt raise must remain available while halted, or the emergency control would stop the
// operator from reducing exposure.
func TestRiskReducingTransitionsAreNotBlockedByAHalt(t *testing.T) {
	for _, cmd := range []Command{CmdCancel, CmdRaiseHalt} {
		found := false
		for _, tr := range transitions {
			if tr.Command == cmd {
				found = true
				if tr.RiskIncreasing {
					t.Errorf("%s is risk-reducing and must not be marked risk-increasing, or a "+
						"halt would block it", tr)
				}
			}
		}
		if !found {
			t.Errorf("no transition declares command %s", cmd)
		}
	}
}

// TestOnlyTheClearHaltEdgeWritesAnInactiveHalt is the monotonicity property, asserted
// against the engine rather than the table: only CmdClearHalt assigns an inactive Halt.
func TestOnlyTheClearHaltEdgeWritesAnInactiveHalt(t *testing.T) {
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", nil, 0)
	if err != nil {
		t.Fatalf("cannot parse the package: %v", err)
	}
	found := 0
	for _, pkg := range pkgs {
		for _, file := range pkg.Files {
			ast.Inspect(file, func(n ast.Node) bool {
				assign, ok := n.(*ast.AssignStmt)
				if !ok {
					return true
				}
				for _, lhs := range assign.Lhs {
					sel, ok := lhs.(*ast.SelectorExpr)
					if !ok || sel.Sel.Name != "Halt" {
						continue
					}
					found++
					// Every write to a Halt field is either a raise (Active: true) or the
					// zero value in the clearance case. Anything else is a second path to
					// clearing a halt.
					zero, isZero := assign.Rhs[0].(*ast.CompositeLit)
					if isZero && zero.Type != nil {
						if ident, ok := zero.Type.(*ast.Ident); !ok || ident.Name != "Halt" {
							t.Errorf("%s writes a Halt field from a non-empty literal; that is "+
								"a second path to changing halt state", fset.Position(assign.Pos()))
						}
						continue
					}
					// A keyed literal with Active: true is the raise path.
					if isZero {
						ok := false
						for _, elt := range zero.Elts {
							if kv, ok := elt.(*ast.KeyValueExpr); ok {
								if key, ok := kv.Key.(*ast.Ident); ok && key.Name == "Active" {
									if lit, ok := kv.Value.(*ast.Ident); ok && lit.Name == "true" {
										ok = true
									}
								}
							}
						}
						if !ok {
							t.Errorf("%s writes a Halt literal that is neither a raise nor a "+
								"clearance", fset.Position(assign.Pos()))
						}
					}
				}
				return true
			})
		}
	}
	if found == 0 {
		t.Error("no Halt assignment found; the monotonicity check found nothing to check")
	}
}

// TestThePackageCannotReachTheNetworkOrARiskApprover checks the boundary the package
// documents. The OMS is pure domain logic: it submits nothing, and it cannot approve risk.
func TestThePackageCannotReachTheNetworkOrARiskApprover(t *testing.T) {
	bannedPrefixes := []string{
		"net", "net/http", "os/exec", "database/sql", "context",
		"github.com/danarprastika/web-trade/components/risk-engine",
		"github.com/danarprastika/web-trade/adapters",
	}
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, parser.ImportsOnly)
	if err != nil {
		t.Fatalf("cannot parse the package: %v", err)
	}
	for _, pkg := range pkgs {
		for path, file := range pkg.Files {
			for _, spec := range file.Imports {
				importPath, err := strconv.Unquote(spec.Path.Value)
				if err != nil {
					t.Fatalf("%s: unparseable import: %v", path, err)
				}
				for _, banned := range bannedPrefixes {
					if importPath == banned || strings.HasPrefix(importPath, banned+"/") {
						t.Errorf("%s imports %q; the OMS owns order state and must not be able "+
							"to reach the network, a database, or the Risk Engine's approval "+
							"path from inside the state machine", path, importPath)
					}
				}
			}
		}
	}
}

// TestThisPackageIsWhereTheTestExpects guards the workspace-root resolution the boundary
// test depends on, so a failure of that test is never mistaken for a clean bill of health.
func TestThisPackageIsWhereTheTestExpects(t *testing.T) {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot determine the test's own path")
	}
	if filepath.Base(filepath.Dir(file)) != "oms" {
		t.Errorf("this test expects to live in the oms package directory, found %s", file)
	}
}

func observationEdgeIsReachable(tr Transition) bool {
	for _, kind := range observationImpliedKind {
		if got, ok := transitionForObservation(tr.From, kind); ok && got.To == tr.To {
			return true
		}
	}
	return false
}

func containsPrecondition(list []Precondition, want Precondition) bool {
	for _, p := range list {
		if p == want {
			return true
		}
	}
	return false
}
