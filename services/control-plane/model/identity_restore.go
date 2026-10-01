package model

import (
	"context"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Restore rebuilds the registry from a durable identity snapshot.
//
// This is the last of the three write-only ports, and the one where the cost of leaving it
// write-only was a security control rather than an inconvenience. The registry refuses to
// re-mint a revoked identity by looking it up in its revocation map; after a restart that map
// was empty, so the refusal found nothing and a compromised workload could present an identity
// whose revocation had been recorded months earlier. The compromise path was enforced in
// memory and lost on restart, which is the worst place for it to be lost: the process that
// restarts is the one that will be asked whether the containment held.
//
// It is all-or-nothing, like every other apply in this package. A registry loaded with some
// identities and no revocations is a registry that will re-issue half of them, so a partial
// restore is more dangerous than no restore.
//
// It also applies the rule the durable record does not: the registry removes a revoked
// identity from its live set, while the store keeps the issuance row beside the revocation
// because a responder needs to see what was issued against. So an identity that appears in
// both halves is the normal durable state, not a contradiction, and it is restored as
// revoked rather than as live. Getting this backwards would either restore a revoked
// identity as live - reintroducing the exact failure this file prevents - or refuse every
// snapshot that came from a real revocation, which is every snapshot worth having.
func (r *WorkloadRegistry) Restore(snapshot IdentitySnapshot) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	identities := make(map[string]WorkloadIdentity, len(snapshot.Identities))
	revocations := make(map[string]Revocation, len(snapshot.Revocations))

	for _, w := range snapshot.Identities {
		if strings.TrimSpace(w.Identity) == "" {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"the snapshot contains a workload identity with no identity string; an "+
					"anonymous workload cannot be presented, evaluated or revoked")
		}
		if _, seen := identities[w.Identity]; seen {
			return reject(contracts.CodeConflict, ErrIncompleteRecord,
				"the snapshot issues identity %q twice; one workload may hold one identity, "+
					"and a second issuance of the same string would make the first unrevocable",
				w.Identity)
		}
		if modelID := w.ModelID; modelID.IsZero() || modelID.Prefix() != contracts.PrefixModel {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"identity %q is bound to a model that carries no %q prefix; it could never "+
					"have been presented, so it does not belong in a restored registry",
				w.Identity, contracts.PrefixModel)
		}
		if !w.Scope.Valid() {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"identity %q carries scope %q, which is not in the closed set", w.Identity, w.Scope)
		}
		identities[w.Identity] = w
	}

	for _, rev := range snapshot.Revocations {
		if strings.TrimSpace(rev.Identity) == "" {
			return reject(contracts.CodeValidation, ErrIncompleteRecord,
				"the snapshot contains a revocation with no identity; an unattributed "+
					"revocation cannot be enforced against anything")
		}
		if _, seen := revocations[rev.Identity]; seen {
			return reject(contracts.CodeConflict, ErrIncompleteRecord,
				"the snapshot revokes identity %q twice; the second revocation would silently "+
					"replace the reason and the evidence reference of the first", rev.Identity)
		}
		revocations[rev.Identity] = rev
	}

	// The removal rule, applied here because the durable record does not apply it: the store
	// keeps the issuance row so a responder can see what the compromised identity held, and
	// the registry holds only what it would still answer "yes" to.
	for identity := range revocations {
		delete(identities, identity)
	}

	r.identities = identities
	r.revocations = revocations
	return nil
}

// RehydratedWorkloadRegistry builds a registry restored from durable identity storage.
//
// It is separate from NewWorkloadRegistryWithStore because the store is the write
// destination and the reader is the recovery source, and a caller that has one does not
// necessarily have the other - a read-only replica, or a migration process, can restore a
// registry it must not write to.
func RehydratedWorkloadRegistry(
	now func() time.Time,
	store IdentityStore,
	reader IdentitySnapshotReader,
) (*WorkloadRegistry, error) {
	registry, err := NewWorkloadRegistryWithStore(now, store)
	if err != nil {
		return nil, err
	}
	if reader == nil {
		return nil, reject(contracts.CodeValidation, ErrIncompleteRecord,
			"rehydrating a workload registry needs an identity snapshot reader; without one "+
				"the registry would be empty, and an empty registry reports no revoked "+
				"identity as revoked")
	}
	snapshot, err := reader.LoadIdentitySnapshot(context.Background())
	if err != nil {
		return nil, err
	}
	if err := registry.Restore(snapshot); err != nil {
		return nil, err
	}
	return registry, nil
}
