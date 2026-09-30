package oms

import (
	"errors"
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// Fixtures build a canonical order and drive it to a chosen state. Each test changes exactly
// one thing from a known-good baseline, because an order state machine is precisely the kind
// of thing where a test that changes three inputs and asserts one verdict passes for the
// wrong reason often enough to be useless.

const (
	fixtureInstrument = "BTC-USDT"
	fixtureVenue      = "VENUE_A"
	fixtureMarket     = "SPOT"
	fixtureOrderType  = "LIMIT"
	fixtureCurrency   = "USDT"
	fixtureHaltRef    = "halt-0001"

	baseRequestedAt = "2026-03-01T12:00:00.000000000Z"
	issuedAt        = "2026-03-01T12:00:01.000000000Z"
	venueAt         = "2026-03-01T12:00:02.000000000Z"
	laterAt         = "2026-03-01T12:00:05.000000000Z"
)

func id(t *testing.T, prefix string) contracts.Identifier {
	t.Helper()
	parsed, err := contracts.ParseIdentifier(prefix + strings.Repeat("0", 26))
	if err != nil {
		t.Fatalf("fixture identifier %s... is not valid: %v", prefix, err)
	}
	return parsed
}

func otherID(t *testing.T, prefix string) contracts.Identifier {
	t.Helper()
	parsed, err := contracts.ParseIdentifier(prefix + "1" + strings.Repeat("0", 25))
	if err != nil {
		t.Fatalf("mutated identifier %s... is not valid: %v", prefix, err)
	}
	return parsed
}

func money(t *testing.T, currency, amount string) *contracts.Money {
	t.Helper()
	m, err := contracts.NewMoney(currency, contracts.MustParseDecimal(amount))
	if err != nil {
		t.Fatalf("fixture money %s %s is not valid: %v", amount, currency, err)
	}
	return &m
}

func qty(t *testing.T, value string) contracts.Quantity {
	t.Helper()
	q, err := contracts.NewQuantity(contracts.MustParseDecimal(value), contracts.UnitBaseAsset)
	if err != nil {
		t.Fatalf("fixture quantity %s is not valid: %v", value, err)
	}
	return q
}

func ts(t *testing.T, s string) contracts.Timestamp {
	t.Helper()
	parsed, err := contracts.ParseTimestamp(s)
	if err != nil {
		t.Fatalf("fixture timestamp %q is not valid: %v", s, err)
	}
	return parsed
}

func serviceActor() Actor {
	return Actor{ID: "svc-order-gateway", Type: contracts.ActorService}
}

func humanActor() Actor {
	return Actor{ID: "op-42", Type: contracts.ActorHuman}
}

func systemActor() Actor {
	return Actor{ID: "sys-orchestrator", Type: contracts.ActorSystem}
}

func agentActor() Actor {
	return Actor{ID: "mdl-signal", Type: contracts.ActorAgent}
}

// newOrder is the baseline: a 10-unit limit buy at 100.00, in StateCreated.
func newOrder(t *testing.T) Order {
	t.Helper()
	order, err := Create(NewOrderRequest{
		CommandID:      id(t, contracts.PrefixCommand),
		AccountID:      id(t, contracts.PrefixLedger),
		StrategyID:     id(t, contracts.PrefixStrategy),
		Instrument:     fixtureInstrument,
		Venue:          fixtureVenue,
		Market:         fixtureMarket,
		Direction:      DirBuy,
		OrderType:      fixtureOrderType,
		Quantity:       qty(t, "10"),
		LimitPrice:     money(t, fixtureCurrency, "100.00"),
		IdempotencyKey: "idem-create-0001",
		RequestedAt:    ts(t, baseRequestedAt),
		Environment:    "PRODUCTION",
	})
	if err != nil {
		t.Fatalf("baseline order cannot be created: %v", err)
	}
	return order
}

func request(t *testing.T, order Order, cmd Command) Request {
	t.Helper()
	return Request{
		OrderID:         order.OrderID,
		ExpectedVersion: order.Version,
		Command:         cmd,
		Actor:           serviceActor(),
		IdempotencyKey:  "idem-" + string(cmd),
		At:              ts(t, issuedAt),
	}
}

// apply is a helper that fails the test rather than returning an error, for use where the
// transition is expected to succeed. Tests that expect a refusal call Apply directly.
func apply(t *testing.T, order Order, req Request) Order {
	t.Helper()
	outcome, err := Apply(order, req)
	if err != nil {
		t.Fatalf("transition %s was expected to apply: %v", req.Command, err)
	}
	return outcome.Order
}

// toRiskPending drives a created order into risk evaluation.
func toRiskPending(t *testing.T) Order {
	t.Helper()
	order := newOrder(t)
	req := request(t, order, CmdSubmitForRisk)
	req.PreconditionsSatisfied = []Precondition{PreRiskEvaluated}
	return apply(t, order, req)
}

// toRiskApproved drives an order through a risk approval.
func toRiskApproved(t *testing.T) Order {
	t.Helper()
	order := toRiskPending(t)
	req := request(t, order, CmdRecordRiskApproval)
	req.PreconditionsSatisfied = []Precondition{PreRiskEvaluated, PreRiskApproved}
	req.RiskReference = "risk-eval-0007"
	return apply(t, order, req)
}

// toSubmitting drives an approved order to submission at the venue.
func toSubmitting(t *testing.T) Order {
	t.Helper()
	order := toRiskApproved(t)
	req := request(t, order, CmdSubmitToVenue)
	req.PreconditionsSatisfied = []Precondition{PreRiskApproved, PreNoActiveHalt}
	return apply(t, order, req)
}

func observation(t *testing.T, kind ObservationKind) Observation {
	t.Helper()
	obs := Observation{
		Kind:          kind,
		VenueOrderRef: "venue-ref-1",
		OccurredAt:    ts(t, venueAt),
		Evidence:      "venue-message-0001",
	}
	if kind == ObsPartiallyFilled || kind == ObsFilled {
		obs.CumulativeFilled = qty(t, "10")
	}
	return obs
}

func requireState(t *testing.T, order Order, want State) {
	t.Helper()
	if order.State != want {
		t.Fatalf("order is in %s, want %s (version %d)", order.State, want, order.Version)
	}
}

func requireRejection(t *testing.T, err error, contains ...string) Rejection {
	t.Helper()
	if err == nil {
		t.Fatal("expected a rejection, got success")
	}
	var r Rejection
	if !errors.As(err, &r) {
		t.Fatalf("expected an oms.Rejection, got %T: %v", err, err)
	}
	for _, want := range contains {
		if !strings.Contains(r.Reason, want) {
			t.Errorf("rejection should mention %q, got: %s", want, r.Reason)
		}
	}
	return r
}
