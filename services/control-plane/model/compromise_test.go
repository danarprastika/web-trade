package model

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// regWithIdentity builds a registry holding the compromised workload's identity, so a
// compromise response has something real to revoke.
func regWithIdentity(t *testing.T) *WorkloadRegistry {
	t.Helper()
	reg, _ := newRegistry(t)
	if _, err := reg.Mint("svc-research-07", mustModelID(t), "3.2.1", ScopeProduceArtifacts); err != nil {
		t.Fatalf("Mint: %v", err)
	}
	return reg
}

func validCompromise(t *testing.T) Compromise {
	t.Helper()
	return Compromise{
		ModelID:          mustModelID(t),
		WorkloadIdentity: "svc-research-07",
		ArtifactDigests:  []Digest{digestArtifact, digestDataset},
		DetectedBy:       "edr/endpoint-agent-33",
		EvidenceRef:      "incident-2026-09-29-001/evidence-bundle",
		Reason:           "outbound connection to an address not in the workload's declared egress set",
	}
}

// TestCompromiseResponseCoversAllFourRequiredActions is acceptance criterion four.
//
// docs/25 section 6 requires exactly four responses to a compromised model or research
// worker: revoke the workload identity, quarantine the artifacts, block promotion, and
// preserve forensic evidence. The test asserts each independently, because a response that
// did three of the four would still be a plausible-looking incident record and the most
// likely omission is artifact quarantine, which has no immediate visible effect.
func TestCompromiseResponseCoversAllFourRequiredActions(t *testing.T) {
	reg := regWithIdentity(t)
	resp, err := Contain(validCompromise(t), reg)
	if err != nil {
		t.Fatalf("Contain refused a complete compromise response: %v", err)
	}
	if !resp.WorkloadIdentityRevoked {
		t.Error("workload identity was not revoked")
	}
	if len(resp.QuarantinedDigests) != 2 {
		t.Errorf("%d artifacts quarantined, want 2", len(resp.QuarantinedDigests))
	}
	if !resp.PromotionBlocked {
		t.Error("promotion was not blocked")
	}
	if !resp.ForensicEvidencePreserved {
		t.Error("forensic evidence was not preserved")
	}
	if resp.LifecycleEventType == "" || resp.IdempotencyScope == "" {
		t.Error("the response names no audit event or idempotency scope, so the quarantine " +
			"would not land in the audit chain like every other state change")
	}
}

// TestContainPerformsTheRevocationRatherThanAssertingIt is the reason Contain takes a
// registry instead of a boolean.
//
// The first version took a bool reporting that the caller had already revoked the identity
// and returned a response asserting the revocation had happened. A caller passing true
// without revoking anything would have produced a CompromiseResponse claiming a workload
// identity was revoked when no such record existed in the system. The response now has to
// be able to point at the revocation it performed, and this test checks that it does and
// that the revocation is real.
func TestContainPerformsTheRevocationRatherThanAssertingIt(t *testing.T) {
	reg := regWithIdentity(t)
	c := validCompromise(t)

	// Before the response, the identity works.
	if _, err := reg.Authenticate(Presentation{
		Identity: c.WorkloadIdentity, ModelID: c.ModelID, ModelVersion: "3.2.1",
	}, epoch); err != nil {
		t.Fatalf("test setup: the compromised identity should work before containment: %v", err)
	}

	resp, err := Contain(c, reg)
	if err != nil {
		t.Fatalf("Contain: %v", err)
	}

	// The response carries the recorded revocation, not a flag about one.
	if resp.Revocation.Identity != c.WorkloadIdentity {
		t.Errorf("the response carries a revocation for %q, not the compromised identity %q",
			resp.Revocation.Identity, c.WorkloadIdentity)
	}
	if resp.Revocation.EvidenceRef != c.EvidenceRef {
		t.Errorf("the revocation cites %q, want the forensic evidence %q",
			resp.Revocation.EvidenceRef, c.EvidenceRef)
	}

	// And the identity no longer works.
	if _, err := reg.Authenticate(Presentation{
		Identity: c.WorkloadIdentity, ModelID: c.ModelID, ModelVersion: "3.2.1",
	}, epoch); err == nil {
		t.Error("the compromised workload identity still authenticates after containment; " +
			"the response reported a revocation without performing one")
	}
}

// TestContainmentWidensToEveryWorkloadServingTheCompromisedVersion is the difference
// between precision and completeness.
//
// Revoking the one identity that was detected is precise and incomplete. The compromised
// thing is the model version that workload served, and every other workload bound to that
// same version is serving output of the same pipeline. Leaving those live means the platform
// can still answer with the compromised artefact, which is the outcome the response exists to
// prevent.
func TestContainmentWidensToEveryWorkloadServingTheCompromisedVersion(t *testing.T) {
	reg, _ := newRegistry(t)
	model := mustModelID(t)
	for _, name := range []string{"svc-research-07", "svc-serve-01", "svc-serve-02"} {
		if _, err := reg.Mint(name, model, "3.2.1", ScopeServeInference); err != nil {
			t.Fatalf("Mint: %v", err)
		}
	}

	resp, err := Contain(validCompromise(t), reg)
	if err != nil {
		t.Fatalf("Contain: %v", err)
	}
	if !resp.ContainmentWiden {
		t.Error("containment did not report widening although three workloads served the " +
			"compromised version")
	}
	if len(resp.ContainedIdentities) != 3 {
		t.Fatalf("containment revoked %v, want all three workloads serving 3.2.1",
			resp.ContainedIdentities)
	}
	if resp.ContainedIdentities[0] != "svc-research-07" {
		t.Errorf("the detected workload is not first in %v; a reader could not tell which "+
			"identity was detected from which were reached as a consequence",
			resp.ContainedIdentities)
	}
	for _, name := range []string{"svc-serve-01", "svc-serve-02"} {
		if !reg.IsRevoked(name) {
			t.Errorf("%s served the compromised version and is still live", name)
		}
		if _, err := reg.Authenticate(Presentation{
			Identity: name, ModelID: model, ModelVersion: "3.2.1",
		}, epoch); err == nil {
			t.Errorf("%s still authenticates after containment", name)
		}
	}
}

// TestContainmentStopsAtTheExactModelVersion is the half of the property that keeps widening
// from becoming indiscriminate.
//
// A workload serving a different version of the same model has different output. A workload
// serving a different model is unrelated. Revoking either would be revoking something with no
// relationship to the compromise, which is its own kind of failure: it destroys availability
// and it makes the containment unreviewable, because a response that revoked half the fleet
// is one nobody trusts.
func TestContainmentStopsAtTheExactModelVersion(t *testing.T) {
	reg, _ := newRegistry(t)
	model := mustModelID(t)
	other, err := contracts.ParseIdentifier("mdl_" + runBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}

	// Same model, different version: different output, not covered.
	if _, err := reg.Mint("svc-serve-other-version", model, "3.2.2", ScopeServeInference); err != nil {
		t.Fatalf("Mint: %v", err)
	}
	// Different model entirely: unrelated, not covered.
	if _, err := reg.Mint("svc-other-model", other, "3.2.1", ScopeServeInference); err != nil {
		t.Fatalf("Mint: %v", err)
	}
	if _, err := reg.Mint("svc-research-07", model, "3.2.1", ScopeProduceArtifacts); err != nil {
		t.Fatalf("Mint: %v", err)
	}

	resp, err := Contain(validCompromise(t), reg)
	if err != nil {
		t.Fatalf("Contain: %v", err)
	}
	if resp.ContainmentWiden {
		t.Errorf("containment widened to %v, but no other workload served the exact "+
			"compromised model version", resp.ContainedIdentities)
	}
	for _, name := range []string{"svc-serve-other-version", "svc-other-model"} {
		if reg.IsRevoked(name) {
			t.Errorf("%s was revoked by a compromise of %s@3.2.1; it has no relationship to "+
				"that compromise", name, model)
		}
	}
}

// TestContainmentWidenReportsWhatTheRevocationsActuallyCovered: the response computes the
// contained versions from the revocations recorded, so a responder cannot overstate the
// blast radius in the record itself.
func TestContainmentWidenReportsWhatTheRevocationsActuallyCovered(t *testing.T) {
	reg, _ := newRegistry(t)
	model := mustModelID(t)
	if _, err := reg.Mint("svc-serve-09", model, "3.1.9", ScopeServeInference); err != nil {
		t.Fatalf("Mint: %v", err)
	}
	for _, name := range []string{"svc-research-07", "svc-serve-01"} {
		if _, err := reg.Mint(name, model, "3.2.1", ScopeServeInference); err != nil {
			t.Fatalf("Mint: %v", err)
		}
	}

	resp, err := Contain(validCompromise(t), reg)
	if err != nil {
		t.Fatalf("Contain: %v", err)
	}
	// Only 3.2.1 is covered. 3.1.9's workload is untouched, so reporting it as contained
	// would tell an investigation to look at a version that is still serving.
	if len(resp.ContainedModelVersions) != 1 || resp.ContainedModelVersions[0] != "3.2.1" {
		t.Errorf("contained versions = %v, want [3.2.1]", resp.ContainedModelVersions)
	}
	if reg.IsRevoked("svc-serve-09") {
		t.Error("a workload serving an untouched version was revoked")
	}
}

// TestWidenedContainmentIsIdempotentOnRetry: an incident gets a second responder, and the
// retry must not fail or double-report.
func TestWidenedContainmentIsIdempotentOnRetry(t *testing.T) {
	reg, _ := newRegistry(t)
	model := mustModelID(t)
	for _, name := range []string{"svc-research-07", "svc-serve-01"} {
		if _, err := reg.Mint(name, model, "3.2.1", ScopeServeInference); err != nil {
			t.Fatalf("Mint: %v", err)
		}
	}
	first, err := Contain(validCompromise(t), reg)
	if err != nil {
		t.Fatalf("first Contain: %v", err)
	}
	second, err := Contain(validCompromise(t), reg)
	if err != nil {
		t.Fatalf("retried Contain failed: %v", err)
	}
	if len(second.ContainedIdentities) != len(first.ContainedIdentities) {
		t.Errorf("the retry contained %v, want the same set as the first response %v",
			second.ContainedIdentities, first.ContainedIdentities)
	}
	if got := len(reg.Revocations()); got != 2 {
		t.Errorf("%d revocations recorded, want 2; a retry is the same record", got)
	}
}

// TestContainRequiresARegistry: a caller given nowhere to perform a revocation cannot
// report one.
func TestContainRequiresARegistry(t *testing.T) {
	if _, err := Contain(validCompromise(t), nil); err == nil {
		t.Error("a compromise response with no registry was accepted; revocation was " +
			"asserted by a caller that had nowhere to perform it")
	}
}

// TestContainRefusesAnIdentityTheRegistryNeverIssued: a response reporting a revocation for
// a workload that does not exist would put a fabricated incident in the audit chain.
func TestContainRefusesAnIdentityTheRegistryNeverIssued(t *testing.T) {
	reg := regWithIdentity(t)
	c := validCompromise(t)
	c.WorkloadIdentity = "svc-never-issued"
	if _, err := Contain(c, reg); err == nil {
		t.Error("a response revoking an unissued identity was accepted")
	}
}

// TestCompromiseMustNameWhatItQuarantines: an empty artifact list would mean quarantining
// nothing, which reads identically to a complete response in an incident record.
func TestCompromiseMustNameWhatItQuarantines(t *testing.T) {
	reg := regWithIdentity(t)
	c := validCompromise(t)
	c.ArtifactDigests = nil
	if _, err := Contain(c, reg); err == nil {
		t.Error("a compromise naming no artifacts was accepted")
	}
}

// TestCompromiseMustBeAttributableAndCarryEvidence.
func TestCompromiseMustBeAttributableAndCarryEvidence(t *testing.T) {
	cases := map[string]func(*Compromise){
		"no workload identity": func(c *Compromise) { c.WorkloadIdentity = "" },
		"no detector":          func(c *Compromise) { c.DetectedBy = "" },
		"no evidence":          func(c *Compromise) { c.EvidenceRef = "" },
		"no reason":            func(c *Compromise) { c.Reason = "" },
		"bad artifact digest": func(c *Compromise) {
			c.ArtifactDigests = []Digest{"truncated"}
		},
		"no model": func(c *Compromise) { c.ModelID = contracts.Identifier{} },
	}
	reg := regWithIdentity(t)
	for name, mutate := range cases {
		c := validCompromise(t)
		mutate(&c)
		if _, err := Contain(c, reg); err == nil {
			t.Errorf("a compromise with %s was accepted", name)
		}
	}
}

// TestQuarantineRoutesThroughTheAuditedLifecyclePath checks that the state change is applied
// by Apply rather than by setting a flag, so it lands in the audit chain and is subject to
// the same idempotency as a promotion.
func TestQuarantineRoutesThroughTheAuditedLifecyclePath(t *testing.T) {
	c := validCompromise(t)
	req, err := QuarantineRequest(c, StateMonitored, "responder-varga", contracts.ActorHuman, "quarantine-key-0001")
	if err != nil {
		t.Fatalf("QuarantineRequest: %v", err)
	}
	if req.Command != CommandQuarantine {
		t.Errorf("quarantine request carries command %q", req.Command)
	}
	if !preconditionSatisfied(PreconditionForensicPreserved, req.PreconditionsSatisfied) {
		t.Error("the quarantine request does not assert that forensic evidence was preserved")
	}
	if req.Reference != c.EvidenceRef {
		t.Errorf("the quarantine request cites %q, not the forensic evidence reference", req.Reference)
	}

	// A quarantine request carrying a state that was not claimed must not apply, so the
	// responder cannot declare a model quarantined by naming a state it is not in.
	req.From = StateRetired
	if _, err := Apply(req); err == nil {
		t.Error("quarantine was applied from a terminal state")
	}

	// The same request, claiming the state the model is actually in, applies.
	for _, from := range []State{StateRegistered, StateEvaluated, StateValidated,
		StateApproved, StatePaper, StateShadow, StatePromoted, StateMonitored} {
		req.From = from
		out, err := Apply(req)
		if err != nil {
			t.Errorf("quarantine refused from %s: %v", from, err)
			continue
		}
		if out.Transition.To != StateQuarantined {
			t.Errorf("quarantine from %s produced %s", from, out.Transition.To)
		}
	}
}

// TestAnAgentCannotQuarantineItself is a control on the containment path rather than an
// ordinary denial. A compromised workload that could declare its own compromise would be
// able to remove itself from the registry at the moment it was most useful to an
// investigator.
func TestAnAgentCannotQuarantineItself(t *testing.T) {
	for _, from := range []State{StateRegistered, StateMonitored} {
		req, err := QuarantineRequest(validCompromise(t), from, "agent-alpha", contracts.ActorAgent, "quarantine-key-0001")
		if err != nil {
			t.Fatalf("QuarantineRequest: %v", err)
		}
		req.From = from
		if _, err := Apply(req); err == nil {
			t.Errorf("an agent actor was permitted to quarantine a model from %s", from)
		}
	}
}

// TestQuarantinePreservesTheEvidenceReference: the forensic bundle is what the incident
// turns on, and a response that quarantined artifacts without naming the evidence would
// leave nothing to reconstruct the compromise from.
func TestQuarantinePreservesTheEvidenceReference(t *testing.T) {
	c := validCompromise(t)
	c.EvidenceRef = "incident-2026-09-29-001/evidence-bundle"
	req, err := QuarantineRequest(c, StateMonitored, "responder-varga", contracts.ActorSystem, "quarantine-key-0001")
	if err != nil {
		t.Fatalf("QuarantineRequest: %v", err)
	}
	if req.Reference != c.EvidenceRef {
		t.Errorf("quarantine request cites %q, want the evidence reference %q",
			req.Reference, c.EvidenceRef)
	}
}

// TestQuarantineAuditRecordNamesTheFourActions: the audit record is what an operator reads
// during the incident, and a record that says only "quarantined" does not tell them whether
// the identity was revoked or the evidence preserved.
func TestQuarantineAuditRecordNamesTheFourActions(t *testing.T) {
	tr, ok := TransitionFor(StateMonitored, StateQuarantined)
	if !ok {
		t.Fatal("no quarantine edge from MONITORED")
	}
	lower := strings.ToLower(tr.AuditRecord)
	for _, want := range []string{"revoked", "quarantined", "promotion blocked", "forensic evidence"} {
		if !strings.Contains(lower, want) {
			t.Errorf("the quarantine audit record omits %q: %s", want, tr.AuditRecord)
		}
	}
}
