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

// What the escalation does to Clear, which the boundedness test above never exercises.
//
// It is stated here rather than left implicit because it is the one place the escalation changes
// an existing safety behaviour. Clear refuses while a backlog halt has unexported evidence, and
// that refusal is keyed on the cause, not on the backlog itself. Escalating rewrites the cause
// from backlog to integrity, so Clear becomes permitted with evidence still unexported - by
// design, per Clear's own comment: the finding an operator must review is the chain break, and
// telling them to go and fix an unrelated export backlog first would be telling them to go and
// clear the finding later.
//
// Nothing asserted that before. TestClearRefusesWhileTheBacklogIsOutstanding reaches Clear with
// only a backlog cause, and TestClearIsPermittedForAnIntegrityHaltWhileTheBacklogIsOutstanding
// sets the integrity cause with a direct Halt rather than through the escalation. Neither sets it
// both ways, so the combination the escalation uniquely creates - integrity cause AND outstanding
// backlog - was untested in either direction. A mutation changing the cause test in
// TestEscalatingToIntegrityStillLeavesTheBacklogBounded would leave all three green.
//
// The residual risk is what this test now pins as well: the latch is released, so Allow
// unblocks, and the backlog's boundedness rests entirely on Accept continuing to refuse - and
// then re-halting. If a future change made Accept permissive after a clear, or left it refusing
// without re-latching, this fails rather than letting a full backlog pass unnoticed while the
// guard reports itself healthy.
func TestClearingAnEscalatedHaltIsPermittedAndTheBacklogStillRefuses(t *testing.T) {
	g, err := NewGuard(2)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	// Fill the backlog. Accept now refuses, so the guard is halted for evidence reasons.
	if err := g.Accept(2); err != nil {
		t.Fatalf("Accept: %v", err)
	}
	if err := g.Accept(1); err == nil {
		t.Fatal("exceeding the limit must be refused")
	}

	// A chain break escalates the cause, and with it Clear's terms.
	g.ObserveVerification(Verification{
		OK:       false,
		Findings: []Finding{{Kind: FindingTamper, Partition: "tenant-a", Sequence: 3, Detail: "altered"}},
	})
	if cause, _ := g.Reason(); cause != causeSev1Integrity {
		t.Fatalf("expected the cause to escalate to %q, got %q", causeSev1Integrity, cause)
	}

	// Permitted, with evidence still outstanding. This is the behaviour under test, not an
	// accident: the operator has reviewed a chain break and the backlog is a separate problem.
	if err := g.Clear(); err != nil {
		t.Fatalf("clearing an escalated integrity halt must be permitted, got: %v. If this now "+
			"refuses, the escalation has started blocking operators on backlog terms it was meant "+
			"to stop them being blocked by", err)
	}
	if err := g.Allow(OpRiskIncreasing); err != nil {
		t.Fatalf("a cleared guard must not refuse risk-increasing work, got: %v", err)
	}

	// The backlog did not go away when the latch was released, and boundedness is Accept's job
	// rather than the latch's. This is the property that makes the clear safe.
	if got := g.Pending(); got != 2 {
		t.Fatalf("clearing must not discard the backlog, pending is %d, expected 2", got)
	}
	if err := g.Accept(1); err == nil {
		t.Fatal("a full backlog must still refuse work after an escalated halt is cleared; the " +
			"boundedness was supposed to outlive the latch")
	}

	// And refusing re-latches the guard on the backlog terms. This is stronger than boundedness
	// alone and is the reason the escalation is safe: the clear releases the chain-break halt, but
	// the first record that does not fit puts the guard straight back into the state it would have
	// been in without any escalation. The state a caller can reach by escalating, clearing and
	// then working is the state it would have reached by filling the backlog and clearing it - so
	// there is no sequence of ordinary operations that ends with a full backlog and a healthy
	// guard.
	if !g.Halted() {
		t.Fatal("a refused Accept must re-halt the guard; releasing the latch must not leave a " +
			"full backlog enforced by nothing")
	}
	if cause, _ := g.Reason(); cause != causeEvidenceBacklog {
		t.Fatalf("after an escalated halt is cleared, a refused Accept must re-halt on %q so the "+
			"backlog regains its own terms, got %q", causeEvidenceBacklog, cause)
	}
	if err := g.Clear(); err == nil {
		t.Fatal("Clear must refuse again once the backlog cause is back and evidence is " +
			"outstanding; the earlier permitted clear applied to the integrity finding only")
	}
}

// The counterpart, adjacent so the pair reads together: a halt that is *only* about the backlog
// still refuses to clear, and the refusal has to name the backlog rather than the halt in general.
//
// This is not a duplicate of TestClearRefusesWhileTheBacklogIsOutstanding in sink_test.go. That
// test reaches Clear through the production path to prove the wiring; this one is here so the
// escalation test above cannot be read as "integrity halts are clearable" without the condition
// that makes them so.
func TestABacklogHaltAloneStillRefusesToClearWhileEvidenceIsUnexported(t *testing.T) {
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

	if cause, _ := g.Reason(); cause != causeEvidenceBacklog {
		t.Fatalf("a full backlog with no chain break must report %q, got %q", causeEvidenceBacklog,
			cause)
	}
	if err := g.Clear(); err == nil {
		t.Fatal("clearing a backlog halt with unexported evidence must be refused; the next " +
			"record would re-halt it and the clear would accomplish nothing")
	}
	if !g.Halted() {
		t.Fatal("a refused Clear must leave the guard halted")
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

// Accept(0) is the one input that makes the guard's accounting depend on the latch without
// changing any of it, and it was the only input with no test. It is pinned here because the
// answer is a decision rather than a consequence, and nothing else in the file states it.
//
// Accept is not the latch. Reading Accept, the only thing standing between a halted guard and
// an Accept that returns nil is the limit check, so Accept(0) - and Accept(n) for any n under
// the limit - succeeds while halted. That is intended: Accept's contract (guard.go) is that it
// never discards and refuses only when full, so the backlog stays bounded even while trading is
// stopped. The latch is enforced by Allow, which is the thing that classifies an operation.
//
// The risk this test forecloses is the opposite reading - "halted means Accept refuses" - which
// would look more defensive and would be a bug. It would mean an unexported backlog could never
// grow while a SEV-1 halt was in force, so the records already accepted when the chain broke
// would sit in memory with no accounting path able to grow the buffer that has to hold them. The
// guard would be refusing to record a debt it had already incurred.
func TestAcceptingZeroRecordsNeitherUnhaltsNorDowngradesTheFinding(t *testing.T) {
	g, err := NewGuard(10)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	g.ObserveVerification(Verification{
		OK:       false,
		Findings: []Finding{{Kind: FindingTamper, Partition: "tenant-a", Sequence: 7}},
	})
	if !g.Halted() {
		t.Fatal("a SEV-1 integrity failure must halt the guard")
	}

	if err := g.Accept(0); err != nil {
		t.Fatalf("Accept(0) must not be refused by the latch: %v", err)
	}
	if g.Pending() != 0 {
		t.Fatalf("Accept(0) must not change the backlog, got %d", g.Pending())
	}

	// The finding has to survive the no-op. Accept does not touch the latch, so this is really
	// asserting that nothing else quietly reached in and reset it - which is the shape of bug
	// this edge is most likely to hide.
	if !g.Halted() {
		t.Fatal("Accept(0) must leave the guard halted")
	}
	cause, reason := g.Reason()
	if cause != causeSev1Integrity {
		t.Fatalf("Accept(0) must leave the recorded cause at %q, got %q", causeSev1Integrity, cause)
	}
	if reason == "" {
		t.Fatal("the recorded reason must survive Accept(0); an empty reason is how a finding " +
			"gets cleared without anyone reviewing it")
	}

	// Clear still reads the escalated cause, so it clears on integrity terms. An empty backlog
	// is not what authorises that - the cause is - and this distinguishes the two: a backlog
	// halt at pending 0 is equally clearable, so the assertions above are the ones carrying
	// the weight.
	if err := g.Clear(); err != nil {
		t.Fatalf("Clear after an escalated halt with an empty backlog: %v", err)
	}
	if g.Halted() {
		t.Fatal("Clear must release the latch")
	}
	if cause, _ := g.Reason(); cause != "" {
		t.Fatalf("Clear must empty the recorded cause, got %q", cause)
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
