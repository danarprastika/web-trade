package contracts

import (
	"errors"
	"fmt"
	"regexp"
	"time"
)

// ErrInvalidEnvelope means an envelope violates the contract.
var ErrInvalidEnvelope = errors.New("invalid contract envelope")

// dottedNamePattern is the schema pattern for command_type and event_type:
// ^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$ with maxLength 128. A dotted name is required, so
// a bare "order" is rejected: a flat name cannot express a domain boundary.
var dottedNamePattern = regexp.MustCompile(`^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$`)

// semverPattern is the schema_version pattern ^[0-9]+\.[0-9]+\.[0-9]+$.
var semverPattern = regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+$`)

const maxDottedNameLength = 128

// ActorType is the closed set of caller kinds.
//
// This is the single closed set for the whole platform. The OMS, the Risk Engine, the
// ledger, and the audit chain all record this type rather than each declaring their own,
// because two sets that drift apart produce audit records the rest of the platform
// cannot interpret: a record naming an actor kind the OMS would refuse is evidence of a
// caller the OMS never accepted.
type ActorType string

// The permitted actor types.
const (
	ActorHuman   ActorType = "HUMAN"
	ActorService ActorType = "SERVICE"
	ActorAgent   ActorType = "AGENT"
	ActorSystem  ActorType = "SYSTEM"
	// ActorStrategy is an automated strategy acting under its own identity, distinct
	// from ActorAgent: a strategy is a deployed decision producer, while an agent is a
	// caller that may reason about arbitrary requests.
	ActorStrategy ActorType = "STRATEGY"
	// ActorBreakGlass is a human acting under the break-glass grant of docs/21 section 8.
	// It is a separate kind rather than a flag on a human, because break-glass activity is
	// reviewed on its own and must be countable without inspecting a reason string.
	ActorBreakGlass ActorType = "BREAK_GLASS"
)

// Valid reports whether the actor type is in the closed set.
func (a ActorType) Valid() bool {
	switch a {
	case ActorHuman, ActorService, ActorAgent, ActorSystem, ActorStrategy, ActorBreakGlass:
		return true
	default:
		return false
	}
}

// String returns the wire form.
func (a ActorType) String() string { return string(a) }

// Environment is the closed set of target environments.
//
// Commands are namespace-isolated by environment, and live credentials are never available
// to lower environments (ADR-012). Live is in the set because the type must be able to
// represent a legitimate live command; its presence here is not a permission.
type Environment string

// The environment ladder, in promotion order.
const (
	EnvDev     Environment = "dev"
	EnvTest    Environment = "test"
	EnvStaging Environment = "staging"
	EnvPaper   Environment = "paper"
	EnvShadow  Environment = "shadow"
	EnvLive    Environment = "live"
)

// IsLive reports whether this is the live environment.
func (e Environment) IsLive() bool { return e == EnvLive }

// Valid reports whether the environment is in the closed set.
func (e Environment) Valid() bool {
	switch e {
	case EnvDev, EnvTest, EnvStaging, EnvPaper, EnvShadow, EnvLive:
		return true
	default:
		return false
	}
}

// String returns the wire form.
func (e Environment) String() string { return string(e) }

// AggregateType is the closed set of aggregate kinds in the event envelope.
type AggregateType string

// The permitted aggregate types.
const (
	AggregateOrder              AggregateType = "order"
	AggregatePosition           AggregateType = "position"
	AggregatePortfolio          AggregateType = "portfolio"
	AggregateLedgerAccount      AggregateType = "ledger_account"
	AggregateStrategy           AggregateType = "strategy"
	AggregateRiskPolicy         AggregateType = "risk_policy"
	AggregateConfigSnapshot     AggregateType = "config_snapshot"
	AggregateReconciliationCase AggregateType = "reconciliation_case"
	AggregateFeed               AggregateType = "feed"
	AggregateModel              AggregateType = "model"
	AggregateDataset            AggregateType = "dataset"
	AggregateExperiment         AggregateType = "experiment"
)

// Valid reports whether the aggregate type is in the closed set.
func (a AggregateType) Valid() bool {
	switch a {
	case AggregateOrder, AggregatePosition, AggregatePortfolio, AggregateLedgerAccount,
		AggregateStrategy, AggregateRiskPolicy, AggregateConfigSnapshot,
		AggregateReconciliationCase, AggregateFeed, AggregateModel,
		AggregateDataset, AggregateExperiment:
		return true
	default:
		return false
	}
}

// String returns the wire form.
func (a AggregateType) String() string { return string(a) }

// requiredIdentifierPrefixes encodes the schema's allOf conditions: an aggregate's
// identifier prefix must agree with its aggregate type.
//
// The schema enforces this itself, and duplicating it in the binding is deliberate. The
// corpus case that exercises it operates on JSON, so a binding that skipped this check
// would pass every fixture while still accepting an order event whose aggregate_id is a
// position identifier. Binding-level checks are what make the invariant hold in Go code.
var requiredIdentifierPrefixes = map[AggregateType][]string{
	AggregateOrder:              {PrefixOrder},
	AggregatePosition:           {PrefixPosition},
	AggregateStrategy:           {PrefixStrategy},
	AggregateModel:              {PrefixModel},
	AggregateLedgerAccount:      {PrefixLedger},
	AggregateConfigSnapshot:     {PrefixRun, PrefixEvent},
	AggregateReconciliationCase: {PrefixRun, PrefixEvent},
	AggregateFeed:               {PrefixRun, PrefixEvent},
	AggregateDataset:            {PrefixRun, PrefixEvent},
	AggregateExperiment:         {PrefixRun, PrefixEvent},
	// portfolio, risk_policy have no dedicated identifier prefix in docs/03, so no
	// binding-level agreement is asserted for them. The schema asserts none either.
}

// CheckAggregateID validates that the identifier's prefix agrees with the aggregate type,
// where the contract defines a relationship.
func CheckAggregateID(agg AggregateType, id Identifier) error {
	if !agg.Valid() {
		return fmt.Errorf("%w: %q is not a known aggregate type", ErrInvalidEnvelope, agg)
	}
	if id.IsZero() {
		return fmt.Errorf("%w: aggregate_id is unset", ErrInvalidEnvelope)
	}
	allowed, constrained := requiredIdentifierPrefixes[agg]
	if !constrained {
		return nil
	}
	for _, prefix := range allowed {
		if id.Prefix() == prefix {
			return nil
		}
	}
	return fmt.Errorf(
		"%w: aggregate_type %q requires an aggregate_id prefixed %v, got %q",
		ErrInvalidEnvelope, agg, allowed, id.Prefix(),
	)
}

// idemKeyMinLength and idemKeyMaxLength bound the idempotency key.
const (
	idemKeyMinLength = 8
	idemKeyMaxLength = 255
)

// CommandEnvelope is a request to change authoritative state.
//
// A command is a request, never a state assertion: the server decides the resulting state.
// The type exists to carry a request, not to describe an outcome.
type CommandEnvelope struct {
	CommandID     Identifier
	CommandType   string
	SchemaVersion string
	CorrelationID Identifier
	// CausationID is nil only for an externally initiated root command.
	CausationID *Identifier
	ActorID     string
	ActorType   ActorType
	Environment Environment
	RequestedAt Timestamp
	// IdempotencyKey is required for every externally initiated mutating command, scoped
	// to actor, endpoint, and environment, and enforced by a database uniqueness
	// constraint rather than application memory (docs/03).
	IdempotencyKey string
	// TraceContext is opaque W3C trace propagation, carried across every language boundary.
	TraceContext map[string]any
	// Payload is validated against the contract named by CommandType and SchemaVersion.
	Payload map[string]any
}

// NewCommandEnvelope builds and validates a command envelope.
func NewCommandEnvelope(env CommandEnvelope) (CommandEnvelope, error) {
	if err := env.Validate(); err != nil {
		return CommandEnvelope{}, err
	}
	return env, nil
}

// Validate checks the command envelope against command-envelope.schema.json.
func (c CommandEnvelope) Validate() error {
	if c.CommandID.IsZero() || c.CommandID.Prefix() != PrefixCommand {
		return fmt.Errorf("%w: command_id must carry the %q prefix", ErrInvalidEnvelope, PrefixCommand)
	}
	if !dottedNamePattern.MatchString(c.CommandType) || len(c.CommandType) > maxDottedNameLength {
		return fmt.Errorf(
			"%w: command_type %q must be a dotted name such as order.place", ErrInvalidEnvelope, c.CommandType,
		)
	}
	if !semverPattern.MatchString(c.SchemaVersion) {
		return fmt.Errorf(
			"%w: schema_version %q must be major.minor.patch", ErrInvalidEnvelope, c.SchemaVersion,
		)
	}
	if c.CorrelationID.IsZero() {
		return fmt.Errorf("%w: correlation_id is required", ErrInvalidEnvelope)
	}
	if !isCommandOrEvent(c.CorrelationID) {
		return fmt.Errorf("%w: correlation_id must carry the %q or %q prefix", ErrInvalidEnvelope, PrefixCommand, PrefixEvent)
	}
	if c.CausationID != nil {
		if c.CausationID.IsZero() {
			return fmt.Errorf("%w: causation_id, when present, must be a valid identifier", ErrInvalidEnvelope)
		}
		if !isCommandOrEvent(*c.CausationID) {
			return fmt.Errorf("%w: causation_id must carry the %q or %q prefix", ErrInvalidEnvelope, PrefixCommand, PrefixEvent)
		}
	}
	if len(c.ActorID) < 1 || len(c.ActorID) > 255 {
		return fmt.Errorf("%w: actor_id must be 1..255 characters", ErrInvalidEnvelope)
	}
	if !c.ActorType.Valid() {
		return fmt.Errorf(
			"%w: actor_type %q is not a known actor type; unknown values are unsupported", ErrInvalidEnvelope, c.ActorType,
		)
	}
	if !c.Environment.Valid() {
		return fmt.Errorf(
			"%w: environment %q is not a known environment; unknown values are unsupported", ErrInvalidEnvelope, c.Environment,
		)
	}
	if c.RequestedAt.IsZero() {
		return fmt.Errorf("%w: requested_at is required", ErrInvalidEnvelope)
	}
	if len(c.IdempotencyKey) < idemKeyMinLength || len(c.IdempotencyKey) > idemKeyMaxLength {
		return fmt.Errorf(
			"%w: idempotency_key must be %d..%d characters; every externally initiated "+
				"mutating command requires one", ErrInvalidEnvelope, idemKeyMinLength, idemKeyMaxLength,
		)
	}
	if c.Payload == nil {
		return fmt.Errorf("%w: payload is required", ErrInvalidEnvelope)
	}
	return nil
}

// IdempotencyScope returns the database-level uniqueness scope for this command: actor,
// endpoint (the command type), and environment.
//
// Deriving the scope in one place is what keeps a replay of the same logical operation
// from being treated as new. The key alone is not enough: the same key issued by a
// different actor, a different endpoint, or a different environment is a different
// command and must not collide.
func (c CommandEnvelope) IdempotencyScope() string {
	return c.ActorID + "|" + c.CommandType + "|" + string(c.Environment)
}

// isCommandOrEvent reports whether the identifier is in the cmd_/evt_ space.
func isCommandOrEvent(id Identifier) bool {
	p := id.Prefix()
	return p == PrefixCommand || p == PrefixEvent
}

// EventEnvelope is an immutable fact that has already occurred.
//
// Events are written in the same transaction as the state change that produced them
// (transactional outbox, ADR-006). Delivery is at-least-once and no exactly-once
// assumption is made anywhere, so Sequence exists to let a consumer detect a gap or a
// duplicate rather than to prove delivery.
type EventEnvelope struct {
	EventID       Identifier
	EventType     string
	SchemaVersion string
	AggregateType AggregateType
	AggregateID   Identifier
	CorrelationID Identifier
	// CausationID is nil only for a root event.
	CausationID *Identifier
	ProducerID  string
	OccurredAt  Timestamp
	RecordedAt  Timestamp
	// SourceTimestamp is a venue-supplied instant where one exists. It is never trusted
	// without a freshness and clock-skew check (docs/16).
	SourceTimestamp *Timestamp
	// Sequence is monotonic per aggregate and starts at 1. A gap or duplicate is a
	// detectable anomaly, never silently tolerated.
	Sequence     int64
	Environment  *Environment
	TraceContext map[string]any
	Payload      map[string]any
}

// NewEventEnvelope builds and validates an event envelope.
func NewEventEnvelope(env EventEnvelope) (EventEnvelope, error) {
	if err := env.Validate(); err != nil {
		return EventEnvelope{}, err
	}
	return env, nil
}

// Validate checks the event envelope against event-envelope.schema.json.
func (e EventEnvelope) Validate() error {
	if e.EventID.IsZero() || e.EventID.Prefix() != PrefixEvent {
		return fmt.Errorf("%w: event_id must carry the %q prefix", ErrInvalidEnvelope, PrefixEvent)
	}
	if !dottedNamePattern.MatchString(e.EventType) || len(e.EventType) > maxDottedNameLength {
		return fmt.Errorf(
			"%w: event_type %q must be a dotted name such as order.accepted", ErrInvalidEnvelope, e.EventType,
		)
	}
	if !semverPattern.MatchString(e.SchemaVersion) {
		return fmt.Errorf(
			"%w: schema_version %q must be major.minor.patch", ErrInvalidEnvelope, e.SchemaVersion,
		)
	}
	if err := CheckAggregateID(e.AggregateType, e.AggregateID); err != nil {
		return err
	}
	if e.CorrelationID.IsZero() || !isCommandOrEvent(e.CorrelationID) {
		return fmt.Errorf("%w: correlation_id must carry the %q or %q prefix", ErrInvalidEnvelope, PrefixCommand, PrefixEvent)
	}
	if e.CausationID != nil {
		if e.CausationID.IsZero() || !isCommandOrEvent(*e.CausationID) {
			return fmt.Errorf(
				"%w: causation_id, when present, must carry the %q or %q prefix",
				ErrInvalidEnvelope, PrefixCommand, PrefixEvent,
			)
		}
	}
	if len(e.ProducerID) < 1 || len(e.ProducerID) > 255 {
		return fmt.Errorf("%w: producer_id must be 1..255 characters", ErrInvalidEnvelope)
	}
	if e.OccurredAt.IsZero() {
		return fmt.Errorf("%w: occurred_at is required", ErrInvalidEnvelope)
	}
	if e.RecordedAt.IsZero() {
		return fmt.Errorf("%w: recorded_at is required", ErrInvalidEnvelope)
	}
	// recorded_at >= occurred_at is deliberately NOT asserted. The schema states that
	// "clock skew is measured, not hidden", so enforcing the ordering here would turn a
	// measurable signal into a hard rejection and hide the drift this platform needs to see.
	if e.Sequence < 1 {
		return fmt.Errorf("%w: sequence must be at least 1, got %d", ErrInvalidEnvelope, e.Sequence)
	}
	if e.Environment != nil && !e.Environment.Valid() {
		return fmt.Errorf(
			"%w: environment %q is not a known environment; unknown values are unsupported",
			ErrInvalidEnvelope, *e.Environment,
		)
	}
	if e.Payload == nil {
		return fmt.Errorf("%w: payload is required", ErrInvalidEnvelope)
	}
	return nil
}

// Skew reports how far the venue-supplied timestamp sits from the platform's recorded
// time, when a source timestamp is present.
//
// The sign is meaningful: a source timestamp after the platform recorded the event usually
// indicates the venue clock runs ahead. The value is returned rather than corrected, so
// the caller can mark the feed unhealthy per docs/08 rather than silently trusting it.
func (e EventEnvelope) Skew() (time.Duration, bool) {
	if e.SourceTimestamp == nil {
		return 0, false
	}
	return e.SourceTimestamp.instant.Sub(e.RecordedAt.instant), true
}
