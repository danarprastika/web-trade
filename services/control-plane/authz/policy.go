package authz

import (
	"sort"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Role is a role from the docs/21 section 5 baseline.
type Role string

const (
	RoleOwner            Role = "OWNER"
	RoleTradingOperator  Role = "TRADING_OPERATOR"
	RoleRiskOperator     Role = "RISK_OPERATOR"
	RoleResearcher       Role = "RESEARCHER"
	RolePlatformOperator Role = "PLATFORM_OPERATOR"
	RoleAuditor          Role = "AUDITOR"
	RoleService          Role = "SERVICE"
)

var roles = map[Role]bool{
	RoleOwner: true, RoleTradingOperator: true, RoleRiskOperator: true,
	RoleResearcher: true, RolePlatformOperator: true, RoleAuditor: true, RoleService: true,
}

// IsValid reports whether the role is in the closed set.
func (r Role) IsValid() bool { return roles[r] }

// roleExclusions are the "explicitly excluded" column of docs/21 section 5, expressed as
// the actions each role may never perform.
//
// The exclusions are modelled as data rather than left to policy authors to remember,
// because every one of them is a control that has been written down once and then
// forgotten at least once: an OWNER does not bypass risk, a RISK_OPERATOR does not submit
// orders, a RESEARCHER does not self-approve, and an AUDITOR does not mutate.
var roleExclusions = map[Role]map[Action]bool{
	RoleOwner: {
		// "Bypass of risk, eligibility, dual-control, or gate checks" has no action to
		// enumerate, because a bypass is the absence of a check rather than an action. The
		// structural answer is that this package has no bypass mechanism: the Risk Engine
		// and the gates are separate authorities, and an allow here cannot satisfy them.
		ActionDeleteEvidence: true, // deletion still needs the retention policy
	},
	RoleTradingOperator: {
		ActionChangeRiskLimit: true,
		ActionGrantRole:       true,
		ActionLiveActivation:  true,
		ActionDeleteEvidence:  true,
		ActionHaltTrading:     true, // may request pause/cancel, not halt
		ActionClearHalt:       true,
		ActionBreakGlass:      true,
	},
	RoleRiskOperator: {
		ActionSubmitOrder:     true, // "Submit orders" is explicitly excluded
		ActionChangeRiskLimit: true, // "approve own policy change" is excluded
		ActionGrantRole:       true,
		ActionLiveActivation:  true,
		ActionDeleteEvidence:  true,
		ActionBreakGlass:      true,
	},
	RoleResearcher: {
		ActionSubmitOrder:     true,
		ActionExportAudit:     true,
		ActionChangeRiskLimit: true,
		ActionHaltTrading:     true,
		ActionClearHalt:       true,
		ActionGrantRole:       true,
		ActionLiveActivation:  true,
		ActionDeleteEvidence:  true,
		ActionBreakGlass:      true,
		ActionPauseStrategy:   true,
	},
	RolePlatformOperator: {
		ActionSubmitOrder:     true,
		ActionChangeRiskLimit: true,
		ActionLiveActivation:  true,
		ActionDeleteEvidence:  true,
		ActionBreakGlass:      true,
	},
	RoleAuditor: {
		// "Mutations, secret access, trading actions".
		ActionSubmitOrder:     true,
		ActionCancelOrder:     true,
		ActionPauseStrategy:   true,
		ActionExportAudit:     true,
		ActionChangeRiskLimit: true,
		ActionHaltTrading:     true,
		ActionClearHalt:       true,
		ActionGrantRole:       true,
		ActionLiveActivation:  true,
		ActionBreakGlass:      true,
		ActionDeleteEvidence:  true,
	},
	RoleService: {
		// "Human login, cross-environment access, arbitrary tool invocation".
		ActionGrantRole:       true,
		ActionBreakGlass:      true,
		ActionDeleteEvidence:  true,
		ActionExportAudit:     true,
		ActionLiveActivation:  true,
		ActionChangeRiskLimit: true,
	},
}

// excludedBy returns the roles that forbid an action outright.
func excludedBy(action Action) map[Role]bool {
	out := map[Role]bool{}
	for role, excluded := range roleExclusions {
		if excluded[action] {
			out[role] = true
		}
	}
	return out
}

// AllRoleExclusions returns a copy of the exclusion matrix.
//
// It exists so the SQL contract test can compare the matrix against the seeded rows in
// db/migrations/0003_authz.sql. The copy matters: the test is in package authz_test and
// must not be able to reach the live map, so a test bug cannot change a production
// constant to make an assertion pass.
func AllRoleExclusions() map[Role]map[Action]bool {
	out := make(map[Role]map[Action]bool, len(roleExclusions))
	for role, excluded := range roleExclusions {
		inner := make(map[Action]bool, len(excluded))
		for action := range excluded {
			inner[action] = true
		}
		out[role] = inner
	}
	return out
}

// AllActions returns every action in the closed set.
func AllActions() []string {
	out := make([]string, 0, len(actions))
	for a := range actions {
		out = append(out, string(a))
	}
	sort.Strings(out)
	return out
}

// Effect is what a rule does when it matches.
type Effect string

const (
	// EffectAllow permits, but only if no other matching rule denies.
	EffectAllow Effect = "ALLOW"
	// EffectDeny refuses, and outranks any allow.
	EffectDeny Effect = "DENY"
)

// IsValid reports whether the effect is in the closed set.
func (e Effect) IsValid() bool { return e == EffectAllow || e == EffectDeny }

// Rule is one entry in a policy bundle.
//
// A rule matches when every populated field matches. An empty field matches anything, so
// a rule can be as narrow as one action for one role in one environment or as broad as the
// policy author writes it, and the narrowness is the author's responsibility except where
// the wildcard and financial-action checks below override it.
type Rule struct {
	// Effect is what the rule does.
	Effect Effect
	// Roles this rule applies to. Empty means any role.
	Roles []Role
	// Actions this rule applies to. Empty means any action.
	Actions []Action
	// Environments this rule applies to. Empty means any environment.
	Environments []string
	// ActorTypes this rule applies to. Empty means any actor type.
	ActorTypes []contracts.ActorType
	// MinAuthStrength is the least authentication strength this rule requires.
	MinAuthStrength AuthStrength
	// Reason is recorded in the decision when the rule matches.
	Reason string
}

// Validate checks the rule is well formed.
func (r Rule) Validate() error {
	if !r.Effect.IsValid() {
		return reject(contracts.CodeValidation, "effect %q is not in the closed set", r.Effect)
	}
	for _, role := range r.Roles {
		if !role.IsValid() {
			return reject(contracts.CodeValidation, "rule names role %q, which is not in the closed set", role)
		}
	}
	for _, action := range r.Actions {
		if !action.IsValid() {
			return reject(contracts.CodeValidation, "rule names action %q, which is not in the closed set", action)
		}
	}
	for _, a := range r.ActorTypes {
		if !a.Valid() {
			return reject(contracts.CodeValidation, "rule names actor type %q, which is not in the closed set", a)
		}
	}
	return nil
}

// matches reports whether the rule applies to the request.
//
// The subject's held roles are passed separately rather than read from the request, so a
// rule can only match on a role that came from an actual grant. A request naming a role it
// does not hold therefore matches nothing, which is what stops a caller from writing a
// role name into its own request and inheriting that role's permissions.
func (r Rule) matches(req Request, held []Role) bool {
	if len(r.Roles) > 0 && !anyRole(r.Roles, held) {
		return false
	}
	if len(r.Actions) > 0 && !containsAction(r.Actions, req.Action) {
		return false
	}
	if len(r.Environments) > 0 && !contains(r.Environments, req.Environment) {
		return false
	}
	if len(r.ActorTypes) > 0 && !containsActor(r.ActorTypes, req.SubjectType) {
		return false
	}
	if req.Session.AuthStrength < r.MinAuthStrength {
		return false
	}
	return true
}

func anyRole(want []Role, have []Role) bool {
	for _, w := range want {
		for _, h := range have {
			if w == h {
				return true
			}
		}
	}
	return false
}

func containsAction(set []Action, want Action) bool {
	for _, v := range set {
		if v == want {
			return true
		}
	}
	return false
}

func containsActor(set []contracts.ActorType, want contracts.ActorType) bool {
	for _, v := range set {
		if v == want {
			return true
		}
	}
	return false
}

// Policy is a signed, versioned bundle of rules.
type Policy struct {
	// Digest identifies the bundle. docs/21 section 10 requires every decision to record
	// it, so that a refusal can be traced to the exact policy that refused.
	Digest string
	// Rules are evaluated in order, but order does not decide the outcome: any matching
	// deny wins over any matching allow regardless of position.
	Rules []Rule
}

// Validate checks every rule in the bundle.
func (p Policy) Validate() error {
	if strings.TrimSpace(p.Digest) == "" {
		return reject(contracts.CodeValidation, "policy bundle digest is required; every decision must record it")
	}
	for i, r := range p.Rules {
		if err := r.Validate(); err != nil {
			return reject(contracts.CodeValidation, "policy rule %d is invalid: %v", i, err)
		}
	}
	return nil
}
