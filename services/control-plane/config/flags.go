package config

import (
	"fmt"
	"sort"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Flag is a documented feature flag.
//
// The set is closed and declared in code rather than read from the document, which is the
// point of the whole file. docs/25 line 97: "unknown flags never grant authority". If the
// documented set lived in the configuration, then a document could introduce a flag by
// naming it, and "unknown flags never grant authority" would be unenforced. Declaring the
// names here means the only flags that exist are the ones this build was reviewed to
// contain, and a document naming anything else resolves to a refusal.
type Flag string

// The documented flags.
//
// Each carries a comment stating what turning it on authorises, because the review that
// admits a new flag is a review of that sentence.
const (
	// FlagSimulatedExecution routes orders to the simulator. It grants no market access.
	FlagSimulatedExecution Flag = "simulated_execution"
	// FlagPaperExecution routes orders to the venue paper environment. It grants no market
	// access and does not authorise a live submission.
	FlagPaperExecution Flag = "paper_execution"
	// FlagShadowExecution observes decisions without submitting them.
	FlagShadowExecution Flag = "shadow_execution"
	// FlagRiskMetricsExport enables exporting risk metrics. It carries no trading authority.
	FlagRiskMetricsExport Flag = "risk_metrics_export"
	// FlagDecisionLedgerExport enables exporting the decision ledger. It carries no
	// trading authority.
	FlagDecisionLedgerExport Flag = "decision_ledger_export"
	// FlagDriftAlerts enables the drift alert path.
	FlagDriftAlerts Flag = "drift_alerts"
	// FlagAuditChainVerification enables audit chain verification.
	FlagAuditChainVerification Flag = "audit_chain_verification"
)

// documentedFlags is the closed set of flag names.
var documentedFlags = map[Flag]struct{}{
	FlagSimulatedExecution:     {},
	FlagPaperExecution:         {},
	FlagShadowExecution:        {},
	FlagRiskMetricsExport:      {},
	FlagDecisionLedgerExport:   {},
	FlagDriftAlerts:            {},
	FlagAuditChainVerification: {},
}

// AllFlags returns every documented flag name in sorted order.
func AllFlags() []string {
	out := make([]string, 0, len(documentedFlags))
	for f := range documentedFlags {
		out = append(out, string(f))
	}
	sort.Strings(out)
	return out
}

// Documented reports whether a flag name is in the closed set.
func Documented(name string) bool {
	_, ok := documentedFlags[Flag(name)]
	return ok
}

// Flags is the resolved feature-flag state of a snapshot.
type Flags struct {
	// enabled is the set of flags that are on. A flag that is not present is off, which is
	// the fail-safe direction and also the reason a document need not enumerate them all.
	enabled map[Flag]struct{}
}

// ResolveFlags computes the effective flag state for a snapshot.
//
// Every name in the document is checked against the documented set. An unknown name is
// refused rather than ignored: ignoring it would make the refusal invisible, and a
// configuration carrying an unrecognised flag has a defect that a reviewer should see. The
// refusal is fail-closed, so a caller that ignores the error still has no flags enabled.
func ResolveFlags(declared map[string]bool) (Flags, error) {
	resolved := Flags{enabled: map[Flag]struct{}{}}
	names := make([]string, 0, len(declared))
	for name := range declared {
		names = append(names, name)
	}
	sort.Strings(names)

	var unknown []string
	for _, name := range names {
		if !Documented(name) {
			unknown = append(unknown, name)
			continue
		}
		if declared[name] {
			resolved.enabled[Flag(name)] = struct{}{}
		}
	}
	if len(unknown) > 0 {
		return Flags{}, reject(contracts.CodeValidation,
			"configuration declares %d undocumented feature flag(s): %v; documented flags are %v. "+
				"An unknown flag never grants authority, so it is refused rather than ignored",
			len(unknown), unknown, AllFlags())
	}
	return resolved, nil
}

// Enabled reports whether a documented flag is on. An undocumented name is always false,
// which is what "unknown flags never grant authority" means at the call site.
func (f Flags) Enabled(name string) bool {
	if !Documented(name) {
		return false
	}
	_, ok := f.enabled[Flag(name)]
	return ok
}

// RequireRiskIncreasingPath reports whether the resolved flags permit a risk-increasing
// order to reach a venue submission path at all.
//
// The three execution flags are mutually exclusive, and each corresponds to a distinct
// environment. Two of them on at once is a contradiction rather than a configuration, and
// serving it would mean the platform does not know which execution path it is on, which is
// exactly the ambiguity the reconciliation model exists to eliminate.
func (f Flags) RequireRiskIncreasingPath(environment Environment) error {
	// Live is handled first and unconditionally. A live snapshot is authorised by its
	// approval and its controls, not by a flag, so there is no flag that a document could
	// set to grant live execution and none is required. Returning here rather than after
	// the checks below is what keeps that true: a later check that demands an active flag
	// would otherwise make live unreachable, and the temptation to satisfy it by
	// introducing a live flag is exactly the failure this design exists to prevent.
	if environment == EnvLive {
		return nil
	}

	var active []Flag
	for _, flag := range []Flag{FlagSimulatedExecution, FlagPaperExecution, FlagShadowExecution} {
		if f.Enabled(string(flag)) {
			active = append(active, flag)
		}
	}
	if len(active) > 1 {
		return reject(contracts.CodeConflict,
			"execution flags %v are mutually exclusive; the platform cannot be on more than "+
				"one execution path at a time", active)
	}
	if len(active) == 0 {
		return reject(contracts.CodeRiskRejected,
			"no execution flag is enabled, so no order can reach a submission path; "+
				"a missing flag is off, not a default to the live path")
	}

	// The enabled execution path must match the environment the snapshot was promoted into.
	// A paper environment with only the simulator on is a misconfiguration that would let an
	// operator believe a paper capability exists when it does not.
	required := executionFlagFor(environment)
	if required == "" {
		return reject(contracts.CodeValidation,
			"environment %s has no mapped execution flag", environment)
	}
	for _, flag := range active {
		if flag != required {
			return reject(contracts.CodeRiskRejected,
				"environment %s requires execution flag %q but %q is enabled", environment, required, flag)
		}
	}
	return nil
}

// executionFlagFor returns the execution flag an environment must have enabled.
//
// Live is absent deliberately: live is authorised by approval and controls rather than by a
// flag, so there is no flag that a document could set to grant live execution.
func executionFlagFor(environment Environment) Flag {
	switch environment {
	case EnvDev, EnvTest:
		return FlagSimulatedExecution
	case EnvStaging, EnvPaper:
		return FlagPaperExecution
	case EnvShadow:
		return FlagShadowExecution
	default:
		return ""
	}
}

// EnabledFlags returns the names of the flags that are on, sorted.
func (f Flags) EnabledFlags() []string {
	out := make([]string, 0, len(f.enabled))
	for flag := range f.enabled {
		out = append(out, string(flag))
	}
	sort.Strings(out)
	return out
}

// SubjectState is whether a named subject may take risk-increasing action.
//
// docs/17 section 2: "A new account, strategy, instrument, venue, or environment starts
// disabled for risk-increasing actions." The zero value of SubjectState is therefore the
// restrictive one, and the only way to enable it is an explicit signed grant.
type SubjectState struct {
	// SubjectID is the account, strategy, instrument, or venue the state applies to.
	SubjectID contracts.Identifier
	// RiskIncreasingEnabled is true only when a signed grant set it.
	RiskIncreasingEnabled bool
	// GrantedByRevision is the configuration revision that granted the capability, so the
	// grant can be revoked by superseding that revision rather than by a separate mechanism
	// that could disagree with it.
	GrantedByRevision string
}

// PermitsRiskIncreasing reports whether the subject may take risk-increasing action.
//
// The subject identifier is checked against a configured subject list as well, because a
// grant recorded against a subject that the policy does not cover is a grant the reviewer
// never saw.
func (s SubjectState) PermitsRiskIncreasing(covered map[string]struct{}) (bool, string) {
	if !s.RiskIncreasingEnabled {
		return false, fmt.Sprintf("subject %s is not enabled for risk-increasing actions", s.SubjectID)
	}
	if _, ok := covered[s.SubjectID.String()]; !ok {
		return false, fmt.Sprintf(
			"subject %s holds a grant but is not covered by the signed policy's permitted set; "+
				"a grant outside the policy is a grant no reviewer approved", s.SubjectID)
	}
	return true, ""
}

// FallbackResult reports what a service may do when the configuration distribution channel
// or flag service is unavailable.
type FallbackResult struct {
	// Snapshot is the last verified safe snapshot, set only when it is inside its
	// configured freshness window.
	Snapshot *Snapshot
	// Halted reports that no configuration may be served and risk-increasing actions must
	// stop.
	Halted bool
	// Reason explains the outcome for the audit record.
	Reason string
}

// LastVerifiedSafe returns the last verified snapshot if and only if it is still inside its
// configured freshness window.
//
// docs/25 line 97: "Use last verified safe snapshot only within configured freshness;
// unknown flags never grant authority." The window is the last-known-good window rather
// than the full max_age, because the fallback is a degraded path: serving a snapshot that
// is merely technically current, while the live path is known to be broken, is how a
// degraded system becomes an unmonitored one. Beyond the window the answer is a halt.
//
// A halt is the safe direction under docs/17 section 2: unavailable configuration state
// means reject.
func LastVerifiedSafe(last *Snapshot, now time.Time) FallbackResult {
	if last == nil {
		return FallbackResult{
			Halted: true,
			Reason: "no last verified safe snapshot is held; a cold start has no configuration to serve",
		}
	}
	if last.Digest == "" {
		return FallbackResult{
			Halted: true,
			Reason: fmt.Sprintf(
				"last known-good snapshot for revision %s has no verified digest; it was never "+
					"verified, so it cannot be treated as the last verified safe snapshot", last.Body.Revision),
		}
	}
	age := now.Sub(last.ActivatedAt)
	if age < 0 {
		return FallbackResult{
			Halted: true,
			Reason: fmt.Sprintf(
				"last known-good snapshot for revision %s is activated in the future relative to %s",
				last.Body.Revision, now.UTC().Format(time.RFC3339)),
		}
	}
	window := last.Body.Freshness.MaxLastKnownGoodAge
	if age > window {
		return FallbackResult{
			Halted: true,
			Reason: fmt.Sprintf(
				"last known-good snapshot for revision %s is %s old, beyond its %s last-known-good "+
					"window; falling back to it now would serve unverified-fresh configuration",
				last.Body.Revision, age.Truncate(time.Second), window),
		}
	}
	return FallbackResult{
		Snapshot: last,
		Reason: fmt.Sprintf(
			"last known-good snapshot for revision %s is %s old, within its %s window",
			last.Body.Revision, age.Truncate(time.Second), window),
	}
}
