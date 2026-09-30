package contracts

import (
	"errors"
	"testing"
	"time"
)

// TestParseTimestampCorpus covers every timestamp case in the shared conformance corpus.
func TestParseTimestampCorpus(t *testing.T) {
	accept := []string{
		"2026-09-28T10:17:46.123456789Z",
		"2026-09-28T10:17:46Z",
	}
	reject := []string{
		"2026-09-28T10:17:46+07:00",       // non-UTC offset
		"2026-09-28 10:17:46Z",            // space separator
		"2026-09-28T10:17:46",             // no zone at all
		"2026-13-01T00:00:00Z",            // month 13
		"2026-09-28T10:17:46.1234567890Z", // ten fraction digits
		"2026-09-28T24:00:00Z",            // hour 24
		"2026-09-28T10:60:00Z",            // minute 60
		"2026-09-32T10:00:00Z",            // day 32
		"2026-09-28t10:17:46z",            // lowercase t and z
		"2026-09-28T10:17:46.Z",           // empty fraction
		"",                                // empty
		"not-a-timestamp",
	}

	for _, s := range accept {
		if _, err := ParseTimestamp(s); err != nil {
			t.Errorf("ParseTimestamp(%q) = error %v, want accept", s, err)
		}
	}
	for _, s := range reject {
		if _, err := ParseTimestamp(s); err == nil {
			t.Errorf("ParseTimestamp(%q) = nil error, want reject", s)
		}
	}
}

// TestTimestampRejectsOffsetsThatTimeParseWouldAccept is the load-bearing test for this
// type.
//
// Probed against Go 1.26.2, time.Parse(time.RFC3339Nano, ...) ACCEPTS two of these three
// inputs: it accepts a numeric UTC offset, and it accepts a tenth fractional digit by
// truncating it. It rejects only the space separator. A binding that delegated to
// time.Parse would therefore fail the reject-non-utc-offset and
// reject-picosecond-fraction corpus cases, and would silently truncate a picosecond
// precision source timestamp rather than rejecting it.
func TestTimestampRejectsOffsetsThatTimeParseWouldAccept(t *testing.T) {
	// Inputs the standard library is known to accept. Each must still be rejected.
	acceptedByStdlib := []string{
		"2026-09-28T10:17:46+07:00",       // non-UTC offset: stored offsets are invalid
		"2026-09-28T10:17:46.1234567890Z", // 10th digit: silently truncated by time.Parse
	}
	for _, s := range acceptedByStdlib {
		if _, err := time.Parse(time.RFC3339Nano, s); err != nil {
			t.Logf("note: time.Parse now rejects %q; the explicit pattern is still "+
				"retained because the contract, not the standard library, is the authority", s)
		}
		if _, err := ParseTimestamp(s); err == nil {
			t.Errorf("ParseTimestamp(%q) = nil error, want reject", s)
		}
	}

	// The space separator is rejected by both, and is pinned as defence in depth.
	if _, err := ParseTimestamp("2026-09-28 10:17:46Z"); err == nil {
		t.Error("ParseTimestamp(space separator) = nil error, want reject")
	}
}

func TestTimestampRejectsImpossibleCalendarDate(t *testing.T) {
	// The pattern admits 2026-02-30; the calendar does not. The pattern alone is not
	// sufficient, so time.Parse is consulted for real-calendar validation.
	if _, err := ParseTimestamp("2026-02-30T00:00:00Z"); err == nil {
		t.Error("ParseTimestamp(2026-02-30) = nil error, want reject")
	}
}

func TestTimestampEmitsNineFractionDigits(t *testing.T) {
	// The schema says producers SHOULD emit nine digits, so a short input is normalised
	// to nanosecond precision on output.
	ts := MustParseTimestamp("2026-09-28T10:17:46Z")
	if got := ts.String(); got != "2026-09-28T10:17:46.000000000Z" {
		t.Errorf("String() = %q, want 2026-09-28T10:17:46.000000000Z", got)
	}
	ts = MustParseTimestamp("2026-09-28T10:17:46.123456789Z")
	if got := ts.String(); got != "2026-09-28T10:17:46.123456789Z" {
		t.Errorf("String() = %q, want the input unchanged", got)
	}
	// The nanosecond value must survive, not be truncated by formatting.
	if got := ts.Time().Nanosecond(); got != 123456789 {
		t.Errorf("Nanosecond() = %d, want 123456789", got)
	}
}

func TestTimestampIsAlwaysUTC(t *testing.T) {
	// A non-UTC time.Time is normalised on the way in; the stored value carries no offset.
	loc := time.FixedZone("plus7", 7*3600)
	ts := TimestampFrom(time.Date(2026, 9, 28, 17, 17, 46, 0, loc))
	if got := ts.String(); got != "2026-09-28T10:17:46.000000000Z" {
		t.Errorf("String() = %q, want the UTC-normalised 10:17:46", got)
	}
	if ts.Time().Location() != time.UTC {
		t.Error("stored location is not UTC; offsets must never be persisted")
	}
}

func TestTimestampOrdering(t *testing.T) {
	early := MustParseTimestamp("2026-09-28T10:00:00Z")
	late := MustParseTimestamp("2026-09-28T10:00:01Z")
	if !early.Before(late) {
		t.Error("early.Before(late) = false, want true")
	}
	if !late.After(early) {
		t.Error("late.After(early) = false, want true")
	}
	if !early.Equal(MustParseTimestamp("2026-09-28T10:00:00Z")) {
		t.Error("Equal on identical instants = false, want true")
	}
}

func TestTimestampSkewWindow(t *testing.T) {
	// Clock drift is a first-class signal (docs/08); the predicate is what lets a caller
	// mark a feed unhealthy rather than silently trusting an out-of-window source.
	reference := MustParseTimestamp("2026-09-28T10:00:00Z")
	within := MustParseTimestamp("2026-09-28T10:00:02Z")
	outside := MustParseTimestamp("2026-09-28T10:00:30Z")

	if !within.IsWithinSkew(reference, 5*time.Second) {
		t.Error("2s drift reported outside a 5s window")
	}
	if outside.IsWithinSkew(reference, 5*time.Second) {
		t.Error("30s drift reported inside a 5s window")
	}
	// Drift in the other direction counts too: a source running fast is equally suspect.
	before := MustParseTimestamp("2026-09-28T09:59:30Z")
	if before.IsWithinSkew(reference, 5*time.Second) {
		t.Error("30s negative drift reported inside a 5s window")
	}
}

func TestTimestampZeroValueIsUnset(t *testing.T) {
	var ts Timestamp
	if !ts.IsZero() {
		t.Error("zero value Timestamp reports IsZero() = false")
	}
}

func TestParseTimestampErrorWrapsSentinel(t *testing.T) {
	_, err := ParseTimestamp("nope")
	if !errors.Is(err, ErrInvalidTimestamp) {
		t.Errorf("error %v does not wrap ErrInvalidTimestamp", err)
	}
}
