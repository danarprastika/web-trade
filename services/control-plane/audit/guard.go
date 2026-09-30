package audit

import (
	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// OperationClass is what an attempted action does, for the purpose of deciding whether
// it may proceed while audit evidence is not safely stored.
//
// The classes are ordered by how much damage proceeding would do if the evidence is
// later found to have been lost, which is the only question this classification answers.
type OperationClass string

const (
	// OpReadOnly reads state and changes nothing.
	OpReadOnly OperationClass = "READ_ONLY"
	// OpRiskReducing reduces exposure: cancelling, closing, flattening, reducing size.
	// It stays permitted during a halt, because the emergency control must not also
	// trap the operator into a position they need to exit.
	OpRiskReducing OperationClass = "RISK_REDUCING"
	// OpRiskIncreasing adds exposure.
	OpRiskIncreasing OperationClass = "RISK_INCREASING"
	// OpPrivilegedMutation changes authorisation, risk policy, retention, or keys.
	OpPrivilegedMutation OperationClass = "PRIVILEGED_MUTATION"
)

// Guard blocks activity when audit evidence cannot be safely stored.
//
// It is the fail-closed half of AC4. docs/22 section 4 requires audit evidence to be
// copied to independent immutable storage, and AC4 requires that when that copy is not
// happening the system blocks sensitive operations rather than accumulating an unbounded
// amount of evidence that might be lost. A guard with an unbounded buffer does not solve
// that; it only defers the loss to a worse moment.
//
// The guard is latched. Once a halt is set it stays set until something with the
// authority to clear it does so explicitly, so a transient recovery in the sink cannot
// silently reopen the system and a later drop of evidence goes unnoticed.
type Guard struct {
	// limit is the number of unexported records the guard tolerates.
	limit int
	// pending is the number of records accepted but not yet exported.
	pending int
	// halted is latched once set.
	halted bool
	// haltReason explains the halt for the operator and for the audit record.
	haltReason string
	// haltCause names what set the halt: evidence backlog or a SEV-1 integrity failure.
	haltCause string
}

// NewGuard returns a guard tolerating limit unexported records.
func NewGuard(limit int) (*Guard, error) {
	if limit < 1 {
		return nil, reject(contracts.CodeValidation, "guard limit must be >= 1, got %d", limit)
	}
	return &Guard{limit: limit}, nil
}

// Pending returns the number of records accepted but not yet exported.
func (g *Guard) Pending() int { return g.pending }

// Limit returns the configured backlog limit.
func (g *Guard) Limit() int { return g.limit }

// Halted reports whether the guard is latched.
func (g *Guard) Halted() bool { return g.halted }

// Reason returns why the guard is halted.
func (g *Guard) Reason() (string, string) { return g.haltCause, g.haltReason }

// Accept records that n more audit records are pending export.
//
// It never discards. An audit record that has been accepted is owed a place in the
// durable store, and the only thing this function can do when the backlog is full is
// refuse the caller, which sends the caller to halt. There is deliberately no drop,
// no overwrite-oldest, and no truncate: each would be a way for evidence to disappear
// without a decision by anyone, which is exactly what audit exists to make impossible.
func (g *Guard) Accept(n int) error {
	if n < 0 {
		return reject(contracts.CodeValidation, "cannot accept a negative number of records")
	}
	if g.pending+n > g.limit {
		g.Halt("EVIDENCE_BACKLOG",
			"audit export backlog reached the limit of "+itoa64(int64(g.limit))+" unexported records")
		return reject(contracts.CodeDependencyUnavailable,
			"audit evidence is not being exported and the backlog is at its limit of %d records; "+
				"this operation is blocked until the sink recovers", g.limit)
	}
	g.pending += n
	return nil
}

// Exported records that n records reached durable independent storage.
func (g *Guard) Exported(n int) error {
	if n < 0 || n > g.pending {
		return reject(contracts.CodeValidation, "cannot mark %d records exported with %d pending", n, g.pending)
	}
	g.pending -= n
	return nil
}

// Halt latches the guard. Once latched it stays latched until Cleared.
func (g *Guard) Halt(cause, reason string) {
	if g.halted {
		return
	}
	g.halted = true
	g.haltCause = cause
	g.haltReason = reason
}

// Clear releases the latch.
//
// It is deliberately a separate, explicitly-called operation rather than something that
// happens as a side effect of the sink recovering, so that clearing is always a decision
// someone made and can itself be recorded.
func (g *Guard) Clear() {
	g.halted = false
	g.haltCause = ""
	g.haltReason = ""
}

// Allow reports whether an operation of the given class may proceed.
//
// While halted, read-only and risk-reducing operations are still permitted. Everything
// that increases risk or changes the system's authority is refused. That split is the
// same one the OMS halt uses, and for the same reason: a control that also stops the
// operator from reducing risk is not a safety control.
func (g *Guard) Allow(class OperationClass) error {
	if !g.halted {
		return nil
	}
	switch class {
	case OpReadOnly, OpRiskReducing:
		return nil
	}
	return reject(contracts.CodeDependencyUnavailable,
		"audit is halted (%s: %s); %s operations are blocked", g.haltCause, g.haltReason, class)
}

// ObserveVerification latches the guard from a verification outcome.
//
// docs/22 section 3 makes a chain break, missing sequence, signature failure, or
// unexpected checkpoint a SEV-1 security event requiring privileged mutations and
// risk-increasing activity to stop. Routing that through the same guard as the
// evidence backlog means there is one fail-closed path rather than two that can
// disagree about whether the platform may trade.
func (g *Guard) ObserveVerification(v Verification) {
	if v.OK {
		return
	}
	kinds := make([]string, 0, len(v.Findings))
	for _, f := range v.Findings {
		kinds = append(kinds, string(f.Kind))
	}
	g.Halt("SEV-1_AUDIT_INTEGRITY",
		"audit integrity verification failed: "+joinKinds(kinds))
}

func joinKinds(kinds []string) string {
	out := ""
	for i, k := range kinds {
		if i > 0 {
			out += ", "
		}
		out += k
	}
	if out == "" {
		out = "unspecified integrity failure"
	}
	return out
}
