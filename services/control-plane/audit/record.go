package audit

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strconv"
	"strings"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// SchemaVersion is the canonical serialization version.
//
// docs/22 section 3 requires the canonical serialization and schema version to be fixed
// and tested. It is part of the hashed payload, so a record written under a different
// version cannot be silently re-encoded into a matching hash: changing the version
// changes every subsequent hash, and the chain break is detected rather than absorbed.
const SchemaVersion = 1

// HashLength is the byte length of a SHA-256 digest.
const HashLength = sha256.Size

// Hash is a SHA-256 digest. It is a fixed-size array rather than a hex string so that a
// zero hash, an unset value, and a malformed value cannot be confused for one another.
type Hash [HashLength]byte

// GenesisHash is the previous_hash of the first record in a partition. It is a fixed,
// non-empty value so that "links to nothing" is a single explicit state rather than an
// ambiguous empty string that a record could also carry.
var GenesisHash = Hash{}

// Hex returns the lowercase hex encoding.
func (h Hash) Hex() string { return hex.EncodeToString(h[:]) }

// IsZero reports whether h is the zero digest.
func (h Hash) IsZero() bool { return h == Hash{} }

// String implements fmt.Stringer. It renders the genesis value explicitly so that a
// zero hash in a log line is distinguishable from a hash that failed to render.
func (h Hash) String() string {
	if h.IsZero() {
		return "genesis"
	}
	return h.Hex()
}

// ParseHash decodes a 64-character lowercase hex digest.
func ParseHash(s string) (Hash, error) {
	var h Hash
	if len(s) != HashLength*2 {
		return h, reject(contracts.CodeValidation, "hash must be %d hex characters, got %d", HashLength*2, len(s))
	}
	raw, err := hex.DecodeString(s)
	if err != nil {
		return h, reject(contracts.CodeValidation, "hash is not valid lowercase hex: %v", err)
	}
	copy(h[:], raw)
	return h, nil
}

// ActorType is the platform's closed set of actor classes, re-exported from contracts.
//
// It is an alias, not a second declaration. The audit chain previously declared its own
// set, which was a defect: two closed sets drift, and an audit record naming an actor
// kind the rest of the platform does not recognise is evidence of a caller that the rest
// of the platform would have refused. One set, defined once, is the only version that
// keeps the audit chain and the OMS telling the same story.
type ActorType = contracts.ActorType

// The actor classes, re-exported so callers of this package need not import contracts
// only to name one.
const (
	ActorHuman      = contracts.ActorHuman
	ActorService    = contracts.ActorService
	ActorAgent      = contracts.ActorAgent
	ActorStrategy   = contracts.ActorStrategy
	ActorSystem     = contracts.ActorSystem
	ActorBreakGlass = contracts.ActorBreakGlass
)

// Result is the outcome recorded on an audit record.
type Result string

// The closed set of outcomes. A record with no result is not evidence of a decision.
const (
	ResultSucceeded Result = "SUCCEEDED"
	ResultRefused   Result = "REFUSED"
	ResultFailed    Result = "FAILED"
	ResultPartial   Result = "PARTIAL"
	ResultUnknown   Result = "UNKNOWN"
)

var results = map[Result]bool{
	ResultSucceeded: true,
	ResultRefused:   true,
	ResultFailed:    true,
	ResultPartial:   true,
	ResultUnknown:   true,
}

// IsValid reports whether the result is in the closed set.
func (r Result) IsValid() bool { return results[r] }

// Record is one audit event, carrying the schema docs/22 section 2 requires.
//
// Every field is present in the canonical form even when empty. Omitting an empty field
// would mean a record with a populated field and one with an absent one could serialise
// identically and therefore hash identically, so "this record says nothing about the
// market scope" and "this record has no market scope" would become indistinguishable.
type Record struct {
	// AuditID is the stable identity of this record.
	AuditID string `json:"audit_id"`
	// Partition is the tenant or owner scope. Records are chained within a partition,
	// not globally, so one tenant's activity cannot be used to reason about another's.
	Partition string `json:"partition"`
	// Sequence is the monotonic position within Partition. The first record in a
	// partition has sequence 1; zero is not a valid sequence.
	Sequence int64 `json:"sequence"`
	// ActorID identifies who performed the action.
	ActorID string `json:"actor_id"`
	// ActorType classifies the actor.
	ActorType ActorType `json:"actor_type"`
	// Action is what was attempted.
	Action string `json:"action"`
	// TargetType and TargetID name what was acted on.
	TargetType string `json:"target_type"`
	TargetID   string `json:"target_id"`
	// Environment is the deployment environment the action occurred in.
	Environment string `json:"environment"`
	// MarketScope is the market scope the action is confined to.
	MarketScope string `json:"market_scope"`
	// OccurredAt is when the action itself happened, which is not the same instant as
	// when it was recorded. The gap between them is what reveals a delayed write.
	OccurredAt contracts.Timestamp `json:"occurred_at_utc"`
	// RecordedAt is when the record was written.
	RecordedAt contracts.Timestamp `json:"recorded_at_utc"`
	// Reason is the justification for the action, required for anything privileged.
	Reason string `json:"reason"`
	// CorrelationID groups records belonging to one request or workflow.
	CorrelationID string `json:"correlation_id"`
	// CausationID names the record that caused this one.
	CausationID string `json:"causation_id"`
	// PolicyVersion is the version of the policy that was evaluated.
	PolicyVersion string `json:"policy_version"`
	// Result is the outcome.
	Result Result `json:"result"`
	// BeforeDigest and AfterDigest are keyed digests of the affected state, not the state
	// itself. docs/22 section 2 requires sensitive values to be referenced by digest
	// rather than copied into the audit payload.
	BeforeDigest string `json:"before_digest"`
	AfterDigest  string `json:"after_digest"`
	// PreviousHash links to the preceding record in the same partition.
	PreviousHash Hash `json:"previous_hash"`
	// SigningKeyID names the key that signed the checkpoint covering this record.
	SigningKeyID string `json:"signing_key_id"`
	// RecordHash is the hash of the canonical payload. It is excluded from that payload,
	// because a record cannot contain its own hash.
	RecordHash Hash `json:"record_hash"`
}

// canonicalField is one key/value pair in the canonical payload, in fixed order.
//
// The order is written out literally rather than taken from struct declaration order or
// map iteration order. Both of those are technically deterministic today and neither is
// a contract, so a refactor or a language change could silently alter every hash in the
// chain. The order here is part of the format, and the format is versioned.
type canonicalField struct {
	key   string
	value string
}

// canonicalFields returns the hashed payload's fields in fixed order.
//
// record_hash is absent by construction: it is the output, not an input. Every other
// field is present, including empty ones, for the reason given on Record.
func (r Record) canonicalFields() []canonicalField {
	return []canonicalField{
		{"schema_version", strconv.Itoa(SchemaVersion)},
		{"audit_id", r.AuditID},
		{"partition", r.Partition},
		{"sequence", strconv.FormatInt(r.Sequence, 10)},
		{"actor_id", r.ActorID},
		{"actor_type", string(r.ActorType)},
		{"action", r.Action},
		{"target_type", r.TargetType},
		{"target_id", r.TargetID},
		{"environment", r.Environment},
		{"market_scope", r.MarketScope},
		{"occurred_at_utc", r.OccurredAt.String()},
		{"recorded_at_utc", r.RecordedAt.String()},
		{"reason", r.Reason},
		{"correlation_id", r.CorrelationID},
		{"causation_id", r.CausationID},
		{"policy_version", r.PolicyVersion},
		{"result", string(r.Result)},
		{"before_digest", r.BeforeDigest},
		{"after_digest", r.AfterDigest},
		{"previous_hash", r.PreviousHash.Hex()},
		{"signing_key_id", r.SigningKeyID},
	}
}

// CanonicalJSON renders the hashed payload.
//
// Field values are escaped with encoding/json, which is deterministic for a given
// input, and the surrounding structure is assembled here so that key order is a
// property of this file rather than of the standard library's internals. The output has
// no insignificant whitespace, so it is also safe to store as the audit payload.
func (r Record) CanonicalJSON() string {
	fields := r.canonicalFields()
	var b []byte
	b = append(b, '{')
	for i, f := range fields {
		if i > 0 {
			b = append(b, ',')
		}
		b = appendQuoted(b, f.key)
		b = append(b, ':')
		b = appendQuoted(b, f.value)
	}
	b = append(b, '}')
	return string(b)
}

// appendQuoted appends a JSON string, using encoding/json's escaping rules.
//
// json.Marshal on a string cannot fail, and it is the only escaping implementation
// worth trusting; hand-rolled escaping is where canonicalisation bugs live.
func appendQuoted(dst []byte, s string) []byte {
	encoded, err := json.Marshal(s)
	if err != nil {
		// Unreachable: encoding every Go string is total. Appending the empty string
		// keeps the output well-formed rather than emitting a truncated document.
		return append(dst, '"', '"')
	}
	return append(dst, encoded...)
}

// ComputeHash returns the record's hash over its canonical payload.
func (r Record) ComputeHash() Hash {
	return Hash(sha256.Sum256([]byte(r.CanonicalJSON())))
}

// Validate checks the record's own fields, before it is chained.
//
// It refuses a record that could never be attributed or ordered, because such a record
// is not evidence: an unknown actor type, a missing result, a non-positive sequence, or
// a timestamp that has not been set.
func (r Record) Validate() error {
	if err := r.validateFields(); err != nil {
		return err
	}
	if r.Sequence < 1 {
		return reject(contracts.CodeValidation, "sequence must be >= 1, got %d", r.Sequence)
	}
	return nil
}

// validateFields checks every field except the sequence.
//
// The sequence is excluded because the chain assigns it. A record arriving at Append is
// legitimately unsequenced, and a candidate's own claim to a sequence is verified against
// the partition's state rather than checked for plausibility. The full check still runs
// on the record as written, once the chain has placed it.
func (r Record) validateFields() error {
	if strings.TrimSpace(r.AuditID) == "" {
		return reject(contracts.CodeValidation, "audit_id is required")
	}
	if strings.TrimSpace(r.Partition) == "" {
		return reject(contracts.CodeValidation, "partition is required; a record cannot be chained without one")
	}
	if strings.TrimSpace(r.ActorID) == "" {
		return reject(contracts.CodeValidation, "actor_id is required; an unattributable record is not evidence")
	}
	if !r.ActorType.Valid() {
		return reject(contracts.CodeValidation, "actor_type %q is not in the closed set", r.ActorType)
	}
	if strings.TrimSpace(r.Action) == "" {
		return reject(contracts.CodeValidation, "action is required")
	}
	if strings.TrimSpace(r.Environment) == "" {
		return reject(contracts.CodeValidation, "environment is required; evidence cannot be placed without one")
	}
	if !r.Result.IsValid() {
		return reject(contracts.CodeValidation, "result %q is not in the closed set", r.Result)
	}
	if r.OccurredAt.IsZero() {
		return reject(contracts.CodeValidation, "occurred_at_utc is required")
	}
	if r.RecordedAt.IsZero() {
		return reject(contracts.CodeValidation, "recorded_at_utc is required")
	}
	return nil
}

// NewRecord builds a validated record with its hash computed.
//
// The caller supplies the sequence and previous hash; this function does not invent
// them, because they are properties of the partition's state rather than of the event.
// Passing a wrong sequence produces a record that the chain will refuse, which is the
// intended failure mode.
func NewRecord(r Record) (Record, error) {
	if err := r.Validate(); err != nil {
		return Record{}, err
	}
	r.RecordHash = r.ComputeHash()
	return r, nil
}

// TimestampFrom converts a time to the canonical audit timestamp.
func TimestampFrom(t time.Time) contracts.Timestamp { return contracts.TimestampFrom(t) }
