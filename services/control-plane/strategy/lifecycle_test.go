package strategy

import (
	"errors"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// strategyBody is a 26-character lowercase Crockford Base32 payload, the fixed length
// identifier.schema.json requires.
const strategyBody = "01hq3k7m9x2f5rb8n0v6c4tqwx"

func mustStrategyID(t *testing.T) contracts.Identifier {
	t.Helper()
	id, err := contracts.ParseIdentifier("str_" + strategyBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	return id
}

// validRequest builds a request that satisfies the transition out of from, so a test can
// invalidate exactly one thing and attribute the refusal to that thing.
func validRequest(t *testing.T, from State, cmd Command, actor contracts.ActorType) Request {
	t.Helper()
	declared := byCmd[cmd]
	return Request{
		StrategyID:             mustStrategyID(t),
		From:                   from,
		Command:                cmd,
		ActorID:                "owner-7",
		ActorType:              actor,
		PreconditionsSatisfied: []Precondition{declared.Precondition},
		IdempotencyKey:         "strategy-transition-0001",
		Reference:              "evidence-ref-0001",
	}
}

// TestEveryDeclaredTransitionApplies walks the documented chain end to end, using an
// actor permitted for each edge. A failure here means either the graph or the permitted
// actor set is wrong, both of which would strand a strategy permanently.
func TestEveryDeclaredTransitionApplies(t *testing.T) {
	// An actor permitted for every edge, to prove each edge is individually sound before
	// the authorisation question is asked separately.
	//
	// The table is keyed by the edge, not by the source state, because a single source state
	// can have an outgoing edge that permits a different actor than another edge. SHADOW is
	// the case in point: a pipeline may promote PAPER -> SHADOW, but the SHADOW -> APPROVED
	// edge is human-only because APPROVED is the first authority-bearing state. Keying by
	// source state would silently apply one actor to both edges and refuse the human-gated
	// one for the wrong reason.
	permissive := map[[2]State]contracts.ActorType{
		{StateDraft, StateReview}:          contracts.ActorHuman,
		{StateReview, StateBacktested}:     contracts.ActorService,
		{StateBacktested, StateSimulation}: contracts.ActorService,
		{StateSimulation, StatePaper}:      contracts.ActorService,
		{StatePaper, StateShadow}:          contracts.ActorService,
		{StateShadow, StateApproved}:       contracts.ActorHuman,
		{StateApproved, StateDeployed}:     contracts.ActorHuman,
		{StateDeployed, StatePaused}:       contracts.ActorHuman,
		{StatePaused, StateRetired}:        contracts.ActorHuman,
	}
	reached := map[State]bool{StateDraft: true}
	for _, t2 := range transitions {
		t2 := t2
		t.Run(string(t2.From)+"_to_"+string(t2.To), func(t *testing.T) {
			actor, ok := permissive[[2]State{t2.From, t2.To}]
			if !ok {
				t.Fatalf("no permissive actor registered for edge %s -> %s", t2.From, t2.To)
			}
			out, err := Apply(validRequest(t, t2.From, t2.Command, actor))
			if err != nil {
				t.Fatalf("declared transition %s -> %s was refused: %v", t2.From, t2.To, err)
			}
			if out.Transition.To != t2.To {
				t.Errorf("outcome state = %s, want %s", out.Transition.To, t2.To)
			}
			// The outcome must carry everything needed to persist the change and its audit
			// record in one transaction.
			if out.EventType == "" || out.AuditRecord == "" || out.IdempotencyScope == "" {
				t.Errorf("outcome is missing audit material: %+v", out)
			}
			if out.FailureBehavior == "" {
				t.Error("outcome declares no failure behaviour")
			}
			reached[t2.To] = true
		})
	}
	for _, s := range AllStates() {
		if !reached[s] {
			t.Errorf("state %s was never reached by any declared transition", s)
		}
	}
}

// TestGraphMatchesDocumentedChain pins the graph to the chain in docs/04 exactly. This is
// the test that would fail if a transition were invented, because it compares against the
// documented sequence rather than against whatever the table happens to contain.
func TestGraphMatchesDocumentedChain(t *testing.T) {
	documented := []State{
		StateDraft, StateReview, StateBacktested, StateSimulation, StatePaper,
		StateShadow, StateApproved, StateDeployed, StatePaused, StateRetired,
	}
	if len(transitions) != len(documented)-1 {
		t.Fatalf("declared %d transitions, want %d for a %d-state chain",
			len(transitions), len(documented)-1, len(documented))
	}
	for i := 0; i < len(documented)-1; i++ {
		from, to := documented[i], documented[i+1]
		got, ok := TransitionFor(from, to)
		if !ok {
			t.Errorf("no declared transition %s -> %s", from, to)
			continue
		}
		if got.From != from || got.To != to {
			t.Errorf("TransitionFor(%s, %s) = %s -> %s", from, to, got.From, got.To)
		}
	}
	// No undeclared edge may exist in the opposite direction, and no state may have more
	// than one successor, because the documented chain is linear.
	for _, from := range AllStates() {
		next := NextStates(from)
		if len(next) > 1 {
			t.Errorf("state %s has %d successors %v; the documented chain is linear", from, len(next), next)
		}
	}
}

// TestEveryTransitionDeclaresEverything enforces acceptance criterion one: each transition
// must declare actor, command, precondition, resulting state, event, idempotency key, audit
// record, and failure behaviour. A blank field is a gap a caller would have to interpret.
func TestEveryTransitionDeclaresEverything(t *testing.T) {
	for _, tr := range transitions {
		name := string(tr.From) + "->" + string(tr.To)
		if tr.Command == "" {
			t.Errorf("%s: no command declared", name)
		}
		if len(tr.PermittedActors) == 0 {
			t.Errorf("%s: no permitted actor declared", name)
		}
		if tr.Precondition == "" {
			t.Errorf("%s: no precondition declared", name)
		}
		if tr.EventType == "" {
			t.Errorf("%s: no event type declared", name)
		}
		if tr.IdempotencyScope == "" {
			t.Errorf("%s: no idempotency scope declared", name)
		}
		if tr.AuditRecord == "" {
			t.Errorf("%s: no audit record declared", name)
		}
		if tr.FailureBehavior != FailureDenyRemain && tr.FailureBehavior != FailureHaltAndReconcile {
			t.Errorf("%s: failure behaviour %q is not one of the declared values", name, tr.FailureBehavior)
		}
		if !tr.From.Valid() || !tr.To.Valid() {
			t.Errorf("%s: transition references an unknown state", name)
		}
		// Every declared actor must itself be in the closed set.
		for _, a := range tr.PermittedActors {
			if !a.Valid() {
				t.Errorf("%s: permitted actor %q is not a known actor type", name, a)
			}
		}
	}
	// Command names must be dotted, matching the envelope convention, so they cannot
	// collide with another module's command in a shared stream.
	for _, tr := range transitions {
		if !strings.Contains(string(tr.Command), ".") {
			t.Errorf("%s: command %q is not a dotted name", tr.From, tr.Command)
		}
	}
}

// TestAgentMayNeverBeActorOfRecord enforces the propose-only rule from docs/01 section 5
// and docs/25 section 3.6: AI proposes, human approval governs. An agent being the actor of
// record for a lifecycle change would let a model advance a strategy by itself.
func TestAgentMayNeverBeActorOfRecord(t *testing.T) {
	for _, tr := range transitions {
		if actorPermitted(tr, contracts.ActorAgent) {
			t.Errorf("%s -> %s permits an AGENT actor; AI may propose but never act", tr.From, tr.To)
		}
	}
	// And the engine actually refuses an agent, for every edge.
	for _, tr := range transitions {
		req := validRequest(t, tr.From, tr.Command, contracts.ActorAgent)
		if _, err := Apply(req); err == nil {
			t.Errorf("%s -> %s accepted an AGENT actor", tr.From, tr.To)
		} else if !isAuthorizationDenial(err) {
			t.Errorf("%s -> %s refused an agent with %v, want an authorization denial", tr.From, tr.To, err)
		}
	}
}

// TestAuthorityBearingTransitionsAreHumanGated pins that the two states that carry authority
// cannot be entered by a pipeline. Getting this wrong is the difference between a
// deployment requiring an owner and one that does not.
func TestAuthorityBearingTransitionsAreHumanGated(t *testing.T) {
	for _, cmd := range []Command{CommandApprove, CommandDeploy} {
		tr := byCmd[cmd]
		if !actorPermitted(tr, contracts.ActorHuman) {
			t.Errorf("%s does not permit a HUMAN actor", cmd)
		}
		for _, machine := range []contracts.ActorType{contracts.ActorService, contracts.ActorSystem} {
			if actorPermitted(tr, machine) {
				t.Errorf("%s permits %s; authority-bearing transitions must be human-gated", cmd, machine)
			}
		}
	}
}

// TestUnknownStateIsRefused covers acceptance criterion two. An unknown state must never be
// treated as a default, because defaulting here would mean guessing a lifecycle position for
// a strategy whose state the platform has lost.
func TestUnknownStateIsRefused(t *testing.T) {
	for _, s := range []State{"", "draft", "LIVE", "DEPLOYED_AND_RUNNING", "UNKNOWN", "PRODUCTION"} {
		req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
		req.From = s
		if _, err := Apply(req); err == nil {
			t.Errorf("state %q was accepted; an unknown state is not a default", s)
		} else if !errors.Is(err, contracts.ErrInvalidContractValue) {
			t.Errorf("state %q refused with %v, want ErrInvalidContractValue", s, err)
		}
	}
}

func TestUnknownCommandIsRefused(t *testing.T) {
	for _, c := range []Command{"", "strategy.promoted", "strategy.deploy", "unknown.command"} {
		req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
		req.Command = c
		if _, err := Apply(req); err == nil {
			t.Errorf("command %q was accepted; unknown commands are unsupported", c)
		}
	}
}

// TestCommandMustMatchClaimedState blocks a caller from naming a real command that belongs
// to a different edge. Without this, a strategy in DRAFT could invoke the approve command
// and be told only that its own declared state did not match.
func TestCommandMustMatchClaimedState(t *testing.T) {
	// strategy.approved is declared for SHADOW -> APPROVED.
	req := validRequest(t, StateDraft, CommandApprove, contracts.ActorHuman)
	req.PreconditionsSatisfied = []Precondition{PreconditionOwnerApproval}
	_, err := Apply(req)
	if err == nil {
		t.Fatal("a DRAFT strategy was allowed to invoke the approve command")
	}
	if !strings.Contains(err.Error(), "is declared for") {
		t.Errorf("error %q does not explain which edge the command belongs to", err)
	}
}

func TestUnauthorisedActorIsDenied(t *testing.T) {
	// Only HUMAN and SERVICE may submit for review; a SYSTEM actor may not.
	req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorSystem)
	_, err := Apply(req)
	if err == nil {
		t.Fatal("a SYSTEM actor was permitted to submit for review")
	}
	if !isAuthorizationDenial(err) {
		t.Errorf("refusal is %v, want an AUTHORIZATION_ERROR denial", err)
	}
	// The denial is a deny code, which authorization policy may not override.
	var rej Rejection
	if !errors.As(err, &rej) {
		t.Fatalf("refusal %v is not a Rejection", err)
	}
	if !rej.Code.IsDeny() {
		t.Errorf("code %s does not report IsDeny(); an authorization refusal is a deny", rej.Code)
	}
	if !strings.Contains(rej.Reason, "permitted:") {
		t.Errorf("reason %q does not tell the caller which actors are permitted", rej.Reason)
	}
}

func TestPreconditionMustBeSatisfied(t *testing.T) {
	req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
	req.PreconditionsSatisfied = nil
	if _, err := Apply(req); err == nil {
		t.Error("a transition with no precondition evidence was accepted")
	}
	// Asserting the wrong precondition is as good as asserting none.
	req.PreconditionsSatisfied = []Precondition{PreconditionFlatPosition}
	if _, err := Apply(req); err == nil {
		t.Error("a transition satisfied by the wrong precondition was accepted")
	}
	// Asserting the right one alongside others is fine.
	req.PreconditionsSatisfied = []Precondition{
		PreconditionFlatPosition, PreconditionReviewSubmission,
	}
	if _, err := Apply(req); err != nil {
		t.Errorf("a transition with its own precondition present was refused: %v", err)
	}
}

func TestMissingEvidenceReferenceIsRefused(t *testing.T) {
	// The audit record cites this reference, so an empty one produces an audit record that
	// points at nothing.
	for _, ref := range []string{"", "   "} {
		req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
		req.Reference = ref
		if _, err := Apply(req); err == nil {
			t.Errorf("reference %q was accepted", ref)
		}
	}
}

func TestUnattributedRequestIsRefused(t *testing.T) {
	for _, mutate := range []struct {
		name string
		fn   func(*Request)
	}{
		{"no actor id", func(r *Request) { r.ActorID = "" }},
		{"no actor type", func(r *Request) { r.ActorType = "" }},
	} {
		req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
		mutate.fn(&req)
		if _, err := Apply(req); err == nil {
			t.Errorf("a request with %s was accepted; an unattributed transition is not auditable", mutate.name)
		}
	}
}

func TestIdentityAndIdempotencyAreEnforced(t *testing.T) {
	// A non-strategy identifier cannot be advanced as a strategy.
	req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
	orderID, err := contracts.ParseIdentifier("ord_" + strategyBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	req.StrategyID = orderID
	if _, err := Apply(req); err == nil {
		t.Error("an order identifier was accepted as a strategy id")
	}
	// A short idempotency key could not deduplicate a retry.
	req = validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
	req.IdempotencyKey = "short"
	if _, err := Apply(req); err == nil {
		t.Error("a 5-character idempotency key was accepted")
	}
	// The zero identifier is not a strategy.
	req = validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorHuman)
	req.StrategyID = contracts.Identifier{}
	if _, err := Apply(req); err == nil {
		t.Error("an unset strategy id was accepted")
	}
}

func TestTerminalStateHasNoOnwardTransition(t *testing.T) {
	req := validRequest(t, StateRetired, CommandRetire, contracts.ActorHuman)
	if _, err := Apply(req); err == nil {
		t.Error("a RETIRED strategy was advanced further")
	}
	if !StateRetired.IsTerminal() {
		t.Error("RETIRED does not report IsTerminal()")
	}
	// DRAFT is the entry point, not an endpoint: it has an onward transition and must not
	// report terminal. The exhaustive loop below covers every non-terminal state, so this
	// case is called out separately only because it is the one most likely to be mistaken
	// for an endpoint when a state is added at the start of the chain.
	if StateDraft.IsTerminal() {
		t.Error("DRAFT reports terminal, but it has a declared transition to REVIEW")
	}
	// RETIRED is the only terminal state in the documented chain.
	for _, s := range AllStates() {
		if s != StateRetired && s.IsTerminal() {
			t.Errorf("state %s reports terminal, but only RETIRED is", s)
		}
	}
}

// TestApplyIsDeterministic checks that the same request always produces the same outcome.
// The Risk Engine contract requires determinism for a decision to be auditable and
// replayable, and a lifecycle transition is such a decision.
func TestApplyIsDeterministic(t *testing.T) {
	req := validRequest(t, StateShadow, CommandApprove, contracts.ActorHuman)
	first, err := Apply(req)
	if err != nil {
		t.Fatalf("first Apply: %v", err)
	}
	for i := 0; i < 50; i++ {
		again, err := Apply(req)
		if err != nil {
			t.Fatalf("Apply attempt %d: %v", i, err)
		}
		// Outcome holds a slice through Transition, so it is not comparable with ==.
		if !reflect.DeepEqual(again, first) {
			t.Fatalf("Apply is not deterministic: attempt %d produced %+v, first produced %+v", i, again, first)
		}
	}
	// A rejected request must be rejected identically every time too.
	bad := req
	bad.ActorType = contracts.ActorAgent
	_, firstErr := Apply(bad)
	if firstErr == nil {
		t.Fatal("an agent was permitted to approve; the determinism check needs a rejection")
	}
	for i := 0; i < 10; i++ {
		_, err := Apply(bad)
		if err == nil || err.Error() != firstErr.Error() {
			t.Fatalf("rejection is not deterministic at attempt %d", i)
		}
	}
}

// TestRejectionCarriesCodeAndCause checks both halves of the rejection contract survive:
// the canonical code for the wire, and the local sentinel for errors.Is.
func TestRejectionCarriesCodeAndCause(t *testing.T) {
	req := validRequest(t, StateDraft, CommandSubmitForReview, contracts.ActorSystem)
	_, err := Apply(req)
	if err == nil {
		t.Fatal("expected a rejection")
	}
	var rej Rejection
	if !errors.As(err, &rej) {
		t.Fatalf("error %v does not unwrap to a Rejection", err)
	}
	if rej.Code != contracts.CodeAuthorization {
		t.Errorf("code = %s, want AUTHORIZATION_ERROR", rej.Code)
	}
	if !errors.Is(err, contracts.ErrInvalidContractValue) {
		t.Error("rejection does not wrap ErrInvalidContractValue")
	}
	// The string form leads with the stable code.
	if !strings.HasPrefix(err.Error(), string(contracts.CodeAuthorization)) {
		t.Errorf("error string %q does not lead with the code", err.Error())
	}
}

func isAuthorizationDenial(err error) bool {
	var rej Rejection
	if errors.As(err, &rej) {
		return rej.Code == contracts.CodeAuthorization
	}
	return false
}

// TestStrategyHoldsNoFinancialAuthority is the mechanical form of acceptance criterion
// three. The strategy lifecycle is a deployment state machine; if its package could reach
// the venue adapter or the OMS, "proposes only" would be a comment rather than a property.
func TestStrategyHoldsNoFinancialAuthority(t *testing.T) {
	forbidden := []string{
		"adapters/venues",
		"components/oms",
		"components/risk-engine",
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
						t.Errorf("%s imports %q; the strategy lifecycle must not reach %s",
							filepath.Base(fset.Position(imp.Pos()).Filename), path, bad)
					}
				}
			}
		}
	}
	if !sawAny {
		t.Fatal("no source files were parsed; the authority check would pass vacuously")
	}
}

// TestDeployedIsEligibilityNotAuthority states the meaning of DEPLOYED, because it is the
// state most likely to be misread. Reaching it makes a strategy eligible for risk
// evaluation; it does not authorize a trade, and the deterministic veto still applies.
func TestDeployedIsEligibilityNotAuthority(t *testing.T) {
	deploy := byCmd[CommandDeploy]
	if deploy.To != StateDeployed {
		t.Fatalf("deploy command leads to %s, want DEPLOYED", deploy.To)
	}
	// Deployment requires no active halt and an explicit actor of record, and it is
	// human-gated. What it must not do is carry an order, fill, or venue reference, so
	// there is no field on the outcome through which financial authority could pass.
	out, err := Apply(validRequest(t, StateApproved, CommandDeploy, contracts.ActorHuman))
	if err != nil {
		t.Fatalf("deployment refused: %v", err)
	}
	if strings.Contains(strings.ToLower(out.AuditRecord), "order") ||
		strings.Contains(strings.ToLower(out.AuditRecord), "venue") ||
		strings.Contains(strings.ToLower(out.AuditRecord), "fill") {
		t.Errorf("deployment audit record implies trading authority: %q", out.AuditRecord)
	}
}
