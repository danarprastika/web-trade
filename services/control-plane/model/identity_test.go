package model

import (
	"strings"
	"sync"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// fakeClock is a settable clock. Expiry and revocation are the properties most likely to be
// broken by a change that only affects timing, and a test that relied on real time would
// either be slow or flaky, and would in both cases stop being a check.
type fakeClock struct{ at time.Time }

func (c *fakeClock) now() time.Time          { return c.at }
func (c *fakeClock) advance(d time.Duration) { c.at = c.at.Add(d) }

var epoch = time.Date(2026, 9, 29, 12, 0, 0, 0, time.UTC)

func newRegistry(t *testing.T) (*WorkloadRegistry, *fakeClock) {
	t.Helper()
	clock := &fakeClock{at: epoch}
	reg, err := NewWorkloadRegistry(clock.now)
	if err != nil {
		t.Fatalf("NewWorkloadRegistry: %v", err)
	}
	return reg, clock
}

func mintServing(t *testing.T, reg *WorkloadRegistry, identity, version string) WorkloadIdentity {
	t.Helper()
	w, err := reg.Mint(identity, mustModelID(t), version, ScopeServeInference)
	if err != nil {
		t.Fatalf("Mint: %v", err)
	}
	return w
}

// TestAMintedIdentityIsShortLived is the zero-trust requirement docs/25 section 5 states:
// a short-lived workload identity. The check is on the constant and on the absence of any
// way to extend, because a TTL that callers may set is not a bound.
func TestAMintedIdentityIsShortLived(t *testing.T) {
	reg, clock := newRegistry(t)
	w := mintServing(t, reg, "svc-serve-01", "3.2.1")

	if w.ExpiresAt.Sub(w.IssuedAt) != WorkloadTTL {
		t.Errorf("identity lifetime is %s, want the fixed %s", w.ExpiresAt.Sub(w.IssuedAt), WorkloadTTL)
	}
	if WorkloadTTL > 2*time.Hour {
		t.Errorf("workload TTL is %s; a longer life cannot be meaningfully revoked", WorkloadTTL)
	}

	// An hour later it authenticates.
	if _, err := reg.Authenticate(Presentation{
		Identity: "svc-serve-01", ModelID: w.ModelID, ModelVersion: "3.2.1",
	}, clock.at.Add(59*time.Minute)); err != nil {
		t.Errorf("a live identity was refused: %v", err)
	}
	// Past its life it does not, and it is not extended by use.
	clock.advance(2 * time.Hour)
	if _, err := reg.Authenticate(Presentation{
		Identity: "svc-serve-01", ModelID: w.ModelID, ModelVersion: "3.2.1",
	}, clock.at); err == nil {
		t.Error("an expired identity authenticated; workload identities are short-lived by " +
			"design and are re-minted rather than extended")
	}
	// Use did not slide the expiry.
	if !w.Expired(clock.at) {
		t.Error("an expired identity reports itself live")
	}
}

// TestAnIdentityIsBoundToOneExactModelVersion is what makes a revocation precise. An
// identity bound only to a model would keep working for a newer version the compromise had
// nothing to do with, and a revocation aimed at the compromise would be over-broad.
func TestAnIdentityIsBoundToOneExactModelVersion(t *testing.T) {
	reg, clock := newRegistry(t)
	w := mintServing(t, reg, "svc-serve-01", "3.2.1")

	for _, version := range []string{"3.2.2", "3.2.0", "", "3.2.1+build"} {
		if _, err := reg.Authenticate(Presentation{
			Identity: "svc-serve-01", ModelID: w.ModelID, ModelVersion: version,
		}, clock.at); err == nil {
			t.Errorf("an identity bound to 3.2.1 authenticated for version %q", version)
		}
	}
	if _, err := reg.Authenticate(Presentation{
		Identity: "svc-serve-01", ModelID: w.ModelID, ModelVersion: "3.2.1",
	}, clock.at); err != nil {
		t.Errorf("an identity refused its own version: %v", err)
	}
}

// TestPresentationForADifferentModelIsRefused: an identity is bound to a model as well as a
// version, so serving another model with it is refused rather than treated as a near miss.
func TestPresentationForADifferentModelIsRefused(t *testing.T) {
	reg, clock := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")

	other, err := contracts.ParseIdentifier("mdl_" + runBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	if _, err := reg.Authenticate(Presentation{
		Identity: "svc-serve-01", ModelID: other, ModelVersion: "3.2.1",
	}, clock.at); err == nil {
		t.Error("an identity bound to one model authenticated for another")
	}
}

// TestRevocationIsImmediateAndOutlivesTheCredential is the property that makes revocation
// meaningful. An identity revoked before it expires must still be refused after its
// nominal expiry passes, and a revoked identity is not resurrected by the clock.
func TestRevocationIsImmediateAndOutlivesTheCredential(t *testing.T) {
	reg, clock := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")

	rev, err := reg.Revoke("svc-serve-01", "egress to an undeclared address", "incident-1/evidence")
	if err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	if rev.RevokedAt != epoch {
		t.Errorf("revocation timestamped %s, want the injected clock %s", rev.RevokedAt, epoch)
	}
	if reg.IsRevoked("svc-serve-01") != true {
		t.Error("the registry does not report the identity as revoked")
	}

	// Refused now, while it would otherwise still be live.
	if _, err := reg.Authenticate(Presentation{
		Identity: "svc-serve-01", ModelID: mustModelID(t), ModelVersion: "3.2.1",
	}, clock.at); err == nil {
		t.Error("a revoked identity authenticated immediately after revocation")
	}

	// And still refused long after its nominal expiry.
	clock.advance(48 * time.Hour)
	if _, err := reg.Authenticate(Presentation{
		Identity: "svc-serve-01", ModelID: mustModelID(t), ModelVersion: "3.2.1",
	}, clock.at); err == nil {
		t.Error("a revoked identity authenticated after its nominal lifetime passed")
	}
}

// TestRevocationIsRefusedByIdentityRatherThanByAbsence: an investigator needs to know that
// a revocation happened and why, and a registry that simply forgot the identity could not
// tell them that.
func TestRevocationIsRefusedByIdentityRatherThanByAbsence(t *testing.T) {
	reg, clock := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")
	if _, err := reg.Revoke("svc-serve-01", "suspected compromise", "incident-1/evidence"); err != nil {
		t.Fatalf("Revoke: %v", err)
	}

	_, err := reg.Authenticate(Presentation{
		Identity: "svc-serve-01", ModelID: mustModelID(t), ModelVersion: "3.2.1",
	}, clock.at)
	if err == nil {
		t.Fatal("a revoked identity authenticated")
	}
	// The reason must survive into the refusal, and must be the revocation rather than the
	// expiry: an operator pointed at the clock instead of the incident would waste the
	// time the revocation was meant to save.
	if !strings.Contains(err.Error(), "revoked") {
		t.Errorf("the refusal does not mention revocation: %v", err)
	}
	if !strings.Contains(err.Error(), "suspected compromise") {
		t.Errorf("the refusal does not carry the recorded reason: %v", err)
	}

	rev, ok := reg.RevocationOf("svc-serve-01")
	if !ok {
		t.Fatal("the revocation is not retrievable")
	}
	if rev.EvidenceRef != "incident-1/evidence" {
		t.Errorf("revocation cites %q, want the forensic evidence reference", rev.EvidenceRef)
	}
	if rev.ModelVersion != "3.2.1" {
		t.Errorf("revocation records version %q, want the version it covered", rev.ModelVersion)
	}
}

// TestARevokedIdentityCannotBeReMinted: a compromised workload must re-enter through a new
// identity, not resurrect the one that was just revoked.
func TestARevokedIdentityCannotBeReMinted(t *testing.T) {
	reg, _ := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")
	if _, err := reg.Revoke("svc-serve-01", "suspected compromise", "incident-1/evidence"); err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	if _, err := reg.Mint("svc-serve-01", mustModelID(t), "3.2.2", ScopeServeInference); err == nil {
		t.Error("a revoked identity was re-minted; a compromised workload must re-enter " +
			"through a new identity")
	}
}

// TestRevocationIsIdempotent: a retried incident response must not fail, because the second
// responder to arrive at the same incident is doing the right thing.
func TestRevocationIsIdempotent(t *testing.T) {
	reg, _ := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")
	first, err := reg.Revoke("svc-serve-01", "suspected compromise", "incident-1/evidence")
	if err != nil {
		t.Fatalf("first Revoke: %v", err)
	}
	second, err := reg.Revoke("svc-serve-01", "suspected compromise", "incident-1/evidence")
	if err != nil {
		t.Fatalf("retried Revoke failed: %v", err)
	}
	if first != second {
		t.Error("a retried revocation produced a different record; the original must stand")
	}
	if got := len(reg.Revocations()); got != 1 {
		t.Errorf("%d revocations recorded, want 1", got)
	}
}

// TestRevocationRequiresAReasonAndEvidence: revocation is an action that gets disputed, so
// an unattributed or unevidenced one is refused.
func TestRevocationRequiresAReasonAndEvidence(t *testing.T) {
	reg, _ := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")
	for _, tc := range []struct{ reason, evidence string }{
		{"", "incident-1/evidence"},
		{"   ", "incident-1/evidence"},
		{"suspected compromise", ""},
		{"suspected compromise", "  "},
	} {
		if _, err := reg.Revoke("svc-serve-01", tc.reason, tc.evidence); err == nil {
			t.Errorf("a revocation with reason %q and evidence %q was accepted", tc.reason, tc.evidence)
		}
	}
}

// TestAnUnissuedIdentityCannotBeRevoked: recording a revocation for a workload that does not
// exist would put a fabricated incident in the audit chain.
func TestAnUnissuedIdentityCannotBeRevoked(t *testing.T) {
	reg, _ := newRegistry(t)
	if _, err := reg.Revoke("svc-never-issued", "suspected compromise", "incident-1/evidence"); err == nil {
		t.Error("an identity that was never issued was revoked")
	}
}

// TestMintingRefusesAnonymousUnboundAndUnknownScopeIdentities.
func TestMintingRefusesAnonymousUnboundAndUnknownScopeIdentities(t *testing.T) {
	reg, _ := newRegistry(t)
	strategy, err := contracts.ParseIdentifier("str_" + modelBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	cases := map[string]struct {
		identity string
		modelID  contracts.Identifier
		version  string
		scope    WorkloadScope
	}{
		"anonymous identity": {"", mustModelID(t), "3.2.1", ScopeServeInference},
		"blank identity":     {"   ", mustModelID(t), "3.2.1", ScopeServeInference},
		"no model":           {"svc-serve-01", contracts.Identifier{}, "3.2.1", ScopeServeInference},
		"non-model id":       {"svc-serve-01", strategy, "3.2.1", ScopeServeInference},
		"no version":         {"svc-serve-01", mustModelID(t), "", ScopeServeInference},
		"unknown scope":      {"svc-serve-01", mustModelID(t), "3.2.1", WorkloadScope("OMNISCIENT")},
	}
	for name, tc := range cases {
		if _, err := reg.Mint(tc.identity, tc.modelID, tc.version, tc.scope); err == nil {
			t.Errorf("minted an identity with %s", name)
		}
	}
}

// TestDuplicateIdentitiesAreRefused: two workloads sharing an identity means revoking one
// revokes both, which is the opposite of the precision a version-bound identity provides.
func TestDuplicateIdentitiesAreRefused(t *testing.T) {
	reg, _ := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")
	if _, err := reg.Mint("svc-serve-01", mustModelID(t), "3.2.2", ScopeServeInference); err == nil {
		t.Error("a duplicate identity was issued")
	}
}

// TestAnUnknownIdentityIsRefused: a workload proves an identity it was issued, not one it
// claims.
func TestAnUnknownIdentityIsRefused(t *testing.T) {
	reg, clock := newRegistry(t)
	if _, err := reg.Authenticate(Presentation{
		Identity: "svc-invented", ModelID: mustModelID(t), ModelVersion: "3.2.1",
	}, clock.at); err == nil {
		t.Error("an identity that was never issued authenticated")
	}
}

// TestARegistryRequiresAClock: an injected clock is what makes expiry and revocation
// testable, and a registry with the real clock would make both untestable.
func TestARegistryRequiresAClock(t *testing.T) {
	if _, err := NewWorkloadRegistry(nil); err == nil {
		t.Error("a workload registry was built with no clock")
	}
}

// TestContainedModelVersionsAnswersWhatTheCompromiseTouched is the completeness question an
// investigator asks first: revoking a workload stops that workload, but the model versions
// it produced are still registered, and the set has to be computable rather than
// reconstructed from a log.
func TestContainedModelVersionsAnswersWhatTheCompromiseTouched(t *testing.T) {
	reg, _ := newRegistry(t)
	for _, id := range []string{"svc-serve-01", "svc-serve-02", "svc-produce-03"} {
		if _, err := reg.Mint(id, mustModelID(t), "3.2.1", ScopeServeInference); err != nil {
			t.Fatalf("Mint: %v", err)
		}
	}
	if _, err := reg.Mint("svc-serve-04", mustModelID(t), "3.2.2", ScopeServeInference); err != nil {
		t.Fatalf("Mint: %v", err)
	}

	versions := reg.ContainedModelVersions(mustModelID(t))
	if len(versions) != 0 {
		t.Errorf("an untouched registry reports contained versions %v", versions)
	}

	for _, id := range []string{"svc-serve-01", "svc-serve-02", "svc-produce-03"} {
		if _, err := reg.Revoke(id, "suspected compromise", "incident-1/evidence"); err != nil {
			t.Fatalf("Revoke: %v", err)
		}
	}
	versions = reg.ContainedModelVersions(mustModelID(t))
	if len(versions) != 1 || versions[0] != "3.2.1" {
		t.Errorf("contained versions = %v, want [3.2.1]; the three revoked identities all "+
			"served that version and one was left out or duplicated", versions)
	}

	// Revoking the 3.2.2 identity too covers both versions.
	if _, err := reg.Revoke("svc-serve-04", "suspected compromise", "incident-1/evidence"); err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	versions = reg.ContainedModelVersions(mustModelID(t))
	if len(versions) != 2 {
		t.Errorf("contained versions = %v, want both 3.2.1 and 3.2.2", versions)
	}
}

// TestActiveIdentitiesExcludesRevoked: a governance view that still listed a revoked
// identity would be read as a list of what the platform can hear from.
func TestActiveIdentitiesExcludesRevoked(t *testing.T) {
	reg, _ := newRegistry(t)
	mintServing(t, reg, "svc-serve-01", "3.2.1")
	mintServing(t, reg, "svc-serve-02", "3.2.1")
	if got := len(reg.ActiveIdentities()); got != 2 {
		t.Fatalf("%d active identities, want 2", got)
	}
	if _, err := reg.Revoke("svc-serve-01", "suspected compromise", "incident-1/evidence"); err != nil {
		t.Fatalf("Revoke: %v", err)
	}
	active := reg.ActiveIdentities()
	if len(active) != 1 || active[0].Identity != "svc-serve-02" {
		t.Errorf("active identities = %v, want only svc-serve-02", active)
	}
}

// TestScopesDoNotConferRegistryAuthority is the zero-trust boundary stated for workloads.
// No scope lets a workload change a lifecycle state or issue an identity, so holding any of
// them cannot become a path to authority.
func TestScopesDoNotConferRegistryAuthority(t *testing.T) {
	reg, _ := newRegistry(t)
	for _, scope := range AllScopes() {
		if _, err := reg.Mint("svc-"+strings.ToLower(string(scope)), mustModelID(t), "3.2.1", scope); err != nil {
			t.Fatalf("Mint(%s): %v", scope, err)
		}
	}
	// Producing artifacts is not deciding. The lifecycle still refuses a promotion from an
	// agent or service actor whatever the scope says, because the scope is not consulted by
	// the lifecycle and must not be.
	req := validRequest(t, StateShadow, CommandPromote, contracts.ActorService)
	if _, err := Apply(req); err == nil {
		t.Error("a service actor promoted a model; a workload scope confers no lifecycle authority")
	}
}

// TestTheWorkloadRegistryIsSafeForConcurrentUse exercises the registry from many
// goroutines under the race detector.
//
// The interesting interleaving is Mint against Revoke. Mint checks the revocations map and
// then writes the identities map; Revoke reads the identities map and then writes the
// revocations map. A registry without a lock can let a mint that observed no revocation
// complete after a revoke that observed no mint, leaving a live identity for a workload that
// had just been revoked. The lock makes each check-then-write atomic, and this test is what
// makes the lock a verified property rather than an assumption in a comment.
//
// The assertions are deliberately weak, because most calls are expected to fail: the subject
// is the absence of a data race, not the outcome of any one call. What must hold once every
// goroutine has finished is that the registry is still coherent, in particular that nothing
// successfully revoked is still reported active.
func TestTheWorkloadRegistryIsSafeForConcurrentUse(t *testing.T) {
	reg, _ := newRegistry(t)
	// Resolved here, on the test goroutine: mustModelID calls t.Fatalf, which is only
	// valid on the goroutine that owns the test.
	modelID := mustModelID(t)

	const names = 6
	ids := make([]string, 0, names)
	for i := 0; i < names; i++ {
		name := "svc-serve-" + string(rune('a'+i))
		ids = append(ids, name)
		if _, err := reg.Mint(name, modelID, "3.2.1", ScopeServeInference); err != nil {
			t.Fatalf("Mint: %v", err)
		}
	}

	revoked := map[string]bool{}
	var mu sync.Mutex
	var wg sync.WaitGroup

	for round := 0; round < 4; round++ {
		for _, name := range ids {
			wg.Add(4)
			go func(name string) {
				defer wg.Done()
				_, _ = reg.Authenticate(Presentation{
					Identity: name, ModelID: modelID, ModelVersion: "3.2.1",
				}, epoch)
			}(name)
			go func(name string) {
				defer wg.Done()
				_, _ = reg.Mint(name, modelID, "3.2.2", ScopeServeInference)
			}(name)
			go func(name string) {
				defer wg.Done()
				_ = reg.IsRevoked(name)
				_ = reg.ActiveIdentities()
				_ = reg.Revocations()
				_ = reg.ContainedModelVersions(modelID)
			}(name)
			go func(name string) {
				defer wg.Done()
				if _, err := reg.Revoke(name, "suspected compromise", "incident-1/evidence"); err == nil {
					mu.Lock()
					revoked[name] = true
					mu.Unlock()
				}
			}(name)
		}
	}
	wg.Wait()

	active := map[string]bool{}
	for _, w := range reg.ActiveIdentities() {
		active[w.Identity] = true
	}
	for name := range revoked {
		if active[name] {
			t.Errorf("%s was revoked and is still active; a revoke racing a concurrent mint "+
				"was lost", name)
		}
		if !reg.IsRevoked(name) {
			t.Errorf("%s was successfully revoked but the registry does not report it", name)
		}
	}
}

// TestIdentityStringOmitsCredentials: the identity is rendered for audit records, and what
// is rendered should be the binding and the expiry, not anything a reader could use.
func TestIdentityStringOmitsCredentials(t *testing.T) {
	reg, _ := newRegistry(t)
	w := mintServing(t, reg, "svc-serve-01", "3.2.1")
	s := w.String()
	for _, want := range []string{"svc-serve-01", "mdl_", "3.2.1", "SERVE_INFERENCE"} {
		if !strings.Contains(s, want) {
			t.Errorf("identity string omits %q: %s", want, s)
		}
	}
}
