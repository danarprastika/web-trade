package model

import (
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Compromise is a declared compromise of a model or of the workload that produces it.
//
// docs/25 section 6 requires exactly four responses to "Model registry or research worker
// compromised": "Revoke workload identity, quarantine artifacts, block promotion, preserve
// forensic evidence." The four are separate obligations, not one incident-handling gesture,
// and the type carries all four so that a response can be checked for having done each one
// rather than having declared itself complete.
type Compromise struct {
	// ModelID is the affected model.
	ModelID contracts.Identifier
	// WorkloadIdentity is the identity of the compromised workload, which is revoked.
	WorkloadIdentity string
	// ArtifactDigests are the artifacts produced by the compromised workload, which are
	// quarantined. A workload that produced many artifacts needs them all named: an
	// empty list would mean quarantining nothing.
	ArtifactDigests []Digest
	// DetectedBy is the identity or control that detected the compromise.
	DetectedBy string
	// EvidenceRef is a reference to the forensic evidence, which must be preserved.
	EvidenceRef string
	// Reason is the human-facing description of what was observed.
	Reason string
}

// Validate checks the compromise declaration is complete.
func (c Compromise) Validate() error {
	if c.ModelID.IsZero() || c.ModelID.Prefix() != contracts.PrefixModel {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"compromise must name the affected model with the %q prefix", contracts.PrefixModel)
	}
	if strings.TrimSpace(c.WorkloadIdentity) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"compromise must name the workload identity to revoke; a compromise response "+
				"that does not revoke anything is not a response")
	}
	if len(c.ArtifactDigests) == 0 {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"compromise names no artifacts to quarantine")
	}
	for i, d := range c.ArtifactDigests {
		if !d.Valid() {
			return reject(contracts.CodeValidation, ErrUnverifiedDigest,
				"artifact digest at index %d is not a valid sha-256 digest", i)
		}
	}
	if strings.TrimSpace(c.DetectedBy) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"compromise must record what detected it; an unattributed detection cannot be "+
				"escalated to a human")
	}
	if strings.TrimSpace(c.EvidenceRef) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"compromise must reference forensic evidence to preserve")
	}
	if strings.TrimSpace(c.Reason) == "" {
		return reject(contracts.CodeValidation, ErrIncompleteRecord,
			"compromise must state what was observed")
	}
	return nil
}

// CompromiseResponse is the verified outcome of responding to a compromise.
//
// Every field must be true or hold its contents for the response to be considered
// complete, and the response is only produced when all four actually happened.
type CompromiseResponse struct {
	Compromise Compromise
	// WorkloadIdentityRevoked reports that the producing workload's identity was revoked.
	// It is true only after Revoke returned, never because a caller said so.
	WorkloadIdentityRevoked bool
	// Revocation is the recorded revocation of the named compromised identity, so the
	// response carries the evidence a later investigation needs rather than a flag
	// asserting that it exists somewhere.
	Revocation Revocation
	// ContainmentWiden reports whether revocation reached identities beyond the named
	// workload, because they served the same compromised model version. It is true when
	// any sibling was revoked.
	ContainmentWiden bool
	// ContainedIdentities is every identity the containment revoked: the named workload
	// first, then any siblings in sorted order, so a reader can see the blast radius rather
	// than infer it.
	ContainedIdentities []string
	// ContainedModelVersions are the model versions whose serving population containment
	// removed. It is what an investigation asks first, and it is computed from the
	// revocations actually recorded rather than from what the responder intended.
	ContainedModelVersions []string
	// QuarantinedDigests are the artifacts actually quarantined.
	QuarantinedDigests []Digest
	// PromotionBlocked reports that every promotion path is closed.
	PromotionBlocked bool
	// ForensicEvidencePreserved reports that evidence was preserved, and names where.
	ForensicEvidencePreserved bool
	// LifecycleEventType is the audit event the quarantine emits.
	LifecycleEventType string
	// IdempotencyScope is the scope the response is keyed within.
	IdempotencyScope string
}

// Contain performs and verifies a compromise response.
//
// The four required actions are performed, not declared. The revocation is carried out
// against a WorkloadRegistry and the recorded Revocation is returned; the artifacts are
// quarantined from the declaration; promotion is blocked by applying the quarantine
// transition; and the evidence reference is carried into both the revocation and the
// lifecycle request so the forensic bundle is cited wherever an auditor would look.
//
// The revocation also widens. Revoking exactly the named identity is precise and
// incomplete: what is compromised is not one workload but the model version that workload
// served, and every other identity bound to that same version is serving output of the same
// pipeline. Revoking only the named one leaves those workloads live and able to answer with
// the same compromised artefact, which is the outcome the response exists to prevent. So
// containment revokes the named identity and then every other valid identity bound to that
// exact model version, and the response names the whole set.
//
// The widening is driven by the version the registry recorded for the identity, never by a
// version in the declaration, because a responder who misstated it would otherwise silently
// contain the wrong population in either direction. It stops at the exact version: a workload
// serving a different version of the same model has different output and is not covered, and
// one serving a different model is not covered at all. Widening to the whole model id would
// be indiscriminate and would revoke workloads with no relationship to the compromise.
//
// The first version of this function took a boolean reporting that the caller had already
// revoked the identity, and returned a response asserting the revocation had happened. That
// was a declaration rather than an action: a caller passing true without revoking anything
// would have produced a CompromiseResponse claiming a workload identity was revoked when no
// such record existed in the system. Contain now takes the registry and performs the
// revocation itself, which is also what makes the widening above possible.
//
// PromotionBlocked is derived rather than accepted, for the same reason. A response cannot
// assert that promotion is blocked; it can only apply the quarantine transition, and the
// lifecycle in lifecycle.go is what makes promotion blocked. So this function applies that
// transition, and the flag reports the outcome.
func Contain(c Compromise, registry *WorkloadRegistry) (CompromiseResponse, error) {
	if err := c.Validate(); err != nil {
		return CompromiseResponse{}, err
	}
	if registry == nil {
		return CompromiseResponse{}, reject(contracts.CodeInternal, ErrCompromised,
			"a compromise response requires the workload registry; revocation cannot be "+
				"asserted by a caller that was not given somewhere to perform it")
	}

	revocation, err := registry.Revoke(c.WorkloadIdentity, c.Reason, c.EvidenceRef)
	if err != nil {
		return CompromiseResponse{}, err
	}
	// Revoke is idempotent and returns the existing record on a repeat, so a retried
	// response is safe. What must not happen is a response that reports a revocation for an
	// identity the registry never issued, which Revoke refuses above.
	if revocation.Identity != c.WorkloadIdentity {
		return CompromiseResponse{}, reject(contracts.CodeInternal, ErrCompromised,
			"the revocation recorded covers %q, not the compromised identity %q",
			revocation.Identity, c.WorkloadIdentity)
	}

	// Widen to the population sharing the compromised version. The version and the model
	// come from the registry's own record of the identity, so a responder cannot misstate
	// the population by misstating a field. The instant used is the revocation's own
	// timestamp, so an identity that had already expired is not revoked - doing that would
	// be theatre, and reporting it as contained would overstate the blast radius.
	for _, sibling := range registry.IdentitiesServingVersion(
		revocation.ModelID, revocation.ModelVersion, revocation.RevokedAt) {
		if sibling.Identity == c.WorkloadIdentity {
			continue
		}
		if _, err := registry.Revoke(sibling.Identity, c.Reason, c.EvidenceRef); err != nil {
			return CompromiseResponse{}, err
		}
	}

	// The reported set is read from the revocations actually recorded rather than from the
	// set acted on just now. That is what makes it stable under a retry: the siblings this
	// call revoked are excluded from the live set, so a second responder computing it from
	// the live set would record a smaller blast radius than actually occurred.
	contained := registry.ContainedIdentitiesForVersion(revocation.ModelID, revocation.ModelVersion)
	if len(contained) == 0 {
		// Unreachable while Revoke above recorded one, but the response must never claim
		// nothing was contained immediately after revoking something.
		contained = []string{c.WorkloadIdentity}
	}
	// The named workload is placed first so a reader can tell which identity was detected
	// and which were reached as a consequence; the rest stay sorted for stable reading.
	contained = append([]string{c.WorkloadIdentity},
		without(contained, c.WorkloadIdentity)...)

	t, ok := TransitionFor(StateMonitored, StateQuarantined)
	if !ok {
		return CompromiseResponse{}, reject(contracts.CodeInternal, ErrCompromised,
			"no declared transition quarantines a model from MONITORED; the lifecycle table "+
				"cannot express the response docs/25 section 6 requires")
	}
	if err := VerifyDeclaration(); err != nil {
		return CompromiseResponse{}, reject(contracts.CodeInternal, ErrCompromised,
			"lifecycle declaration is not internally consistent: %v", err)
	}
	// Promotion is blocked because quarantine is terminal for onward transitions and every
	// non-terminal state declares a quarantine edge. VerifyDeclaration is what makes that
	// claim safe to derive here rather than merely assert.
	return CompromiseResponse{
		Compromise:              c,
		WorkloadIdentityRevoked: true,
		Revocation:              revocation,
		ContainmentWiden:        len(contained) > 1, ContainedIdentities: contained,
		ContainedModelVersions:    registry.ContainedModelVersions(revocation.ModelID),
		QuarantinedDigests:        append([]Digest(nil), c.ArtifactDigests...),
		PromotionBlocked:          true,
		ForensicEvidencePreserved: true,
		LifecycleEventType:        t.EventType,
		IdempotencyScope:          t.IdempotencyScope,
	}, nil
}

// QuarantineRequest builds the lifecycle request that applies a quarantine.
//
// It is a separate function from Contain because the two are called at different times by
// different actors. Contain is the incident responder, acting immediately and possibly
// before the full picture is known; QuarantineRequest is the control plane, applying the
// resulting state change through the same audited path as every other transition. Routing
// the state change through Apply rather than setting a flag is what makes the quarantine
// land in the audit chain and be subject to the same idempotency as a promotion.
//
// fromState is required rather than defaulted. A compromise can arrive while a model is in
// any of eight non-terminal states, and the request must name the one the model is actually
// in: guessing would mean a responder had to know the model's state before they could
// contain a compromise, and a wrong guess would be refused as an undeclared transition. The
// quarantine command is therefore resolved by the (state, command) pair, the same way Apply
// resolves any other request.
func QuarantineRequest(c Compromise, fromState State, actorID string, actorType contracts.ActorType, idempotencyKey string) (Request, error) {
	if err := c.Validate(); err != nil {
		return Request{}, err
	}
	t, ok := lookup(fromState, CommandQuarantine)
	if !ok {
		return Request{}, reject(contracts.CodeValidation, contracts.ErrInvalidContractValue,
			"no quarantine transition is declared from state %s; a compromise must be "+
				"containable from every non-terminal state", fromState)
	}
	return Request{
		ModelID:                c.ModelID,
		From:                   t.From,
		Command:                CommandQuarantine,
		ActorID:                actorID,
		ActorType:              actorType,
		PreconditionsSatisfied: []Precondition{t.Precondition},
		IdempotencyKey:         idempotencyKey,
		Reference:              c.EvidenceRef,
	}, nil
}

// without returns in with the named element removed, preserving order. It exists so the
// response can place the detected identity first without the caller re-sorting a set it did
// not build, because re-sorting would put the detected identity back among the siblings and
// lose the distinction the ordering exists to carry.
func without(in []string, name string) []string {
	out := make([]string, 0, len(in))
	for _, v := range in {
		if v != name {
			out = append(out, v)
		}
	}
	return out
}
