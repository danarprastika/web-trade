package contracts

import (
	"bytes"
	"encoding/json"
	"fmt"
)

// This file binds the canonical types to JSON so they can actually cross a service
// boundary. Every schema it serves declares additionalProperties: false, and several
// corpus cases exist purely to catch an over-permissive decoder, so the decode helper
// rejects unknown fields rather than ignoring them. A decoder that silently dropped an
// unexpected field would accept a document carrying state this platform does not model,
// and the field would then be lost with no signal that it was ever there.

// decodeStrict decodes exactly one JSON document into v, rejecting unknown fields and any
// trailing content after it.
//
// Both restrictions matter. DisallowUnknownFields is what makes additionalProperties:false
// real rather than decorative. Rejecting trailing content is what stops `{}{}` or a valid
// object followed by a second document from being read as success: a peer that sends more
// than it should is either buggy or hostile, and neither should decode as a clean value.
func decodeStrict(data []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		return err
	}
	// A second Decode must report io.EOF; anything else means trailing content.
	var extra json.RawMessage
	if err := dec.Decode(&extra); err == nil {
		return fmt.Errorf("unexpected trailing content after the JSON document")
	}
	return nil
}

// decodeString requires a JSON string. A number, boolean, null, object, or array is a
// schema violation, and this is where the difference is caught.
//
// It matters most for the decimal types. money.schema.json binds amount by $ref to
// decimal.schema.json, whose type is string precisely so a value cannot be carried as a
// JSON number: a number would already have passed through a double, and the digits are
// gone before this type ever sees it. The corpus case
// money/reject-amount-as-number exists to hold that line.
func decodeString(data []byte, field string) (string, error) {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return "", fmt.Errorf("field %q must be a JSON string: %w", field, err)
	}
	return s, nil
}

// decodeInt32 requires a JSON number that is a valid int32. A quoted number is rejected,
// so a limit cannot arrive as "100" and be quietly coerced.
func decodeInt32(data []byte, field string) (int32, error) {
	var n int32
	if err := json.Unmarshal(data, &n); err != nil {
		return 0, fmt.Errorf("field %q must be a JSON integer: %w", field, err)
	}
	return n, nil
}

// MarshalJSON encodes an identifier as its canonical string form.
func (i Identifier) MarshalJSON() ([]byte, error) {
	if i.IsZero() {
		// Emitting "" would produce a document that fails its own schema on the way out.
		// Failing here names the real problem: the field was never set.
		return nil, fmt.Errorf("%w: cannot encode an unset identifier", ErrInvalidIdentifier)
	}
	return json.Marshal(i.String())
}

// UnmarshalJSON decodes and validates an identifier.
func (i *Identifier) UnmarshalJSON(data []byte) error {
	s, err := decodeString(data, "identifier")
	if err != nil {
		return err
	}
	parsed, err := ParseIdentifier(s)
	if err != nil {
		return err
	}
	*i = parsed
	return nil
}

// MarshalJSON encodes a decimal as its canonical text, preserving trailing zeros.
func (d Decimal) MarshalJSON() ([]byte, error) {
	if !d.IsSet() {
		return nil, fmt.Errorf("%w: cannot encode an unset decimal", ErrInvalidDecimal)
	}
	return json.Marshal(d.String())
}

// UnmarshalJSON decodes and validates a decimal.
func (d *Decimal) UnmarshalJSON(data []byte) error {
	s, err := decodeString(data, "decimal")
	if err != nil {
		return err
	}
	parsed, err := ParseDecimal(s)
	if err != nil {
		return err
	}
	*d = parsed
	return nil
}

// MarshalJSON encodes a timestamp in canonical nine-digit UTC form.
func (ts Timestamp) MarshalJSON() ([]byte, error) {
	if ts.IsZero() {
		return nil, fmt.Errorf("%w: cannot encode an unset timestamp", ErrInvalidTimestamp)
	}
	return json.Marshal(ts.String())
}

// UnmarshalJSON decodes and validates a timestamp.
func (ts *Timestamp) UnmarshalJSON(data []byte) error {
	s, err := decodeString(data, "timestamp")
	if err != nil {
		return err
	}
	parsed, err := ParseTimestamp(s)
	if err != nil {
		return err
	}
	*ts = parsed
	return nil
}

// moneyWire mirrors money.schema.json exactly.
type moneyWire struct {
	Currency string  `json:"currency"`
	Amount   Decimal `json:"amount"`
	Scale    *int32  `json:"scale,omitempty"`
}

// MarshalJSON encodes a money value.
func (m Money) MarshalJSON() ([]byte, error) {
	if !m.amount.IsSet() {
		return nil, fmt.Errorf("%w: cannot encode an unset money value", ErrInvalidMoney)
	}
	return json.Marshal(moneyWire{Currency: m.currency, Amount: m.amount, Scale: m.scale})
}

// UnmarshalJSON decodes a money value. Structural decoding only; call Validate for the
// coherence checks.
func (m *Money) UnmarshalJSON(data []byte) error {
	var wire moneyWire
	if err := decodeStrict(data, &wire); err != nil {
		return err
	}
	decoded, err := NewMoneyWithScale(wire.Currency, wire.Amount, wire.Scale)
	if err != nil {
		return err
	}
	*m = decoded
	return nil
}

// quantityWire mirrors quantity.schema.json exactly.
type quantityWire struct {
	Value Decimal      `json:"value"`
	Unit  QuantityUnit `json:"unit"`
	Scale *int32       `json:"scale,omitempty"`
}

// MarshalJSON encodes a quantity.
func (q Quantity) MarshalJSON() ([]byte, error) {
	if !q.value.IsSet() {
		return nil, fmt.Errorf("%w: cannot encode an unset quantity", ErrInvalidQuantity)
	}
	return json.Marshal(quantityWire{Value: q.value, Unit: q.unit, Scale: q.scale})
}

// UnmarshalJSON decodes a quantity.
func (q *Quantity) UnmarshalJSON(data []byte) error {
	var wire quantityWire
	if err := decodeStrict(data, &wire); err != nil {
		return err
	}
	unit, err := ParseQuantityUnit(string(wire.Unit))
	if err != nil {
		return err
	}
	decoded, err := NewQuantityWithScale(wire.Value, unit, wire.Scale)
	if err != nil {
		return err
	}
	*q = decoded
	return nil
}

// errorWire mirrors error.schema.json exactly.
//
// Retryable is a plain bool with no pointer because the schema does not require it. An
// absent retryable decodes to false, which is the safe direction: a caller that cannot tell
// whether a retry is safe must not be told it is.
type errorWire struct {
	Code          ErrorCode      `json:"code"`
	Message       string         `json:"message"`
	CorrelationID *Identifier    `json:"correlation_id,omitempty"`
	Details       map[string]any `json:"details,omitempty"`
	Retryable     bool           `json:"retryable"`
}

// MarshalJSON encodes a canonical error.
func (e ContractError) MarshalJSON() ([]byte, error) {
	var corr *Identifier
	if !e.correlationID.IsZero() {
		id := e.correlationID
		corr = &id
	}
	return json.Marshal(errorWire{
		Code:          e.code,
		Message:       e.message,
		CorrelationID: corr,
		Details:       e.details,
		Retryable:     e.retryable,
	})
}

// UnmarshalJSON decodes a canonical error.
func (e *ContractError) UnmarshalJSON(data []byte) error {
	var wire errorWire
	if err := decodeStrict(data, &wire); err != nil {
		return err
	}
	// The schema narrows correlation_id to the cmd_/evt_ space, which is stricter than the
	// general identifier pattern, so the narrowing is applied here rather than left to a
	// later stage that may not exist.
	if wire.CorrelationID != nil && !isCommandOrEvent(*wire.CorrelationID) {
		return fmt.Errorf("%w: correlation_id must carry the %q or %q prefix",
			ErrInvalidContractValue, PrefixCommand, PrefixEvent)
	}
	decoded, err := NewContractError(wire.Code, wire.Message, wire.Retryable)
	if err != nil {
		return err
	}
	if wire.CorrelationID != nil {
		decoded = decoded.WithCorrelation(*wire.CorrelationID)
	}
	if wire.Details != nil {
		decoded = decoded.WithDetails(wire.Details)
	}
	*e = decoded
	return nil
}

// commandWire mirrors command-envelope.schema.json exactly.
//
// CausationID is emitted even when nil, because the schema requires the key. A nil pointer
// encodes as null, which the schema permits through its oneOf. Omitting the key with
// omitempty would make every root command produce a schema-invalid document.
type commandWire struct {
	CommandID      Identifier     `json:"command_id"`
	CommandType    string         `json:"command_type"`
	SchemaVersion  string         `json:"schema_version"`
	CorrelationID  Identifier     `json:"correlation_id"`
	CausationID    *Identifier    `json:"causation_id"`
	ActorID        string         `json:"actor_id"`
	ActorType      ActorType      `json:"actor_type"`
	Environment    Environment    `json:"environment"`
	RequestedAt    Timestamp      `json:"requested_at"`
	IdempotencyKey string         `json:"idempotency_key"`
	TraceContext   map[string]any `json:"trace_context,omitempty"`
	Payload        map[string]any `json:"payload"`
}

// MarshalJSON encodes a command envelope.
func (c CommandEnvelope) MarshalJSON() ([]byte, error) {
	if err := c.Validate(); err != nil {
		// Encoding an envelope that fails its own contract would push the failure to the
		// consumer, where the cause is no longer visible.
		return nil, err
	}
	return json.Marshal(commandWire{
		CommandID: c.CommandID, CommandType: c.CommandType, SchemaVersion: c.SchemaVersion,
		CorrelationID: c.CorrelationID, CausationID: c.CausationID, ActorID: c.ActorID,
		ActorType: c.ActorType, Environment: c.Environment, RequestedAt: c.RequestedAt,
		IdempotencyKey: c.IdempotencyKey, TraceContext: c.TraceContext, Payload: c.Payload,
	})
}

// UnmarshalJSON decodes a command envelope.
func (c *CommandEnvelope) UnmarshalJSON(data []byte) error {
	var wire commandWire
	if err := decodeStrict(data, &wire); err != nil {
		return err
	}
	*c = CommandEnvelope{
		CommandID: wire.CommandID, CommandType: wire.CommandType,
		SchemaVersion: wire.SchemaVersion, CorrelationID: wire.CorrelationID,
		CausationID: wire.CausationID, ActorID: wire.ActorID, ActorType: wire.ActorType,
		Environment: wire.Environment, RequestedAt: wire.RequestedAt,
		IdempotencyKey: wire.IdempotencyKey, TraceContext: wire.TraceContext,
		Payload: wire.Payload,
	}
	return c.Validate()
}

// eventWire mirrors event-envelope.schema.json exactly.
//
// CausationID is required-but-nullable here for the same reason as in commandWire, and
// SourceTimestamp is a *Timestamp so an absent venue timestamp stays distinguishable from
// a zero instant.
type eventWire struct {
	EventID         Identifier     `json:"event_id"`
	EventType       string         `json:"event_type"`
	SchemaVersion   string         `json:"schema_version"`
	AggregateType   AggregateType  `json:"aggregate_type"`
	AggregateID     Identifier     `json:"aggregate_id"`
	CorrelationID   Identifier     `json:"correlation_id"`
	CausationID     *Identifier    `json:"causation_id"`
	ProducerID      string         `json:"producer_id"`
	OccurredAt      Timestamp      `json:"occurred_at"`
	RecordedAt      Timestamp      `json:"recorded_at"`
	SourceTimestamp *Timestamp     `json:"source_timestamp,omitempty"`
	Sequence        int64          `json:"sequence"`
	Environment     *Environment   `json:"environment,omitempty"`
	TraceContext    map[string]any `json:"trace_context,omitempty"`
	Payload         map[string]any `json:"payload"`
}

// MarshalJSON encodes an event envelope.
func (e EventEnvelope) MarshalJSON() ([]byte, error) {
	if err := e.Validate(); err != nil {
		return nil, err
	}
	return json.Marshal(eventWire{
		EventID: e.EventID, EventType: e.EventType, SchemaVersion: e.SchemaVersion,
		AggregateType: e.AggregateType, AggregateID: e.AggregateID,
		CorrelationID: e.CorrelationID, CausationID: e.CausationID, ProducerID: e.ProducerID,
		OccurredAt: e.OccurredAt, RecordedAt: e.RecordedAt,
		SourceTimestamp: e.SourceTimestamp, Sequence: e.Sequence,
		Environment: e.Environment, TraceContext: e.TraceContext, Payload: e.Payload,
	})
}

// UnmarshalJSON decodes an event envelope.
func (e *EventEnvelope) UnmarshalJSON(data []byte) error {
	var wire eventWire
	if err := decodeStrict(data, &wire); err != nil {
		return err
	}
	*e = EventEnvelope{
		EventID: wire.EventID, EventType: wire.EventType, SchemaVersion: wire.SchemaVersion,
		AggregateType: wire.AggregateType, AggregateID: wire.AggregateID,
		CorrelationID: wire.CorrelationID, CausationID: wire.CausationID,
		ProducerID: wire.ProducerID, OccurredAt: wire.OccurredAt, RecordedAt: wire.RecordedAt,
		SourceTimestamp: wire.SourceTimestamp, Sequence: wire.Sequence,
		Environment: wire.Environment, TraceContext: wire.TraceContext, Payload: wire.Payload,
	}
	return e.Validate()
}
