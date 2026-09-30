package model

import (
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// TestQuarantineCommandResolvesFromEverySourceState is the regression test for a real
// defect.
//
// The transition table declared the quarantine command on eight edges, and the request
// lookup was originally keyed by command alone. A single-valued map keeps one entry per
// key, so only the last edge survived and a request to quarantine a model in REGISTERED
// was rejected as though the command did not belong to the claimed state.
//
// The consequence was silent and severe in the way that matters here: seven of the eight
// states from which a compromise must be contained would not have contained it, and a
// compromised model sitting in one of those states would have remained promotable. The
// table was correct, the doc comment explained why the edges existed, and the code
// compiled; only the behaviour was wrong, and only in the direction that failed safe for
// the responder and unsafe for the operator.
//
// The test walks the documented progression and applies the command from each state, so a
// future table that adds a state without a quarantine edge fails here.
func TestQuarantineCommandResolvesFromEverySourceState(t *testing.T) {
	progression := []State{
		StateRegistered, StateEvaluated, StateValidated, StateApproved,
		StatePaper, StateShadow, StatePromoted, StateMonitored,
	}
	for _, from := range progression {
		req := Request{
			ModelID:                mustModelID(t),
			From:                   from,
			Command:                CommandQuarantine,
			ActorID:                "responder-varga",
			ActorType:              contracts.ActorSystem,
			PreconditionsSatisfied: []Precondition{PreconditionForensicPreserved},
			IdempotencyKey:         "model-quarantine-0001",
			Reference:              "incident-2026-09-29-001",
		}
		out, err := Apply(req)
		if err != nil {
			t.Errorf("quarantine refused from %s: %v; a compromise must be containable from "+
				"every non-terminal state", from, err)
			continue
		}
		if out.Transition.To != StateQuarantined {
			t.Errorf("quarantine from %s produced %s, want QUARANTINED", from, out.Transition.To)
		}
	}
}

// TestQuarantineIsMultiSourceAndConsistent checks the declaration invariant that the fix
// introduced, so that adding a command on two edges without marking it cannot reintroduce
// the ambiguity by a different route.
func TestQuarantineIsMultiSourceAndConsistent(t *testing.T) {
	if err := VerifyDeclaration(); err != nil {
		t.Fatalf("declaration inconsistent: %v", err)
	}
	if _, present := byCmd[CommandQuarantine]; present {
		t.Error("the multi-source quarantine command is present in the single-source lookup; " +
			"it must be resolvable only by (state, command)")
	}
	if len(transitionsFrom(StateQuarantined)) == 0 {
		t.Error("QUARANTINED has no onward transition; a cleared quarantine must route " +
			"through RETIRED")
	}
}

// TestOnlyQuarantineIsMultiSource pins which commands may legitimately have several
// sources. If a promotion command ever became multi-source, the (state, command) lookup
// would make a promotion valid from a state nobody approved, and the table would still
// pass every other check in this file.
func TestOnlyQuarantineIsMultiSource(t *testing.T) {
	allowed := map[Command]bool{CommandQuarantine: true}
	counts := map[Command]int{}
	for _, tr := range transitions {
		counts[tr.Command]++
	}
	for cmd, n := range counts {
		if n > 1 && !allowed[cmd] {
			t.Errorf("command %s is declared on %d edges; only the quarantine command may be "+
				"multi-source, because only it must be available from a state the responder "+
				"does not yet know", cmd, n)
		}
	}
}

// TestQuarantineClearingIsHumanOnly is the defect that the second failing test found.
//
// The quarantine edge permits a system actor so an automated control can contain a
// compromise immediately. Its inverse was declared with the same actor set, which would
// have let a system restore a compromised model on a schedule of its own choosing. The
// recovery from a security incident is a human decision taken after forensic review, so
// the clear path is human-only and additionally requires an independent approver.
func TestQuarantineClearingIsHumanOnly(t *testing.T) {
	tr, ok := TransitionFor(StateQuarantined, StateRetired)
	if !ok {
		t.Fatal("no declared transition from QUARANTINED to RETIRED")
	}
	for _, forbidden := range []contracts.ActorType{
		contracts.ActorAgent, contracts.ActorService, contracts.ActorSystem, contracts.ActorStrategy,
	} {
		if actorPermitted(tr, forbidden) {
			t.Errorf("clearing a quarantine permits %s; a compromised workload must not be "+
				"able to schedule its own restoration", forbidden)
		}
	}
	if !actorPermitted(tr, contracts.ActorHuman) {
		t.Error("no human actor may clear a quarantine")
	}
	if !tr.RequiresIndependentApprover {
		t.Error("clearing a quarantine does not require an independent approver")
	}

	// The inverse asymmetry is deliberate and asserted: containment may be automated,
	// recovery may not.
	quarantine, ok := byFromCmd[transitionKey{state: StateMonitored, command: CommandQuarantine}]
	if !ok {
		t.Fatal("no quarantine edge from MONITORED")
	}
	if !actorPermitted(quarantine, contracts.ActorSystem) {
		t.Error("containment must be available to a system actor; an automated control has " +
			"to be able to shut a compromised model down without waiting for a human")
	}
}
