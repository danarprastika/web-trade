package authz

import (
	"time"
)

// Evaluator decides authorization requests against a server-held context.
//
// It is constructed with the context rather than given one per call, so a single
// evaluation cannot mix a policy bundle from one moment with a session from another.
type Evaluator struct {
	ctx Context
}

// New returns an evaluator over a context.
func New(ctx Context) (*Evaluator, error) {
	if err := ctx.Policy.Validate(); err != nil {
		return nil, err
	}
	return &Evaluator{ctx: ctx}, nil
}

// Evaluate decides one request.
//
// The order of the checks is deliberate and is not an implementation detail:
//
//  1. Structural validity. A request that cannot be evaluated is not evaluated.
//  2. Risk boundary. A caller asking this package to approve financial risk is refused
//     outright, before any rule is consulted.
//  3. Fail-closed. An unavailable or stale source refuses risk-increasing and privileged
//     work before anything else is considered, so an outage cannot be reasoned around by
//     a permissive rule.
//  4. Session validity, grant currency, and step-up.
//  5. Role exclusions from docs/21 section 5.
//  6. Scope, including the wildcard prohibition for live financial operations.
//  7. Explicit deny, which outranks allow regardless of rule order.
//  8. Allow, which requires at least one matching rule. Everything above this point is
//     subtractive; only here is a request permitted.
func (e *Evaluator) Evaluate(req Request) Decision {
	digest := e.ctx.Policy.Digest
	age := e.ctx.staleness(req.Now)

	if err := req.Validate(); err != nil {
		return Decision{
			Refusal:            RefusedNoRule,
			Reason:             err.Error(),
			PolicyBundleDigest: digest,
			PolicyBundleAge:    age,
		}
	}

	// 2. The risk boundary. ADR-018: authorization policy cannot approve or override
	// financial risk. This package has no affirmative risk decision to give, so the only
	// thing it can do with such a request is refuse it and say so.
	if req.Action == ActionApproveRisk {
		return deny(RefusedRiskIsNotAuthorization, digest, age,
			"%s is decided by the Risk Engine; authorization cannot approve or override financial risk", req.Action)
	}

	// 2a. Impersonation. A non-human subject exercising a human-only role is refused before
	// any rule is consulted, so no policy edit can route a workload through an operator
	// role. This sits next to the risk boundary rather than with the role exclusions
	// because it is about who is asking, not about what the role may do.
	if role, ok := req.impersonates(); ok {
		return deny(RefusedExplicitly, digest, age,
			"a %s subject cannot exercise the human-only role %s; service identities cannot impersonate humans",
			req.SubjectType, role)
	}

	// 3. Fail closed. The policy bundle is stale, or the source is unavailable.
	if e.ctx.FailClosed || age > MaxPolicyBundleAge {
		if req.Action.IsRiskIncreasing() || req.Action.IsPrivileged() {
			return deny(RefusedStaleContext, digest, age,
				"the authorization source is %s; risk-increasing and privileged actions are refused",
				describeStaleness(e.ctx.FailClosed, age))
		}
		// docs/21 section 3 permits already-accepted non-financial read-only work to
		// continue while the source is merely unavailable. It is not permitted past a
		// stale bundle, which the branch above already covers.
	}

	// 4. Session validity and step-up.
	sessionPolicy, bad := checkSession(req.Session, req.Now)
	if bad != nil {
		bad.PolicyBundleDigest = digest
		bad.PolicyBundleAge = age
		return *bad
	}
	// The session must have been built against the current grant revision. A session
	// holding an older revision cannot know about a revocation that has since happened,
	// which is the same reason the bundle must not be stale.
	if req.Session.PermissionRevision != e.ctx.PermissionRevision {
		return deny(RefusedStaleContext, digest, age,
			"the session was built against permission revision %d but the current revision is %d",
			req.Session.PermissionRevision, e.ctx.PermissionRevision)
	}
	if bad := checkStepUp(req.Session, sessionPolicy, req.Action, req.Now); bad != nil {
		bad.PolicyBundleDigest = digest
		bad.PolicyBundleAge = age
		return *bad
	}

	// 5. Role exclusions from docs/21 section 5. These are refusals, not absences of
	// permission: a role that is excluded from an action is refused even if a rule would
	// allow it, and no role name in the request lifts the exclusion. That is deliberate.
	// docs/21 section 5 states the exclusions absolutely: an OWNER does not bypass risk, a
	// RISK_OPERATOR does not submit orders, a RESEARCHER does not self-approve. Encoding a
	// plausible-sounding override here would be the easiest possible way for that guarantee
	// to quietly stop being true, so there is no override to call.
	held := req.roles()
	if blocked := excludedBy(req.Action); len(blocked) > 0 {
		for _, role := range held {
			if blocked[role] {
				return deny(RefusedExplicitly, digest, age,
					"role %s is explicitly excluded from %s", role, req.Action)
			}
		}
	}

	// 6. Scope. Every role the subject holds must come from a grant, and some grant must
	// admit this request's market, account, and environment.
	if !req.covers(req.Now) {
		return deny(RefusedOutOfScope, digest, age,
			"no grant admits %s/%s/%s at this time", req.Market, req.Account, req.Environment)
	}
	if req.wildcardFinancial() {
		return deny(RefusedWildcardLive, digest, age,
			"%s is a live financial operation and wildcard grants are prohibited", req.Action)
	}

	// 7. Explicit deny outranks allow, regardless of rule order.
	for _, rule := range e.ctx.Policy.Rules {
		if rule.Effect == EffectDeny && rule.matches(req, held) {
			return deny(RefusedExplicitly, digest, age, "an explicit deny matched: %s", rule.Reason)
		}
	}

	// 8. Allow requires a matching rule. This is where deny-by-default lives: reaching
	// this point without a match is a refusal, not a permission.
	for _, rule := range e.ctx.Policy.Rules {
		if rule.Effect == EffectAllow && rule.matches(req, held) {
			return allow(digest, age)
		}
	}
	return deny(RefusedNoRule, digest, age, "no rule allows %s for this subject", req.Action)
}

// describeStaleness names why the source was considered unavailable.
func describeStaleness(failClosed bool, age time.Duration) string {
	switch {
	case failClosed:
		return "unavailable"
	case age > MaxPolicyBundleAge:
		return "stale"
	default:
		return "unavailable or stale"
	}
}
