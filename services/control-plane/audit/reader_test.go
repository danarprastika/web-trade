package audit

import (
	"reflect"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/db/dbgen"
)

// accepted returns a fully sequenced, hashed, linked record for a partition.
//
// It goes through Append because that is the only way to obtain a record with a sequence and
// a predecessor link. Building one by hand means recomputing the chain by hand in every test,
// and a fixture that re-implements the code under test cannot fail for the right reason.
func accepted(t *testing.T, auditID, partition string) Record {
	t.Helper()
	c := NewChain()
	out, err := c.Append([]Record{stagedRecord(auditID, partition)})
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	return out[0]
}

// rowFor is the inverse of paramsFor, expressed at the driver boundary.
//
// This helper models the stored row rather than reading one back from PostgreSQL, and the
// modelling is still worth doing: it isolates the encode/decode pair from the database so a
// failure names which half is wrong. Where PostgreSQL alters a value on the way in, the
// alteration is written out below instead of being assumed away.
//
// It is no longer the only evidence. EV-046 recorded that no Go process had connected to a
// database, and this comment used to treat that as the reason nothing here could be asserted
// against a live one. EV-060 then found github.com/lib/pq v1.10.9 satisfies the pinning gate,
// the driver was adopted, and services/control-plane/integration now round-trips audit records
// through PostgreSQL 17.11 for real. This file is therefore the fast layer and the integration
// suite is the load-bearing one; where the two could disagree, the integration result wins.
func rowFor(r Record) dbgen.AuditRecord {
	return dbgen.AuditRecord{
		AuditID:       r.AuditID,
		Partition:     r.Partition,
		Sequence:      r.Sequence,
		ActorID:       r.ActorID,
		ActorType:     string(r.ActorType),
		Action:        r.Action,
		TargetType:    r.TargetType,
		TargetID:      r.TargetID,
		Environment:   r.Environment,
		MarketScope:   r.MarketScope,
		OccurredAtUtc: r.OccurredAt.Time(),
		RecordedAtUtc: r.RecordedAt.Time(),
		Reason:        r.Reason,
		CorrelationID: r.CorrelationID,
		CausationID:   r.CausationID,
		PolicyVersion: r.PolicyVersion,
		Result:        string(r.Result),
		BeforeDigest:  r.BeforeDigest,
		AfterDigest:   r.AfterDigest,
		PreviousHash:  append([]byte(nil), r.PreviousHash[:]...),
		RecordHash:    append([]byte(nil), r.RecordHash[:]...),
		SigningKeyID:  r.SigningKeyID,
		SchemaVersion: SchemaVersion,
	}
}

// timestamptzRoundTrip models what PostgreSQL's timestamptz does to a value on the way in.
//
// The column is declared timestamptz, whose resolution is one microsecond. The column type
// is not incidental and is not a detail of the driver: it is in the migration, and the
// migration is what any independent verifier of this evidence has to work from.
func timestamptzRoundTrip(v time.Time) time.Time { return v.Truncate(time.Microsecond) }

func applyDriverStorage(row dbgen.AuditRecord) dbgen.AuditRecord {
	row.OccurredAtUtc = timestamptzRoundTrip(row.OccurredAtUtc)
	row.RecordedAtUtc = timestamptzRoundTrip(row.RecordedAtUtc)
	return row
}

func TestEveryRecordFieldSurvivesTheStorageRoundTrip(t *testing.T) {
	// The mirror of TestEveryRecordFieldReachesTheDatabase. That test proves nothing is
	// dropped on the way to the database; this proves nothing is dropped on the way back.
	// A field dropped here produces a record whose hash does not match its content, which
	// Restore refuses as tampering - a correct diagnosis of a mapping bug.
	original := accepted(t, "aud-roundtrip", "tenant-a")
	original.Reason = "a reason with a quote \" and a backslash \\ in it"
	original.TargetType = "order"
	original.TargetID = "ord-1"
	original.MarketScope = "BTC/USDT"
	original.PolicyVersion = "v1"
	original.BeforeDigest = "before"
	original.AfterDigest = "after"
	original.SigningKeyID = "key-1"
	hashed, err := NewRecord(original)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}

	back, err := recordFrom(rowFor(hashed))
	if err != nil {
		t.Fatalf("recordFrom: %v", err)
	}

	// Compared by name against the struct rather than field by field, so a field added to
	// Record without a mapping fails here instead of quietly defaulting.
	want, got := reflect.TypeOf(hashed), reflect.TypeOf(back)
	if want != got {
		t.Fatalf("round-trip returned %s, want %s", got, want)
	}
	if !reflect.DeepEqual(hashed, back) {
		diff := firstDifference(hashed, back)
		t.Fatalf("a record changed across the storage round trip: %s", diff)
	}
	if back.ComputeHash() != hashed.RecordHash {
		t.Fatal("a record read back from storage does not hash to its stored value")
	}
}

func TestEveryRowFieldIsMapped(t *testing.T) {
	// Guards the other direction: a column in the schema that the reader ignores. A new
	// column added to the migration would otherwise be silently dropped on read, and would
	// first show up as a record that fails to verify with no hint as to why.
	//
	// Three columns have no same-named counterpart on Record and are listed explicitly
	// rather than waved through. Declaring the exceptions is the point: an exception that is
	// written down can be reviewed, whereas one that is implicit cannot be noticed.
	renamed := map[string]string{
		// The row carries a driver time; Record carries the canonical wrapper.
		"OccurredAtUtc": "OccurredAt",
		"RecordedAtUtc": "RecordedAt",
		// Carried per row in storage, compared against the package constant on read rather
		// than adopted, because the version is part of the hashed payload.
		"SchemaVersion": "",
	}
	rowType := reflect.TypeOf(dbgen.AuditRecord{})
	recordType := reflect.TypeOf(Record{})

	for i := 0; i < rowType.NumField(); i++ {
		f := rowType.Field(i)
		if f.Name == "RecordHash" {
			continue // the hash is the output of hashing the content, not part of it
		}
		target, renamedColumn := renamed[f.Name]
		if !renamedColumn {
			target = f.Name
		}
		if target == "" {
			continue
		}
		if _, ok := recordType.FieldByName(target); !ok {
			t.Errorf("row field %s maps to %s, which is not a field on Record", f.Name, target)
		}
	}
}

func TestAStoredRecordSurvivesPostgresStorage(t *testing.T) {
	// The test that matters most in this file. Restore recomputes the hash of every record
	// it loads and refuses the record when the recomputation does not match. That check is
	// only sound if the stored row carries enough information to reproduce the hash, which
	// means the round trip through PostgreSQL's own types has to be lossless.
	//
	// The timestamp here carries nanoseconds, because that is what a real caller has:
	// contracts.TimestampFrom normalises to UTC and does not truncate.
	nanoseconds := time.Date(2026, 9, 30, 12, 0, 0, 123456789, time.UTC)
	if nanoseconds.Nanosecond()%1000 == 0 {
		t.Fatal("the fixture must carry sub-microsecond precision or it proves nothing")
	}
	original := accepted(t, "aud-timestamp", "tenant-a")
	original.OccurredAt = TimestampFrom(nanoseconds)
	original.RecordedAt = TimestampFrom(nanoseconds.Add(time.Second))
	hashed, err := NewRecord(original)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}

	stored := applyDriverStorage(rowFor(hashed))
	back, err := recordFrom(stored)
	if err != nil {
		t.Fatalf("recordFrom: %v", err)
	}
	if back.RecordHash != hashed.RecordHash {
		t.Fatalf("PostgreSQL storage is lossy for this record: the hash of the value that "+
			"comes back is not the hash that was stored.\n  stored content: %s\n  "+
			"occurred_at_utc before: %s\n  occurred_at_utc after:  %s",
			hashed.CanonicalJSON(), hashed.OccurredAt.String(), back.OccurredAt.String())
	}
	// And the consequence, stated as behaviour rather than as arithmetic: Restore must be
	// able to load the record the sink just wrote.
	chain := NewChain()
	if err := chain.Restore([]Record{back}); err != nil {
		t.Fatalf("a record written by the sink cannot be read back by Restore: %v", err)
	}
}

func TestRecordFromRefusesARowWithAForeignSchemaVersion(t *testing.T) {
	original := accepted(t, "aud-version", "tenant-a")
	hashed, err := NewRecord(original)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}
	row := rowFor(hashed)
	row.SchemaVersion = SchemaVersion + 1

	if _, err := recordFrom(row); err == nil {
		t.Fatal("a row written under a different schema version must be refused; its content " +
			"hashes under a different canonical payload and cannot be re-derived here")
	} else if !strings.Contains(err.Error(), "schema_version") {
		t.Fatalf("the refusal should name the cause, got: %v", err)
	}
}

func TestRecordFromRefusesAMalformedHashColumn(t *testing.T) {
	original := accepted(t, "aud-hash", "tenant-a")
	hashed, err := NewRecord(original)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}
	for _, tc := range []struct {
		name  string
		apply func(*dbgen.AuditRecord)
	}{
		{"record_hash", func(r *dbgen.AuditRecord) { r.RecordHash = r.RecordHash[:31] }},
		{"record_hash empty", func(r *dbgen.AuditRecord) { r.RecordHash = nil }},
		{"record_hash long", func(r *dbgen.AuditRecord) { r.RecordHash = append(r.RecordHash, 0) }},
		{"previous_hash", func(r *dbgen.AuditRecord) { r.PreviousHash = r.PreviousHash[:16] }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			row := rowFor(hashed)
			tc.apply(&row)
			if _, err := recordFrom(row); err == nil {
				t.Fatal("a hash column of the wrong length must be refused; it cannot have " +
					"come from this writer, and padding or truncating it would produce a " +
					"record that verifies against nothing")
			}
		})
	}
}

func TestNewRecordCanonicalisesInstantPrecision(t *testing.T) {
	// Pins the fix itself, separately from the end-to-end test above, so that reverting it
	// produces a named failure rather than a confusing one somewhere else.
	//
	// The nanosecond value is built with contracts.ParseTimestamp rather than audit's own
	// TimestampFrom, and that is the whole point. A Record can be assembled from a parsed
	// Timestamp directly - the fixtures in this package do exactly that - so a fix placed in
	// TimestampFrom alone would leave this path unnormalised while the round-trip test still
	// passed, because that fixture goes through the converter.
	nanoseconds := contracts.MustParseTimestamp("2026-09-30T12:00:00.123456789Z")
	if nanoseconds.Time().Nanosecond() != 123456789 {
		t.Fatal("the fixture must carry sub-microsecond precision or it proves nothing")
	}
	r := fixtureRecord()
	r.OccurredAt = nanoseconds

	hashed, err := NewRecord(r)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}
	if got := hashed.OccurredAt.Time().Nanosecond(); got != 123456000 {
		t.Fatalf("canonical instant kept %d nanoseconds, want the microsecond resolution "+
			"timestamptz can hold (123456000)", got)
	}
	// The hash must be over the canonical form, not over the value handed in. Hashing the
	// original would make the stored row unreproducible.
	if hashed.ComputeHash() != hashed.RecordHash {
		t.Fatal("the hash is not over the returned record's own canonical form")
	}
	if hashed.ComputeHash() == r.ComputeHash() {
		t.Fatal("the nanosecond input and the canonical form hash identically, so this test " +
			"cannot tell whether normalisation happened")
	}
}

func TestRecordFromCopiesRatherAliasesDriverOwnedSlices(t *testing.T) {
	// The generated accessor hands back slices the driver may reuse between rows. If a
	// Record aliased one, the next scan step could overwrite the bytes of a record that has
	// already been stored, and a record whose hash changes after storage is precisely the
	// failure this package exists to make impossible.
	original := accepted(t, "aud-alias", "tenant-a")
	hashed, err := NewRecord(original)
	if err != nil {
		t.Fatalf("NewRecord: %v", err)
	}
	row := rowFor(hashed)
	back, err := recordFrom(row)
	if err != nil {
		t.Fatalf("recordFrom: %v", err)
	}
	before := back.RecordHash
	row.RecordHash[0] ^= 0xff // the driver reuses its buffer
	if back.RecordHash != before {
		t.Fatal("the record aliases the driver's slice: mutating the row changed the record")
	}
}

func firstDifference(want, got Record) string {
	w := reflect.ValueOf(want)
	g := reflect.ValueOf(got)
	for i := 0; i < w.NumField(); i++ {
		if !reflect.DeepEqual(w.Field(i).Interface(), g.Field(i).Interface()) {
			return w.Type().Field(i).Name
		}
	}
	return "none"
}
