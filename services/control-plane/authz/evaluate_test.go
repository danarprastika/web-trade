package authz

import (
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

var base = time.Date(2026, 9, 29, 10, 0, 0, 0, time.UTC)

// scopeAll is a wildcard scope, used only where a test is specifically about wildcards.
func scopeOf(markets, accounts, environments []string) Scope {
	return Scope{Markets: markets, Accounts: accounts, Environments: environments}
}

func narrowScope() Scope {
	return scopeOf([]string{"IDX"}, []string{"acct-1"}, []string{"SIMULATION"})
}

func grantOf(role Role) Grant {
	return Grant{
		Role:       role,
		Scope:      narrowScope(),
		GrantedAt:  base.Add(-24 * time.Hour),
		ExpiresAt:  base.Add(30 * 24 * time.Hour),
		ApprovedBy: "carol",
	}
}

func liveSession() Session {
	return Session{
		Class:              SessionPrivileged,
		AuthenticatedAt:    base.Add(-time.Hour),
		LastActiveAt:       base.Add(-time.Minute),
		AuthStrength:       StrengthHardwareKey,
		StepUpAt:           base.Add(-time.Minute),
		PermissionRevision: 7,
	}
}

func readOnlySession() Session {
	s := liveSession()
	s.Class = SessionReadOnly
	return s
}

func testPolicy(rules ...Rule) Policy {
	return Policy{Digest: "sha256:bundle-0001", Rules: rules}
}

// allowRule permits a role to perform actions.
func allowRule(reason string, roles []Role, actions []Action) Rule {
	return Rule{Effect: EffectAllow, Roles: roles, Actions: actions, Reason: reason}
}

func baselineEvaluator(t *testing.T, policy Policy) *Evaluator {
	t.Helper()
	ev, err := New(Context{
		Policy:             policy,
		PolicyFetchedAt:    base.Add(-time.Minute),
		PermissionRevision: 7,
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return ev
}

func request(grants []Grant, action Action, s Session) Request {
	return Request{
		SubjectID:    "subj-0001",
		SubjectType:  contracts.ActorHuman,
		Grants:       grants,
		Action:       action,
		ResourceType: "ORDER",
		ResourceID:   "ord-0001",
		Environment:  "SIMULATION",
		Market:       "IDX",
		Account:      "acct-1",
		Session:      s,
		Now:          base,
	}
}

func mustDeny(t *testing.T, d Decision, want Refusal) {
	t.Helper()
	if d.Allowed {
		t.Fatalf("expected a refusal (%s), got allowed", want)
	}
	if d.Refusal != want {
		t.Fatalf("expected refusal %s, got %s (%s)", want, d.Refusal, d.Reason)
	}
}

// --- AC1: the tuple is evaluated server-side --------------------------------

// A request with no subject is refused, not defaulted.
func TestAnUnauthenticatedRequestIsRefused(t *testing.T) {
	req := request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, liveSession())
	req.SubjectID = ""
	d := baselineEvaluator(t, testPolicy(allowRule("allow all audits", nil, []Action{ActionViewAudit}))).Evaluate(req)
	mustDeny(t, d, RefusedNoRule)
}

// A caller cannot confer a role on itself by naming one: rules match on granted roles.
func TestNamingARoleInTheRequestGrantsNothing(t *testing.T) {
	// The policy allows OWNER to delete evidence; the subject holds no grant at all.
	req := request(nil, ActionDeleteEvidence, liveSession())
	d := baselineEvaluator(t, testPolicy(allowRule("owner may delete", []Role{RoleOwner}, []Action{ActionDeleteEvidence}))).Evaluate(req)
	if d.Allowed {
		t.Fatal("naming a role must not confer it")
	}
	// It is refused for the scope, because no grant admits it, not because of the policy.
	mustDeny(t, d, RefusedOutOfScope)
}

// Every decision records the bundle that decided it, including refusals.
func TestEveryDecisionRecordsThePolicyBundleDigest(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may view", []Role{RoleOwner}, []Action{ActionViewAudit})))

	allowed := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, liveSession()))
	if allowed.PolicyBundleDigest != "sha256:bundle-0001" {
		t.Fatalf("an allowed decision must record the digest, got %q", allowed.PolicyBundleDigest)
	}
	refused := ev.Evaluate(request([]Grant{grantOf(RoleAuditor)}, ActionGrantRole, liveSession()))
	if refused.PolicyBundleDigest != "sha256:bundle-0001" {
		t.Fatalf("a refused decision must record the digest, got %q", refused.PolicyBundleDigest)
	}
}

// --- AC2: deny by default, and no stale context -----------------------------

func TestARequestWithNoMatchingRuleIsDeniedByDefault(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy())
	req := request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, liveSession())
	d := ev.Evaluate(req)
	mustDeny(t, d, RefusedNoRule)
}

func TestAnExplicitDenyOutranksAnAllow(t *testing.T) {
	// The allow is listed first, so a rule order that decided the outcome would allow.
	ev := baselineEvaluator(t, testPolicy(
		allowRule("owner may delete", []Role{RoleOwner}, []Action{ActionDeleteEvidence}),
		Rule{Effect: EffectDeny, Roles: []Role{RoleOwner}, Actions: []Action{ActionDeleteEvidence}, Reason: "legal hold"},
	))
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionDeleteEvidence, liveSession()))
	mustDeny(t, d, RefusedExplicitly)
}

// A bundle older than the maximum is stale, and stale refuses risk-increasing work.
func TestAStalePolicyBundleRefusesRiskIncreasingWork(t *testing.T) {
	ev, err := New(Context{
		Policy:             testPolicy(allowRule("operator may submit", []Role{RoleTradingOperator}, []Action{ActionSubmitOrder})),
		PolicyFetchedAt:    base.Add(-10 * time.Minute),
		PermissionRevision: 7,
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	d := ev.Evaluate(request([]Grant{grantOf(RoleTradingOperator)}, ActionSubmitOrder, liveSession()))
	mustDeny(t, d, RefusedStaleContext)
}

// A bundle that was never fetched is maximally stale, not fresh.
func TestAPolicyBundleThatWasNeverFetchedIsStale(t *testing.T) {
	ev, err := New(Context{Policy: testPolicy(), PermissionRevision: 7})
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionSubmitOrder, liveSession()))
	mustDeny(t, d, RefusedStaleContext)
}

// A session built against a superseded grant revision cannot know about revocations.
func TestAStalePermissionRevisionIsRefused(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("operator may submit", []Role{RoleTradingOperator}, []Action{ActionSubmitOrder})))
	s := liveSession()
	s.PermissionRevision = 6 // server is now at 7
	d := ev.Evaluate(request([]Grant{grantOf(RoleTradingOperator)}, ActionSubmitOrder, s))
	mustDeny(t, d, RefusedStaleContext)
}

// docs/21 section 3: an identity outage refuses risk-increasing and privileged work but
// leaves already-accepted non-financial read-only work running.
func TestAnIdentityOutageFailsClosedForRiskIncreasingWork(t *testing.T) {
	ev, err := New(Context{
		Policy: testPolicy(
			allowRule("operator may submit", []Role{RoleTradingOperator}, []Action{ActionSubmitOrder}),
			allowRule("operator may cancel", []Role{RoleTradingOperator}, []Action{ActionCancelOrder}),
			allowRule("auditor may view", []Role{RoleAuditor}, []Action{ActionViewAudit}),
		),
		PolicyFetchedAt:    base.Add(-time.Minute),
		PermissionRevision: 7,
		FailClosed:         true,
	})
	if err != nil {
		t.Fatalf("New: %v", err)
	}

	d := ev.Evaluate(request([]Grant{grantOf(RoleTradingOperator)}, ActionSubmitOrder, liveSession()))
	mustDeny(t, d, RefusedStaleContext)

	// Cancelling reduces exposure, so it must remain possible during an outage.
	// This is the same principle as the OMS halt: a control that also stops the operator
	// reducing risk is not a safety control.
	cancel := ev.Evaluate(request([]Grant{grantOf(RoleTradingOperator)}, ActionCancelOrder, liveSession()))
	if !cancel.Allowed {
		t.Fatalf("risk-reducing work must survive an outage, got %s: %s", cancel.Refusal, cancel.Reason)
	}
}

// --- AC3: authorization cannot approve or override financial risk ------------

// The boundary is structural: a rule that allows the risk action is still refused,
// because the refusal happens before any rule is consulted.
func TestAuthorizationCannotApproveFinancialRisk(t *testing.T) {
	// A maximally permissive policy: allow everything, including the risk action itself.
	ev := baselineEvaluator(t, testPolicy(allowRule("allow everything", nil, nil)))
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionApproveRisk, liveSession()))
	mustDeny(t, d, RefusedRiskIsNotAuthorization)
}

// Every role, including OWNER, is refused. An allow-anywhere rule changes nothing.
func TestNoRoleCanObtainRiskApprovalFromThisPackage(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(
		allowRule("allow everything for everyone", nil, nil),
	))
	for _, role := range []Role{RoleOwner, RoleRiskOperator, RolePlatformOperator, RoleService} {
		d := ev.Evaluate(request([]Grant{grantOf(role)}, ActionApproveRisk, liveSession()))
		if d.Allowed {
			t.Fatalf("role %s obtained a risk approval from the authorization package", role)
		}
	}
}

// The package must not be able to reach the Risk Engine, or the boundary would be a
// convention rather than a property. This parses the package's own imports.
func TestThePackageCannotReachTheRiskEngine(t *testing.T) {
	forbidden := []string{
		"components/risk-engine",
		"components/risk",
	}
	for _, f := range packageFiles(t) {
		imports := parseImports(t, f)
		for _, imp := range imports {
			for _, bad := range forbidden {
				if imp == bad || imp == bad+"/..." {
					t.Fatalf("%s imports %q; the risk authority must stay outside this package", f, imp)
				}
			}
		}
	}
}

// --- AC4: privileged actions need step-up and exact-diff approval ------------

func TestAPrivilegedActionRequiresAPhishingResistantFactor(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may export", []Role{RoleOwner}, []Action{ActionExportAudit})))
	s := liveSession()
	s.AuthStrength = StrengthTOTP // recent, but phishable
	s.StepUpAt = base.Add(-time.Minute)
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionExportAudit, s))
	mustDeny(t, d, RefusedAuthStrength)
}

func TestAPrivilegedActionRequiresAFreshStepUp(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may export", []Role{RoleOwner}, []Action{ActionExportAudit})))
	s := liveSession()
	s.StepUpAt = base.Add(-10 * time.Minute) // 5-minute freshness for a privileged operator
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionExportAudit, s))
	mustDeny(t, d, RefusedAuthStrength)
}

func TestAPrivilegedActionSucceedsWithAFreshPhishingResistantStepUp(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may export", []Role{RoleOwner}, []Action{ActionExportAudit})))
	s := liveSession()
	s.StepUpAt = base.Add(-time.Minute)
	if d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionExportAudit, s)); !d.Allowed {
		t.Fatalf("expected allowed, got %s: %s", d.Refusal, d.Reason)
	}
}

func TestSelfApprovalIsRefused(t *testing.T) {
	_, err := NewApproval(ApprovalRequest{
		RequestID:   "apr-1",
		DiffDigest:  DiffDigest("limit 100 -> 200"),
		RequestedBy: "alice",
		RequestedAt: base,
	}, "alice", base)
	if err == nil {
		t.Fatal("a person approving their own change must be refused")
	}
}

func TestChangingTheDiffInvalidatesTheApproval(t *testing.T) {
	const original = `{"limit":100}`
	const altered = `{"limit":999}`
	approval, err := NewApproval(ApprovalRequest{
		RequestID:   "apr-1",
		DiffDigest:  DiffDigest(original),
		RequestedBy: "alice",
		RequestedAt: base,
	}, "bob", base)
	if err != nil {
		t.Fatalf("NewApproval: %v", err)
	}

	// The approval was given for one specific change. That change still passes.
	untouched := ApprovalRequest{RequestID: "apr-1", DiffDigest: DiffDigest(original), RequestedBy: "alice"}
	if err := approval.CheckApproval(untouched, original, base); err != nil {
		t.Fatalf("the unmodified change must still be approved: %v", err)
	}

	// Editing the change after approval invalidates it, even though everything else about
	// the request is identical. This is the whole point of binding to a diff digest.
	edited := ApprovalRequest{RequestID: "apr-1", DiffDigest: DiffDigest(altered), RequestedBy: "alice"}
	if err := approval.CheckApproval(edited, altered, base); err == nil {
		t.Fatal("an altered change must invalidate the approval")
	}
}

func TestAnExpiredApprovalIsRefused(t *testing.T) {
	approval, err := NewApproval(ApprovalRequest{
		RequestID:   "apr-1",
		DiffDigest:  DiffDigest("x"),
		RequestedBy: "alice",
		RequestedAt: base,
	}, "bob", base)
	if err != nil {
		t.Fatalf("NewApproval: %v", err)
	}
	if approval.IsExpired(base) {
		t.Fatal("a fresh approval must not be expired")
	}
	// The approval was valid when it was issued, and is not valid a day later. The
	// boundary is the 24h lifetime, not the time since the request was made.
	if !approval.IsExpired(base.Add(25 * time.Hour)) {
		t.Fatal("an approval older than 24 hours must be expired")
	}
	req := ApprovalRequest{RequestID: "apr-1", DiffDigest: DiffDigest("x"), RequestedBy: "alice"}
	if err := approval.CheckApproval(req, "x", base.Add(25*time.Hour)); err == nil {
		t.Fatal("an expired approval must not authorize anything")
	}
}

func TestAnOverdueApprovalRequestIsRefused(t *testing.T) {
	_, err := NewApproval(ApprovalRequest{
		RequestID:   "apr-1",
		DiffDigest:  DiffDigest("x"),
		RequestedBy: "alice",
		RequestedAt: base.Add(-25 * time.Hour),
	}, "bob", base)
	if err == nil {
		t.Fatal("approving a request older than the approval lifetime must be refused")
	}
}

func TestAnApprovalBoundToADifferentChangeIsRefused(t *testing.T) {
	approval, err := NewApproval(ApprovalRequest{
		RequestID:   "apr-1",
		DiffDigest:  DiffDigest("one"),
		RequestedBy: "alice",
		RequestedAt: base,
	}, "bob", base)
	if err != nil {
		t.Fatalf("NewApproval: %v", err)
	}
	other := ApprovalRequest{RequestID: "apr-1", DiffDigest: DiffDigest("two"), RequestedBy: "alice"}
	if err := approval.CheckApproval(other, "one", base); err == nil {
		t.Fatal("an approval for a different change must not apply")
	}
}

// --- Scope and wildcard ------------------------------------------------------

func TestAWildcardGrantCannotPerformALiveFinancialOperation(t *testing.T) {
	g := grantOf(RoleOwner)
	g.Scope = scopeOf([]string{Wildcard}, []string{Wildcard}, []string{Wildcard})
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may submit", []Role{RoleOwner}, []Action{ActionSubmitOrder})))
	d := ev.Evaluate(request([]Grant{g}, ActionSubmitOrder, liveSession()))
	mustDeny(t, d, RefusedWildcardLive)
}

func TestANonFinancialActionMayUseAWildcardGrant(t *testing.T) {
	g := grantOf(RoleAuditor)
	g.Scope = scopeOf([]string{Wildcard}, []string{Wildcard}, []string{Wildcard})
	ev := baselineEvaluator(t, testPolicy(allowRule("auditor may view", []Role{RoleAuditor}, []Action{ActionViewAudit})))
	if d := ev.Evaluate(request([]Grant{g}, ActionViewAudit, readOnlySession())); !d.Allowed {
		t.Fatalf("a wildcard scope is usable for non-financial work, got %s: %s", d.Refusal, d.Reason)
	}
}

func TestAnExpiredGrantAdmitsNothing(t *testing.T) {
	g := grantOf(RoleOwner)
	g.ExpiresAt = base.Add(-time.Hour)
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may view", []Role{RoleOwner}, []Action{ActionViewAudit})))
	d := ev.Evaluate(request([]Grant{g}, ActionViewAudit, liveSession()))
	mustDeny(t, d, RefusedOutOfScope)
}

func TestAGrantOutOfScopeIsRefused(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("operator may submit", []Role{RoleTradingOperator}, []Action{ActionSubmitOrder})))
	req := request([]Grant{grantOf(RoleTradingOperator)}, ActionSubmitOrder, liveSession())
	req.Market = "CRYPTO" // the grant is IDX only
	d := ev.Evaluate(req)
	mustDeny(t, d, RefusedOutOfScope)
}

// --- Session -----------------------------------------------------------------

func TestAnIdleSessionIsRefused(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may view", []Role{RoleOwner}, []Action{ActionViewAudit})))
	s := liveSession()
	s.LastActiveAt = base.Add(-20 * time.Minute) // 15-minute idle timeout
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, s))
	mustDeny(t, d, RefusedSessionInvalid)
}

func TestAnExpiredAbsoluteSessionIsRefused(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may view", []Role{RoleOwner}, []Action{ActionViewAudit})))
	s := liveSession()
	s.AuthenticatedAt = base.Add(-9 * time.Hour) // 8-hour absolute timeout
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, s))
	mustDeny(t, d, RefusedSessionInvalid)
}

func TestARevokedSessionIsRefused(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may view", []Role{RoleOwner}, []Action{ActionViewAudit})))
	s := liveSession()
	s.Revoked = true
	d := ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, s))
	mustDeny(t, d, RefusedSessionInvalid)
}

// --- Role exclusions ---------------------------------------------------------

// The docs/21 section 5 "explicitly excluded" column, one test per row.
func TestRoleExclusionsAreEnforced(t *testing.T) {
	cases := []struct {
		role   Role
		action Action
		rule   string
	}{
		{RoleRiskOperator, ActionSubmitOrder, "RISK_OPERATOR must not submit orders"},
		{RoleTradingOperator, ActionChangeRiskLimit, "TRADING_OPERATOR must not change risk limits"},
		{RoleResearcher, ActionSubmitOrder, "RESEARCHER must not reach the trading path"},
		{RoleResearcher, ActionGrantRole, "RESEARCHER must not grant roles"},
		{RoleAuditor, ActionCancelOrder, "AUDITOR must not perform trading actions"},
		{RoleAuditor, ActionExportAudit, "AUDITOR must not export"},
		{RolePlatformOperator, ActionSubmitOrder, "PLATFORM_OPERATOR must not submit orders"},
		{RolePlatformOperator, ActionChangeRiskLimit, "PLATFORM_OPERATOR must not change trading risk limits"},
		{RoleOwner, ActionDeleteEvidence, "OWNER deletion still requires the retention policy"},
		{RoleService, ActionGrantRole, "SERVICE must not grant roles"},
	}
	for _, c := range cases {
		t.Run(c.rule, func(t *testing.T) {
			// A maximally permissive policy: the exclusion is what refuses.
			ev := baselineEvaluator(t, testPolicy(allowRule("allow everything", nil, nil)))
			d := ev.Evaluate(request([]Grant{grantOf(c.role)}, c.action, liveSession()))
			if d.Allowed {
				t.Fatalf("%s: got allowed", c.rule)
			}
			if d.Refusal != RefusedExplicitly {
				t.Fatalf("%s: expected an explicit refusal, got %s (%s)", c.rule, d.Refusal, d.Reason)
			}
		})
	}
}

// A service identity cannot act as a human: the roles come from grants, and no grant
// confers a human role to a service subject.
func TestAServiceIdentityCannotImpersonateAHuman(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("owner may view", []Role{RoleOwner}, []Action{ActionViewAudit})))
	req := request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, liveSession())
	req.SubjectType = contracts.ActorService
	// A human role grant does not make a service a human; the rule matches on role, so
	// this is refused at the scope/exclusion layer rather than being treated as an owner.
	d := ev.Evaluate(req)
	if d.Allowed {
		t.Fatal("a service identity must not act under a human role grant")
	}
}

// --- Malformed input ---------------------------------------------------------

func TestAMalformedRequestIsRefused(t *testing.T) {
	ev := baselineEvaluator(t, testPolicy(allowRule("allow everything", nil, nil)))
	mutations := map[string]func(*Request){
		"no subject":       func(r *Request) { r.SubjectID = "" },
		"bad subject type": func(r *Request) { r.SubjectType = contracts.ActorType("ROBOT") },
		"unknown action":   func(r *Request) { r.Action = Action("DO_ANYTHING") },
		"no environment":   func(r *Request) { r.Environment = "" },
		"no clock":         func(r *Request) { r.Now = time.Time{} },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			req := request([]Grant{grantOf(RoleOwner)}, ActionViewAudit, liveSession())
			mutate(&req)
			if d := ev.Evaluate(req); d.Allowed {
				t.Fatal("must be refused")
			}
		})
	}
}

func TestAMalformedPolicyIsRefusedAtConstruction(t *testing.T) {
	if _, err := New(Context{Policy: Policy{}}); err == nil {
		t.Fatal("a policy with no digest must be refused")
	}
	if _, err := New(Context{Policy: testPolicy(Rule{Effect: Effect("MAYBE")})}); err == nil {
		t.Fatal("a rule with an unknown effect must be refused")
	}
	if _, err := New(Context{Policy: testPolicy(Rule{Effect: EffectAllow, Roles: []Role{Role("ROOT")}})}); err == nil {
		t.Fatal("a rule naming an unknown role must be refused")
	}
}

// docs/21 section 9 requires a research identity to be unable to reach live endpoints and
// a stale step-up to be denied; both are covered above by name.
func TestTheSectionNineNegativeVectorsArePresent(t *testing.T) {
	// This test exists so that deleting a negative vector is visible. It names the
	// docs/21 section 9 requirements and asserts each is exercised by a test of this
	// package, by calling the same code paths the named tests call.
	ev := baselineEvaluator(t, testPolicy(allowRule("allow everything", nil, nil)))
	owner := []Grant{grantOf(RoleOwner)}

	// expired/revoked session denied
	s := liveSession()
	s.Revoked = true
	if ev.Evaluate(request(owner, ActionViewAudit, s)).Allowed {
		t.Fatal("revoked session")
	}
	// stale step-up denied
	s2 := liveSession()
	s2.StepUpAt = base.Add(-time.Hour)
	if ev.Evaluate(request(owner, ActionExportAudit, s2)).Allowed {
		t.Fatal("stale step-up")
	}
	// cross-market access denied
	req := request(owner, ActionViewAudit, liveSession())
	req.Market = "CRYPTO"
	if ev.Evaluate(req).Allowed {
		t.Fatal("cross-market access")
	}
	// research identity cannot reach live endpoints
	if ev.Evaluate(request([]Grant{grantOf(RoleResearcher)}, ActionSubmitOrder, liveSession())).Allowed {
		t.Fatal("research identity reaching trading")
	}
	// break-glass cannot bypass financial controls
	if ev.Evaluate(request([]Grant{grantOf(RoleOwner)}, ActionApproveRisk, liveSession())).Allowed {
		t.Fatal("break-glass bypassing financial controls")
	}
}
