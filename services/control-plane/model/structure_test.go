package model

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// TestModelPackageHoldsNoFinancialAuthority is the mechanical form of the boundary this
// package exists to draw.
//
// docs/07 makes the model registry authoritative, and the risk of that is a registry that
// grows a way to act on the market while it is deciding which models may act. If this
// package could reach the venue adapter, the OMS, or the risk engine, "a model may not
// authorize its own execution" would be a comment rather than a property: the same package
// deciding the deployment and being able to place the order.
//
// The check is on imports rather than on behaviour, because a behavioural test would pass
// for every behaviour that happens to exist today and fail only when somebody adds the
// import that matters.
func TestModelPackageHoldsNoFinancialAuthority(t *testing.T) {
	forbidden := []string{
		"adapters/venues",
		"components/oms",
		"components/risk-engine",
		"components/reconciliation",
		"services/control-plane/ledger",
	}
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, parser.ImportsOnly)
	if err != nil {
		t.Fatalf("parsing package: %v", err)
	}
	sawAny := false
	for _, pkg := range pkgs {
		for _, file := range pkg.Files {
			sawAny = true
			for _, imp := range file.Imports {
				path, err := strconv.Unquote(imp.Path.Value)
				if err != nil {
					t.Fatalf("unquoting import %s: %v", imp.Path.Value, err)
				}
				for _, bad := range forbidden {
					if strings.Contains(path, bad) {
						t.Errorf("%s imports %q; the model registry decides what may be "+
							"deployed and must not be able to place, amend, or cancel an order",
							filepath.Base(fset.Position(imp.Pos()).Filename), path)
					}
				}
			}
		}
	}
	if !sawAny {
		t.Fatal("no source files were parsed; the authority check would pass vacuously")
	}
}

// TestNoFloatingPointArithmetic enforces docs/02: financial and threshold values are exact
// decimals, never float32 or float64.
//
// The monitored thresholds in this package are the reason this matters here specifically. A
// rejection rate of 0.40 stored as a float64 is not exactly 0.40, so a measured value that
// equals the threshold exactly can compare as greater or less depending on rounding, and a
// monitoring policy whose breach is a comparison would then pause or not pause
// unpredictably. Carrying the threshold and the value as canonical text removes the
// question rather than bounding it.
func TestNoFloatingPointArithmetic(t *testing.T) {
	fset := token.NewFileSet()
	pkgs, err := parser.ParseDir(fset, ".", func(fi os.FileInfo) bool {
		return !strings.HasSuffix(fi.Name(), "_test.go")
	}, 0)
	if err != nil {
		t.Fatalf("parsing package: %v", err)
	}
	sawAny := false
	for _, pkg := range pkgs {
		for name, file := range pkg.Files {
			sawAny = true
			ast.Inspect(file, func(n ast.Node) bool {
				id, ok := n.(*ast.Ident)
				if !ok {
					return true
				}
				switch id.Name {
				case "float32", "float64":
					t.Errorf("%s: the model package must not use %s; thresholds and "+
						"lineage values are exact decimal or content digests",
						filepath.Base(fset.Position(id.Pos()).Filename), id.Name)
				}
				return true
			})
			_ = name
		}
	}
	if !sawAny {
		t.Fatal("no source files were parsed; the float check would pass vacuously")
	}
}

// TestEveryTransitionEmitsADistinctAuditEvent backs the "complete audit trails" half of
// acceptance criterion one. Two transitions sharing an event type would collapse two
// distinct state changes into one line of the audit chain, and a chain that cannot
// distinguish a promotion from a retirement cannot reconstruct how a model got deployed.
func TestEveryTransitionEmitsADistinctAuditEvent(t *testing.T) {
	// Keyed by command, not by edge. The quarantine command is declared on eight edges
	// because a compromise can arrive from any state, and all eight are one logical action
	// that must produce one audit event: an investigation reads "the model was quarantined
	// from SHADOW", and the source state is part of the event payload, not a separate event
	// type. Two *different* commands sharing an event type is the defect, because then two
	// unrelated state changes become indistinguishable in the chain.
	seen := map[string]Command{}
	for _, tr := range transitions {
		if prev, dup := seen[tr.EventType]; dup && prev != tr.Command {
			t.Errorf("event %q is emitted by both %s and %s; two distinct commands sharing "+
				"an event type cannot be told apart in the audit chain",
				tr.EventType, prev, tr.Command)
		}
		seen[tr.EventType] = tr.Command
	}
	// Conversely, no command may emit two event types.
	perCommand := map[Command]string{}
	for _, tr := range transitions {
		if prev, dup := perCommand[tr.Command]; dup && prev != tr.EventType {
			t.Errorf("command %s emits both %q and %q; one command is one logical action "+
				"and must produce one event type", tr.Command, prev, tr.EventType)
		}
		perCommand[tr.Command] = tr.EventType
	}
	// Every lifecycle event the audit chain can receive from this package must carry the
	// "model." prefix, so an operator can filter for model events without a per-event map.
	for _, tr := range transitions {
		if !strings.HasPrefix(tr.EventType, "model.") {
			t.Errorf("transition %s emits %q, which does not carry the model. prefix",
				tr.Command, tr.EventType)
		}
	}
}

// TestIdempotencyScopesAreDistinct is the retry-safety property. Two transitions sharing a
// scope would let a retry of one suppress the other, so a promotion could be silently
// dropped by a retried evaluation.
func TestIdempotencyScopesAreDistinct(t *testing.T) {
	// The quarantine command is multi-source by design, so several edges legitimately share
	// one scope: they are one logical action applied from different states, and a retried
	// quarantine must not quarantine twice.
	byScope := map[string][]Command{}
	for _, tr := range transitions {
		byScope[tr.IdempotencyScope] = append(byScope[tr.IdempotencyScope], tr.Command)
	}
	for scope, cmds := range byScope {
		unique := map[Command]bool{}
		for _, c := range cmds {
			unique[c] = true
		}
		if len(unique) > 1 {
			t.Errorf("idempotency scope %q is shared by %d distinct commands %v; a retry of "+
				"one could suppress the other", scope, len(unique), cmds)
		}
	}
}

// TestProgressionMatchesTheDocumentedChain checks the lifecycle against docs/07 verbatim.
// The check is on the set of non-quarantine states, because QUARANTINED is declared out of
// band and is deliberately not part of the progression.
func TestProgressionMatchesTheDocumentedChain(t *testing.T) {
	documented := []State{
		StateRegistered, StateEvaluated, StateValidated, StateApproved,
		StatePaper, StateShadow, StatePromoted, StateMonitored, StateRetired,
	}
	if len(documented) != 9 {
		t.Fatalf("the documented chain has %d states; docs/07 lists nine", len(documented))
	}
	for _, s := range documented {
		if !s.Valid() {
			t.Errorf("documented state %s is not in the closed set", s)
		}
	}
	if _, ok := TransitionFor(StateRegistered, StateEvaluated); !ok {
		t.Error("REGISTERED -> EVALUATED is not declared")
	}
	if _, ok := TransitionFor(StateEvaluated, StateValidated); !ok {
		t.Error("EVALUATED -> VALIDATED is not declared")
	}
	if _, ok := TransitionFor(StateValidated, StateApproved); !ok {
		t.Error("VALIDATED -> APPROVED is not declared")
	}
	if _, ok := TransitionFor(StateApproved, StatePaper); !ok {
		t.Error("APPROVED -> PAPER is not declared")
	}
	if _, ok := TransitionFor(StatePaper, StateShadow); !ok {
		t.Error("PAPER -> SHADOW is not declared")
	}
	if _, ok := TransitionFor(StateShadow, StatePromoted); !ok {
		t.Error("SHADOW -> PROMOTED is not declared")
	}
	if _, ok := TransitionFor(StatePromoted, StateMonitored); !ok {
		t.Error("PROMOTED -> MONITORED is not declared")
	}
	if _, ok := TransitionFor(StateMonitored, StateRetired); !ok {
		t.Error("MONITORED -> RETIRED is not declared")
	}
}

// TestEveryNonTerminalStateHasAnOnwardTransition: a state with no declared onward edge
// would be an accidental dead end rather than a designed terminal state.
func TestEveryNonTerminalStateHasAnOnwardTransition(t *testing.T) {
	for _, s := range AllStates() {
		if s.IsTerminal() {
			continue
		}
		if len(NextStates(s)) == 0 {
			t.Errorf("state %s is not terminal but has no declared onward transition", s)
		}
	}
}

// TestNoStateCanReachPromotedWithoutPassingApproval: the progression must not contain a
// shortcut. A model reaching PROMOTED without an APPROVED state would have been deployed
// without the independent review docs/07 requires.
func TestNoStateCanReachPromotedWithoutPassingApproval(t *testing.T) {
	// Walk the declared edges from every state and confirm that no state other than
	// APPROVED, PAPER, and SHADOW can reach PROMOTED in one step.
	for _, from := range AllStates() {
		for _, to := range NextStates(from) {
			if to == StatePromoted && from != StateShadow {
				t.Errorf("%s -> PROMOTED is declared; promotion must be reached only from "+
					"SHADOW, which is only reachable after an independent approval", from)
			}
		}
	}
}

// TestNoStateCanReachApprovedWithoutPassingValidation: approval requires an evaluation and
// a validation to have been recorded first.
func TestNoStateCanReachApprovedWithoutPassingValidation(t *testing.T) {
	for _, from := range AllStates() {
		for _, to := range NextStates(from) {
			if to == StateApproved && from != StateValidated {
				t.Errorf("%s -> APPROVED is declared; approval must be reached only from "+
					"VALIDATED", from)
			}
		}
	}
}
