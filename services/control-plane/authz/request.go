package authz

import (
	"sort"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Action is what the subject is attempting.
//
// The set is closed so a policy author cannot invent an action, and so an action this
// package does not know about is refused rather than falling through to a default that
// might be allow.
type Action string

const (
	ActionViewAudit       Action = "AUDIT_VIEW"
	ActionExportAudit     Action = "AUDIT_EXPORT"
	ActionViewPosition    Action = "POSITION_VIEW"
	ActionSubmitOrder     Action = "ORDER_SUBMIT"
	ActionCancelOrder     Action = "ORDER_CANCEL"
	ActionPauseStrategy   Action = "STRATEGY_PAUSE"
	ActionChangeRiskLimit Action = "RISK_LIMIT_CHANGE"
	ActionHaltTrading     Action = "HALT_TRADING"
	ActionClearHalt       Action = "HALT_CLEAR"
	ActionGrantRole       Action = "ROLE_GRANT"
	ActionLiveActivation  Action = "LIVE_ACTIVATION"
	ActionBreakGlass      Action = "BREAK_GLASS_RELEASE"
	ActionDeleteEvidence  Action = "AUDIT_DELETE"
	// ActionApproveRisk is the action a caller would use to ask this package to approve
	// financial risk. It is in the set only so such a request is refused by name, as
	// ADR-018 requires, rather than as an unrecognised action. No rule can allow it: the
	// evaluator refuses it before any rule is consulted, and no role holds it.
	ActionApproveRisk Action = "RISK_APPROVE"
)

var actions = map[Action]bool{
	ActionViewAudit: true, ActionExportAudit: true, ActionViewPosition: true,
	ActionSubmitOrder: true, ActionCancelOrder: true, ActionPauseStrategy: true,
	ActionChangeRiskLimit: true, ActionHaltTrading: true, ActionClearHalt: true,
	ActionGrantRole: true, ActionLiveActivation: true, ActionBreakGlass: true,
	ActionDeleteEvidence: true, ActionApproveRisk: true,
}

// IsValid reports whether the action is in the closed set.
func (a Action) IsValid() bool { return actions[a] }

// IsPrivileged reports whether the action needs a step-up and, for high-impact actions,
// a second-person approval.
//
// The classification is a property of the action rather than of the role, so a policy
// cannot mark a privileged action as ordinary by granting it to a low-privilege role.
//
// ActionApproveRisk is privileged because it would be the most privileged thing possible;
// it is listed so that a caller trying it is refused with a step-up complaint before the
// risk-boundary check explains why it could never have worked.
func (a Action) IsPrivileged() bool {
	switch a {
	case ActionExportAudit, ActionChangeRiskLimit, ActionHaltTrading, ActionClearHalt,
		ActionGrantRole, ActionLiveActivation, ActionBreakGlass, ActionDeleteEvidence,
		ActionApproveRisk:
		return true
	default:
		return false
	}
}

// IsRiskIncreasing reports whether the action adds financial exposure.
//
// This is used to decide what a fail-closed state must block, per docs/21 sections 3 and
// 10. It is deliberately about exposure and not about permission: cancelling an order is
// financially significant and still permitted during a fail-closed stop, because trapping
// an operator in an open position is not a safety control.
func (a Action) IsRiskIncreasing() bool {
	switch a {
	case ActionSubmitOrder, ActionLiveActivation, ActionChangeRiskLimit:
		return true
	default:
		return false
	}
}

// IsFinancial reports whether the action touches live financial state.
//
// docs/21 section 4 prohibits wildcard grants for live financial operations, so this
// classification is what the wildcard check keys on.
func (a Action) IsFinancial() bool {
	switch a {
	case ActionSubmitOrder, ActionCancelOrder, ActionChangeRiskLimit,
		ActionHaltTrading, ActionClearHalt, ActionLiveActivation:
		return true
	default:
		return false
	}
}

// AuthStrength is how well the subject proved who they are.
//
// docs/21 section 2 requires phishing-resistant MFA for privileged roles and section 3
// requires a fresh step-up for sensitive actions. The order matters and is enforced by
// comparison, so a stronger method always satisfies a weaker requirement.
type AuthStrength int

const (
	// StrengthNone is unauthenticated. It satisfies nothing.
	StrengthNone AuthStrength = iota
	// StrengthPassword is a single factor.
	StrengthPassword
	// StrengthTOTP is a time-based second factor. It is not phishing-resistant.
	StrengthTOTP
	// StrengthWebAuthn is a phishing-resistant factor.
	StrengthWebAuthn
	// StrengthHardwareKey is a phishing-resistant factor bound to a specific operator.
	StrengthHardwareKey
)

// String implements fmt.Stringer.
func (a AuthStrength) String() string {
	switch a {
	case StrengthNone:
		return "NONE"
	case StrengthPassword:
		return "PASSWORD"
	case StrengthTOTP:
		return "TOTP"
	case StrengthWebAuthn:
		return "WEBAUTHN"
	case StrengthHardwareKey:
		return "HARDWARE_KEY"
	default:
		return "UNKNOWN"
	}
}

// IsPhishingResistant reports whether the factor resists phishing.
func (a AuthStrength) IsPhishingResistant() bool {
	return a == StrengthWebAuthn || a == StrengthHardwareKey
}

// SessionClass is the timeout profile of a session, from docs/21 section 3.
type SessionClass string

const (
	SessionPrivileged SessionClass = "PRIVILEGED_OPERATOR"
	SessionReadOnly   SessionClass = "READ_ONLY_OPERATOR"
	SessionService    SessionClass = "SERVICE_WORKLOAD"
)

// SessionPolicy is the timeout profile for a session class.
type SessionPolicy struct {
	// IdleTimeout is how long the session may sit unused.
	IdleTimeout time.Duration
	// AbsoluteTimeout is how long the session may exist in total.
	AbsoluteTimeout time.Duration
	// StepUpFreshness is how recently a privileged action must have been re-authenticated.
	StepUpFreshness time.Duration
}

// sessionPolicies implements the table in docs/21 section 3.
//
// These are the specification's numbers, not defaults chosen for convenience. The read-only
// class has a shorter step-up freshness than privileged, which looks backwards until you
// notice it applies only to confidential export; the values are carried through as written.
var sessionPolicies = map[SessionClass]SessionPolicy{
	SessionPrivileged: {IdleTimeout: 15 * time.Minute, AbsoluteTimeout: 8 * time.Hour, StepUpFreshness: 5 * time.Minute},
	SessionReadOnly:   {IdleTimeout: 30 * time.Minute, AbsoluteTimeout: 8 * time.Hour, StepUpFreshness: 15 * time.Minute},
	SessionService:    {IdleTimeout: 15 * time.Minute, AbsoluteTimeout: time.Hour, StepUpFreshness: 0},
}

// PolicyFor returns the timeout profile for a session class.
func PolicyFor(class SessionClass) (SessionPolicy, bool) {
	p, ok := sessionPolicies[class]
	return p, ok
}

// AllSessionClasses returns every session class in the closed set.
//
// It exists so the SQL contract test can check that db/migrations/0003_authz.sql seeds the
// same classes with the same numbers. The table is duplicated in SQL on purpose, so a test
// that can see only one copy cannot notice the copies disagreeing.
func AllSessionClasses() []SessionClass {
	out := make([]SessionClass, 0, len(sessionPolicies))
	for class := range sessionPolicies {
		out = append(out, class)
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

// MaxPolicyBundleAge is the oldest an authorization policy bundle may be and still be
// used, from docs/21 sections 3 and 10. Beyond it, the source is unavailable or stale and
// the request is denied rather than evaluated against what is cached.
const MaxPolicyBundleAge = 5 * time.Minute

// RevocationWindow is how long a role revocation or account disablement may take to
// propagate, from docs/21 section 2 item 7. A context that could predate a revocation by
// longer than this is refused.
const RevocationWindow = 60 * time.Second

// ApprovalTTL is how long an approval of a high-impact change remains valid, from
// docs/21 section 6.
const ApprovalTTL = 24 * time.Hour

// Scope is the resource boundary a subject is confined to.
//
// Scope is expressed as explicit sets rather than as a wildcard. docs/21 section 4
// prohibits wildcard grants for live financial operations, and the only way to enforce
// that is for the data model to have no wildcard to grant.
type Scope struct {
	// Markets the subject may act in, e.g. "IDX".
	Markets []string
	// Accounts the subject may act on, e.g. "acct-1".
	Accounts []string
	// Environments the subject may act in, e.g. "SIMULATION".
	Environments []string
}

// Covers reports whether the scope admits a value.
//
// A scope with no entries for a dimension admits nothing in that dimension. An empty
// scope is therefore the most restrictive scope, not the least, which is the safe
// direction for a field that fails to load. A wildcard entry admits everything in that
// dimension, which is what makes a wildcard usable at all and is why
// docs/21 section 4 can prohibit it for live financial operations.
func (s Scope) Covers(market, account, environment string) bool {
	return scopeContains(s.Markets, market) &&
		scopeContains(s.Accounts, account) &&
		scopeContains(s.Environments, environment)
}

func contains(set []string, value string) bool {
	for _, v := range set {
		if v == value {
			return true
		}
	}
	return false
}

// Wildcard is the scope token docs/21 section 4 prohibits for live financial operations.
const Wildcard = "*"

// scopeContains reports whether a grant's scope admits a value in one dimension.
//
// A wildcard entry admits everything in that dimension. That is what makes a wildcard a
// grant rather than a literal value, and it is deliberately a grant-side concept: the
// request states what it wants, and only the grant can widen to cover it.
func scopeContains(set []string, value string) bool {
	return contains(set, value) || contains(set, Wildcard)
}

// hasWildcard reports whether any dimension of the scope is a wildcard.
func (s Scope) hasWildcard() bool {
	return contains(s.Markets, Wildcard) || contains(s.Accounts, Wildcard) || contains(s.Environments, Wildcard)
}

// Grant is one role grant held by a subject.
//
// Grants are server-held. A caller cannot present a grant, widen one, or invent one, so
// every field here comes from the authorization service's own record rather than from the
// request. docs/21 section 5 requires grants to carry request, second-person approval,
// expiry, and review, which is why this is a record with an expiry rather than a bare role
// name in the request.
type Grant struct {
	// Role is what the grant confers.
	Role Role
	// Scope is what the grant is confined to.
	Scope Scope
	// GrantedAt is when the grant was made.
	GrantedAt time.Time
	// ExpiresAt is when the grant lapses. docs/21 section 5 caps privileged grants at 90
	// days unless re-approved.
	ExpiresAt time.Time
	// ApprovedBy names the second approver.
	ApprovedBy string
}

// MaxGrantAge is how long a privileged grant may stand before re-approval, from
// docs/21 section 5.
const MaxGrantAge = 90 * 24 * time.Hour

// Covers reports whether the grant admits a request in a scope, at a time.
//
// An expired grant covers nothing. That is checked here rather than at policy-load time so
// that expiry is evaluated against the request's own clock and not against whatever time
// the bundle happened to be built.
func (g Grant) Covers(market, account, environment string, now time.Time) bool {
	if !g.ExpiresAt.IsZero() && now.After(g.ExpiresAt) {
		return false
	}
	return g.Scope.Covers(market, account, environment)
}

// HasWildcard reports whether the grant is scoped by a wildcard in any dimension.
func (g Grant) HasWildcard() bool { return g.Scope.hasWildcard() }

// Request is one authorization question.
//
// It is the tuple docs/21 section 4 names, verbatim. Every field is present in every
// request, so a missing dimension is an explicit empty value rather than an absent one.
//
// Roles is the list of role names the subject holds. It is carried for rule matching
// against rule text, but it grants nothing: scope comes from Grants, and a role name in
// the request cannot widen a grant.
type Request struct {
	// SubjectID and SubjectType identify who is asking. Both are required: docs/06 treats
	// an unauthenticated request as refused, and a subject with no type cannot be checked
	// against the rule that service identities cannot impersonate humans.
	SubjectID   string
	SubjectType contracts.ActorType
	// Grants are the subject's role grants, as held server-side.
	Grants []Grant
	// Action is what is being attempted.
	Action Action
	// ResourceType and ResourceID name what is acted on.
	ResourceType string
	ResourceID   string
	// Environment, Market, and Account are the scope dimensions of this request.
	Environment string
	Market      string
	Account     string
	// Session is the server-held session state.
	Session Session
	// Context is the server-held authorization context.
	Context Context
	// Now is the current time, supplied rather than read.
	Now time.Time
}

// roles returns the role names held across all grants.
func (r Request) roles() []Role {
	var out []Role
	for _, g := range r.Grants {
		out = append(out, g.Role)
	}
	return out
}

// humanOnlyRoles are the roles that may only be exercised by a human subject.
//
// docs/21 section 4 states that service identities cannot impersonate humans, and
// section 7 gives each worker its own principal and capability list. A workload therefore
// has no route to an operator role: not because a policy is expected to omit it, but
// because a role that only a human may hold is a property of the role rather than of the
// bundle someone happens to be editing.
var humanOnlyRoles = map[Role]bool{
	RoleOwner: true, RoleTradingOperator: true, RoleRiskOperator: true,
	RoleResearcher: true, RolePlatformOperator: true, RoleAuditor: true,
}

// impersonates reports whether the subject is a non-human exercising a human-only role.
func (r Request) impersonates() (Role, bool) {
	if r.SubjectType == contracts.ActorHuman || r.SubjectType == contracts.ActorBreakGlass {
		return "", false
	}
	for _, g := range r.Grants {
		if humanOnlyRoles[g.Role] {
			return g.Role, true
		}
	}
	return "", false
}

// covers reports whether any grant admits this request's scope at this time.
func (r Request) covers(now time.Time) bool {
	for _, g := range r.Grants {
		if g.Covers(r.Market, r.Account, r.Environment, now) {
			return true
		}
	}
	return false
}

// wildcardFinancial reports whether a wildcard-scoped grant is being used for a live
// financial operation, which docs/21 section 4 prohibits outright.
func (r Request) wildcardFinancial() bool {
	if !r.Action.IsFinancial() {
		return false
	}
	for _, g := range r.Grants {
		if g.HasWildcard() {
			return true
		}
	}
	return false
}

// Validate checks the request is well formed before it is evaluated.
//
// A malformed request is refused rather than defaulted, because a request that cannot be
// evaluated must not be evaluated optimistically.
func (r Request) Validate() error {
	if strings.TrimSpace(r.SubjectID) == "" {
		return reject(contracts.CodeAuthentication, "subject_id is required; an unauthenticated request is refused")
	}
	if !r.SubjectType.Valid() {
		return reject(contracts.CodeAuthentication, "subject_type %q is not in the closed set", r.SubjectType)
	}
	if !r.Action.IsValid() {
		return reject(contracts.CodeValidation, "action %q is not in the closed set", r.Action)
	}
	if strings.TrimSpace(r.Environment) == "" {
		return reject(contracts.CodeValidation, "environment is required; a request cannot be placed without one")
	}
	if r.Now.IsZero() {
		return reject(contracts.CodeValidation, "now is required; the evaluator reads no clock")
	}
	return nil
}
