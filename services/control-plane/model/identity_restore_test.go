package model

import (
	"context"
	"errors"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

func identityClock() func() time.Time {
	at := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	return func() time.Time { return at }
}

// issuedRegistry mints one identity and returns a registry holding it, plus its store.
func issuedRegistry(t *testing.T) (*WorkloadRegistry, *MemoryIdentityStore) {
	t.Helper()
	store := NewMemoryIdentityStore()
	r, err := NewWorkloadRegistryWithStore(identityClock(), store)
	if err != nil {
		t.Fatalf("NewWorkloadRegistryWithStore: %v", err)
	}
	if _, err := r.MintContext(context.Background(), "wl-alpha", modelIDN(t, 0), "1.0.0",
		ScopeServeInference); err != nil {
		t.Fatalf("MintContext: %v", err)
	}
	return r, store
}

// The property this whole file exists for: a revoked identity must still be revoked after the
// process that revoked it has gone away.
//
// Without the identity snapshot this assertion fails, because the refusal to re-mint is a
// lookup in the registry's revocation map and that map starts empty. The failure is silent -
// Mint succeeds and returns a fresh credential for a workload whose compromise is on record -
// which is why it needs a test rather than a review.
func TestARevokedIdentityCannotBeReMintedAfterARestart(t *testing.T) {
	live, store := issuedRegistry(t)
	if _, err := live.RevokeContext(context.Background(), "wl-alpha",
		"credential observed in an unrelated tenant", "case-42"); err != nil {
		t.Fatalf("RevokeContext: %v", err)
	}

	restored, err := RehydratedWorkloadRegistry(identityClock(), store, store)
	if err != nil {
		t.Fatalf("RehydratedWorkloadRegistry: %v", err)
	}

	if !restored.IsRevoked("wl-alpha") {
		t.Fatal("the revocation did not survive the restart; the registry would re-issue a " +
			"credential for a workload whose compromise is on record")
	}
	_, err = restored.MintContext(context.Background(), "wl-alpha", modelIDN(t, 0), "1.0.0",
		ScopeServeInference)
	if err == nil {
		t.Fatal("a revoked identity was re-minted after a restart. This is the failure the " +
			"revocation check exists to prevent, arriving through the maintenance path")
	}
	if !errors.Is(err, ErrCompromised) {
		t.Fatalf("the refusal should be a compromise refusal so callers distinguish it from a "+
			"validation error, got %v", err)
	}
	// And the reason must come back with it, because a compromise response that cannot say
	// why is one that has to go and find out.
	rev, ok := restored.RevocationOf("wl-alpha")
	if !ok {
		t.Fatal("the restored registry cannot say why the identity was revoked")
	}
	if rev.Reason != "credential observed in an unrelated tenant" {
		t.Fatalf("restored revocation reason is %q, want the recorded one", rev.Reason)
	}
}

func TestALiveIdentitySurvivesARestart(t *testing.T) {
	live, store := issuedRegistry(t)
	restored, err := RehydratedWorkloadRegistry(identityClock(), store, store)
	if err != nil {
		t.Fatalf("RehydratedWorkloadRegistry: %v", err)
	}
	got, ok := restored.IdentityOf("wl-alpha")
	if !ok {
		t.Fatal("a live identity did not survive the restart")
	}
	want, _ := live.IdentityOf("wl-alpha")
	if got.ModelVersion != want.ModelVersion || got.Scope != want.Scope {
		t.Fatalf("restored identity is %+v, want %+v", got, want)
	}
	if len(restored.IdentitiesServingVersion(modelIDN(t, 0), "1.0.0", identityClock()())) == 0 {
		t.Fatal("the restored registry does not consider the identity to be serving its version")
	}
}

func TestARevokedIdentityIsNotRestoredLive(t *testing.T) {
	// The durable store keeps the issuance row beside the revocation, because a responder
	// needs to see what the compromised identity held. So an identity in both halves is the
	// normal durable state, and the restore has to apply the rule the store does not: the
	// registry holds only what it would still answer "yes" to.
	w, err := workloadFrom(dbgen.WorkloadIdentity{
		Identity: "wl-alpha", ModelID: modelIDN(t, 0).String(), ModelVersion: "1.0.0",
		Scope: string(ScopeServeInference),
	})
	if err != nil {
		t.Fatalf("workloadFrom: %v", err)
	}
	rev, err := revocationFrom(dbgen.WorkloadRevocation{
		Identity: "wl-alpha", ModelID: modelIDN(t, 0).String(), ModelVersion: "1.0.0",
		RevokedAtUtc: time.Date(2026, 9, 30, 12, 30, 0, 0, time.UTC),
		Reason:       "compromise", EvidenceRef: "case-1",
	})
	if err != nil {
		t.Fatalf("revocationFrom: %v", err)
	}

	r, err := NewWorkloadRegistry(identityClock())
	if err != nil {
		t.Fatalf("NewWorkloadRegistry: %v", err)
	}
	if err := r.Restore(IdentitySnapshot{
		Identities:  []WorkloadIdentity{w},
		Revocations: []Revocation{rev},
	}); err != nil {
		t.Fatalf("an identity that was issued and then revoked must restore, not fail: %v", err)
	}
	if _, live := r.IdentityOf("wl-alpha"); live {
		t.Fatal("a revoked identity came back live; the restore did not apply the removal rule")
	}
	if !r.IsRevoked("wl-alpha") {
		t.Fatal("the revocation was not restored")
	}
	if _, err := r.MintContext(context.Background(), "wl-alpha", modelIDN(t, 0), "1.0.0",
		ScopeServeInference); err == nil {
		t.Fatal("the restored registry will re-mint an identity it records as revoked")
	}
}

func TestRestoreRefusesADuplicateIssuance(t *testing.T) {
	w, _ := workloadFrom(dbgen.WorkloadIdentity{
		Identity: "wl-alpha", ModelID: modelIDN(t, 1).String(), ModelVersion: "1.0.0",
		Scope: string(ScopeServeInference),
	})
	r, _ := NewWorkloadRegistry(identityClock())
	if err := r.Restore(IdentitySnapshot{
		Identities: []WorkloadIdentity{w, w},
	}); err == nil {
		t.Fatal("issuing one identity string twice must be refused; the second issuance would " +
			"make the first unrevocable")
	}
}

func TestRestoreRefusesADuplicateRevocation(t *testing.T) {
	rev, _ := revocationFrom(dbgen.WorkloadRevocation{
		Identity: "wl-alpha", ModelID: modelIDN(t, 1).String(), ModelVersion: "1.0.0",
		RevokedAtUtc: time.Date(2026, 9, 30, 12, 30, 0, 0, time.UTC), Reason: "first",
	})
	second := rev
	second.Reason = "second"

	r, _ := NewWorkloadRegistry(identityClock())
	if err := r.Restore(IdentitySnapshot{Revocations: []Revocation{rev, second}}); err == nil {
		t.Fatal("two revocations of one identity must be refused; the second would silently " +
			"replace the reason and evidence of the first")
	}
}

func TestRestoreRefusesAnUnusableIdentity(t *testing.T) {
	for _, tc := range []struct {
		name  string
		build func() WorkloadIdentity
	}{
		{"no identity", func() WorkloadIdentity {
			return WorkloadIdentity{ModelID: modelIDN(t, 2), ModelVersion: "1.0.0", Scope: ScopeServeInference}
		}},
		{"no model binding", func() WorkloadIdentity {
			return WorkloadIdentity{Identity: "wl-a", ModelVersion: "1.0.0", Scope: ScopeServeInference}
		}},
		{"unknown scope", func() WorkloadIdentity {
			return WorkloadIdentity{Identity: "wl-a", ModelID: modelIDN(t, 2), ModelVersion: "1.0.0", Scope: WorkloadScope("ROOT")}
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, _ := NewWorkloadRegistry(identityClock())
			if err := r.Restore(IdentitySnapshot{Identities: []WorkloadIdentity{tc.build()}}); err == nil {
				t.Fatal("an identity that could never have been presented must not be restored")
			}
		})
	}
}

func TestRestoreRefusesAnUnattributedRevocation(t *testing.T) {
	rev, _ := revocationFrom(dbgen.WorkloadRevocation{
		ModelID: modelIDN(t, 2).String(), ModelVersion: "1.0.0",
		RevokedAtUtc: time.Date(2026, 9, 30, 12, 30, 0, 0, time.UTC), Reason: "compromise",
	})
	r, _ := NewWorkloadRegistry(identityClock())
	if err := r.Restore(IdentitySnapshot{Revocations: []Revocation{rev}}); err == nil {
		t.Fatal("a revocation with no identity cannot be enforced against anything and must be refused")
	}
}

// TestARefusedRestoreLeavesTheRegistryUntouched is the all-or-nothing claim in Restore's own
// documentation, and it is the one property the refusal tests above cannot reach. They all
// build an empty registry and assert only that an error came back, so a Restore that published
// the snapshot's identities and then failed later would still pass every one of them.
//
// The ordering that matters is the revocation loop. Identities are validated first, so by the
// time a revocation is rejected the identity half of the snapshot is already accepted and
// sitting in a local map. If that map were published to the registry before the revocation
// loop ran, the refusal would leave the process holding the snapshot's identities instead of
// its own - and the damage is not cosmetic. The snapshot is the input to a restart, so
// replacing the live set with a rejected one strips exactly the entries the restarting process
// depends on to keep refusing.
func TestARefusedRestoreLeavesTheRegistryUntouched(t *testing.T) {
	live, _ := issuedRegistry(t)
	if _, err := live.RevokeContext(context.Background(), "wl-alpha",
		"credential observed in an unrelated tenant", "case-42"); err != nil {
		t.Fatalf("RevokeContext: %v", err)
	}
	// A second live identity, so the registry holds both a standing revocation and a live
	// entry. A refused restore then cannot be excused as having had nothing to lose.
	if _, err := live.MintContext(context.Background(), "wl-beta", modelIDN(t, 1), "1.0.0",
		ScopeServeInference); err != nil {
		t.Fatalf("MintContext: %v", err)
	}

	before := append([]WorkloadIdentity(nil), live.ActiveIdentities()...)
	beforeRevocations := len(live.Revocations())
	if len(before) != 1 || before[0].Identity != "wl-beta" || beforeRevocations != 1 {
		t.Fatalf("the fixture should hold one live identity (wl-beta) and one revocation, got %d and %d",
			len(before), beforeRevocations)
	}

	// A snapshot whose identities all validate and whose revocations do not. This is the only
	// ordering that can catch publication-before-validation.
	replacement, _ := workloadFrom(dbgen.WorkloadIdentity{
		Identity: "wl-attacker", ModelID: modelIDN(t, 2).String(), ModelVersion: "9.9.9",
		Scope: string(ScopeServeInference),
	})
	unattributed, _ := revocationFrom(dbgen.WorkloadRevocation{
		ModelID: modelIDN(t, 2).String(), ModelVersion: "9.9.9",
		RevokedAtUtc: identityClock()(), Reason: "compromise",
	})

	for _, tc := range []struct {
		name     string
		snapshot IdentitySnapshot
	}{
		{"unattributed revocation", IdentitySnapshot{
			Identities:  []WorkloadIdentity{replacement},
			Revocations: []Revocation{unattributed},
		}},
		{"duplicate revocation", IdentitySnapshot{
			Identities:  []WorkloadIdentity{replacement},
			Revocations: []Revocation{unattributed, unattributed},
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := live.Restore(tc.snapshot); err == nil {
				t.Fatal("this snapshot must be refused")
			}
			after := live.ActiveIdentities()
			if len(after) != len(before) {
				t.Fatalf("a refused restore changed the live identity set to %d identities, want %d",
					len(after), len(before))
			}
			for i := range before {
				if after[i].Identity != before[i].Identity {
					t.Fatalf("a refused restore replaced live identity %q with %q",
						before[i].Identity, after[i].Identity)
				}
			}
			if got := len(live.Revocations()); got != beforeRevocations {
				t.Fatalf("a refused restore changed the revocation set to %d, want %d",
					got, beforeRevocations)
			}
			// And the reason to care about the specific identity rather than the counts: the
			// standing revocation is what stops wl-alpha being re-minted, so losing it is the
			// failure this whole file exists to prevent, arriving through the restore path.
			if !live.IsRevoked("wl-alpha") {
				t.Fatal("a refused restore dropped the standing revocation")
			}
			if _, err := live.MintContext(context.Background(), "wl-alpha", modelIDN(t, 0), "1.0.0",
				ScopeServeInference); !errors.Is(err, ErrCompromised) {
				t.Fatalf("the standing revocation stopped refusing re-mint after a refused restore, got %v", err)
			}
		})
	}
}

// malformedSnapshotReader serves a snapshot that Restore must refuse, so the rehydration
// constructor's own refusal path can be reached. The in-memory store cannot produce one,
// because every row it holds went through the same validation Restore repeats.
type malformedSnapshotReader struct{ snapshot IdentitySnapshot }

func (m malformedSnapshotReader) LoadIdentitySnapshot(context.Context) (IdentitySnapshot, error) {
	return m.snapshot, nil
}

// TestRehydrationRefusesASnapshotTheRegistryCannotRestore is the other half of the "an empty
// registry reports no revoked identity as revoked" argument, and it is the quieter failure of
// the two.
//
// Dropping a refusal from Restore does not fail loudly. It returns a registry that is present,
// empty, and answering "no" to every revocation question - and the caller receives a usable
// object with no signal that the durable record was never loaded. That is worse than the
// missing-reader case, which is refused before a registry exists at all, because here the
// process comes up healthy and then re-issues credentials for identities whose compromise is
// on record. It is the silent direction this file exists to prevent, so the constructor has to
// fail rather than hand back a registry nobody asked for.
func TestRehydrationRefusesASnapshotTheRegistryCannotRestore(t *testing.T) {
	usable, _ := workloadFrom(dbgen.WorkloadIdentity{
		Identity: "wl-alpha", ModelID: modelIDN(t, 0).String(), ModelVersion: "1.0.0",
		Scope: string(ScopeServeInference),
	})

	for _, tc := range []struct {
		name     string
		snapshot IdentitySnapshot
	}{
		{"duplicate issuance", IdentitySnapshot{Identities: []WorkloadIdentity{usable, usable}}},
		{"unattributed revocation", IdentitySnapshot{Revocations: []Revocation{{}}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			store := NewMemoryIdentityStore()
			registry, err := RehydratedWorkloadRegistry(identityClock(), store,
				malformedSnapshotReader{snapshot: tc.snapshot})
			if err == nil {
				t.Fatal("rehydrating from a snapshot the registry cannot restore must fail; " +
					"returning the empty registry instead reports no revoked identity as revoked")
			}
			if registry != nil {
				t.Fatal("a refused rehydration must not hand back a registry; the caller would " +
					"hold a usable object that answers no to every revocation question")
			}
		})
	}
}

func TestLoadIdentitySnapshotPropagatesAReadFailure(t *testing.T) {
	store := NewMemoryIdentityStore()
	want := errors.New("identity store unavailable")
	store.FailReads(want)
	if _, err := store.LoadIdentitySnapshot(context.Background()); !errors.Is(err, want) {
		t.Fatalf("a read failure must surface, got %v", err)
	}
	// And a restore that cannot read must fail rather than produce an empty registry, which
	// would report no revoked identity as revoked.
	if _, err := RehydratedWorkloadRegistry(identityClock(), store, store); !errors.Is(err, want) {
		t.Fatalf("a failed load must be returned rather than producing an empty registry, got %v", err)
	}
}

func TestRehydratedWorkloadRegistryRefusesAMissingReader(t *testing.T) {
	store := NewMemoryIdentityStore()
	if _, err := RehydratedWorkloadRegistry(identityClock(), store, nil); err == nil {
		t.Fatal("rehydrating without a reader would produce an empty registry, which reports " +
			"no revoked identity as revoked")
	}
}

func TestLoadIdentitySnapshotIsStableAcrossRuns(t *testing.T) {
	store := NewMemoryIdentityStore()
	r, _ := NewWorkloadRegistryWithStore(identityClock(), store)
	for i := 0; i < 4; i++ {
		if _, err := r.MintContext(context.Background(), "wl-"+string(rune('a'+i)),
			modelIDN(t, 3+i), "1.0.0", ScopeServeInference); err != nil {
			t.Fatalf("MintContext: %v", err)
		}
	}
	first, err := store.LoadIdentitySnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadIdentitySnapshot: %v", err)
	}
	for i := 0; i < 8; i++ {
		again, err := store.LoadIdentitySnapshot(context.Background())
		if err != nil {
			t.Fatalf("LoadIdentitySnapshot: %v", err)
		}
		for k := range first.Identities {
			if again.Identities[k].Identity != first.Identities[k].Identity {
				t.Fatalf("load %d returned identities in a different order", i)
			}
		}
	}
}

func TestSQLIdentitySnapshotReaderMapsEveryRow(t *testing.T) {
	id := modelIDN(t, 7).String()
	q := &fakeIdentitySnapshotQuerier{
		identities: []dbgen.WorkloadIdentity{{
			Identity: "wl-alpha", ModelID: id, ModelVersion: "1.0.0",
			Scope:        string(ScopeServeInference),
			IssuedAtUtc:  time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC),
			ExpiresAtUtc: time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC),
		}},
		revocations: []dbgen.WorkloadRevocation{{
			Identity: "wl-beta", ModelID: id, ModelVersion: "1.0.0",
			RevokedAtUtc: time.Date(2026, 9, 30, 12, 30, 0, 0, time.UTC),
			Reason:       "compromise", EvidenceRef: "case-1",
			RevokedBy: "control-plane",
		}},
	}
	reader, err := NewSQLIdentitySnapshotReaderInTx(q)
	if err != nil {
		t.Fatalf("NewSQLIdentitySnapshotReaderInTx: %v", err)
	}
	snapshot, err := reader.LoadIdentitySnapshot(context.Background())
	if err != nil {
		t.Fatalf("LoadIdentitySnapshot: %v", err)
	}
	if len(snapshot.Identities) != 1 || len(snapshot.Revocations) != 1 {
		t.Fatalf("read %d identities and %d revocations, want 1 and 1",
			len(snapshot.Identities), len(snapshot.Revocations))
	}
	w := snapshot.Identities[0]
	if w.Identity != "wl-alpha" || w.ModelID.String() != id || w.Scope != ScopeServeInference {
		t.Fatalf("issuance not mapped: %+v", w)
	}
	if !w.ExpiresAt.Equal(time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)) {
		t.Fatalf("expiry was not mapped: %v", w.ExpiresAt)
	}
	rev := snapshot.Revocations[0]
	if rev.Identity != "wl-beta" || rev.Reason != "compromise" || rev.EvidenceRef != "case-1" {
		t.Fatalf("revocation not mapped: %+v", rev)
	}
	if !rev.RevokedAt.Equal(time.Date(2026, 9, 30, 12, 30, 0, 0, time.UTC)) {
		t.Fatalf("revocation time was not mapped: %v", rev.RevokedAt)
	}
}

func TestSQLIdentitySnapshotReaderRefusesRowsThatAreNotWellFormed(t *testing.T) {
	for _, tc := range []struct {
		name string
		q    *fakeIdentitySnapshotQuerier
	}{
		{"identity with no model id", &fakeIdentitySnapshotQuerier{
			identities: []dbgen.WorkloadIdentity{{Identity: "wl-a", ModelID: "nope"}},
		}},
		{"revocation with no model id", &fakeIdentitySnapshotQuerier{
			revocations: []dbgen.WorkloadRevocation{{Identity: "wl-a", ModelID: "nope"}},
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			reader, _ := NewSQLIdentitySnapshotReaderInTx(tc.q)
			if _, err := reader.LoadIdentitySnapshot(context.Background()); err == nil {
				t.Fatal("a row naming a model that is not an identifier must be refused")
			}
		})
	}
}

func TestSQLIdentitySnapshotReaderPropagatesAQueryError(t *testing.T) {
	want := errors.New("connection reset by peer")
	reader, _ := NewSQLIdentitySnapshotReaderInTx(&fakeIdentitySnapshotQuerier{err: want})
	if _, err := reader.LoadIdentitySnapshot(context.Background()); !errors.Is(err, want) {
		t.Fatalf("the underlying cause is lost: %v", err)
	}
}

func TestIdentitySnapshotReaderConstructionGuards(t *testing.T) {
	if _, err := NewSQLIdentitySnapshotReader(nil); err == nil {
		t.Fatal("a nil database handle must be refused")
	}
	if _, err := NewSQLIdentitySnapshotReaderInTx(nil); err == nil {
		t.Fatal("a nil querier must be refused")
	}
}

// fakeIdentitySnapshotQuerier serves identity rows without a database.
type fakeIdentitySnapshotQuerier struct {
	identities  []dbgen.WorkloadIdentity
	revocations []dbgen.WorkloadRevocation
	err         error
}

func (q *fakeIdentitySnapshotQuerier) ListAllWorkloadIdentities(
	context.Context,
) ([]dbgen.WorkloadIdentity, error) {
	if q.err != nil {
		return nil, q.err
	}
	return q.identities, nil
}

func (q *fakeIdentitySnapshotQuerier) ListAllWorkloadRevocations(
	context.Context,
) ([]dbgen.WorkloadRevocation, error) {
	if q.err != nil {
		return nil, q.err
	}
	return q.revocations, nil
}

var _ = contracts.PrefixModel
