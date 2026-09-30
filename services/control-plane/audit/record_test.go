package audit

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// fixtureRecord returns a fully populated record. Tests mutate copies of it.
func fixtureRecord() Record {
	return Record{
		AuditID:       "aud-0000000000000000001",
		Partition:     "tenant-a",
		Sequence:      1,
		ActorID:       "actor-0000000000000001",
		ActorType:     ActorHuman,
		Action:        "ORDER_APPROVED",
		TargetType:    "ORDER",
		TargetID:      "ord-0000000000000000001",
		Environment:   "SIMULATION",
		MarketScope:   "IDX",
		OccurredAt:    contracts.MustParseTimestamp("2026-09-28T10:00:00.000000000Z"),
		RecordedAt:    contracts.MustParseTimestamp("2026-09-28T10:00:01.000000000Z"),
		Reason:        "within pre-trade limit",
		CorrelationID: "cor-000000000000000001",
		CausationID:   "aud-0000000000000000000",
		PolicyVersion: "risk-policy-v3",
		Result:        ResultSucceeded,
		BeforeDigest:  "sha256:0000",
		AfterDigest:   "sha256:1111",
		PreviousHash:  GenesisHash,
		SigningKeyID:  "key-0001",
	}
}

func TestCanonicalJSONIsStableAcrossRepeatedCalls(t *testing.T) {
	r := fixtureRecord()
	first := r.CanonicalJSON()
	for i := 0; i < 100; i++ {
		if got := r.CanonicalJSON(); got != first {
			t.Fatalf("canonical form is not stable at iteration %d:\n first: %s\n  got: %s", i, first, got)
		}
	}
	if got := r.ComputeHash(); got != r.ComputeHash() {
		t.Fatalf("computed hash is not stable")
	}
}

// docs/22 section 3 requires the canonical serialization to be fixed. This pins the
// exact bytes so that a change to field order, escaping, or the schema version is a test
// failure rather than a silent re-hashing of the entire chain.
func TestCanonicalJSONIsPinnedToExactBytes(t *testing.T) {
	const want = `{"schema_version":"1","audit_id":"aud-0000000000000000001","partition":"tenant-a","sequence":"1",` +
		`"actor_id":"actor-0000000000000001","actor_type":"HUMAN","action":"ORDER_APPROVED","target_type":"ORDER",` +
		`"target_id":"ord-0000000000000000001","environment":"SIMULATION","market_scope":"IDX",` +
		`"occurred_at_utc":"2026-09-28T10:00:00.000000000Z","recorded_at_utc":"2026-09-28T10:00:01.000000000Z",` +
		`"reason":"within pre-trade limit","correlation_id":"cor-000000000000000001",` +
		`"causation_id":"aud-0000000000000000000","policy_version":"risk-policy-v3","result":"SUCCEEDED",` +
		`"before_digest":"sha256:0000","after_digest":"sha256:1111","previous_hash":"` +
		"0000000000000000000000000000000000000000000000000000000000000000" +
		`","signing_key_id":"key-0001"}`

	got := fixtureRecord().CanonicalJSON()
	if got != want {
		t.Fatalf("canonical form drifted:\n want: %s\n  got: %s", want, got)
	}
}

func TestCanonicalJSONIsValidJSON(t *testing.T) {
	var decoded map[string]string
	if err := json.Unmarshal([]byte(fixtureRecord().CanonicalJSON()), &decoded); err != nil {
		t.Fatalf("canonical form is not valid JSON: %v", err)
	}
	// record_hash must be absent: a record cannot contain its own hash.
	if _, present := decoded["record_hash"]; present {
		t.Fatal("record_hash must not appear in the canonical payload")
	}
	if len(decoded) != 22 {
		t.Fatalf("expected 22 canonical fields (schema_version + 21 record fields), got %d", len(decoded))
	}
}

// The record's own hash field must not influence the hash, or a record could be
// "verified" against a hash that was never computed from its content.
func TestRecordHashExcludesItself(t *testing.T) {
	r := fixtureRecord()
	clean := r.ComputeHash()

	// Setting a fabricated record_hash must not change the computed hash.
	r.RecordHash = Hash{0xAB}
	if got := r.ComputeHash(); got != clean {
		t.Fatal("computing the hash must ignore the existing record_hash field")
	}
}

func TestEveryFieldAffectsTheHash(t *testing.T) {
	base := fixtureRecord()
	baseHash := base.ComputeHash()

	mutations := map[string]func(*Record){
		"audit_id":       func(r *Record) { r.AuditID = "aud-0000000000000000002" },
		"partition":      func(r *Record) { r.Partition = "tenant-b" },
		"sequence":       func(r *Record) { r.Sequence = 2 },
		"actor_id":       func(r *Record) { r.ActorID = "actor-0000000000000002" },
		"actor_type":     func(r *Record) { r.ActorType = ActorAgent },
		"action":         func(r *Record) { r.Action = "ORDER_REFUSED" },
		"target_type":    func(r *Record) { r.TargetType = "FILL" },
		"target_id":      func(r *Record) { r.TargetID = "ord-0000000000000000002" },
		"environment":    func(r *Record) { r.Environment = "LIVE" },
		"market_scope":   func(r *Record) { r.MarketScope = "CRYPTO" },
		"occurred_at":    func(r *Record) { r.OccurredAt = contracts.MustParseTimestamp("2026-09-28T10:00:02.000000000Z") },
		"recorded_at":    func(r *Record) { r.RecordedAt = contracts.MustParseTimestamp("2026-09-28T10:00:09.000000000Z") },
		"reason":         func(r *Record) { r.Reason = "different reason" },
		"correlation_id": func(r *Record) { r.CorrelationID = "cor-000000000000000009" },
		"causation_id":   func(r *Record) { r.CausationID = "aud-0000000000000000009" },
		"policy_version": func(r *Record) { r.PolicyVersion = "risk-policy-v4" },
		"result":         func(r *Record) { r.Result = ResultRefused },
		"before_digest":  func(r *Record) { r.BeforeDigest = "sha256:2222" },
		"after_digest":   func(r *Record) { r.AfterDigest = "sha256:3333" },
		"previous_hash":  func(r *Record) { r.PreviousHash = Hash{0x01} },
		"signing_key_id": func(r *Record) { r.SigningKeyID = "key-0002" },
	}

	for name, mutate := range mutations {
		t.Run(name, func(t *testing.T) {
			r := base
			mutate(&r)
			if r.ComputeHash() == baseHash {
				t.Fatalf("mutating %s did not change the hash; the field is not covered by the canonical payload", name)
			}
		})
	}
}

// An absent field and an empty field must not serialise identically, or "no market
// scope" and "an empty market scope" would be indistinguishable to a verifier.
func TestEmptyAndAbsentFieldsAreBothPresent(t *testing.T) {
	r := fixtureRecord()
	r.MarketScope = ""
	decoded := r.CanonicalJSON()
	if !strings.Contains(decoded, `"market_scope":""`) {
		t.Fatalf("an empty field must still appear in the canonical form: %s", decoded)
	}
	var fields map[string]string
	if err := json.Unmarshal([]byte(decoded), &fields); err != nil {
		t.Fatalf("canonical form is not valid JSON: %v", err)
	}
	if _, present := fields["market_scope"]; !present {
		t.Fatal("empty field must be present in the canonical form")
	}
}

func TestTimestampCanonicalisesToUTC(t *testing.T) {
	// A record's hash must not depend on the host timezone it was written in. A
	// time.Time carrying an offset and the same instant in UTC must hash identically.
	//
	// Note that this is a property of TimestampFrom, not of parsing: contracts already
	// refuses a non-UTC timestamp at parse time, so an offset can only reach a record
	// through a time.Time handed in by a caller. That path is what is covered here.
	utc := fixtureRecord()
	offset := fixtureRecord()

	plusSeven := time.FixedZone("UTC+7", 7*60*60)
	instant := time.Date(2026, 9, 28, 17, 0, 1, 0, plusSeven)
	if got := instant.UTC().Format("2006-01-02T15:04:05.000000000Z"); got != utc.RecordedAt.String() {
		t.Fatalf("fixture mismatch: offset instant in UTC is %s, fixture has %s", got, utc.RecordedAt.String())
	}
	offset.RecordedAt = TimestampFrom(instant)

	if offset.RecordedAt.String() != utc.RecordedAt.String() {
		t.Fatalf("TimestampFrom did not normalise to UTC: %s vs %s", offset.RecordedAt, utc.RecordedAt)
	}
	if utc.ComputeHash() != offset.ComputeHash() {
		t.Fatal("the same instant expressed in two zones must produce the same hash")
	}
}

func TestParseTimestampRefusesNonUTC(t *testing.T) {
	// The contract layer rejects a non-UTC timestamp outright, so an offset cannot
	// reach a record by parsing. This pins that behaviour because the audit chain's
	// canonicalisation guarantee depends on it.
	if _, err := contracts.ParseTimestamp("2026-09-28T17:00:01.000000000+07:00"); err == nil {
		t.Fatal("parsing a non-UTC timestamp must fail")
	}
}

func TestParseHashRoundTrips(t *testing.T) {
	h := fixtureRecord().ComputeHash()
	parsed, err := ParseHash(h.Hex())
	if err != nil {
		t.Fatalf("ParseHash: %v", err)
	}
	if parsed != h {
		t.Fatalf("round trip changed the hash: %v vs %v", parsed, h)
	}
}

func TestParseHashRejectsMalformedInput(t *testing.T) {
	cases := map[string]string{
		"too short": "abcd",
		"too long":  strings.Repeat("a", 66),
		"not hex":   strings.Repeat("z", 64),
		"empty":     "",
	}
	for name, input := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := ParseHash(input); err == nil {
				t.Fatalf("ParseHash(%q) must fail", input)
			}
		})
	}
}

func TestGenesisHashRendersExplicitly(t *testing.T) {
	if !GenesisHash.IsZero() {
		t.Fatal("genesis hash must be zero")
	}
	if got := GenesisHash.String(); got != "genesis" {
		t.Fatalf("genesis hash must render explicitly, got %q", got)
	}
}
