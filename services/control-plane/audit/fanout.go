package audit

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

// FanOut writes every exported batch to more than one Sink.
//
// This exists because docs/22 section 4 requires the authoritative audit stream to be copied to a
// distinct account, project and region under object-lock/WORM retention, and one database is not
// independent of the process that writes to it. The Sink interface has always permitted a second
// destination, but permission is not capability: nothing assembled two, and no test could fail if
// the property were dropped, because nothing depended on it. A requirement stated only in a comment
// is a requirement nobody is checking.
//
// Independence is the whole point, so the type is built around the way that can be defeated. Two
// copies of the same database are one copy. A fan-out assembled from one sink would report success
// while giving the appearance of redundancy, which is worse than no redundancy because it is
// believed; NewFanOut therefore refuses fewer than two destinations. That is not a style rule. It is
// the difference between two independent copies and one destination written twice.
//
// It is also why nothing here dedups its arguments for you. Two handles onto one database are two
// non-nil interfaces and are not comparable in general, so a duplicate check would either be
// unsound or would compare interface identity and report two genuinely distinct pools to the same
// destination. The constructor cannot tell, and neither can the type. Independence is a property of
// how the caller wired the database, not of what was passed here, so the error message says so
// rather than implying the constructor verified it.

// FanOut is a Sink that writes each batch to every destination it was built with.
type FanOut struct {
	// destinations are the sinks to write, in the order they were supplied. Every one is
	// attempted on every export, including after an earlier one has failed.
	destinations []Sink
	// labels name each destination for the operator-facing error. A bare index in a message
	// about audit retention is not actionable, and the operator who has to act on this is the
	// one who knows which destination is which.
	labels []string
}

// NewFanOut returns a Sink writing every batch to all of sinks.
//
// At least two are required, and none may be nil. Both refusals are safety refusals rather than
// argument validation: one destination is not independent retention however it is labelled, and a
// nil destination would be dereferenced at export time, which is the moment the operator needs a
// working process most.
func NewFanOut(sinks ...Sink) (*FanOut, error) {
	if len(sinks) < 2 {
		return nil, errors.New("an audit fan-out needs at least two destinations; one sink is not " +
			"independent immutable retention, which is the property docs/22 section 4 requires " +
			"and the reason this type exists")
	}
	for i, s := range sinks {
		if s == nil {
			return nil, fmt.Errorf("audit fan-out destination %d is nil; a fan-out cannot report "+
				"retention it never delivered to, so a missing destination is refused at "+
				"construction rather than at the first export", i)
		}
	}
	labels := make([]string, len(sinks))
	for i := range sinks {
		labels[i] = "destination " + strconv.Itoa(i)
	}
	return &FanOut{destinations: append([]Sink(nil), sinks...), labels: labels}, nil
}

// NewLabeledFanOut returns a FanOut whose failures are reported under names the operator chose.
//
// A name is not trusted as an identifier; it only appears in an error, and it is never used to
// look anything up. That is why a caller may name two destinations the same thing without the
// fan-out refusing to build: the labels are prose for a human, and the dedup that would make
// naming them identical a correctness requirement would itself be the unsound check described on
// FanOut.
func NewLabeledFanOut(labels []string, sinks ...Sink) (*FanOut, error) {
	f, err := NewFanOut(sinks...)
	if err != nil {
		return nil, err
	}
	if len(labels) != len(sinks) {
		return nil, fmt.Errorf("got %d label(s) for %d audit fan-out destination(s); every "+
			"destination needs a name in a retention failure, because an operator cannot act on "+
			"'destination 1'", len(labels), len(sinks))
	}
	f.labels = append([]string(nil), labels...)
	return f, nil
}

// Export writes records to every destination, and reports failure unless all of them stored them.
//
// Three properties define this, and each of them is a choice rather than a default.
//
// Every destination is attempted, even after one has already failed. Stopping at the first failure
// would let a broken destination starve a healthy one: the second copy would never be written, so
// the system would report that retention lapsed precisely when it lapsed, and the one place the
// evidence still existed would be the one never written to. Independence is the mitigation for a
// destination being unavailable, and a fan-out that stops trying is not independent.
//
// An error is returned unless every destination stored the batch. The caller is Exporter, which
// releases the guard's backlog only when its sink returns nil, so returning nil for a batch that
// reached one of two destinations would release evidence that was never independently retained. The
// guard's backlog would then read zero while the second copy did not exist, which is the exact
// discrepancy this type is in the business of preventing.
//
// Every failed destination is named. A single error naming one of two failures reports a
// retention state the operator cannot reconstruct: they cannot tell whether the remaining copy is
// current, and they cannot tell which destination to look at.
//
// What this does not solve is stated rather than implied. A batch that reached one destination and
// then failed on another leaves the first holding a record the second does not, and retrying the
// whole fan-out writes it again to the first. Audit records are append-only and AppendAuditRecord
// has no ON CONFLICT, so that retry is a conflict rather than a no-op, and the caller must treat
// the returned error as naming a batch to investigate rather than a batch to blindly replay.
// Tracking per-destination progress across attempts belongs with the outbox in WI-121, which is
// where a durable record of what has been sent where belongs; until then this type is honest about
// the retry it cannot perform.
func (f *FanOut) Export(ctx context.Context, records []Record) error {
	if len(records) == 0 {
		return nil
	}

	var failed []string
	var firstErr error
	for i, sink := range f.destinations {
		if err := sink.Export(ctx, records); err != nil {
			failed = append(failed, f.labels[i])
			if firstErr == nil {
				firstErr = err
			}
		}
	}

	if len(failed) == 0 {
		return nil
	}

	// The count is in the message because the operator's first question is whether anything at
	// all was retained, and "destination 2 failed" does not answer it.
	return fmt.Errorf("audit fan-out wrote to %d of %d destination(s); %s failed to store the "+
		"batch: %w. Independent immutable retention is not satisfied for this batch, so the "+
		"guard's backlog has not been released",
		len(f.destinations)-len(failed), len(f.destinations), strings.Join(failed, ", "), firstErr)
}

// Compile-time assertion that a FanOut is usable wherever a Sink is required, which is the only
// reason this type could be mistaken for an improvement rather than a type.
var _ Sink = (*FanOut)(nil)
