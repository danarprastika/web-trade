package authz

import (
	"errors"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The tests here cover AC1: "every command carries actor_id/actor_type and is evaluated
// server-side." The domain evaluator alone does not establish that. A Decision says a
// request was allowed; it does not say the command that permission was for, and it does not
// stop a handler from naming a subject other than the one on the envelope. These tests
// cover the binding that closes both gaps.

// mustID parses a command identifier or fails the test.
//
// The identifier type has no public constructor for a known-good value on purpose, so a
// test has to go through the parser. That is the same path production takes, which means a
// test cannot accidentally use an identifier the contract would reject. The payload is 26
// Crockford Base32 characters, matching the fixture idiom used elsewhere in the repository.
func mustID(t *testing.T, s string) contracts.Identifier {
	t.Helper()
	id, err := contracts.ParseIdentifier(s)
	if err != nil {
		t.Fatalf("parsing identifier %q: %v", s, err)
	}
	return id
}

// cmdID builds a valid, distinct command identifier. Each call with a different ordinal
// returns a different command, which is what the replay tests need in order to differ only
// in command identity.
func cmdID(t *testing.T, ordinal string) contracts.Identifier {
	t.Helper()
	return mustID(t, "cmd_"+ordinal+strings.Repeat("0", 26-len(ordinal)))
}

func envelopeFor(t *testing.T, actor string, actorType contracts.ActorType) contracts.CommandEnvelope {
	t.Helper()
	return contracts.CommandEnvelope{
		CommandID:      cmdID(t, "1"),
		CommandType:    "order.place",
		SchemaVersion:  "1.0.0",
		CorrelationID:  cmdID(t, "1"),
		ActorID:        actor,
		ActorType:      actorType,
		Environment:    contracts.EnvPaper,
		RequestedAt:    contracts.TimestampFrom(base),
		IdempotencyKey: "idem-0001",
		// The payload is not read by authorization; it is present because the command
		// contract requires one. A command without a payload is not a command.
		Payload: map[string]any{"account": "acct-1"},
	}
}

func submitIntent() CommandIntent {
	return CommandIntent{
		Action:       ActionSubmitOrder,
		ResourceType: "ORDER",
		ResourceID:   "ord-0001",
		Market:       "IDX",
		Account:      "acct-1",
	}
}

func ownerState() SubjectState {
	return SubjectState{Grants: []Grant{paperGrant(RoleOwner)}, Session: liveSession()}
}

func submitPolicy() Policy {
	return testPolicy(allowRule("trading operator may submit", []Role{RoleTradingOperator}, []Action{ActionSubmitOrder}))
}

func tradingState() SubjectState {
	return SubjectState{Grants: []Grant{paperGrant(RoleTradingOperator)}, Session: liveSession()}
}

// paperGrant is a grant scoped to the environment the command envelope carries.
//
// The environment comes from the envelope, which is authoritative, so a command test cannot
// use a grant scoped to a different environment. That is the point: it is what stops a
// simulation grant from authorizing a paper or live command, and the test would be
// meaningless if the two happened to share a scope string.
func paperGrant(role Role) Grant {
	g := grantOf(role)
	g.Scope = scopeOf([]string{"IDX"}, []string{"acct-1"}, []string{string(contracts.EnvPaper)})
	return g
}

// The whole point of the binding: a command is authorized as the actor on its envelope,
// not as whatever subject a handler names.
func TestACommandIsAuthorizedAsTheActorOnItsEnvelope(t *testing.T) {
	ev := baselineEvaluator(t, submitPolicy())
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)

	d, err := AuthorizeCommand(ev, env, submitIntent(), tradingState(), base)
	if err != nil {
		t.Fatalf("AuthorizeCommand: %v", err)
	}
	if !d.Effect.Allowed {
		t.Fatalf("a trading operator with a valid session and grant must be allowed: %s", d.Effect.Reason)
	}
}

// An actor with no grants is refused, even though the policy is permissive. This is the
// deny-by-default property, reached through the command path rather than the domain path.
func TestACommandFromAnActorWithNoGrantsIsRefused(t *testing.T) {
	ev := baselineEvaluator(t, submitPolicy())
	env := envelopeFor(t, "stranger", contracts.ActorHuman)

	d, err := AuthorizeCommand(ev, env, submitIntent(), SubjectState{Session: liveSession()}, base)
	if err != nil {
		t.Fatalf("AuthorizeCommand: %v", err)
	}
	mustDeny(t, d.Effect, RefusedOutOfScope)
}

// A permission is for one command. Replaying it against another command's envelope must
// fail, or the binding is decorative.
func TestAPermissionCannotBeReplayedAgainstADifferentCommand(t *testing.T) {
	ev := baselineEvaluator(t, submitPolicy())
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)

	d, err := AuthorizeCommand(ev, env, submitIntent(), tradingState(), base)
	if err != nil {
		t.Fatalf("AuthorizeCommand: %v", err)
	}
	if !d.Effect.Allowed {
		t.Fatalf("precondition: the command must be allowed, got %s", d.Effect.Reason)
	}

	other := env
	other.CommandID = cmdID(t, "2")
	if err := d.authorizesCommand(other); err == nil {
		t.Fatal("a permission issued for cmd-0001 must not authorize cmd-0002")
	} else if !errors.Is(err, ErrCommandNotEvaluated) {
		t.Fatalf("the refusal must be the command-not-evaluated sentinel, got %v", err)
	}
}

// Swapping the actor on the envelope must also fail, even with the same command ID. The
// command ID check alone would not catch this, which is why the actor is checked too.
func TestAPermissionCannotBeReplayedUnderADifferentActor(t *testing.T) {
	ev := baselineEvaluator(t, submitPolicy())
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)

	d, err := AuthorizeCommand(ev, env, submitIntent(), tradingState(), base)
	if err != nil {
		t.Fatalf("AuthorizeCommand: %v", err)
	}

	impostor := env
	impostor.ActorID = "trader-2"
	if err := d.authorizesCommand(impostor); err == nil {
		t.Fatal("a permission issued for trader-1 must not authorize trader-2")
	}
}

// The environment is authoritative on the envelope, so a permission issued for simulation
// must not carry into live. A grant scoped to SIMULATION would still admit the command if
// the environment came from anywhere but the envelope.
func TestAPermissionDoesNotCarryAcrossEnvironments(t *testing.T) {
	ev := baselineEvaluator(t, submitPolicy())
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)

	d, err := AuthorizeCommand(ev, env, submitIntent(), tradingState(), base)
	if err != nil {
		t.Fatalf("AuthorizeCommand: %v", err)
	}

	escalated := env
	escalated.Environment = contracts.EnvLive
	// The command is refused twice over: the grant does not cover LIVE, and the decision
	// is bound to a different environment. The binding check is what the test is about.
	if err := d.authorizesCommand(escalated); err == nil {
		t.Fatal("a permission issued for SIMULATION must not authorize a LIVE command")
	}
}

// An actor type change is a different subject, not a relabelling.
func TestAPermissionDoesNotCarryAcrossActorTypes(t *testing.T) {
	ev := baselineEvaluator(t, submitPolicy())
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)

	d, err := AuthorizeCommand(ev, env, submitIntent(), tradingState(), base)
	if err != nil {
		t.Fatalf("AuthorizeCommand: %v", err)
	}

	relabelled := env
	relabelled.ActorType = contracts.ActorBreakGlass
	if err := d.authorizesCommand(relabelled); err == nil {
		t.Fatal("a permission issued for a human must not authorize a break-glass actor")
	}
}

// A command that does not satisfy the envelope contract cannot be a trustworthy carrier of
// an identity, so it is refused before its actor fields are used at all.
func TestAMalformedEnvelopeIsRefusedBeforeEvaluation(t *testing.T) {
	ev := baselineEvaluator(t, submitPolicy())
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)
	env.CommandID = contracts.Identifier{} // the zero identifier is not a valid command ID

	if _, err := AuthorizeCommand(ev, env, submitIntent(), tradingState(), base); err == nil {
		t.Fatal("an envelope that violates the command contract must be refused")
	}
}

// The risk boundary must hold on the command path too. This is the same guarantee as
// TestTheNegativeVectorSuiteIsNonEmptyAndEveryVectorRefuses, reached the way production
// reaches it.
func TestACommandCannotAskAuthorizationToApproveRisk(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(
		allowRule("owner may do anything", []Role{RoleOwner}, []Action{ActionApproveRisk}),
	))
	env := envelopeFor(t, "owner-1", contracts.ActorHuman)
	intent := submitIntent()
	intent.Action = ActionApproveRisk

	d, err := AuthorizeCommand(ev, env, intent, ownerState(), base)
	if err != nil {
		t.Fatalf("AuthorizeCommand: %v", err)
	}
	mustDeny(t, d.Effect, RefusedRiskIsNotAuthorization)
}

// --- The executor guard --------------------------------------------------------

func executorFor(t *testing.T, p Policy) AuthorizeExecutor {
	t.Helper()
	return AuthorizeExecutor{
		Eval: baselineEvaluator(t, p),
		Now:  func() time.Time { return base },
	}
}

// A refusal must be an error as well as a decision, because a handler that ignores the
// decision and only checks the error must still be stopped.
func TestTheExecutorRefusesAndStillReturnsTheDecision(t *testing.T) {
	x := executorFor(t, submitPolicy())
	env := envelopeFor(t, "stranger", contracts.ActorHuman)

	d, err := x.Execute(env, submitIntent(), SubjectState{Session: liveSession()})
	if err == nil {
		t.Fatal("the executor must return an error for a refused command")
	}
	if !errors.Is(err, ErrUnauthorized) {
		t.Fatalf("the refusal must be attributable to authorization, got %v", err)
	}
	// The decision is still returned so the refusal can be audited, per docs/21 section 10.
	if d.Effect.Allowed || d.Effect.Refusal == "" {
		t.Fatal("a refused command must still produce a decision for the audit record")
	}
	if d.Envelope.CommandID != env.CommandID {
		t.Fatal("the returned decision must be bound to the command it was refused for")
	}
}

func TestTheExecutorAllowsAValidCommand(t *testing.T) {
	x := executorFor(t, submitPolicy())
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)

	d, err := x.Execute(env, submitIntent(), tradingState())
	if err != nil {
		t.Fatalf("a valid command must be permitted: %v", err)
	}
	if err := d.RequireAllowed(); err != nil {
		t.Fatalf("RequireAllowed: %v", err)
	}
	if d.Effect.PolicyBundleDigest == "" {
		t.Fatal("every decision must record which policy bundle made it")
	}
}

// An executor with no evaluator or no clock would otherwise evaluate optimistically, since
// there is nothing to refuse with. Making that a compile-visible runtime error keeps the
// failure explicit.
func TestAnUnconfiguredExecutorCannotAuthorize(t *testing.T) {
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)
	intent := submitIntent()

	if _, err := (AuthorizeExecutor{}).Execute(env, intent, tradingState()); err == nil {
		t.Fatal("an executor with no evaluator must not authorize anything")
	}
	noClock := AuthorizeExecutor{Eval: baselineEvaluator(t, submitPolicy())}
	if _, err := noClock.Execute(env, intent, tradingState()); err == nil {
		t.Fatal("an executor with no clock must not authorize anything")
	}
}

// The decision time must be the time the command is judged at, not the time the bundle was
// built. An executor whose clock has drifted past the bundle window must refuse
// risk-increasing work.
func TestTheExecutorJudgesAtItsOwnClockTime(t *testing.T) {
	x := AuthorizeExecutor{
		Eval: baselineEvaluator(t, submitPolicy()),
		Now:  func() time.Time { return base.Add(2 * time.Hour) },
	}
	env := envelopeFor(t, "trader-1", contracts.ActorHuman)

	if _, err := x.Execute(env, submitIntent(), tradingState()); err == nil {
		t.Fatal("a stale policy bundle must refuse a risk-increasing command")
	}
}
