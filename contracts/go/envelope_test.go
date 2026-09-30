package contracts

import (
	"errors"
	"strings"
	"testing"
	"time"
)

// validCommand returns a command that satisfies command-envelope.schema.json, so each test
// can invalidate exactly one field and attribute the rejection to that field.
func validCommand(t *testing.T) CommandEnvelope {
	t.Helper()
	commandID, err := ParseIdentifier("cmd_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	return CommandEnvelope{
		CommandID:      commandID,
		CommandType:    "order.place",
		SchemaVersion:  "1.0.0",
		CorrelationID:  commandID,
		CausationID:    nil, // a root command has no cause
		ActorID:        "trader-42",
		ActorType:      ActorHuman,
		Environment:    EnvPaper,
		RequestedAt:    MustParseTimestamp("2026-09-28T10:17:46.123456789Z"),
		IdempotencyKey: "place-order-0001",
		Payload:        map[string]any{"symbol": "BTC/USD"},
	}
}

// validEvent returns an event that satisfies event-envelope.schema.json.
func validEvent(t *testing.T) EventEnvelope {
	t.Helper()
	eventID, err := ParseIdentifier("evt_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	orderID, err := ParseIdentifier("ord_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	commandID, err := ParseIdentifier("cmd_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	env := EnvPaper
	source := MustParseTimestamp("2026-09-28T10:17:46.100000000Z")
	return EventEnvelope{
		EventID:         eventID,
		EventType:       "order.accepted",
		SchemaVersion:   "1.0.0",
		AggregateType:   AggregateOrder,
		AggregateID:     orderID,
		CorrelationID:   commandID,
		CausationID:     &commandID,
		ProducerID:      "oms",
		OccurredAt:      MustParseTimestamp("2026-09-28T10:17:46.123456789Z"),
		RecordedAt:      MustParseTimestamp("2026-09-28T10:17:46.140000000Z"),
		SourceTimestamp: &source,
		Sequence:        3,
		Environment:     &env,
		Payload:         map[string]any{"status": "accepted"},
	}
}

func TestValidCommandAccepts(t *testing.T) {
	c := validCommand(t)
	if err := c.Validate(); err != nil {
		t.Fatalf("Validate() = %v, want nil for a well-formed command", err)
	}
	// NewCommandEnvelope must not alter a valid envelope.
	built, err := NewCommandEnvelope(c)
	if err != nil {
		t.Fatalf("NewCommandEnvelope: %v", err)
	}
	if built.CommandID != c.CommandID {
		t.Error("NewCommandEnvelope altered the command identity")
	}
}

// TestCommandRejectsUnknownEnumValues covers the two closed-set cases in the corpus.
// docs/03 requires unknown enum values to be treated as unsupported rather than silently
// mapped, so there is no fallback that guesses a default.
func TestCommandRejectsUnknownEnumValues(t *testing.T) {
	badEnv := validCommand(t)
	badEnv.Environment = Environment("production")
	if err := badEnv.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("unknown environment = %v, want ErrInvalidEnvelope", err)
	}

	badActor := validCommand(t)
	badActor.ActorType = ActorType("ROBOT")
	if err := badActor.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("unknown actor type = %v, want ErrInvalidEnvelope", err)
	}
}

func TestCommandRejectsNonSemverSchemaVersion(t *testing.T) {
	for _, v := range []string{"1.0", "1", "v1.0.0", "1.0.0-alpha", "1.0.0.0", ""} {
		c := validCommand(t)
		c.SchemaVersion = v
		if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
			t.Errorf("schema_version %q = %v, want ErrInvalidEnvelope", v, err)
		}
	}
	// "01.0.0" is accepted, and that is a deliberate consequence of matching the contract
	// rather than the more familiar SemVer 2.0.0 rule. The schema pattern is
	// ^[0-9]+\.[0-9]+\.[0-9]+$, which permits leading zeros; SemVer 2.0.0 itself forbids
	// them. The binding follows the schema, because a binding stricter than the contract
	// would reject documents the schema accepts, and the corpus exists precisely to detect
	// a binding and schema disagreeing. Tightening this belongs in the schema, not here.
	for _, v := range []string{"1.0.0", "0.0.1", "12.34.56", "01.0.0"} {
		c := validCommand(t)
		c.SchemaVersion = v
		if err := c.Validate(); err != nil {
			t.Errorf("schema_version %q = %v, want accept under the schema pattern", v, err)
		}
	}
}

// TestCommandTypeMustBeDotted pins that command_type carries a domain boundary. A bare
// "order" is rejected, so two modules cannot both define "order.something" without
// colliding in a shared event stream.
func TestCommandTypeMustBeDotted(t *testing.T) {
	for _, ct := range []string{"order.place", "risk.override", "reconciliation.case.opened"} {
		c := validCommand(t)
		c.CommandType = ct
		if err := c.Validate(); err != nil {
			t.Errorf("command_type %q = %v, want accept", ct, err)
		}
	}
	for _, ct := range []string{"order", "Order.Place", "order.", ".order", "order-place", "1order.place", ""} {
		c := validCommand(t)
		c.CommandType = ct
		if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
			t.Errorf("command_type %q = %v, want ErrInvalidEnvelope", ct, err)
		}
	}
	// maxLength 128.
	long := "a." + strings.Repeat("b", 127)
	c := validCommand(t)
	c.CommandType = long
	if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("129-character command_type = %v, want ErrInvalidEnvelope", err)
	}
}

// TestCommandRequiresIdempotencyKey pins the corpus case reject-missing-idempotency-key.
//
// A mutating command without a key cannot be deduplicated on replay, which is precisely how
// a retried order turns into two orders.
func TestCommandRequiresIdempotencyKey(t *testing.T) {
	c := validCommand(t)
	c.IdempotencyKey = ""
	if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("empty idempotency_key = %v, want ErrInvalidEnvelope", err)
	}
	// minLength is 8.
	c.IdempotencyKey = "short"
	if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("7-character idempotency_key = %v, want ErrInvalidEnvelope", err)
	}
	c.IdempotencyKey = strings.Repeat("k", 8)
	if err := c.Validate(); err != nil {
		t.Errorf("8-character idempotency_key = %v, want accept", err)
	}
	// maxLength is 255.
	c.IdempotencyKey = strings.Repeat("k", 256)
	if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("256-character idempotency_key = %v, want ErrInvalidEnvelope", err)
	}
}

// TestCommandIdempotencyScope covers the uniqueness scope: actor, endpoint, and
// environment. The key alone is not enough to deduplicate, because the same key issued by a
// different actor, endpoint, or environment is a genuinely different command.
func TestCommandIdempotencyScope(t *testing.T) {
	base := validCommand(t)
	baseline := base.IdempotencyScope()

	otherActor := base
	otherActor.ActorID = "trader-99"
	if otherActor.IdempotencyScope() == baseline {
		t.Error("a different actor produced the same idempotency scope")
	}

	otherEndpoint := base
	otherEndpoint.CommandType = "order.cancel"
	if otherEndpoint.IdempotencyScope() == baseline {
		t.Error("a different endpoint produced the same idempotency scope")
	}

	otherEnv := base
	otherEnv.Environment = EnvDev
	if otherEnv.IdempotencyScope() == baseline {
		t.Error("a different environment produced the same idempotency scope")
	}

	// The same logical command produces the same scope, which is what makes replay safe.
	if base.IdempotencyScope() != baseline {
		t.Error("the same command produced two different idempotency scopes")
	}
}

func TestCommandRejectsWrongIdentifierPrefixes(t *testing.T) {
	eventID, err := ParseIdentifier("evt_" + canonicalBody)
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	// command_id must be cmd_.
	c := validCommand(t)
	c.CommandID = eventID
	if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("event identifier as command_id = %v, want ErrInvalidEnvelope", err)
	}
	// correlation_id must be cmd_ or evt_, so an order identifier cannot correlate a command.
	c = validCommand(t)
	c.CorrelationID = mustIdentifier(t, "ord_"+canonicalBody)
	if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("order identifier as correlation_id = %v, want ErrInvalidEnvelope", err)
	}
}

// TestCommandAcceptsNullCausation covers the corpus case accept-null-causation: a root
// command legitimately has no cause. Causation is optional on the way in and only becomes
// mandatory once something has caused something else.
func TestCommandAcceptsNullCausation(t *testing.T) {
	c := validCommand(t)
	c.CausationID = nil
	if err := c.Validate(); err != nil {
		t.Errorf("null causation_id = %v, want accept for a root command", err)
	}
	// causation_id may also be a command or an event.
	for _, prefix := range []string{PrefixCommand, PrefixEvent} {
		c := validCommand(t)
		id := mustIdentifier(t, prefix+canonicalBody)
		c.CausationID = &id
		if err := c.Validate(); err != nil {
			t.Errorf("causation_id %q = %v, want accept", id, err)
		}
	}
	// A position identifier is not a cause.
	c = validCommand(t)
	bad := mustIdentifier(t, PrefixPosition+canonicalBody)
	c.CausationID = &bad
	if err := c.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("position identifier as causation_id = %v, want ErrInvalidEnvelope", err)
	}
}

func TestValidEventAccepts(t *testing.T) {
	e := validEvent(t)
	if err := e.Validate(); err != nil {
		t.Fatalf("Validate() = %v, want nil for a well-formed event", err)
	}
}

// TestEventRejectsMismatchedAggregateIDPrefix covers the corpus case
// reject-mismatched-aggregate-id-prefix.
//
// The schema enforces this through allOf. The binding repeats it because the corpus case
// is a JSON document: a binding that skipped the check would pass every fixture while
// still accepting an order event whose aggregate_id points at a position.
func TestEventRejectsMismatchedAggregateIDPrefix(t *testing.T) {
	cases := []struct {
		agg  AggregateType
		want string // the prefix the schema permits
	}{
		{AggregateOrder, PrefixOrder},
		{AggregatePosition, PrefixPosition},
		{AggregateStrategy, PrefixStrategy},
		{AggregateModel, PrefixModel},
		{AggregateLedgerAccount, PrefixLedger},
		{AggregateConfigSnapshot, PrefixRun},
		{AggregateFeed, PrefixEvent},
	}
	for _, tc := range cases {
		// The correct prefix is accepted.
		e := validEvent(t)
		e.AggregateType = tc.agg
		e.AggregateID = mustIdentifier(t, tc.want+canonicalBody)
		if err := e.Validate(); err != nil {
			t.Errorf("%s with a %q aggregate_id = %v, want accept", tc.agg, tc.want, err)
		}
		// A different registered prefix is rejected: the type and the id must agree.
		wrong := PrefixOrder
		if tc.want == PrefixOrder {
			wrong = PrefixPosition
		}
		e = validEvent(t)
		e.AggregateType = tc.agg
		e.AggregateID = mustIdentifier(t, wrong+canonicalBody)
		if err := e.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
			t.Errorf("%s with a %q aggregate_id = %v, want ErrInvalidEnvelope", tc.agg, wrong, err)
		}
	}
}

// TestEventAggregateTypesWithoutAPrefixConstraint records the two aggregate types the
// schema leaves unconstrained. portfolio and risk_policy have no dedicated identifier
// prefix, so the binding asserts nothing beyond a known aggregate type and a valid
// identifier. This is pinned so that adding a prefix constraint later is a deliberate
// change rather than an unnoticed behaviour shift.
func TestEventAggregateTypesWithoutAPrefixConstraint(t *testing.T) {
	for _, agg := range []AggregateType{AggregatePortfolio, AggregateRiskPolicy} {
		e := validEvent(t)
		e.AggregateType = agg
		e.AggregateID = mustIdentifier(t, PrefixOrder+canonicalBody)
		if err := e.Validate(); err != nil {
			t.Errorf("%s = %v, want accept; the schema constrains no prefix here", agg, err)
		}
	}
	// An unknown aggregate type is still rejected.
	e := validEvent(t)
	e.AggregateType = AggregateType("widget")
	if err := e.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("unknown aggregate_type = %v, want ErrInvalidEnvelope", err)
	}
}

func TestEventRejectsSequenceBelowOne(t *testing.T) {
	// Covers the corpus case reject-sequence-zero. The sequence is monotonic per aggregate
	// and starts at 1; a zero would collide with the unset default.
	for _, s := range []int64{0, -1} {
		e := validEvent(t)
		e.Sequence = s
		if err := e.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
			t.Errorf("sequence %d = %v, want ErrInvalidEnvelope", s, err)
		}
	}
	e := validEvent(t)
	e.Sequence = 1
	if err := e.Validate(); err != nil {
		t.Errorf("sequence 1 = %v, want accept", err)
	}
}

// TestEventDoesNotEnforceRecordedAtOrdering pins a deliberate omission.
//
// event-envelope.schema.json says "recorded_at >= occurred_at is not assumed; clock skew is
// measured, not hidden". Enforcing the ordering here would convert a measurable signal into
// a hard rejection and hide the drift this platform needs to observe.
func TestEventDoesNotEnforceRecordedAtOrdering(t *testing.T) {
	e := validEvent(t)
	e.OccurredAt = MustParseTimestamp("2026-09-28T10:17:46.140000000Z")
	e.RecordedAt = MustParseTimestamp("2026-09-28T10:17:46.120000000Z")
	if err := e.Validate(); err != nil {
		t.Errorf("recorded_at earlier than occurred_at = %v, want accept; skew must remain visible", err)
	}
}

// TestEventReportsClockSkew covers the venue clock signal. A source timestamp outside the
// window is something a caller acts on, not something this type silently corrects.
func TestEventReportsClockSkew(t *testing.T) {
	e := validEvent(t)
	skew, ok := e.Skew()
	if !ok {
		t.Fatal("Skew() reports no source timestamp, want one")
	}
	// source 10:17:46.100 against recorded 10:17:46.140 is 40ms behind.
	if skew != -40*time.Millisecond {
		t.Errorf("Skew() = %v, want -40ms", skew)
	}
	if !e.SourceTimestamp.IsWithinSkew(e.RecordedAt, time.Second) {
		t.Error("40ms drift reported outside a 1s window")
	}

	noSource := e
	noSource.SourceTimestamp = nil
	if _, ok := noSource.Skew(); ok {
		t.Error("Skew() reports a value with no source timestamp, want (0, false)")
	}
}

func TestEventEnvironmentIsOptional(t *testing.T) {
	// The schema does not list environment as required, so an event may omit it. An
	// unknown value, when present, is still a hard rejection.
	e := validEvent(t)
	e.Environment = nil
	if err := e.Validate(); err != nil {
		t.Errorf("nil environment = %v, want accept", err)
	}
	e = validEvent(t)
	bad := Environment("production")
	e.Environment = &bad
	if err := e.Validate(); !errors.Is(err, ErrInvalidEnvelope) {
		t.Errorf("unknown environment = %v, want ErrInvalidEnvelope", err)
	}
}

func TestEnvironmentLadder(t *testing.T) {
	// Live is in the closed set because the type must be able to represent a legitimate live
	// command. Its presence is not a permission, and the validator never grants one.
	for _, e := range []Environment{EnvDev, EnvTest, EnvStaging, EnvPaper, EnvShadow, EnvLive} {
		if !e.Valid() {
			t.Errorf("environment %q reported invalid", e)
		}
	}
	if !EnvLive.IsLive() {
		t.Error("EnvLive.IsLive() = false, want true")
	}
	if EnvPaper.IsLive() {
		t.Error("EnvPaper.IsLive() = true, want false")
	}
	for _, e := range []Environment{"", "prod", "LIVE", "Dev"} {
		if e.Valid() {
			t.Errorf("environment %q reported valid, want invalid", e)
		}
	}
}

func mustIdentifier(t *testing.T, s string) Identifier {
	t.Helper()
	id, err := ParseIdentifier(s)
	if err != nil {
		t.Fatalf("ParseIdentifier(%q): %v", s, err)
	}
	return id
}
