package model

import (
	"context"
	"errors"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// These tests cover the claims the registry's existing tests could not check.
//
// The registry's guarantees - a revoked identity cannot be re-minted, an identity is bound
// to one exact model version, expiry is bounded - were all provable against maps, because
// maps hold what they are told and never refuse. With a durable store behind them, two new
// claims appear, and both are the ones this work item exists to prevent:
//
//   - a revocation is durable, so a compromise response survives a restart; and
//   - a revocation that was NOT made durable is NOT reported as made.
//
// The second is the one that matters. EV-040 established that the reported blast radius must
// be derived from the revocations recorded rather than from the live set, precisely so that
// an incident record cannot understate its own reach. That property is worthless if the
// registry will report a revocation the store never accepted.

// recordingIdentityStore captures durable identity writes in order and can fail any of them.
//
// It is not MemoryIdentityStore because that one answers "was anything written"; this one
// answers "what was written, and when", which is what the durability claims are about.
type recordingIdentityStore struct {
	inserted []WorkloadIdentity
	revoked  []Revocation
	// failOn, when non-empty, fails the named call ("insert" or "revoke").
	failOn string
	// observe runs before each write is recorded.
	observe func()
}

func (r *recordingIdentityStore) before(kind string) error {
	if r.observe != nil {
		r.observe()
	}
	if r.failOn == kind {
		r.failOn = ""
		return errors.New("injected identity store failure")
	}
	return nil
}

func (r *recordingIdentityStore) InsertIdentity(_ context.Context, w WorkloadIdentity) error {
	if err := r.before("insert"); err != nil {
		return err
	}
	r.inserted = append(r.inserted, w)
	return nil
}

func (r *recordingIdentityStore) InsertRevocation(_ context.Context, rev Revocation) error {
	if err := r.before("revoke"); err != nil {
		return err
	}
	r.revoked = append(r.revoked, rev)
	return nil
}

// durableRegistry builds a registry whose writes go through store.
func durableRegistry(t *testing.T, store IdentityStore) *WorkloadRegistry {
	t.Helper()
	r, err := NewWorkloadRegistryWithStore(func() time.Time { return epoch }, store)
	if err != nil {
		t.Fatalf("NewWorkloadRegistryWithStore: %v", err)
	}
	return r
}

// mintOne issues one identity against a registry and returns it.
func mintOne(t *testing.T, r *WorkloadRegistry, name string, version string) WorkloadIdentity {
	t.Helper()
	w, err := r.Mint(name, mustModelID(t), version, ScopeServeInference)
	if err != nil {
		t.Fatalf("Mint %s: %v", name, err)
	}
	return w
}

// TestARefusedRevocationLeavesTheIdentityLive is the central claim of this file.
//
// Containment reports its blast radius to an investigator. If a durable write fails and the
// registry revokes anyway, the response says containment happened and the record that an
// investigation would later consult does not contain it. The failure is silent, it is in the
// direction that looks like success, and it is exactly what EV-040's blast-radius rule was
// written to prevent - so the ordering has to be enforced, not merely intended.
func TestARefusedRevocationLeavesTheIdentityLive(t *testing.T) {
	store := &recordingIdentityStore{failOn: "revoke"}
	r := durableRegistry(t, store)
	mintOne(t, r, "svc-01", "3.2.1")

	if _, err := r.Revoke("svc-01", "egress to an undeclared address", "incident-1/evidence"); err == nil {
		t.Fatal("Revoke reported success although the durable store refused the revocation")
	}

	if r.IsRevoked("svc-01") {
		t.Error("the registry believes svc-01 is revoked after a refused durable write; " +
			"containment would report work that was never recorded")
	}
	if _, live := r.IdentityOf("svc-01"); !live {
		t.Error("the identity was removed from the live set despite the revocation failing; " +
			"the workload is dead to this process and alive to every other")
	}
	if len(store.revoked) != 0 {
		t.Fatalf("%d revocations reached the store, want 0", len(store.revoked))
	}
}

// TestAWorkloadStillAuthenticatesAfterARefusedRevocation is the check that makes the first
// one concrete.
//
// A registry that revoked in memory would refuse the presentation, and the test above would
// catch that too - but only by inspecting internal state. This asks the question a request
// handler actually asks, which is the one that matters: does a workload whose revocation
// failed still get in? It must, because nothing was revoked.
func TestAWorkloadStillAuthenticatesAfterARefusedRevocation(t *testing.T) {
	store := &recordingIdentityStore{failOn: "revoke"}
	r := durableRegistry(t, store)
	w := mintOne(t, r, "svc-01", "3.2.1")

	if _, err := r.Revoke("svc-01", "egress to an undeclared address", "incident-1/evidence"); err == nil {
		t.Fatal("Revoke reported success although the store refused it")
	}

	if _, err := r.Authenticate(Presentation{
		Identity: "svc-01", ModelID: w.ModelID, ModelVersion: "3.2.1",
	}, epoch); err != nil {
		t.Fatalf("the workload is refused although nothing was revoked: %v", err)
	}
}

// TestARefusedMintIssuesNothing is the issuance counterpart.
//
// A credential handed out by this process and recorded nowhere else would be authenticated
// here and invisible everywhere else. That is the failure a shared registry exists to
// prevent, and it is reachable from exactly the branch that returns success.
func TestARefusedMintIssuesNothing(t *testing.T) {
	store := &recordingIdentityStore{failOn: "insert"}
	r := durableRegistry(t, store)

	if _, err := r.Mint("svc-01", mustModelID(t), "3.2.1", ScopeServeInference); err == nil {
		t.Fatal("Mint reported success although the durable store refused the issuance")
	}
	if _, ok := r.IdentityOf("svc-01"); ok {
		t.Error("the identity was issued in memory after a refused durable write")
	}
	if _, err := r.Authenticate(Presentation{
		Identity: "svc-01", ModelID: mustModelID(t), ModelVersion: "3.2.1",
	}, epoch); err == nil {
		t.Error("the workload authenticated with an identity that was never recorded; a " +
			"credential that exists in one process and nowhere else")
	}
}

// TestTheRetryAfterARefusedRevocationSucceeds proves the failure is recoverable.
//
// The refusal above is the easy case. This is the one an incident response depends on: a
// responder whose revocation failed must be able to retry and get it applied exactly once.
// If the failed attempt had recorded the revocation in memory, the retry would return it as
// already done and the containment would stay permanently incomplete while reporting success.
func TestTheRetryAfterARefusedRevocationSucceeds(t *testing.T) {
	store := &recordingIdentityStore{failOn: "revoke"}
	r := durableRegistry(t, store)
	mintOne(t, r, "svc-01", "3.2.1")

	if _, err := r.Revoke("svc-01", "egress to an undeclared address", "incident-1/evidence"); err == nil {
		t.Fatal("the first revocation reported success although the store refused it")
	}

	rev, err := r.Revoke("svc-01", "egress to an undeclared address", "incident-1/evidence")
	if err != nil {
		t.Fatalf("the retry after a refused durable revocation failed: %v", err)
	}
	if rev.Identity != "svc-01" {
		t.Fatalf("the retry produced a revocation for %q, want svc-01", rev.Identity)
	}
	if !r.IsRevoked("svc-01") {
		t.Error("the retry reported success but the identity is not revoked")
	}
	if len(store.revoked) != 1 {
		t.Fatalf("%d revocations reached the store, want exactly 1; the failed attempt must "+
			"not have left one behind for the retry to duplicate", len(store.revoked))
	}
}

// TestTheDurableRevocationCarriesTheReasonAndEvidence is the attribution check.
//
// The migration refuses a revocation with neither a reason nor an evidence reference, and
// that guard is only load-bearing if the registry actually supplies them. An operator
// disputing a revocation asks what it covered and why; a row with empty strings answers
// neither and is worse than no row, because it looks like a deliberate decision.
func TestTheDurableRevocationCarriesTheReasonAndEvidence(t *testing.T) {
	store := &recordingIdentityStore{}
	r := durableRegistry(t, store)
	mintOne(t, r, "svc-01", "3.2.1")

	const (
		reason   = "egress to an undeclared address"
		evidence = "incident-1/evidence"
	)
	if _, err := r.Revoke("svc-01", reason, evidence); err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	if len(store.revoked) != 1 {
		t.Fatalf("%d revocations recorded, want 1", len(store.revoked))
	}
	got := store.revoked[0]
	if got.Reason != reason {
		t.Errorf("the durable revocation records reason %q, want %q", got.Reason, reason)
	}
	if got.EvidenceRef != evidence {
		t.Errorf("the durable revocation cites evidence %q, want %q", got.EvidenceRef, evidence)
	}
	if got.ModelVersion != "3.2.1" {
		t.Errorf("the durable revocation covers version %q, want 3.2.1; a revocation that does "+
			"not record what it covered cannot be reviewed for being too broad or too narrow",
			got.ModelVersion)
	}
}

// TestTheDurableRevocationRecordsTheVersionTheRegistryHeld, not the caller's.
//
// Containment reads the model version from the registry's own record of the identity and
// never from the declaration, because a responder who misstated the version would otherwise
// silently widen or narrow the blast radius. This is the durable half of that rule: the row
// must carry the registry's binding.
func TestTheDurableRevocationRecordsTheVersionTheRegistryHeld(t *testing.T) {
	store := &recordingIdentityStore{}
	r := durableRegistry(t, store)
	mintOne(t, r, "svc-01", "9.9.9")

	// Revoke takes no version at all, so anything in the durable row came from the
	// registry's record. That is the point: the caller has no way to state a version, so
	// there is nothing for a responder to get wrong.
	if _, err := r.Revoke("svc-01", "reason", "evidence"); err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	if got := store.revoked[0].ModelVersion; got != "9.9.9" {
		t.Fatalf("the durable revocation covers version %q, want the 9.9.9 the registry held", got)
	}
}

// TestTheIssuedIdentityIsRecordedDurably checks that a minted credential exists outside this
// process.
//
// Mint now writes durably, and this is the test that it does - without it, a registry that
// quietly stopped calling the store would keep passing every other test in this file, because
// they all assert refusals and refusals do not require a write to have happened.
func TestTheIssuedIdentityIsRecordedDurably(t *testing.T) {
	store := &recordingIdentityStore{}
	r := durableRegistry(t, store)
	mintOne(t, r, "svc-01", "3.2.1")

	if len(store.inserted) != 1 {
		t.Fatalf("%d identities reached the store, want 1", len(store.inserted))
	}
	got := store.inserted[0]
	if got.Identity != "svc-01" || got.ModelVersion != "3.2.1" {
		t.Fatalf("the durable issuance records %s@%s, want svc-01@3.2.1",
			got.Identity, got.ModelVersion)
	}
	if got.Scope != ScopeServeInference {
		t.Errorf("the durable issuance records scope %q, want %q", got.Scope, ScopeServeInference)
	}
	// The expiry is the registry's bounded value, carried through rather than recomputed.
	if !got.ExpiresAt.Equal(epoch.Add(WorkloadTTL)) {
		t.Errorf("the durable issuance expires at %s, want %s; the store must carry the "+
			"registry's bounded expiry rather than computing its own",
			got.ExpiresAt, epoch.Add(WorkloadTTL))
	}
}

// TestTheDurableRecordKeepsTheIdentityAfterRevocation is the no-delete check.
//
// The registry removes a revoked identity from its live map, because a revoked identity is
// no longer one it answers "yes" to. The durable record must not: the row is what the
// revocation is evidence about, and a revocation whose subject exists nowhere is not
// reviewable. This is the asymmetry that a store mirroring the in-memory behaviour would get
// wrong, and it is asserted here rather than left to a comment.
func TestTheDurableRecordKeepsTheIdentityAfterRevocation(t *testing.T) {
	mem := NewMemoryIdentityStore()
	r := durableRegistry(t, mem)
	mintOne(t, r, "svc-01", "3.2.1")

	if _, err := r.Revoke("svc-01", "reason", "evidence"); err != nil {
		t.Fatalf("Revoke: %v", err)
	}

	if _, ok := r.IdentityOf("svc-01"); ok {
		t.Error("the identity is still live after revocation")
	}
	held, ok := mem.HasIdentity("svc-01")
	if !ok {
		t.Fatal("the durable record no longer holds the revoked identity; the row is the " +
			"evidence the revocation is about and must survive it")
	}
	if held.ModelVersion != "3.2.1" {
		t.Errorf("the retained identity records version %q, want 3.2.1", held.ModelVersion)
	}
	rev, ok := mem.Revocation("svc-01")
	if !ok {
		t.Fatal("no revocation was recorded durably")
	}
	if rev.ModelID != held.ModelID {
		t.Errorf("the revocation covers %s but the retained identity is %s; a revocation "+
			"citing a different subject cannot be reviewed", rev.ModelID, held.ModelID)
	}
}

// TestContainmentWideningSurvivesTheDurableRefusal is the EV-040 property under failure.
//
// Containment reports the identities it revoked, derived from recorded revocations. If one
// of those revocations is refused durably, the reported set must not include it. Asserting
// only the happy path would leave the rule looking stronger than it is: the widening is
// correct, and it would still be wrong under exactly the conditions an incident response runs
// in.
func TestContainmentWideningSurvivesTheDurableRefusal(t *testing.T) {
	mem := NewMemoryIdentityStore()
	r := durableRegistry(t, mem)
	id := mustModelID(t)
	for _, name := range []string{"svc-01", "svc-02", "svc-03"} {
		if _, err := r.Mint(name, id, "3.2.1", ScopeServeInference); err != nil {
			t.Fatalf("Mint %s: %v", name, err)
		}
	}

	// The middle revocation fails durably. Containment revokes all three; the reported
	// blast radius must reflect the two that were actually recorded. The failure is armed
	// immediately before that revocation rather than before the loop, because
	// FailNextWrite arms the next write and the first two are meant to succeed.
	if _, err := r.Revoke("svc-01", "reason", "evidence"); err != nil {
		t.Fatalf("the first revocation failed: %v", err)
	}
	mem.FailNextWrite(errors.New("injected"))
	if _, err := r.Revoke("svc-02", "reason", "evidence"); err == nil {
		t.Fatal("the second revocation reported success although the store refused it")
	}
	if _, err := r.Revoke("svc-03", "reason", "evidence"); err != nil {
		t.Fatalf("the third revocation failed: %v", err)
	}

	contained := r.ContainedIdentitiesForVersion(id, "3.2.1")
	if len(contained) != 2 {
		t.Fatalf("the recorded blast radius is %v, want exactly two identities; a refused "+
			"revocation must not be reported as contained", contained)
	}
	for _, name := range contained {
		if name == "svc-02" {
			t.Fatal("the blast radius includes svc-02, whose revocation was refused durably")
		}
	}
}

// TestARegistryReportsWhetherItIsDurable keeps "does this persist" answerable.
func TestARegistryReportsWhetherItIsDurable(t *testing.T) {
	inMemory, err := NewWorkloadRegistry(func() time.Time { return epoch })
	if err != nil {
		t.Fatalf("NewWorkloadRegistry: %v", err)
	}
	if inMemory.Durable() {
		t.Error("a registry built by NewWorkloadRegistry reports itself durable")
	}
	if !durableRegistry(t, NewMemoryIdentityStore()).Durable() {
		t.Error("a registry built with a store reports itself in-memory")
	}
}

// TestAnUnattachedRegistryStillWorks is the negative control.
//
// Without it, a suite where every test wires a store would still pass if the registry had
// stopped consulting it, because every remaining test asserts a refusal.
func TestAnUnattachedRegistryStillWorks(t *testing.T) {
	r, err := NewWorkloadRegistry(func() time.Time { return epoch })
	if err != nil {
		t.Fatalf("NewWorkloadRegistry: %v", err)
	}
	mintOne(t, r, "svc-01", "3.2.1")
	if _, err := r.Revoke("svc-01", "reason", "evidence"); err != nil {
		t.Fatalf("Revoke without a store failed: %v", err)
	}
	if !r.IsRevoked("svc-01") {
		t.Error("Revoke reported success but the identity is not revoked")
	}
}

// TestTheStoreConstructorsRefuseAMissingHandle keeps the constructors honest. A store built
// over nil would fail at the first write from inside database/sql, far from the mistake.
func TestTheStoreConstructorsRefuseAMissingHandle(t *testing.T) {
	if _, err := NewSQLIdentityStore(nil); err == nil {
		t.Error("NewSQLIdentityStore accepted a nil database handle")
	}
}

// TestTheIdentityStoreIsSeparateFromTheModelStore checks that the two ports are not
// interchangeable.
//
// A journal that could insert a revocation would be a journal that could revoke a workload,
// and the containment path is the one place in this package where that would matter. The
// separation is a type-level claim, so it is asserted at the type level.
func TestTheIdentityStoreIsSeparateFromTheModelStore(t *testing.T) {
	// Both ports are satisfiable by a struct implementing both; what must not hold is that
	// satisfying one satisfies the other. A Store value is not an IdentityStore.
	var s Store = NewMemoryStore()
	if _, ok := s.(IdentityStore); ok {
		t.Error("a model Store also satisfies IdentityStore; the journal could then revoke a " +
			"workload identity")
	}
	var is IdentityStore = NewMemoryIdentityStore()
	if _, ok := is.(Store); ok {
		t.Error("an IdentityStore also satisfies Store; an identity write could then " +
			"advance a lifecycle state")
	}
}

// unusedContracts keeps the contracts import honest if this file is edited down.
var _ = contracts.Identifier{}
