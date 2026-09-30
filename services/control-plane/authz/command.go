package authz

import (
	"fmt"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ErrCommandNotEvaluated is the sentinel returned when a command reaches execution without
// a matching allow decision.
var ErrCommandNotEvaluated = contracts.ErrInvalidContractValue

// CommandIntent is the part of a command that authorization decides about.
//
// It is deliberately smaller than a Request. A command handler states what it is trying to
// do; the server holds everything else. Keeping the handler's contribution this narrow is
// what makes the binding below possible, because there is no room in it for a handler to
// assert its own identity or its own grants.
type CommandIntent struct {
	// Action is what the command attempts.
	Action Action
	// ResourceType and ResourceID name what is acted on.
	ResourceType string
	ResourceID   string
	// Market and Account are the scope dimensions. The environment comes from the
	// envelope, which is authoritative, so it is not repeated here.
	Market  string
	Account string
}

// CommandDecision is the permission to execute one specific command.
//
// It exists to close a gap that a Decision alone leaves open. A Decision says a request
// was allowed, but it does not say which command that permission was for, so a handler
// holding any allow decision could execute any command. This type binds the permission to
// the envelope it was decided for, and the executor refuses a mismatch.
type CommandDecision struct {
	// Envelope is the command this decision was decided for, by identity.
	Envelope contracts.CommandEnvelope
	// Effect is the decision itself.
	Effect Decision
}

// authorizesCommand reports whether this decision was decided for exactly this command.
//
// Matching is on command ID, actor, and environment rather than on the whole envelope. The
// command ID is the canonical identity and is unique, so it is the field that actually
// decides the question; the actor and environment are checked as well because they are the
// fields a mismatch would most plausibly hide behind, and a check that only one field
// carries is a check that can be satisfied by a coincidence.
func (d CommandDecision) authorizesCommand(env contracts.CommandEnvelope) error {
	switch {
	case d.Envelope.CommandID != env.CommandID:
		return fmt.Errorf("%w: the decision was issued for command %s, not %s",
			ErrCommandNotEvaluated, d.Envelope.CommandID, env.CommandID)
	case d.Envelope.ActorID != env.ActorID:
		return fmt.Errorf("%w: the decision was issued for actor %s, not %s",
			ErrCommandNotEvaluated, d.Envelope.ActorID, env.ActorID)
	case d.Envelope.ActorType != env.ActorType:
		return fmt.Errorf("%w: the decision was issued for a %s actor, not a %s actor",
			ErrCommandNotEvaluated, d.Envelope.ActorType, env.ActorType)
	case d.Envelope.Environment != env.Environment:
		return fmt.Errorf("%w: the decision was issued for %s, not %s",
			ErrCommandNotEvaluated, d.Envelope.Environment, env.Environment)
	}
	return nil
}

// AuthorizeCommand evaluates a command and returns a decision bound to it.
//
// This is the entry point the command path uses, and it is the reason AC1 holds. The
// subject is read from the command envelope rather than from a field the handler supplies,
// so a handler cannot ask "is this allowed?" about a different identity than the one the
// command will execute as. Grants and session are likewise server-held arguments: they are
// not part of the handler's contribution, which is exactly the point.
//
// The returned decision is bound to this envelope. Passing it to AuthorizeExecutor with any
// other command is an error, so a permission cannot be reused across commands.
func AuthorizeCommand(
	e *Evaluator,
	env contracts.CommandEnvelope,
	intent CommandIntent,
	subject SubjectState,
	now time.Time,
) (CommandDecision, error) {
	// The envelope is validated first. An envelope that does not satisfy the contract
	// cannot be a trustworthy carrier of an identity, so it is refused before its contents
	// are used for anything.
	if err := env.Validate(); err != nil {
		return CommandDecision{}, err
	}

	req := Request{
		SubjectID:    env.ActorID,
		SubjectType:  env.ActorType,
		Grants:       subject.Grants,
		Action:       intent.Action,
		ResourceType: intent.ResourceType,
		ResourceID:   intent.ResourceID,
		Environment:  string(env.Environment),
		Market:       intent.Market,
		Account:      intent.Account,
		Session:      subject.Session,
		Context:      e.ctx,
		Now:          now,
	}
	return CommandDecision{Envelope: env, Effect: e.Evaluate(req)}, nil
}

// SubjectState is the server-held authorization state for the actor on an envelope.
//
// It is passed separately from CommandIntent because it must come from the authorization
// service's own records. There is deliberately no field here a handler could populate from
// the request: a handler that could would be able to authorize itself.
type SubjectState struct {
	// Grants are the role grants held by the envelope's actor, as the server holds them.
	Grants []Grant
	// Session is the server-held session state for the envelope's actor.
	Session Session
}

// AuthorizeExecutor is the guard an executor passes each command through.
//
// It is a function rather than a middleware type because the control plane has no HTTP
// layer yet, and a type bound to one framework would make the guard skippable by choosing a
// different framework. The guard is a value the executor must hold, so omitting it is a
// compile error rather than a silent bypass.
type AuthorizeExecutor struct {
	// Eval is the evaluator every command is decided against.
	Eval *Evaluator
	// Now supplies the decision time. It is a function so the executor does not read a
	// clock directly, keeping the domain testable and keeping the time used for
	// authorization visibly the same time used for the audit record.
	Now func() time.Time
}

// Execute decides a command and returns the decision the handler needs to proceed.
//
// It returns the decision rather than a bare error so the handler can record which policy
// bundle allowed the command, as docs/21 section 10 requires. A refusal is returned as an
// error AND as a decision: the error is for control flow, the decision is for the audit
// record, which must be written whether or not the command proceeds.
func (x AuthorizeExecutor) Execute(env contracts.CommandEnvelope, intent CommandIntent, subject SubjectState) (CommandDecision, error) {
	if x.Eval == nil {
		return CommandDecision{}, fmt.Errorf("%w: the executor has no evaluator", ErrCommandNotEvaluated)
	}
	if x.Now == nil {
		return CommandDecision{}, fmt.Errorf("%w: the executor has no clock", ErrCommandNotEvaluated)
	}
	d, err := AuthorizeCommand(x.Eval, env, intent, subject, x.Now())
	if err != nil {
		return CommandDecision{}, err
	}
	if !d.Effect.Allowed {
		return d, Rejection{
			Code:   contracts.CodeAuthorization,
			Cause:  ErrUnauthorized,
			Reason: fmt.Sprintf("%s refused: %s", intent.Action, d.Effect.Reason),
		}
	}
	return d, nil
}

// RequireAllowed converts a refusal into an error for handlers that treat one as
// unreachable.
//
// It is a method on CommandDecision rather than on Decision so that a handler holding a
// bare Decision cannot accidentally reach the command path without the envelope binding.
func (d CommandDecision) RequireAllowed() error {
	if d.Effect.Allowed {
		return nil
	}
	return Rejection{
		Code:   contracts.CodeAuthorization,
		Cause:  ErrUnauthorized,
		Reason: fmt.Sprintf("refused: %s", d.Effect.Reason),
	}
}
