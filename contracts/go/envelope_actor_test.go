package contracts

import "testing"

// The actor closed set is shared by the OMS, the Risk Engine, the ledger, and the audit
// chain, so a change to it reaches every one of them at once. This pins the set
// explicitly: without it, deleting a member would leave the remaining tests green and
// every record naming that actor would be silently un-interpretable elsewhere.
func TestTheActorTypeClosedSetIsExactlyTheseValues(t *testing.T) {
	permitted := []ActorType{
		ActorHuman,
		ActorService,
		ActorAgent,
		ActorSystem,
		ActorStrategy,
		ActorBreakGlass,
	}

	for _, a := range permitted {
		if !a.Valid() {
			t.Errorf("actor type %q is declared but not reported valid", a)
		}
	}

	// Anything outside the list must be refused.
	for _, a := range []ActorType{"", "ROBOT", "human", "HUMAN ", "ADMIN", "BREAKGLASS"} {
		if a.Valid() {
			t.Errorf("actor type %q must not be in the closed set", a)
		}
	}
}

// The wire form and the string form must agree, because the audit chain stores the
// string form and the envelope validates the typed form. A mismatch would let a record
// name an actor the envelope would refuse.
func TestActorTypeStringMatchesItsWireForm(t *testing.T) {
	cases := map[ActorType]string{
		ActorHuman:      "HUMAN",
		ActorService:    "SERVICE",
		ActorAgent:      "AGENT",
		ActorSystem:     "SYSTEM",
		ActorStrategy:   "STRATEGY",
		ActorBreakGlass: "BREAK_GLASS",
	}
	for actor, wire := range cases {
		if got := actor.String(); got != wire {
			t.Errorf("actor %v renders as %q, want %q", actor, got, wire)
		}
	}
}
