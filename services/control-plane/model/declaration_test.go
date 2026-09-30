package model

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// TestTheRealDeclarationIsConsistent is the positive control: the table this package
// actually uses must pass the rules the package enforces.
func TestTheRealDeclarationIsConsistent(t *testing.T) {
	if err := VerifyDeclaration(); err != nil {
		t.Fatalf("the package's own transition table is inconsistent: %v", err)
	}
}

// TestEveryDeclarationRuleIsEnforced feeds the verifier malformed tables and requires it to
// refuse each one.
//
// This test exists because of a mutation that survived. The empty-source guard in
// verifyDeclaration - the one permitting only registration to have no prior state - could be
// deleted and every test in the package still passed, because the real table has exactly one
// empty-source edge and it is the permitted one. A rule stated in code and unexercised is a
// rule that is not enforced, and the only way to enforce it is to hand the verifier
// something it must refuse.
//
// Each case mutates a copy of the real table, so the cases are about the declared rules and
// not about whether a hand-built table happens to be well formed.
func TestEveryDeclarationRuleIsEnforced(t *testing.T) {
	base := func() []Transition {
		out := make([]Transition, len(transitions))
		copy(out, transitions)
		return out
	}
	find := func(tab []Transition, cmd Command) int {
		for i, t := range tab {
			if t.Command == cmd {
				return i
			}
		}
		return -1
	}

	cases := map[string]struct {
		mutate func(tab []Transition) []Transition
		expect string
	}{
		"an undeclared empty source state": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].From = ""
				return tab
			},
			expect: "empty source state",
		},
		"an empty source into a state other than REGISTERED": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRegister)
				tab[i].To = StateEvaluated
				return tab
			},
			expect: "empty source state",
		},
		"an unknown source state": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].From = State("UNLISTED")
				return tab
			},
			expect: "unknown source state",
		},
		"an unknown destination state": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].To = State("UNLISTED")
				return tab
			},
			expect: "unknown destination state",
		},
		"no precondition": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].Precondition = ""
				return tab
			},
			expect: "declares no precondition",
		},
		"no audit event": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].EventType = ""
				return tab
			},
			expect: "declares no audit event",
		},
		"no idempotency scope": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].IdempotencyScope = ""
				return tab
			},
			expect: "declares no idempotency scope",
		},
		"no audit record description": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].AuditRecord = ""
				return tab
			},
			expect: "declares no audit record",
		},
		"an unknown failure behaviour": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].FailureBehavior = FailureBehavior("RETRY_FOREVER")
				return tab
			},
			expect: "unknown failure behaviour",
		},
		"no permitted actor": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].PermittedActors = nil
				return tab
			},
			expect: "permits no actor",
		},
		"an AI actor as the actor of record": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].PermittedActors = []contracts.ActorType{contracts.ActorAgent}
				return tab
			},
			expect: "forbids an AI or strategy actor",
		},
		"a strategy actor as the actor of record": {
			mutate: func(tab []Transition) []Transition {
				i := find(tab, CommandRecordEvaluation)
				tab[i].PermittedActors = []contracts.ActorType{contracts.ActorStrategy}
				return tab
			},
			expect: "forbids an AI or strategy actor",
		},
		"an inconsistent MultiSource flag": {
			mutate: func(tab []Transition) []Transition {
				// The quarantine command is genuinely multi-source. Drop the flag from one
				// edge only, which is the case the flag exists to make impossible to miss.
				cleared := false
				for i := range tab {
					if tab[i].Command == CommandQuarantine && !cleared {
						tab[i].MultiSource = false
						cleared = true
					}
				}
				return tab
			},
			expect: "MultiSource",
		},
		"a state that cannot reach quarantine": {
			mutate: func(tab []Transition) []Transition {
				out := tab[:0]
				for _, t := range tab {
					if t.Command == CommandQuarantine {
						continue
					}
					out = append(out, t)
				}
				return out
			},
			expect: "no transition to QUARANTINED",
		},
		"a transition out of quarantine into a non-terminal state": {
			mutate: func(tab []Transition) []Transition {
				// The quarantine clear command is the declared way out. Removing its edge
				// entirely and adding a direct one is the shape the rule forbids.
				out := tab[:0]
				for _, t := range tab {
					if t.Command == CommandClearQuarantine {
						continue
					}
					out = append(out, t)
				}
				base := -1
				for i, t := range out {
					if t.Command == CommandRegister {
						base = i
						break
					}
				}
				if base >= 0 {
					forged := out[base]
					forged.From = StateQuarantined
					forged.To = StateMonitored
					forged.Command = "model.quarantine.escaped"
					forged.EventType = "model.quarantine.escaped"
					forged.IdempotencyScope = "model/lifecycle/escape"
					forged.AuditRecord = "a forged edge out of quarantine"
					out = append(out, forged)
				}
				return out
			},
			expect: "quarantine",
		},
	}

	for name, tc := range cases {
		err := verifyDeclaration(tc.mutate(base()), allStates)
		if err == nil {
			t.Errorf("%s: the declaration was accepted", name)
			continue
		}
		if !strings.Contains(err.Error(), tc.expect) {
			t.Errorf("%s: refused, but for the wrong reason: %v", name, err)
		}
	}
}

// TestAMultiSourceCommandIsNotResolvableWithoutItsSource is the check that the (state,
// command) lookup replaced the lossy single-valued map. A multi-source command reachable by
// command alone would be the original defect: the last edge declared would be the only one
// the caller could see.
func TestAMultiSourceCommandIsNotResolvableWithoutItsSource(t *testing.T) {
	multi := false
	for _, t := range transitions {
		if t.Command == CommandQuarantine {
			multi = true
			break
		}
	}
	if !multi {
		t.Skip("the declaration declares no multi-source command")
	}
	if _, present := byCmd[CommandQuarantine]; present {
		t.Error("a multi-source command is present in the single-source lookup; a caller " +
			"could resolve it ambiguously by naming the command alone")
	}
	// It must still resolve per state.
	resolved := 0
	for _, s := range AllStates() {
		if _, ok := lookup(s, CommandQuarantine); ok {
			resolved++
		}
	}
	if resolved < 2 {
		t.Errorf("the multi-source quarantine command resolved from %d states, want the "+
			"several the declaration requires", resolved)
	}
}
