//go:build integration

package integration

import (
	"context"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/model"
)

// TestWorkloadIdentitySurvivesAProcessRestart is the identity half of G5.7.
//
// The model registry proves the durable layer holds models. This proves it holds the thing
// that makes models safe to expose: the identities permitted to serve them, and the revocations
// that stop them. A control plane that restarted with an empty workload registry would mint
// fresh identities freely; one that restarted with the issuances but without the revocations
// would re-issue names it had already shut down. Both are security failures, and neither is
// visible in any test that does not discard the process.
func TestWorkloadIdentitySurvivesAProcessRestart(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	owner := uniqueOwner()
	partition := owner
	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)

	first := buildStack(t, ctx, db, partition, at)

	live := mintIdentity(t, ctx, first.Registry, "wld-live-issued", at)
	minted := mintIdentity(t, ctx, first.Registry, "wld-shut-down", at)

	// Containment: revoke one of them through the registry's real write path, so the
	// revocation row is written by the same code a responder's call would use.
	if _, err := first.Registry.RevokeContext(
		ctx, minted.Identity, "containment: workload observed exfiltrating outside its scope",
		"forensics/2026-03-04/wld-shut-down"); err != nil {
		t.Fatalf("revoking %s: %v", minted.Identity, err)
	}

	// The registry must already refuse the revoked identity in this process, so a later
	// assertion about the restarted one is testing restart behaviour and not the revoke path.
	if _, err := first.Registry.Authenticate(model.Presentation{
		Identity:     minted.Identity,
		ModelID:      minted.ModelID,
		ModelVersion: minted.ModelVersion,
	}, at); err == nil {
		t.Fatal("a revoked identity authenticated before the restart; the containment in " +
			"this process is already broken, so a restart assertion would prove nothing")
	}

	// The reason and evidence must survive too. A revocation that comes back without its
	// reason is a bare flag, and revocation is the action that gets disputed. The expected
	// values are captured before the restart so the comparison is against what was written,
	// not against whatever happens to be in the second stack.
	issuedRev, found := first.Registry.RevocationOf(minted.Identity)
	if !found {
		t.Fatal("the issuing registry reports no revocation for the identity it just revoked")
	}

	// --- Second process, rebuilt from PostgreSQL alone ---
	second := buildStack(t, ctx, db, partition, at.Add(time.Hour))

	// The still-valid identity is back and still works.
	restored, found := second.Registry.IdentityOf(live.Identity)
	if !found {
		t.Fatalf("identity %s was issued and never revoked but did not survive the restart; "+
			"every workload would have to be re-issued, and re-issue is what a containment "+
			"race looks like from the outside", live.Identity)
	}
	if restored.ModelVersion != live.ModelVersion {
		t.Errorf("restored identity is bound to version %q, expected %q",
			restored.ModelVersion, live.ModelVersion)
	}
	if restored.Scope != live.Scope {
		t.Errorf("restored identity carries scope %q, expected %q", restored.Scope, live.Scope)
	}
	if _, err := second.Registry.Authenticate(model.Presentation{
		Identity:     live.Identity,
		ModelID:      live.ModelID,
		ModelVersion: live.ModelVersion,
	}, at); err != nil {
		t.Errorf("the identity that survived the restart no longer authenticates: %v", err)
	}

	// The revoked identity is the important half. It must come back *as revoked*, and it
	// must not come back as live.
	if !second.Registry.IsRevoked(minted.Identity) {
		t.Fatal("a revocation recorded before the restart is unknown to the restarted " +
			"registry; the compromised workload could mint again under the same name, " +
			"which is precisely the failure the durable revocation table exists to prevent")
	}
	if _, found := second.Registry.IdentityOf(minted.Identity); found {
		t.Error("the revoked identity is present in the restored registry's live set; the " +
			"issuance row is supposed to be kept for responders while the identity itself " +
			"is removed from what the registry would answer yes to")
	}
	if _, err := second.Registry.Authenticate(model.Presentation{
		Identity:     minted.Identity,
		ModelID:      minted.ModelID,
		ModelVersion: minted.ModelVersion,
	}, at); err == nil {
		t.Error("the restarted registry authenticated a revoked identity")
	}

	// The reason and evidence must survive too. A revocation that comes back without its
	// reason is a bare flag, and revocation is the action that gets disputed.
	rev, found := second.Registry.RevocationOf(minted.Identity)
	if !found {
		t.Fatal("the registry reports the identity revoked but holds no revocation record")
	}
	if rev.Reason != issuedRev.Reason {
		t.Errorf("restored revocation reason is %q, expected %q", rev.Reason, issuedRev.Reason)
	}
	if rev.EvidenceRef != issuedRev.EvidenceRef {
		t.Errorf("restored revocation evidence reference is %q, expected %q",
			rev.EvidenceRef, issuedRev.EvidenceRef)
	}
	if rev.EvidenceRef == "" {
		t.Error("the restored revocation lost its evidence reference; an unattributed " +
			"revocation is not auditable")
	}

	// The issuer, not the database, decided the scope. Both layers bound the identity
	// lifetime independently, and a mismatch between them is an identity valid in one layer
	// and expired in the other.
	if expired := restored.Expired(at); expired {
		t.Errorf("the restored identity is reported expired at %s but was issued at %s "+
			"and expires at %s", at, restored.IssuedAt, restored.ExpiresAt)
	}
}

// TestRevocationSurvivesAsARecordBesideItsIssuance pins the asymmetry the restore rule depends
// on: the store keeps the issuance row beside the revocation, while the registry drops the
// identity from its live set.
//
// This is checked against the database rather than the registry because the registry's half is
// covered above, and it is this half that would silently stop being true if someone ever
// "tidied up" the revocation path.
func TestRevocationSurvivesAsARecordBesideItsIssuance(t *testing.T) {
	db := open(t)
	ctx := ctxFor(t)
	truncate(t, ctx, db)

	at := time.Date(2026, 3, 4, 5, 6, 7, 0, time.UTC)
	stack := buildStack(t, ctx, db, uniqueOwner(), at)

	minted := mintIdentity(t, ctx, stack.Registry, "wld-contained-record", at)
	if _, err := stack.Registry.RevokeContext(
		ctx, minted.Identity, "containment: credential observed in an unrelated workload",
		"forensics/2026-03-04/wld-contained-record"); err != nil {
		t.Fatalf("revoking: %v", err)
	}

	var issuanceRows, revocationRows int
	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.workload_identities WHERE identity = $1;`,
		minted.Identity).Scan(&issuanceRows); err != nil {
		t.Fatalf("counting issuance rows: %v", err)
	}
	if issuanceRows != 1 {
		t.Errorf("the durable store holds %d issuance rows for the revoked identity %s, "+
			"expected 1; a responder needs to see what was issued against a shut-down identity",
			issuanceRows, minted.Identity)
	}

	if err := db.QueryRowContext(ctx,
		`SELECT count(*) FROM public.workload_revocations WHERE identity = $1;`,
		minted.Identity).Scan(&revocationRows); err != nil {
		t.Fatalf("counting revocation rows: %v", err)
	}
	if revocationRows != 1 {
		t.Errorf("the durable store holds %d revocation rows for %s, expected 1",
			revocationRows, minted.Identity)
	}

	// The store's contents, read back through the snapshot reader, must be enough to rebuild
	// a registry that refuses the identity. This is the rehydration path in reverse: it proves
	// the reader is not silently dropping the revocation half.
	reader, err := model.NewSQLIdentitySnapshotReader(db)
	if err != nil {
		t.Fatalf("building the identity snapshot reader: %v", err)
	}
	snapshot, err := reader.LoadIdentitySnapshot(ctx)
	if err != nil {
		t.Fatalf("loading the identity snapshot: %v", err)
	}
	if len(snapshot.Revocations) != 1 {
		t.Fatalf("the snapshot reader returned %d revocations, expected 1; the restart "+
			"path would restore a registry with no revocation map", len(snapshot.Revocations))
	}
	if snapshot.Revocations[0].Reason != "containment: credential observed in an unrelated workload" {
		t.Errorf("the snapshot's revocation reason is %q; the reason did not survive",
			snapshot.Revocations[0].Reason)
	}
}

// mintIdentity issues one workload identity through the registry's durable write path.
//
// The model id comes from the same unique generator the registry tests use, because
// workload_identities enforces the mdl_ prefix and the identity is bound to the model rather
// than to a name.
func mintIdentity(
	t *testing.T,
	ctx context.Context,
	registry *model.WorkloadRegistry,
	identity string,
	at time.Time,
) model.WorkloadIdentity {
	t.Helper()

	if !registry.Durable() {
		t.Fatal("the registry has no durable store; a mint would vanish with the process, " +
			"which is the condition this whole file exists to test")
	}

	modelID, err := contracts.ParseIdentifier(uniqueModelID())
	if err != nil {
		t.Fatalf("parsing a unique model identifier: %v", err)
	}

	minted, err := registry.MintContext(
		ctx, identity, modelID, "1.0.0", model.ScopeServeInference)
	if err != nil {
		t.Fatalf("minting %s: %v", identity, err)
	}
	if minted.Identity != identity {
		t.Fatalf("mint returned identity %q, expected %q", minted.Identity, identity)
	}
	// The migration bounds the lifetime to 24 hours and the Go registry to WorkloadTTL, which
	// the migration's own drift test pins at one hour. Minting through the real path and then
	// writing through the real SQL store is what proves the two bounds agree in practice
	// rather than only in a unit test with hand-written values.
	if ttl := minted.ExpiresAt.Sub(minted.IssuedAt); ttl <= 0 || ttl > model.WorkloadTTL {
		t.Fatalf("minted lifetime is %s, expected a positive value no greater than the "+
			"registry's own WorkloadTTL of %s", ttl, model.WorkloadTTL)
	}
	return minted
}
