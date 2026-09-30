package authz

import "time"

// Session is the server-held session state for a subject.
//
// Every field is server-held. None of it is read from a token the caller presented, which
// is what makes the evaluation server-side: a caller cannot extend its own session,
// restate its own auth strength, or claim a permission revision it was never granted.
type Session struct {
	// Class selects the timeout profile.
	Class SessionClass
	// AuthenticatedAt is when the session was established.
	AuthenticatedAt time.Time
	// LastActiveAt is the last time the session was used, for the idle timeout.
	LastActiveAt time.Time
	// AuthStrength is the strength of the authentication backing this session.
	AuthStrength AuthStrength
	// StepUpAt is when the subject last re-authenticated for a privileged action. It is
	// separate from AuthenticatedAt because a session opened this morning with a fresh
	// login can still be too old to authorise a high-impact action.
	StepUpAt time.Time
	// PermissionRevision is the revision of the subject's role grants that this session
	// was built against. A session built against an older revision than the server
	// currently holds has not seen the current grants, and is refused rather than
	// evaluated against a superseded view.
	PermissionRevision int
	// Revoked marks a session that has been invalidated.
	Revoked bool
}

// Context is the server-held authorization context for a policy evaluation.
type Context struct {
	// Policy is the bundle to evaluate against.
	Policy Policy
	// PolicyFetchedAt is when the bundle was obtained. An old bundle is not stale in
	// every respect, but it cannot know what changed since, so beyond MaxPolicyBundleAge
	// the request is refused rather than decided.
	PolicyFetchedAt time.Time
	// PermissionRevision is the current revision of role grants on the server.
	PermissionRevision int
	// FailClosed marks that the identity or policy source is unavailable. docs/21 sections
	// 3 and 10 require denial of new sessions, privileged mutations, live activation, and
	// risk-increasing commands in that state, while already-accepted non-financial
	// read-only work may continue under the bounded cache rule.
	FailClosed bool
}

// staleness returns how old the policy bundle is.
func (c Context) staleness(now time.Time) time.Duration {
	if c.PolicyFetchedAt.IsZero() {
		// A bundle that was never fetched is maximally stale rather than fresh.
		return time.Duration(1<<63 - 1)
	}
	return now.Sub(c.PolicyFetchedAt)
}

// checkSession validates the session against its class policy and the current time.
func checkSession(s Session, now time.Time) (SessionPolicy, *Decision) {
	policy, ok := PolicyFor(s.Class)
	if !ok {
		return policy, decisionPtr(deny(RefusedSessionInvalid, "", 0,
			"session class %q is not in the closed set", s.Class))
	}

	if s.Revoked {
		return policy, decisionPtr(deny(RefusedSessionInvalid, "", 0,
			"the session has been revoked; revocation takes effect within %s and this session predates or follows it", RevocationWindow))
	}
	if s.AuthenticatedAt.IsZero() || s.LastActiveAt.IsZero() {
		return policy, decisionPtr(deny(RefusedSessionInvalid, "", 0,
			"the session carries no established time"))
	}
	if now.Sub(s.AuthenticatedAt) > policy.AbsoluteTimeout {
		return policy, decisionPtr(deny(RefusedSessionInvalid, "", 0,
			"the session exceeded its %s absolute timeout", policy.AbsoluteTimeout))
	}
	if now.Sub(s.LastActiveAt) > policy.IdleTimeout {
		return policy, decisionPtr(deny(RefusedSessionInvalid, "", 0,
			"the session exceeded its %s idle timeout", policy.IdleTimeout))
	}
	return policy, nil
}

// checkStepUp verifies the subject re-authenticated recently enough for a privileged
// action, with a phishing-resistant factor.
//
// Both halves are required. A recent step-up with a phishable factor is not a step-up for
// a privileged action, and a phishing-resistant factor from yesterday is not a fresh one.
func checkStepUp(s Session, policy SessionPolicy, action Action, now time.Time) *Decision {
	if !action.IsPrivileged() {
		return nil
	}
	if s.AuthStrength < StrengthWebAuthn || !s.AuthStrength.IsPhishingResistant() {
		return decisionPtr(deny(RefusedAuthStrength, "", 0,
			"%s is privileged and requires a phishing-resistant factor; the session has %s", action, s.AuthStrength))
	}
	if policy.StepUpFreshness == 0 {
		return decisionPtr(deny(RefusedAuthStrength, "", 0,
			"%s is privileged and this session class has no step-up policy", action))
	}
	if s.StepUpAt.IsZero() {
		return decisionPtr(deny(RefusedAuthStrength, "", 0,
			"%s is privileged and requires a step-up within %s; the session records none", action, policy.StepUpFreshness))
	}
	if now.Sub(s.StepUpAt) > policy.StepUpFreshness {
		return decisionPtr(deny(RefusedAuthStrength, "", 0,
			"%s requires a step-up within %s; the last one was %s ago",
			action, policy.StepUpFreshness, now.Sub(s.StepUpAt).Round(time.Second)))
	}
	return nil
}

// decisionPtr wraps a denial for return as an optional value. It exists so the checks can
// return a decision without every caller having to allocate a pointer first.
func decisionPtr(d Decision) *Decision { return &d }
