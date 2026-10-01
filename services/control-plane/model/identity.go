package model

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// WorkloadTTL bounds how long a workload identity is valid.
//
// docs/25 section 5 requires a "short-lived workload identity" and lists revocation as one of
// the evidence tests. The two requirements are the same requirement: an identity that lives
// for a week cannot be meaningfully revoked, because by the time an operator decides to
// revoke it, most of its life has already been spent.
//
// One hour is deliberately shorter than the operator session timeouts in authz. A workload
// holds no human judgement and needs no re-authentication, so there is nothing a longer life
// buys, while every extra hour is an hour during which a compromised identity still works.
const WorkloadTTL = time.Hour

// WorkloadScope is what a workload identity is permitted to do.
//
// It is a closed set rather than a free string, because a scope is an authority statement and
// an unrecognised scope must be refused rather than treated as something harmless. The
// default is nothing: a workload that has not been given a scope holds none.
type WorkloadScope string

// The closed set of workload scopes.
const (
	// ScopeServeInference lets the workload answer inference requests. It grants no ability
	// to change a lifecycle state, register a model, or invoke a tool.
	ScopeServeInference WorkloadScope = "SERVE_INFERENCE"
	// ScopeProduceArtifacts lets the workload produce datasets, models, and evaluations
	// that are then registered by the control plane. Producing is not deciding: nothing
	// this scope allows places a model in a lifecycle state.
	ScopeProduceArtifacts WorkloadScope = "PRODUCE_ARTIFACTS"
)

var allScopes = []WorkloadScope{ScopeServeInference, ScopeProduceArtifacts}

// Valid reports whether the scope is in the closed set.
func (s WorkloadScope) Valid() bool {
	for _, k := range allScopes {
		if k == s {
			return true
		}
	}
	return false
}

// AllScopes returns the closed set, ordered least to most privilege.
func AllScopes() []WorkloadScope {
	out := make([]WorkloadScope, len(allScopes))
	copy(out, allScopes)
	return out
}

// WorkloadIdentity is a short-lived identity bound to one model at one version.
//
// The binding to a specific model and version is the load-bearing part. An identity bound
// only to a model would let a compromised producer's identity keep working for a newer
// version of the same model that the compromise had nothing to do with, and a revocation
// aimed at the compromise would be over-broad. Binding to the version means a revocation
// closes exactly what was compromised.
type WorkloadIdentity struct {
	// Identity is the identity string presented by the workload.
	Identity string
	// ModelID is the model this identity may serve or produce.
	ModelID contracts.Identifier
	// ModelVersion is the exact model version. Both must match on presentation.
	ModelVersion string
	// Scope is the authority this identity carries.
	Scope WorkloadScope
	// IssuedAt is when the identity was minted.
	IssuedAt time.Time
	// ExpiresAt is when it stops being valid regardless of revocation.
	ExpiresAt time.Time
}

// Expired reports whether the identity is past its lifetime at the given time.
func (w WorkloadIdentity) Expired(now time.Time) bool {
	return !now.Before(w.ExpiresAt)
}

// Revocation is a recorded workload identity revocation.
//
// It is a record rather than a boolean so that the audit chain carries when a revocation
// happened and what it covered, which are the two things an investigation asks first. A
// revoked flag on an identity that is then deleted tells an investigator that a revocation
// occurred and nothing else.
type Revocation struct {
	Identity string
	// ModelID and ModelVersion record what the revocation covered, so a scope that turns
	// out to have been too broad or too narrow can be seen after the fact.
	ModelID      contracts.Identifier
	ModelVersion string
	// RevokedAt is when the identity stopped being accepted.
	RevokedAt time.Time
	// Reason is why. It is required: an unattributed revocation is not auditable, and
	// revocation is the kind of action that is later disputed.
	Reason string
	// EvidenceRef cites the forensic evidence preserved alongside it.
	EvidenceRef string
}

// WorkloadRegistry mints, evaluates, and revokes workload identities.
//
// It exists as a type rather than as a set of free functions because revocation has to be
// authoritative and shared. A revocation that lived in one component's memory would not
// reach the component that evaluates presentations, and the compromise response would then
// report a revocation that nothing enforces.
//
// The registry holds only identity metadata. It holds no credentials: a workload proves
// possession out of band, and what the registry answers is whether the identity it is
// presenting is one that is currently valid. That is the same server-side posture authz
// takes for operator sessions, for the same reason - a caller cannot assert that the
// identity it presents is a good one.
type WorkloadRegistry struct {
	// identities holds the currently valid identities by identity string.
	identities map[string]WorkloadIdentity
	// revocations records every revocation, including for identities already removed, so
	// that a presentation of a revoked identity can be answered with a reason rather than
	// an absence.
	revocations map[string]Revocation
	// now is the clock, injected so that expiry and revocation are testable without
	// sleeping and so that a test cannot accidentally pass because time moved.
	now func() time.Time

	// store is the durable destination for issuance and revocation. It is optional and nil
	// means in-memory only, for the same reason as the journal's: a read-only or
	// migration-time caller legitimately wants a registry with no durable record, while a
	// caller that believes it has one and does not is the thing to prevent. Durable reports
	// which it is.
	store IdentityStore

	// mu guards identities and revocations.
	//
	// Every method below reads or writes both maps, and several are read-modify-write
	// across the pair: Mint checks revocations and then writes identities, Revoke reads
	// identities and then writes revocations. Concurrent call from a request handler and a
	// compromise response would therefore be a data race on a Go map, which is not a
	// recoverable error but an undefined one, and it lands in the middle of the compromise
	// path where it is least welcome.
	//
	// The lock is held for the whole of each method rather than per map access, so that a
	// check-then-write sequence is atomic with respect to another caller. That is what
	// makes "a revoked identity cannot be re-minted" hold under concurrency rather than
	// only when the two calls happen not to interleave.
	mu sync.Mutex
}

// NewWorkloadRegistry builds a registry with an injected clock.
func NewWorkloadRegistry(now func() time.Time) (*WorkloadRegistry, error) {
	return NewWorkloadRegistryWithStore(now, nil)
}

// NewWorkloadRegistryWithStore builds a registry whose issuance and revocation are recorded
// durably in store.
//
// A nil store is permitted and means in-memory only. See Durable for why that is a question
// with an answer rather than a nil check at every call site.
func NewWorkloadRegistryWithStore(now func() time.Time, store IdentityStore) (*WorkloadRegistry, error) {
	if now == nil {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"a workload registry requires a clock; an injected clock is what makes expiry "+
				"and revocation testable without sleeping")
	}
	return &WorkloadRegistry{
		identities:  map[string]WorkloadIdentity{},
		revocations: map[string]Revocation{},
		now:         now,
		store:       store,
	}, nil
}

// Durable reports whether this registry writes through a store.
func (r *WorkloadRegistry) Durable() bool { return r.store != nil }

// Mint issues a short-lived workload identity for one model version.
//
// The identity is bound to the model version supplied and to nothing else. There is
// deliberately no "mint a second identity for the same model" convenience: a second
// identity is a second thing to revoke, and the compromise response has to be able to
// close every identity a compromised producer held, which is only tractable if the count is
// small and known.
func (r *WorkloadRegistry) Mint(
	identity string,
	modelID contracts.Identifier,
	modelVersion string,
	scope WorkloadScope,
) (WorkloadIdentity, error) {
	return r.MintContext(context.Background(), identity, modelID, modelVersion, scope)
}

// MintContext issues a short-lived workload identity, honouring ctx.
//
// Mint exists as the background-context form so the existing callers keep working. A durable
// write is a network call, so a caller that has a context and lets this one be invented
// cannot cancel it.
func (r *WorkloadRegistry) MintContext(
	ctx context.Context,
	identity string,
	modelID contracts.Identifier,
	modelVersion string,
	scope WorkloadScope,
) (WorkloadIdentity, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if strings.TrimSpace(identity) == "" {
		return WorkloadIdentity{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"workload identity is required; an anonymous workload cannot be revoked")
	}
	if _, previously := r.revocations[identity]; previously {
		return WorkloadIdentity{}, reject(contracts.CodeAuthorization, ErrCompromised,
			"identity %q has been revoked and cannot be re-minted; a compromised workload "+
				"must re-enter through a new identity, not a resurrected one", identity)
	}
	if modelID.IsZero() || modelID.Prefix() != contracts.PrefixModel {
		return WorkloadIdentity{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"workload identity must be bound to a model carrying the %q prefix",
			contracts.PrefixModel)
	}
	if strings.TrimSpace(modelVersion) == "" {
		return WorkloadIdentity{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"workload identity must be bound to an exact model version; binding to the model "+
				"alone would let a revocation aimed at one version close an unrelated one")
	}
	if !scope.Valid() {
		return WorkloadIdentity{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"scope %q is not in the closed set; unknown scopes are unsupported, not treated "+
				"as harmless", scope)
	}
	if _, exists := r.identities[identity]; exists {
		return WorkloadIdentity{}, reject(contracts.CodeConflict, ErrIncompleteRecord,
			"identity %q is already issued", identity)
	}

	now := r.now()
	issued := WorkloadIdentity{
		Identity:     identity,
		ModelID:      modelID,
		ModelVersion: modelVersion,
		Scope:        scope,
		IssuedAt:     now,
		// The expiry is computed from now and not from a caller-supplied duration, so a
		// caller cannot mint a long-lived identity by passing a large TTL.
		ExpiresAt: now.Add(WorkloadTTL),
	}

	// The durable write precedes the in-memory one. If it fails, the identity is not issued:
	// handing out a credential that nothing durable records would let a workload be
	// authenticated by this process and be invisible to every other one, which is the
	// precise failure a shared registry exists to prevent.
	if r.store != nil {
		if err := r.store.InsertIdentity(ctx, issued); err != nil {
			return WorkloadIdentity{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
				"the durable store refused to record the issuance of identity %q, so it was "+
					"not minted: %v", identity, err)
		}
	}

	r.identities[identity] = issued
	return issued, nil
}

// Presentation is a workload's claim about who it is.
type Presentation struct {
	Identity     string
	ModelID      contracts.Identifier
	ModelVersion string
}

// Authenticate evaluates a workload's presentation of its identity.
//
// The order of checks is the security-relevant part. Revocation is checked before expiry and
// before the model binding, because the reason a revoked identity is refused is that someone
// revoked it, and answering "your credential expired" instead would send an operator looking
// at the clock rather than at the incident. A registry that has forgotten an identity reports
// it as unknown, which is true, but the revocations map is kept precisely so that the more
// useful answer is available.
//
// The function fails closed in every branch. There is no path that returns an error and a
// usable identity, and no field of the returned identity is populated from the presentation
// rather than from the registry: a caller cannot widen its own scope by asking.
func (r *WorkloadRegistry) Authenticate(p Presentation, now time.Time) (WorkloadIdentity, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if rev, revoked := r.revocations[p.Identity]; revoked {
		return WorkloadIdentity{}, reject(contracts.CodeAuthentication, ErrCompromised,
			"identity %q was revoked at %s: %s", p.Identity,
			rev.RevokedAt.Format(time.RFC3339), rev.Reason)
	}
	held, ok := r.identities[p.Identity]
	if !ok {
		return WorkloadIdentity{}, reject(contracts.CodeAuthentication, contracts.ErrInvalidContractValue,
			"identity %q is not issued by this registry; a workload proves an identity it "+
				"was issued, not one it claims", p.Identity)
	}
	if held.Expired(now) {
		return WorkloadIdentity{}, reject(contracts.CodeAuthentication, contracts.ErrInvalidContractValue,
			"identity %q expired at %s; workload identities are short-lived by design and are "+
				"re-minted rather than extended", p.Identity, held.ExpiresAt.Format(time.RFC3339))
	}
	if p.ModelID != held.ModelID || p.ModelVersion != held.ModelVersion {
		return WorkloadIdentity{}, reject(contracts.CodeAuthorization, ErrSelfAuthorization,
			"identity %q is bound to %s@%s but presented for %s@%s; an identity is bound to "+
				"one exact model version and cannot be presented for another",
			p.Identity, held.ModelID, held.ModelVersion, p.ModelID, p.ModelVersion)
	}
	return held, nil
}

// Revoke invalidates an identity immediately and records why.
//
// It is the operation the compromise response needed and did not have. Contain previously
// took a boolean from its caller reporting that revocation had happened, which meant the
// response asserted a revocation rather than performing one: a caller that passed true
// without revoking anything would have produced a CompromiseResponse claiming a workload
// identity was revoked when no such record existed anywhere.
func (r *WorkloadRegistry) Revoke(
	identity string,
	reason string,
	evidenceRef string,
) (Revocation, error) {
	return r.RevokeContext(context.Background(), identity, reason, evidenceRef)
}

// RevokeContext invalidates an identity immediately and records why, honouring ctx.
//
// The ordering here is the most consequential in the package. The durable write happens
// first and the in-memory revocation only after it succeeds, because the caller of this
// function is the compromise response and its return value is reported to an investigator
// as work that was done. A registry that revoked in memory and failed to persist would
// return a successful Revocation naming an incident, and the durable record an
// investigation would later consult would not contain it.
//
// The two directions of failure are not symmetric and the code treats them as such. An
// in-memory revocation that outran its durable write leaves the registry believing a
// workload is dead while every other process still accepts it - containment reported and not
// achieved. The reverse - a durable revocation whose in-memory write failed - leaves the
// registry stricter than the store, which a later retry repairs, because Revoke is
// idempotent and returns the existing record.
func (r *WorkloadRegistry) RevokeContext(
	ctx context.Context,
	identity string,
	reason string,
	evidenceRef string,
) (Revocation, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if strings.TrimSpace(identity) == "" {
		return Revocation{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"revocation must name the identity to revoke")
	}
	if strings.TrimSpace(reason) == "" {
		return Revocation{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"a revocation requires a reason; an unattributed revocation is not auditable and "+
				"revocation is an action that gets disputed")
	}
	if strings.TrimSpace(evidenceRef) == "" {
		return Revocation{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"a revocation must cite the forensic evidence preserved alongside it")
	}
	if existing, already := r.revocations[identity]; already {
		return existing, nil
	}

	held, known := r.identities[identity]
	if !known {
		return Revocation{}, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"identity %q is not issued by this registry; revoking an identity that was never "+
				"issued would record a revocation for a workload that does not exist", identity)
	}

	now := r.now()
	rev := Revocation{
		Identity:     identity,
		ModelID:      held.ModelID,
		ModelVersion: held.ModelVersion,
		RevokedAt:    now,
		Reason:       reason,
		EvidenceRef:  evidenceRef,
	}
	// The durable write precedes the in-memory revocation. See the method comment for why
	// this direction and not the other.
	if r.store != nil {
		if err := r.store.InsertRevocation(ctx, rev); err != nil {
			return Revocation{}, reject(contracts.CodeInternal, ErrIncompleteRecord,
				"the durable store refused to record the revocation of %q, so it was not "+
					"revoked and the identity is still live: %v", identity, err)
		}
	}

	r.revocations[identity] = rev
	// Removing the identity from the live map is a cache invalidation, not a deletion of
	// record. The durable store keeps the row: it is what the revocation is evidence about,
	// and removing it would leave a revocation citing a subject that exists nowhere.
	delete(r.identities, identity)
	return rev, nil
}

// RevocationOf returns the recorded revocation for an identity, if any.
func (r *WorkloadRegistry) RevocationOf(identity string) (Revocation, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()

	rev, ok := r.revocations[identity]
	return rev, ok
}

// IsRevoked reports whether an identity has been revoked.
func (r *WorkloadRegistry) IsRevoked(identity string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	_, ok := r.revocations[identity]
	return ok
}

// ActiveIdentities returns the identities currently valid, sorted.
//
// It is a governance view: it answers "what can this control plane still hear from" without
// requiring a caller to know which models exist.
func (r *WorkloadRegistry) ActiveIdentities() []WorkloadIdentity {
	r.mu.Lock()
	defer r.mu.Unlock()

	out := make([]WorkloadIdentity, 0, len(r.identities))
	for _, w := range r.identities {
		out = append(out, w)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Identity < out[j].Identity })
	return out
}

// Revocations returns every recorded revocation, sorted by identity.
func (r *WorkloadRegistry) Revocations() []Revocation {
	r.mu.Lock()
	defer r.mu.Unlock()

	out := make([]Revocation, 0, len(r.revocations))
	for _, v := range r.revocations {
		out = append(out, v)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Identity < out[j].Identity })
	return out
}

// ContainedModelVersions returns the model versions covered by recorded revocations for a
// model.
//
// This is what makes a compromise response complete. Revoking a workload identity stops that
// workload, but the model versions it produced are still registered, and a reader asking
// "what did the compromised workload touch" needs the answer computed rather than
// reconstructed from a log.
// IdentityOf reports the identity currently held under a name, and whether one is held.
//
// It is what makes containment able to widen from a named workload to the population that
// shares its risk. A compromise names one workload identity, but the thing that is actually
// compromised is the model version that workload served: every other identity bound to that
// same version is serving output of the same compromised pipeline, and revoking only the
// named one leaves them live. Reading the binding from the registry rather than from the
// declaration matters, because a responder who states the version and states it wrong would
// silently widen or narrow the containment.
func (r *WorkloadRegistry) IdentityOf(identity string) (WorkloadIdentity, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	w, ok := r.identities[identity]
	return w, ok
}

// IdentitiesServingVersion reports every currently valid identity bound to one exact model
// version, sorted by identity.
//
// "Currently valid" means not revoked and not known to be expired, so the result is the
// population containment actually has to act on rather than every identity ever issued. The
// set is defined by the exact model version and nothing else: a workload serving a different
// version of the same model has different output and is not covered, and one serving a
// different model certainly is not. The version binding is what makes the widening precise
// instead of indiscriminate.
func (r *WorkloadRegistry) IdentitiesServingVersion(
	modelID contracts.Identifier,
	modelVersion string,
	now time.Time,
) []WorkloadIdentity {
	r.mu.Lock()
	defer r.mu.Unlock()

	var out []WorkloadIdentity
	for _, w := range r.identities {
		if w.ModelID != modelID || w.ModelVersion != modelVersion {
			continue
		}
		if _, revoked := r.revocations[w.Identity]; revoked {
			continue
		}
		if w.Expired(now) {
			continue
		}
		out = append(out, w)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Identity < out[j].Identity })
	return out
}

// ContainedIdentitiesForVersion reports every identity revoked for one exact model
// version, sorted, whether or not the revocation came from the response being run now.
//
// This is deliberately a different question from IdentitiesServingVersion, and the
// difference is the whole point. IdentitiesServingVersion answers "who is still serving
// this?", which is what a responder needs in order to act. ContainedIdentitiesForVersion
// answers "who is not serving this any more?", which is what an incident record has to
// state. Deriving the second from the first makes the record unstable under a retry: the
// siblings the first response revoked are excluded from the live set, so a second responder
// - or a replayed automation - would produce a record claiming containment reached one
// workload when it had in fact reached three. Reading it from the recorded revocations makes
// the record a function of what happened rather than of when it was written.
func (r *WorkloadRegistry) ContainedIdentitiesForVersion(
	modelID contracts.Identifier,
	modelVersion string,
) []string {
	r.mu.Lock()
	defer r.mu.Unlock()

	var out []string
	for _, v := range r.revocations {
		if v.ModelID == modelID && v.ModelVersion == modelVersion {
			out = append(out, v.Identity)
		}
	}
	sort.Strings(out)
	return out
}

func (r *WorkloadRegistry) ContainedModelVersions(modelID contracts.Identifier) []string {
	r.mu.Lock()
	defer r.mu.Unlock()

	seen := map[string]bool{}
	var out []string
	for _, v := range r.revocations {
		if v.ModelID != modelID {
			continue
		}
		if seen[v.ModelVersion] {
			continue
		}
		seen[v.ModelVersion] = true
		out = append(out, v.ModelVersion)
	}
	sort.Strings(out)
	return out
}

// String renders an identity for an audit record without exposing anything sensitive.
func (w WorkloadIdentity) String() string {
	return fmt.Sprintf("workload %s for %s@%s scope=%s expires=%s",
		w.Identity, w.ModelID, w.ModelVersion, w.Scope, w.ExpiresAt.Format(time.RFC3339))
}
