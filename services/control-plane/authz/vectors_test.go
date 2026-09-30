package authz

import (
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// negativeVector is one case that must be refused, expressed as data.
//
// The vectors are table-driven rather than written as individual test functions so a
// reviewer can read the whole set at once and see what the policy is expected to refuse.
// A negative vector that is missing is a control nobody claimed to have tested, which is
// the failure mode AC5 exists to prevent.
type negativeVector struct {
	// name identifies the control the vector defends.
	name string
	// policy is the bundle in force for this case.
	policy Policy
	// request is the question being asked.
	request Request
	// failClosed marks the identity or policy source as unavailable.
	failClosed bool
	// policyAge is how old the policy bundle is. It exists because "the bundle is stale"
	// is itself a control that has to be exercised, and a harness that always fetched the
	// bundle a minute ago could never express it.
	policyAge time.Duration
	// expect is the refusal code the vector requires.
	//
	// Asserting the code is what makes this suite diagnostic rather than merely green. A
	// vector that checks only "this was refused" keeps passing after its own control has
	// been removed, because some unrelated check usually happens to catch the same request
	// anyway. That is how a broken control gets reported as a working one. Requiring the
	// specific reason means deleting a control turns its vector red, which is the only way
	// to know the control was there.
	expect Refusal
}

// permissivePolicy allows everything, so that a refusal in these vectors can only come
// from a structural control and not from a rule that happens not to match. This is what
// makes the suite meaningful: a vector tested against an empty policy would pass whether
// or not the control exists.
func permissivePolicy() Policy {
	return Policy{
		Digest: "sha256:negative-vectors-0001",
		Rules: []Rule{
			{Effect: EffectAllow, Reason: "allow every action to every role"},
		},
	}
}

// vectorRequest builds a request carrying a single valid, in-scope grant.
func vectorRequest(role Role, action Action, s Session) Request {
	return request([]Grant{grantOf(role)}, action, s)
}

var negativeVectors = []negativeVector{
	{
		name:   "authorization cannot approve financial risk",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleOwner, ActionApproveRisk, liveSession())
		}(),
		expect: RefusedRiskIsNotAuthorization,
	},
	{
		name:   "a risk operator cannot submit orders",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleRiskOperator, ActionSubmitOrder, liveSession())
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "a trading operator cannot change risk limits",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleTradingOperator, ActionChangeRiskLimit, liveSession())
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "a researcher cannot reach the trading path",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleResearcher, ActionSubmitOrder, liveSession())
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "an auditor cannot perform a trading action",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleAuditor, ActionCancelOrder, liveSession())
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "a platform operator cannot authorize live trading",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RolePlatformOperator, ActionLiveActivation, liveSession())
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "an owner cannot delete audit evidence directly",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleOwner, ActionDeleteEvidence, liveSession())
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "a service identity cannot grant roles",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleService, ActionGrantRole, liveSession())
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "a workload cannot exercise a human-only role",
		policy: permissivePolicy(),
		request: func() Request {
			r := vectorRequest(RoleOwner, ActionViewAudit, liveSession())
			r.SubjectType = contracts.ActorService
			return r
		}(),
		expect: RefusedExplicitly,
	},
	{
		name:   "a wildcard grant cannot perform a live financial operation",
		policy: permissivePolicy(),
		request: func() Request {
			g := grantOf(RoleTradingOperator)
			g.Scope = scopeOf([]string{Wildcard}, []string{Wildcard}, []string{Wildcard})
			return request([]Grant{g}, ActionSubmitOrder, liveSession())
		}(),
		expect: RefusedWildcardLive,
	},
	{
		name:   "a privileged action with a phishable factor is refused",
		policy: permissivePolicy(),
		request: func() Request {
			s := liveSession()
			s.AuthStrength = StrengthTOTP
			return vectorRequest(RoleOwner, ActionExportAudit, s)
		}(),
		expect: RefusedAuthStrength,
	},
	{
		name:   "a privileged action with a stale step-up is refused",
		policy: permissivePolicy(),
		request: func() Request {
			s := liveSession()
			s.StepUpAt = base.Add(-30 * time.Minute)
			return vectorRequest(RoleOwner, ActionLiveActivation, s)
		}(),
		expect: RefusedAuthStrength,
	},
	{
		name:   "an expired session is refused",
		policy: permissivePolicy(),
		request: func() Request {
			s := liveSession()
			s.AuthenticatedAt = base.Add(-24 * time.Hour)
			return vectorRequest(RoleOwner, ActionViewAudit, s)
		}(),
		expect: RefusedSessionInvalid,
	},
	{
		name:   "an idle session is refused",
		policy: permissivePolicy(),
		request: func() Request {
			s := liveSession()
			s.LastActiveAt = base.Add(-time.Hour)
			return vectorRequest(RoleOwner, ActionViewAudit, s)
		}(),
		expect: RefusedSessionInvalid,
	},
	{
		name:   "a revoked session is refused",
		policy: permissivePolicy(),
		request: func() Request {
			s := liveSession()
			s.Revoked = true
			return vectorRequest(RoleOwner, ActionViewAudit, s)
		}(),
		expect: RefusedSessionInvalid,
	},
	{
		name:   "a session on a superseded permission revision is refused",
		policy: permissivePolicy(),
		request: func() Request {
			s := liveSession()
			s.PermissionRevision = 6
			return vectorRequest(RoleOwner, ActionViewAudit, s)
		}(),
		expect: RefusedStaleContext,
	},
	{
		name:   "an expired grant admits nothing",
		policy: permissivePolicy(),
		request: func() Request {
			g := grantOf(RoleOwner)
			g.ExpiresAt = base.Add(-time.Minute)
			return request([]Grant{g}, ActionViewAudit, liveSession())
		}(),
		expect: RefusedOutOfScope,
	},
	{
		name:   "a cross-market request is refused",
		policy: permissivePolicy(),
		request: func() Request {
			r := vectorRequest(RoleTradingOperator, ActionSubmitOrder, liveSession())
			r.Market = "CRYPTO"
			return r
		}(),
		expect: RefusedOutOfScope,
	},
	{
		name:   "a cross-account request is refused",
		policy: permissivePolicy(),
		request: func() Request {
			r := vectorRequest(RoleTradingOperator, ActionSubmitOrder, liveSession())
			r.Account = "acct-999"
			return r
		}(),
		expect: RefusedOutOfScope,
	},
	{
		name:   "a cross-environment request is refused",
		policy: permissivePolicy(),
		request: func() Request {
			r := vectorRequest(RoleTradingOperator, ActionSubmitOrder, liveSession())
			r.Environment = "LIVE"
			return r
		}(),
		expect: RefusedOutOfScope,
	},
	{
		name:   "an unauthenticated request is refused",
		policy: permissivePolicy(),
		request: func() Request {
			r := vectorRequest(RoleOwner, ActionViewAudit, liveSession())
			r.SubjectID = ""
			return r
		}(),
		expect: RefusedNoRule,
	},
	{
		name:   "a subject with no grant is refused",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleOwner, ActionViewAudit, liveSession()).withGrants(nil)
		}(),
		expect: RefusedOutOfScope,
	},
	{
		name:   "an identity outage refuses risk-increasing work",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleTradingOperator, ActionSubmitOrder, liveSession())
		}(),
		failClosed: true,
		expect:     RefusedStaleContext,
	},
	{
		name:   "an identity outage refuses privileged work",
		policy: permissivePolicy(),
		request: func() Request {
			return vectorRequest(RoleOwner, ActionLiveActivation, liveSession())
		}(),
		failClosed: true,
		expect:     RefusedStaleContext,
	},
	{
		name: "a stale policy bundle refuses risk-increasing work",
		policy: Policy{
			Digest: "sha256:stale-0001",
			Rules:  []Rule{{Effect: EffectAllow, Reason: "allow everything"}},
		},
		policyAge: 10 * time.Minute,
		request: func() Request {
			return vectorRequest(RoleTradingOperator, ActionSubmitOrder, liveSession())
		}(),
		expect: RefusedStaleContext,
	},
	{
		name: "a stale policy bundle refuses privileged work",
		policy: Policy{
			Digest: "sha256:stale-0002",
			Rules:  []Rule{{Effect: EffectAllow, Reason: "allow everything"}},
		},
		policyAge: 30 * time.Minute,
		request: func() Request {
			return vectorRequest(RoleOwner, ActionLiveActivation, liveSession())
		}(),
		expect: RefusedStaleContext,
	},
	{
		// The vector is a break-glass subject reaching for the risk boundary directly, not
		// a break-glass subject using break-glass. A break-glass grant that could approve
		// risk would make the whole authority separation decorative during an incident,
		// which is exactly when it would be tried.
		name:   "a break-glass release cannot approve financial risk",
		policy: permissivePolicy(),
		request: func() Request {
			r := vectorRequest(RoleOwner, ActionApproveRisk, liveSession())
			r.SubjectType = contracts.ActorBreakGlass
			return r
		}(),
		expect: RefusedRiskIsNotAuthorization,
	},
	{
		name:   "a break-glass release cannot use a wildcard to place a live order",
		policy: permissivePolicy(),
		request: func() Request {
			g := grantOf(RoleOwner)
			g.Scope = scopeOf([]string{Wildcard}, []string{Wildcard}, []string{Wildcard})
			r := request([]Grant{g}, ActionSubmitOrder, liveSession())
			r.SubjectType = contracts.ActorBreakGlass
			return r
		}(),
		expect: RefusedWildcardLive,
	},
}

// withGrants returns a copy of the request with different grants.
func (r Request) withGrants(grants []Grant) Request {
	r.Grants = grants
	return r
}
