package audit

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
)

// The tests here exist because the Sink interface has always claimed the same chain can be
// exported to more than one destination, and nothing tested that claim. A second database is the
// mitigation docs/22 section 4 requires for one database not being independent of the process that
// writes to it, so the capability that makes independence possible was asserted only in a comment.
// Dropping it would have failed nothing.

// recordingSink is one destination, keeping whatever it was handed.
type recordingSink struct {
	mu     sync.Mutex
	stored [][]Record
	err    error
	calls  int
}

func (s *recordingSink) Export(_ context.Context, records []Record) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	if s.err != nil {
		return s.err
	}
	// Copied, because a fan-out hands the same slice to every destination and a test that
	// asserted on a later mutation of it would be asserting on its own fixture.
	s.stored = append(s.stored, append([]Record(nil), records...))
	return nil
}

func (s *recordingSink) batches() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.stored)
}

func (s *recordingSink) callCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

// A fan-out of one is not independent retention. Allowing it would let a caller believe they had
// two copies while having one, which is worse than admitting a single sink.
func TestAFanOutNeedsAtLeastTwoDestinations(t *testing.T) {
	if _, err := NewFanOut(&recordingSink{}); err == nil {
		t.Fatal("a single destination must be refused; it is not independent retention")
	}
	if _, err := NewFanOut(); err == nil {
		t.Fatal("a fan-out with no destinations must be refused")
	}
}

func TestAFanOutRefusesANilDestination(t *testing.T) {
	if _, err := NewFanOut(&recordingSink{}, nil); err == nil {
		t.Fatal("a nil destination must be refused at construction, not dereferenced at export")
	}
}

// The point of the whole type: every destination holds the batch.
func TestEveryDestinationReceivesEveryRecord(t *testing.T) {
	a, b, c := &recordingSink{}, &recordingSink{}, &recordingSink{}
	fan, err := NewFanOut(a, b, c)
	if err != nil {
		t.Fatalf("NewFanOut: %v", err)
	}

	records := exportedBatch(t, "tenant-a", 3)
	if err := fan.Export(context.Background(), records); err != nil {
		t.Fatalf("Export: %v", err)
	}

	for i, s := range []*recordingSink{a, b, c} {
		if s.batches() != 1 {
			t.Fatalf("destination %d stored %d batch(es), expected 1", i, s.batches())
		}
		if got := len(s.stored[0]); got != len(records) {
			t.Fatalf("destination %d stored %d record(s), expected %d", i, got, len(records))
		}
		for j, rec := range s.stored[0] {
			if rec.AuditID != records[j].AuditID {
				t.Fatalf("destination %d record %d is %q, expected %q: the chain order must be "+
					"the same at every destination or the integrity verifier is comparing one "+
					"archive against another", i, j, rec.AuditID, records[j].AuditID)
			}
		}
	}
}

// A broken destination must not starve a healthy one. Stopping at the first failure would mean
// the healthy copy is never written at the exact moment retention lapsed, which is the moment it
// matters most.
func TestAFailingDestinationDoesNotStopTheOthers(t *testing.T) {
	broken := &recordingSink{err: errors.New("independent account unreachable")}
	healthyA, healthyB := &recordingSink{}, &recordingSink{}
	fan, err := NewFanOut(broken, healthyA, healthyB)
	if err != nil {
		t.Fatalf("NewFanOut: %v", err)
	}

	records := exportedBatch(t, "tenant-a", 2)
	if err := fan.Export(context.Background(), records); err == nil {
		t.Fatal("Export must report failure when a destination did not store the batch")
	}

	if healthyA.batches() != 1 || healthyB.batches() != 1 {
		t.Fatalf("the healthy destinations stored %d and %d batches, expected 1 each: a fan-out "+
			"that stops at the first failure never writes the copies that would have mitigated it",
			healthyA.batches(), healthyB.batches())
	}
	if broken.batches() != 0 {
		t.Fatal("the failing destination must not have stored anything")
	}
}

// The operator cannot act on a message naming one of two failures, because they cannot tell
// whether the other copy is current.
func TestEveryFailedDestinationIsNamed(t *testing.T) {
	a := &recordingSink{err: errors.New("first is down")}
	b := &recordingSink{}
	c := &recordingSink{err: errors.New("third is down")}
	fan, err := NewFanOut(a, b, c)
	if err != nil {
		t.Fatalf("NewFanOut: %v", err)
	}

	err = fan.Export(context.Background(), exportedBatch(t, "tenant-a", 1))
	if err == nil {
		t.Fatal("Export must fail when two of three destinations did not store the batch")
	}
	msg := err.Error()
	for _, want := range []string{"destination 0", "destination 2"} {
		if !strings.Contains(msg, want) {
			t.Fatalf("the error must name %s so the operator knows what to look at, got: %s", want, msg)
		}
	}
	if strings.Contains(msg, "destination 1") {
		t.Fatalf("the error named a destination that succeeded, which would send the operator to "+
			"investigate a healthy copy: %s", msg)
	}
	// The count is what answers "was anything retained at all".
	if !strings.Contains(msg, "1 of 3") {
		t.Fatalf("the error must state how many destinations stored the batch, got: %s", msg)
	}
}

// The reason Export fails at all: Exporter releases the guard's backlog only when its sink
// returns nil, so a nil here would report evidence as independently retained when one of two
// copies never received it.
func TestBacklogIsNotReleasedWhileAnyDestinationHasNotStoredTheBatch(t *testing.T) {
	guard, err := NewGuard(10)
	if err != nil {
		t.Fatalf("NewGuard: %v", err)
	}
	if err := guard.Accept(2); err != nil {
		t.Fatalf("Accept: %v", err)
	}

	healthy := &recordingSink{}
	broken := &recordingSink{err: errors.New("object-lock bucket unavailable")}
	fan, err := NewFanOut(healthy, broken)
	if err != nil {
		t.Fatalf("NewFanOut: %v", err)
	}
	exp, err := NewExporter(guard, fan)
	if err != nil {
		t.Fatalf("NewExporter: %v", err)
	}

	if err := exp.Export(context.Background(), exportedBatch(t, "tenant-a", 2)); err == nil {
		t.Fatal("export must report failure while a destination has not stored the batch")
	}
	if got := guard.Pending(); got != 2 {
		t.Fatalf("pending is %d, expected 2: the backlog was released for evidence that only one "+
			"of two independent copies holds, which is the discrepancy this type exists to stop", got)
	}
	if healthy.batches() != 1 {
		t.Fatalf("the destination that did store the batch holds %d, expected 1", healthy.batches())
	}

	// And with both destinations working, the backlog is released.
	broken.err = nil
	if err := exp.Export(context.Background(), exportedBatch(t, "tenant-a", 2)); err != nil {
		t.Fatalf("Export once both destinations work: %v", err)
	}
	if got := guard.Pending(); got != 0 {
		t.Fatalf("pending is %d, expected 0 once every destination stored the batch", got)
	}
}

// Labels exist so a retention failure names something the operator recognises. A mismatched count
// would produce an error naming the wrong destination, which is worse than a default index.
func TestLabelsMustCoverEveryDestination(t *testing.T) {
	if _, err := NewLabeledFanOut([]string{"only-one"}, &recordingSink{}, &recordingSink{}); err == nil {
		t.Fatal("a label count that does not match the destination count must be refused")
	}
	fan, err := NewLabeledFanOut([]string{"primary-eu", "coldline-eu"}, &recordingSink{},
		&recordingSink{err: errors.New("coldline unreachable")})
	if err != nil {
		t.Fatalf("NewLabeledFanOut: %v", err)
	}
	err = fan.Export(context.Background(), exportedBatch(t, "tenant-a", 1))
	if err == nil {
		t.Fatal("Export must fail when a destination did not store the batch")
	}
	if !strings.Contains(err.Error(), "coldline-eu") {
		t.Fatalf("the error must name the operator's own label, got: %s", err)
	}
	if strings.Contains(err.Error(), "primary-eu") {
		t.Fatalf("the error named a destination that succeeded: %s", err)
	}
}

func TestAnEmptyBatchTouchesNoDestination(t *testing.T) {
	a, b := &recordingSink{}, &recordingSink{}
	fan, err := NewFanOut(a, b)
	if err != nil {
		t.Fatalf("NewFanOut: %v", err)
	}
	if err := fan.Export(context.Background(), nil); err != nil {
		t.Fatalf("an empty batch must not fail: %v", err)
	}
	if a.callCount() != 0 || b.callCount() != 0 {
		t.Fatalf("an empty batch called destination(s) %d and %d times, expected none",
			a.callCount(), b.callCount())
	}
}
