package config

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// DriftSeverity ranks a drift finding. The ordering is load-bearing because a halt is
// monotonic in severity (docs/25 line 41): a lower-severity finding may never clear a
// higher-severity one.
type DriftSeverity int

// The drift severities, least to most severe.
const (
	// DriftNone means the runtime state matches the signed snapshot.
	DriftNone DriftSeverity = iota
	// DriftAdvisory means something changed that is recorded but does not itself change a
	// financial control, such as an audit-only field.
	DriftAdvisory
	// DriftLimit means a limit, allow-list, or authority differs from the signed snapshot.
	// This is a risk control divergence and halts risk-increasing actions.
	DriftLimit
	// DriftStructural means the runtime cannot be reconciled with the snapshot at all,
	// such as a policy digest that matches no signed revision.
	DriftStructural
)

// String renders the severity for audit records and alerts.
func (s DriftSeverity) String() string {
	switch s {
	case DriftNone:
		return "NONE"
	case DriftAdvisory:
		return "ADVISORY"
	case DriftLimit:
		return "LIMIT"
	case DriftStructural:
		return "STRUCTURAL"
	default:
		return "UNKNOWN"
	}
}

// HaltsRiskIncreasing reports whether the severity stops risk-increasing actions.
func (s DriftSeverity) HaltsRiskIncreasing() bool { return s >= DriftLimit }

// Drift is one detected divergence between the signed snapshot and observed runtime state.
type Drift struct {
	// Path is the dotted location that diverged, such as "policy.limits.max_order_notional".
	Path string
	// Severity is the ranked impact.
	Severity DriftSeverity
	// Detail states what was observed.
	Detail string
	// ObservedAt is when the comparison was made.
	ObservedAt time.Time
}

// DriftReport is the outcome of a drift check.
//
// It is a report and not a repair. A runtime that could correct drift automatically would be
// a runtime that can decide a signed control is wrong, and docs/25 line 41 forbids recovery
// automation from silently clearing a control state. So the report is returned to an
// operator-facing path and nothing here mutates the snapshot.
type DriftReport struct {
	// Revision is the snapshot that was compared against.
	Revision string
	// Severity is the highest severity found, which is what the caller acts on.
	Severity DriftSeverity
	// Findings is every divergence, sorted by path so two runs over the same inputs
	// produce the same report.
	Findings []Drift
	// CheckedAt is when the check ran.
	CheckedAt time.Time
}

// ObservedState is what the runtime believes its effective configuration to be.
//
// It is supplied by the runtime rather than derived from the snapshot, because drift is by
// definition a disagreement, and computing both sides from the same object could only ever
// agree.
type ObservedState struct {
	// PolicyDigest is a digest of the policy the runtime actually enforced. The runtime is
	// expected to build it from the same canonical body shape, so a mismatch means the
	// enforced policy is not the signed one.
	PolicyDigest string
	// FeatureFlags is the flag state the runtime actually applied.
	FeatureFlags map[string]bool
	// HaltAuthority and ReEnableAuthority are the authorities actually in force, which
	// drift can change without changing any numeric limit.
	HaltAuthority     contracts.ActorType
	ReEnableAuthority contracts.ActorType
}

// DigestPolicy returns the canonical digest of a body, for a runtime to record what it
// enforced.
func DigestPolicy(b Body) (string, error) {
	canonical, err := CanonicalBytes(b)
	if err != nil {
		return "", err
	}
	return ComputeDigest(canonical), nil
}

// DetectDrift compares observed runtime state against a signed snapshot.
//
// The comparison is over the parts that constitute a financial control: the policy digest,
// the feature-flag state, and the halt and re-enable authorities. A divergence in any of
// them is reported at DriftLimit or above and halts risk-increasing actions, because each
// of them changes what the platform is permitted to do rather than merely what it recorded.
func DetectDrift(snap Snapshot, observed ObservedState, now time.Time) DriftReport {
	report := DriftReport{
		Revision:  snap.Body.Revision,
		Severity:  DriftNone,
		CheckedAt: now,
	}

	add := func(path string, sev DriftSeverity, detail string) {
		report.Findings = append(report.Findings, Drift{
			Path: path, Severity: sev, Detail: detail, ObservedAt: now,
		})
		if sev > report.Severity {
			report.Severity = sev
		}
	}

	// An empty observed digest means the runtime never resolved a policy. That is not a
	// mismatch between two policies, it is the absence of one, and it is the most severe
	// case: there is no evidence of what was enforced.
	switch {
	case observed.PolicyDigest == "":
		add("policy.digest", DriftStructural,
			"runtime reported no policy digest; nothing records which policy was enforced")
	case observed.PolicyDigest != snap.Digest:
		add("policy.digest", DriftStructural,
			fmt.Sprintf("runtime enforced policy %s but the signed snapshot is %s",
				observed.PolicyDigest, snap.Digest))
	}

	// Authorities are compared directly rather than through the digest, because an
	// authority divergence is the case where a hash collision is not the concern: the
	// concern is that a person gained halt or re-enable authority, and that has to be
	// legible in the alert.
	if observed.HaltAuthority != snap.Body.Policy.HaltAuthority {
		add("policy.halt_authority", DriftLimit,
			fmt.Sprintf("runtime halt authority is %s, snapshot declares %s",
				observed.HaltAuthority, snap.Body.Policy.HaltAuthority))
	}
	if observed.ReEnableAuthority != snap.Body.Policy.ReEnableAuthority {
		add("policy.re_enable_authority", DriftLimit,
			fmt.Sprintf("runtime re-enable authority is %s, snapshot declares %s",
				observed.ReEnableAuthority, snap.Body.Policy.ReEnableAuthority))
	}

	// Flags are compared as a set so a flag that is on in the runtime but absent from the
	// snapshot is reported by name. An extra enabled flag is a limit-severity finding
	// because an unrecognised flag that is on is unaccounted authority.
	flagPaths := make(map[string]struct{}, len(snap.Body.Flags))
	for name := range snap.Body.Flags {
		flagPaths[name] = struct{}{}
	}
	for name := range observed.FeatureFlags {
		flagPaths[name] = struct{}{}
	}
	names := make([]string, 0, len(flagPaths))
	for name := range flagPaths {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		want, inSnapshot := snap.Body.Flags[name]
		got, inRuntime := observed.FeatureFlags[name]
		switch {
		case inSnapshot && inRuntime && want == got:
			continue
		case inSnapshot && inRuntime:
			add("flags."+name, DriftLimit,
				fmt.Sprintf("snapshot declares %v, runtime applied %v", want, got))
		case inSnapshot:
			add("flags."+name, DriftLimit,
				fmt.Sprintf("snapshot declares %v, runtime has no value for it", want))
		default:
			// A flag the snapshot never declared is undocumented configuration that is
			// nevertheless active, which is the same hazard as an unknown field entering
			// the document, one level up.
			add("flags."+name, DriftStructural,
				fmt.Sprintf("runtime applied undocumented flag %v, which the signed snapshot does not declare", got))
		}
	}

	return report
}

// Alert is the operator-facing notification a drift report raises.
//
// It is a separate type from DriftReport because the report is a fact about state and the
// alert is a claim about what must be done, and conflating them would let a caller
// acknowledge the alert as though the drift were resolved.
type Alert struct {
	// ID identifies this alert occurrence.
	ID string
	// Revision is the snapshot involved.
	Revision string
	// Severity is the ranked severity.
	Severity DriftSeverity
	// Summary is a single line for a notification body.
	Summary string
	// Findings is the evidence, which the alert must carry because a halt with no
	// explanation is not actionable.
	Findings []Drift
	// RaisedAt is when the alert was raised.
	RaisedAt time.Time
	// RequiresOperator is always true for a limit or structural finding. It is a field
	// rather than an inference so a caller cannot accidentally treat a halting alert as
	// self-clearing.
	RequiresOperator bool
}

// AlertFrom builds the alert a report raises. A clean report raises nothing.
func AlertFrom(r DriftReport) (Alert, bool) {
	if r.Severity == DriftNone {
		return Alert{}, false
	}
	// The alert id is derived from the revision, severity, and finding paths, so the same
	// drift produces the same id. That makes a repeated detection idempotent for a
	// notification system, which matters because the alternative is a new alert on every
	// poll for a condition that has not changed.
	h := sha256.New()
	fmt.Fprintf(h, "%s|%s", r.Revision, r.Severity)
	for _, f := range r.Findings {
		fmt.Fprintf(h, "|%s:%s", f.Path, f.Severity)
	}
	id := hex.EncodeToString(h.Sum(nil))[:16]

	return Alert{
		ID:               id,
		Revision:         r.Revision,
		Severity:         r.Severity,
		Summary:          fmt.Sprintf("configuration drift %s detected for revision %s across %d finding(s)", r.Severity, r.Revision, len(r.Findings)),
		Findings:         r.Findings,
		RaisedAt:         r.CheckedAt,
		RequiresOperator: r.Severity.HaltsRiskIncreasing(),
	}, true
}
