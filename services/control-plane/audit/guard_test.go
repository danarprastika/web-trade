package audit

import (
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// AC4: when the sink stops accepting evidence, sensitive operations must be blocked
// before the backlog can grow without bound, and nothing may be dropped.
func TestSensitiveOperationsAreBlockedWhenTheBacklogIsFull(t *testing.T) {
	g, err := NewGuard(3)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}

	// The backlog may fill to the limit without blocking: that is the buffer working.
	for i := 0; i < 3; i++ {
		if err := g.Accept(1); err != nil {
			t.Fatalf("accepting record %d within the limit must succeed: %v", i, err)
		}
	}
	if err := g.Allow(OpRiskIncreasing); err != nil {
		t.Fatalf("a full-but-not-overflowed guard must still permit work: %v", err)
	}

	// The next record would exceed the bound, so it is refused and the guard latches.
	if err := g.Accept(1); err == nil {
		t.Fatal("exceeding the backlog limit must be refused")
	}
	if !g.Halted() {
		t.Fatal("an overflow must latch the guard")
	}
	if err := g.Allow(OpRiskIncreasing); err == nil {
		t.Fatal("risk-increasing work must be blocked once evidence cannot be stored")
	}
	if err := g.Allow(OpPrivilegedMutation); err == nil {
		t.Fatal("privileged mutations must be blocked once evidence cannot be stored")
	}
}

// A halt must not trap the operator in an open position.
func TestRiskReducingAndReadOnlyWorkContinuesDuringAHalt(t *testing.T) {
	g, _ := NewGuard(1)
	g.Halt("SEV-1_AUDIT_INTEGRITY", "test halt")

	if err := g.Allow(OpRiskReducing); err != nil {
		t.Fatalf("cancelling must remain possible during a halt: %v", err)
	}
	if err := g.Allow(OpReadOnly); err != nil {
		t.Fatalf("reading must remain possible during a halt: %v", err)
	}
}

func TestGuardLatchRequiresAnExplicitClear(t *testing.T) {
	g, _ := NewGuard(2)
	_ = g.Accept(1)
	_ = g.Accept(1)
	// This one exceeds the limit: it is refused, and the refusal latches the guard.
	if err := g.Accept(1); err == nil {
		t.Fatal("exceeding the limit must be refused")
	}
	if !g.Halted() {
		t.Fatal("expected the guard to latch")
	}

	// Draining the backlog must not silently reopen the platform.
	if err := g.Exported(2); err != nil {
		t.Fatalf("Exported: %v", err)
	}
	if !g.Halted() {
		t.Fatal("draining the backlog must not clear the halt; clearing is an explicit decision")
	}
	if err := g.Allow(OpRiskIncreasing); err == nil {
		t.Fatal("work must stay blocked until the halt is explicitly cleared")
	}

	g.Clear()
	if err := g.Allow(OpRiskIncreasing); err != nil {
		t.Fatalf("after an explicit clear, work must be permitted: %v", err)
	}
}

func TestAHaltIsNotReplacedByASecondHalt(t *testing.T) {
	g, _ := NewGuard(1)
	g.Halt("FIRST", "first cause")
	g.Halt("SECOND", "second cause")
	cause, reason := g.Reason()
	if cause != "FIRST" {
		t.Fatalf("the first halt cause must be preserved, got %q", cause)
	}
	if reason != "first cause" {
		t.Fatalf("the first halt reason must be preserved, got %q", reason)
	}
}

// An integrity failure arriving after a backlog halt must be surfaced, not discarded.
//
// This is the case that made the latch itself the defect. A backlog halt records
// EVIDENCE_BACKLOG; a chain break arriving afterwards called Halt, which returned because
// the guard was already latched. Reason() went on reporting the backlog, and once the
// backlog drained, Clear's precondition was satisfied and the latch was released - so the
// chain break was detected, never surfaced, and cleared away by an operator who was told
// the halt was about export lag.
func TestASev1FindingIsNotMaskedByAnEarlierBacklogHalt(t *testing.T) {
	g, err := NewGuard(2)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	// Fill the backlog so the overflow refusal raises the first halt.
	if err := g.Accept(2); err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if err := g.Accept(1); err == nil {
		t.Fatal("exceeding the limit must be refused")
	}
	cause, _ := g.Reason()
	if cause != causeEvidenceBacklog {
		t.Fatalf("expected the first halt to be the backlog, got %q", cause)
	}

	// Drain the backlog, which is what used to make the integrity finding unrecoverable.
	if err := g.Exported(2); err != nil {
		t.Fatalf("Exported: %v", err)
	}

	g.ObserveVerification(Verification{
		OK:       false,
		Findings: []Finding{{Kind: FindingTamper, Partition: "tenant-a", Sequence: 3, Detail: "altered"}},
	})

	cause, reason := g.Reason()
	if cause != causeSev1Integrity {
		t.Fatalf("a chain break after a backlog halt must be reported as %q, got %q - the finding "+
			"was masked by the earlier halt and would be cleared away unreviewed",
			causeSev1Integrity, cause)
	}
	if !strings.Contains(reason, string(FindingTamper)) {
		t.Fatalf("the reason must name the finding that was detected, got %q", reason)
	}
	if err := g.Allow(OpRiskIncreasing); err == nil {
		t.Fatal("risk-increasing work must stay blocked until the finding is reviewed and cleared")
	}
}

// The escalation must not become a way to clear while evidence is still unexported.
//
// An integrity halt is deliberately clearable regardless of the backlog, so raising the
// cause while a backlog is outstanding hands the operator a clear that the backlog case
// would have refused. That is acceptable only because the backlog stays bounded elsewhere:
// Accept refuses once the limit is reached, so releasing the latch cannot cause a drop.
func TestEscalatingToIntegrityStillLeavesTheBacklogBounded(t *testing.T) {
	g, err := NewGuard(2)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	if err := g.Accept(2); err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if err := g.Accept(1); err == nil {
		t.Fatal("exceeding the limit must be refused")
	}
	g.ObserveVerification(Verification{
		OK:       false,
		Findings: []Finding{{Kind: FindingReorder, Partition: "tenant-a", Sequence: 9}},
	})

	cause, _ := g.Reason()
	if cause != causeSev1Integrity {
		t.Fatalf("expected the cause to escalate to %q, got %q", causeSev1Integrity, cause)
	}
	// The backlog is untouched by the escalation, and still refuses work once it is full.
	if got := g.Pending(); got != 2 {
		t.Fatalf("the escalation must not alter the backlog, pending is %d, expected 2", got)
	}
	if err := g.Accept(1); err == nil {
		t.Fatal("a full backlog must still refuse work after the cause escalated")
	}
}

// The escalation is one-directional. A chain break already recorded must not be
// downgraded to a backlog, or the integrity finding would become clearable on backlog
// terms and would then be blocked by a backlog that was never the problem.
func TestAnIntegrityHaltIsNotDowngradedByALaterBacklogHalt(t *testing.T) {
	g, err := NewGuard(2)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	g.ObserveVerification(Verification{
		OK:       false,
		Findings: []Finding{{Kind: FindingSignature, Partition: "tenant-a", Sequence: 4}},
	})
	// A backlog halt follows, from a full buffer.
	if err := g.Accept(2); err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if err := g.Accept(1); err == nil {
		t.Fatal("exceeding the limit must be refused")
	}

	cause, _ := g.Reason()
	if cause != causeSev1Integrity {
		t.Fatalf("a recorded chain break must not be downgraded to %q, got %q",
			causeEvidenceBacklog, cause)
	}
	if err := g.Allow(OpPrivilegedMutation); err == nil {
		t.Fatal("privileged mutations must stay blocked on a recorded chain break")
	}
}

// A SEV-1 integrity failure must stop trading even when the buffer is empty. A clean
// backlog says nothing about whether the evidence already written is intact.
func TestASev1VerificationFailureHaltsEvenWithAnEmptyBacklog(t *testing.T) {
	g, _ := NewGuard(100)
	g.ObserveVerification(Verification{
		OK:       false,
		Findings: []Finding{{Kind: FindingTamper, Partition: "tenant-a", Sequence: 3, Detail: "altered"}},
	})
	if !g.Halted() {
		t.Fatal("a SEV-1 integrity failure must halt the guard")
	}
	if err := g.Allow(OpRiskIncreasing); err == nil {
		t.Fatal("a SEV-1 integrity failure must block risk-increasing work")
	}
	if err := g.Allow(OpRiskReducing); err != nil {
		t.Fatalf("risk-reducing work must still be permitted: %v", err)
	}
}

func TestACleanVerificationDoesNotHalt(t *testing.T) {
	g, _ := NewGuard(100)
	g.ObserveVerification(Verification{OK: true})
	if g.Halted() {
		t.Fatal("a clean verification must not halt")
	}
}

func TestTheHaltReasonNamesWhatFailed(t *testing.T) {
	g, _ := NewGuard(100)
	g.ObserveVerification(Verification{
		OK: false,
		Findings: []Finding{
			{Kind: FindingTamper, Detail: "a"},
			{Kind: FindingDeletion, Detail: "b"},
		},
	})
	_, reason := g.Reason()
	if !strings.Contains(reason, "TAMPER") || !strings.Contains(reason, "DELETION") {
		t.Fatalf("the halt reason must name what failed, got %q", reason)
	}
}

func TestGuardRejectsNonsensicalAccounting(t *testing.T) {
	g, _ := NewGuard(5)
	if err := g.Accept(-1); err == nil {
		t.Fatal("accepting a negative count must be refused")
	}
	if err := g.Exported(1); err == nil {
		t.Fatal("exporting more than is pending must be refused")
	}
	if _, err := NewGuard(0); err == nil {
		t.Fatal("a guard with no capacity must be refused")
	}
}

// AC2: deletion is permitted only after expiry, legal-hold clearance, and two-person
// approval. Each precondition is checked independently.
func TestDeletionIsRefusedWithoutEveryPrecondition(t *testing.T) {
	base := DeletionRequest{
		Partition:        "tenant-a",
		FirstSequence:    1,
		LastSequence:     10,
		RequestedBy:      "alice",
		ApprovedBy:       "bob",
		LegalHoldCleared: true,
		RetentionExpired: true,
		Now:              contracts.MustParseTimestamp("2033-09-28T11:00:00.000000000Z"),
	}
	if err := EvaluateDeletion(base); err != nil {
		t.Fatalf("a fully approved request must be permitted: %v", err)
	}

	mutations := map[string]func(*DeletionRequest){
		"no partition":  func(r *DeletionRequest) { r.Partition = "" },
		"bad range":     func(r *DeletionRequest) { r.FirstSequence, r.LastSequence = 10, 1 },
		"zero start":    func(r *DeletionRequest) { r.FirstSequence = 0 },
		"legal hold":    func(r *DeletionRequest) { r.LegalHoldCleared = false },
		"not expired":   func(r *DeletionRequest) { r.RetentionExpired = false },
		"no requester":  func(r *DeletionRequest) { r.RequestedBy = "" },
		"no approver":   func(r *DeletionRequest) { r.ApprovedBy = "" },
		"self approved": func(r *DeletionRequest) { r.ApprovedBy = r.RequestedBy },
	}
	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			req := base
			mutate(&req)
			if err := EvaluateDeletion(req); err == nil {
				t.Fatal("must be refused")
			}
		})
	}
}

// Two-person approval that is one person twice is not two-person approval.
func TestTheSamePersonCannotBothRequestAndApproveADeletion(t *testing.T) {
	req := DeletionRequest{
		Partition:        "tenant-a",
		FirstSequence:    1,
		LastSequence:     10,
		RequestedBy:      "alice",
		ApprovedBy:       "alice",
		LegalHoldCleared: true,
		RetentionExpired: true,
	}
	if _, err := NewDeletionEvent(req); err == nil {
		t.Fatal("a deletion self-approved by one person must be refused")
	}
}

// docs/22 section 4: the deletion event itself is retained.
func TestAnApprovedDeletionProducesARetainedEvent(t *testing.T) {
	req := DeletionRequest{
		Partition:        "tenant-a",
		FirstSequence:    1,
		LastSequence:     10,
		RequestedBy:      "alice",
		ApprovedBy:       "bob",
		LegalHoldCleared: true,
		RetentionExpired: true,
		Now:              contracts.MustParseTimestamp("2033-09-28T11:00:00.000000000Z"),
	}
	ev, err := NewDeletionEvent(req)
	if err != nil {
		t.Fatalf("NewDeletionEvent: %v", err)
	}
	if ev.AuditID == "" {
		t.Fatal("a deletion must leave a retained, identified record")
	}
	// A retried deletion must produce the same event rather than a second one.
	again, err := NewDeletionEvent(req)
	if err != nil {
		t.Fatalf("NewDeletionEvent: %v", err)
	}
	if again.AuditID != ev.AuditID {
		t.Fatalf("a retried deletion must be the same event: %q vs %q", again.AuditID, ev.AuditID)
	}
}
