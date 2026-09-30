package riskengine

import (
	"errors"
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// docs/04 orders the halt scopes SYSTEM > VENUE > MARKET > STRATEGY > ACCOUNT and docs/25
// invariant 9 requires halts to be monotonic: a broader halt cannot be bypassed by a narrower
// enable. These tests pin the rank comparison that makes that true, because equality-based
// blocking would let a SYSTEM halt be escaped by a command that happens to name another scope.

func halt(t *testing.T, scope HaltScope, authority contracts.ActorType) HaltRecord {
	t.Helper()
	return HaltRecord{
		Scope:     scope,
		Reason:    "test halt",
		RaisedAt:  ts(t, baselineIssued),
		Authority: authority,
	}
}

func TestHaltHierarchyIsOrderedBySeverity(t *testing.T) {
	want := map[HaltScope]int{
		HaltAccount: 1, HaltStrategy: 2, HaltMarket: 3, HaltVenue: 4, HaltSystem: 5,
	}
	for scope, rank := range want {
		if got := scope.Rank(); got != rank {
			t.Errorf("scope %s has rank %d, want %d", scope, got, rank)
		}
	}
	if got := HaltScope("NOT_A_SCOPE").Rank(); got != -1 {
		t.Errorf("an unknown scope must rank -1, got %d", got)
	}
}

func TestAHaltBlocksEveryScopeAtOrBelowIt(t *testing.T) {
	// The monotonicity rule: SYSTEM stops everything. Checking each scope in turn is what
	// distinguishes rank-based blocking from the weaker "this exact scope is halted" check.
	halts, err := NewHaltState(halt(t, HaltSystem, contracts.ActorHuman))
	if err != nil {
		t.Fatalf("a system halt is coherent: %v", err)
	}
	for _, scope := range haltOrder {
		if !halts.Blocks(scope) {
			t.Errorf("a SYSTEM_HALT must block %s", scope)
		}
	}
}

func TestANarrowHaltDoesNotBlockABroaderScope(t *testing.T) {
	// The converse. An ACCOUNT_HALT is about one account and must not silently stop the whole
	// platform, or the hierarchy would be a permanent global switch.
	halts, err := NewHaltState(halt(t, HaltAccount, contracts.ActorHuman))
	if err != nil {
		t.Fatalf("an account halt is coherent: %v", err)
	}
	if !halts.Blocks(HaltAccount) {
		t.Error("an ACCOUNT_HALT must block ACCOUNT scope")
	}
	for _, scope := range []HaltScope{HaltStrategy, HaltMarket, HaltVenue, HaltSystem} {
		if halts.Blocks(scope) {
			t.Errorf("an ACCOUNT_HALT must not block %s", scope)
		}
	}
}

func TestAnUnknownScopeIsTreatedAsBlocked(t *testing.T) {
	// A scope that cannot be reasoned about must not be reasoned about permissively.
	halts, err := NewHaltState()
	if err != nil {
		t.Fatalf("an empty halt state is coherent: %v", err)
	}
	if !halts.Blocks(HaltScope("NOT_A_SCOPE")) {
		t.Error("an unknown scope must be treated as blocked, because it cannot be reasoned " +
			"about and guessing permissively would let an unrecognised halt scope through")
	}
	if len(halts.Blocking(HaltScope("NOT_A_SCOPE"))) != 0 {
		t.Error("an unknown scope has no blocking halts to report")
	}
}

func TestHaltsAreReportedMostSevereFirst(t *testing.T) {
	// Reporting order is fixed so an audit record reads the same way on every run.
	halts, err := NewHaltState(
		halt(t, HaltAccount, contracts.ActorHuman),
		halt(t, HaltSystem, contracts.ActorHuman),
		halt(t, HaltVenue, contracts.ActorHuman),
	)
	if err != nil {
		t.Fatalf("halts are coherent: %v", err)
	}
	active := halts.Active()
	want := []HaltScope{HaltSystem, HaltVenue, HaltAccount}
	for i, scope := range want {
		if active[i].Scope != scope {
			t.Errorf("position %d is %s, want %s", i, active[i].Scope, scope)
		}
	}
	highest, ok := halts.Highest()
	if !ok || highest.Scope != HaltSystem {
		t.Errorf("Highest should report SYSTEM_HALT, got %s (present=%t)", highest.Scope, ok)
	}
}

func TestAnAgentMayNotHoldHaltAuthority(t *testing.T) {
	// docs/25 invariant 9: a model may never hold halt authority. A model that could raise a
	// halt it could then influence is a second authority over risk.
	_, err := NewHaltState(halt(t, HaltSystem, contracts.ActorAgent))
	if err == nil {
		t.Fatal("a halt raised by an agent must be refused")
	}
	var rejection Rejection
	if !errors.As(err, &rejection) {
		t.Fatalf("expected a Rejection, got %T: %v", err, err)
	}
	if rejection.Code != contracts.CodeAuthorization {
		t.Errorf("expected an authorization code, got %s", rejection.Code)
	}
}

func TestAnIncoherentHaltRecordIsRefused(t *testing.T) {
	cases := map[string]func(HaltRecord) HaltRecord{
		"no scope":     func(h HaltRecord) HaltRecord { h.Scope = ""; return h },
		"no reason":    func(h HaltRecord) HaltRecord { h.Reason = ""; return h },
		"no timestamp": func(h HaltRecord) HaltRecord { h.RaisedAt = contracts.Timestamp{}; return h },
		"no authority": func(h HaltRecord) HaltRecord { h.Authority = ""; return h },
		"unknown authority": func(h HaltRecord) HaltRecord {
			h.Authority = contracts.ActorType("ROBOT")
			return h
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := NewHaltState(mutate(halt(t, HaltVenue, contracts.ActorHuman))); err == nil {
				t.Fatal("an incoherent halt record must be refused")
			}
		})
	}
}

func TestAHaltBlocksTheRiskGate(t *testing.T) {
	// The end-to-end consequence: a halt anywhere at or above account scope stops the order.
	for _, scope := range haltOrder {
		t.Run(string(scope), func(t *testing.T) {
			halts, err := NewHaltState(halt(t, scope, contracts.ActorHuman))
			if err != nil {
				t.Fatalf("halt is coherent: %v", err)
			}
			facts := baselineFacts(t)
			facts.Halts = halts

			result := evaluate(t, baselineIntent(t), facts, baselinePolicy(t), Advisory{})
			requireFailed(t, result, ControlHaltState)
		})
	}
}

func TestAHaltNamesTheReasonAndScopeInTheRejection(t *testing.T) {
	// A rejection a reviewer cannot act on is only half useful, so the reason and the active
	// scopes are both in the report.
	halts, err := NewHaltState(HaltRecord{
		Scope:     HaltVenue,
		Reason:    "venue maintenance window",
		RaisedAt:  ts(t, baselineIssued),
		Authority: contracts.ActorHuman,
	})
	if err != nil {
		t.Fatalf("halt is coherent: %v", err)
	}
	facts := baselineFacts(t)
	facts.Halts = halts

	result := evaluate(t, baselineIntent(t), facts, baselinePolicy(t), Advisory{})
	got := controlResult(t, result, ControlHaltState)
	for _, want := range []string{"venue maintenance window", "VENUE_HALT"} {
		if !strings.Contains(got.Reason, want) {
			t.Errorf("halt rejection should mention %q, got: %s", want, got.Reason)
		}
	}
}
