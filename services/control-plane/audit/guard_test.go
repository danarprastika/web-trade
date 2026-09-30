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
