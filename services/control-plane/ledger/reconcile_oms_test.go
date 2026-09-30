package ledger_test

import (
	"testing"

	oms "github.com/danarprastika/web-trade/components/oms"
	contracts "github.com/danarprastika/web-trade/contracts/go"
	"github.com/danarprastika/web-trade/services/control-plane/ledger"
)

// These tests are the reconciliation WI-116's fourth acceptance criterion asks for, and they
// drive a real OMS order rather than a hand-built quantity. The claim "positions reconcile to
// validated fills" is only worth anything if "validated fill" means what the OMS says a
// validated fill is, and a fixture that invents its own numbers proves only that arithmetic
// adds up.
//
// The dependency on the OMS is test-only. Production code in this package does not import it,
// and the boundary test in structure_test.go enforces that, because the ledger trusts the OMS
// as an input rather than calling into it.

const (
	integrInstrument = "BTC-USD"
	integrQuote      = "USD"
	integrPortfolio  = "PORT-ALPHA"
	integrVenue      = "VENUE-X"
)

func mustID(t *testing.T, prefix string, n int) contracts.Identifier {
	t.Helper()
	const alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
	var digits []byte
	for v := n; v > 0; v /= 32 {
		digits = append([]byte{alphabet[v%32]}, digits...)
	}
	body := []byte("01jq7x5a")
	for len(body)+len(digits) < 26 {
		body = append(body, '0')
	}
	body = append(body, digits...)
	parsed, err := contracts.ParseIdentifier(prefix + string(body))
	if err != nil {
		t.Fatalf("identifier %q is not canonical: %v", prefix+string(body), err)
	}
	return parsed
}

func mustDec(t *testing.T, s string) contracts.Decimal {
	t.Helper()
	v, err := contracts.ParseDecimal(s)
	if err != nil {
		t.Fatalf("decimal %q is not canonical: %v", s, err)
	}
	return v
}

func mustTS(t *testing.T, s string) contracts.Timestamp {
	t.Helper()
	v, err := contracts.ParseTimestamp(s)
	if err != nil {
		t.Fatalf("timestamp %q is not canonical: %v", s, err)
	}
	return v
}

func mustQty(t *testing.T, s string) contracts.Quantity {
	t.Helper()
	q, err := contracts.NewQuantity(contracts.MustParseDecimal(s), contracts.UnitBaseAsset)
	if err != nil {
		t.Fatalf("quantity %q is not canonical: %v", s, err)
	}
	return q
}

func mustMoney(t *testing.T, s string) contracts.Money {
	t.Helper()
	v, err := contracts.NewMoney(integrQuote, mustDec(t, s))
	if err != nil {
		t.Fatalf("money %q is not canonical: %v", s, err)
	}
	return v
}

func svcActor() oms.Actor {
	return oms.Actor{ID: "svc-order-gateway", Type: contracts.ActorService}
}

// driveToFilled walks a real OMS order through its lifecycle to FILLED and returns it. Every
// step goes through the OMS's own Apply and Observe, so the quantity the ledger is given is
// one the state machine actually produced.
func driveToFilled(t *testing.T, direction oms.Direction, quantity string) oms.Order {
	t.Helper()
	at := mustTS(t, "2026-09-28T10:00:00Z")
	price := mustMoney(t, "30000")

	order, err := oms.Create(oms.NewOrderRequest{
		CommandID:      mustID(t, contracts.PrefixCommand, 1),
		AccountID:      mustID(t, contracts.PrefixPosition, 2),
		StrategyID:     mustID(t, contracts.PrefixStrategy, 3),
		Instrument:     integrInstrument,
		Venue:          integrVenue,
		Market:         "BTC-USD",
		Direction:      direction,
		OrderType:      "LIMIT",
		Quantity:       mustQty(t, quantity),
		LimitPrice:     &price,
		IdempotencyKey: "oms-order-0001",
		RequestedAt:    at,
		Environment:    "paper",
	})
	if err != nil {
		t.Fatalf("oms.Create: %v", err)
	}

	step := func(cmd oms.Command, actor oms.Actor, pre []oms.Precondition) oms.Order {
		t.Helper()
		outcome, err := oms.Apply(order, oms.Request{
			OrderID:                order.OrderID,
			ExpectedVersion:        order.Version,
			Command:                cmd,
			Actor:                  actor,
			PreconditionsSatisfied: pre,
			// Every risk decision must name the reference it came from, so the audit chain
			// reaches the decision that authorised the order.
			RiskReference: "risk-decision-0001",
			At:            at,
		})
		if err != nil {
			t.Fatalf("oms.Apply %s: %v", cmd, err)
		}
		order = outcome.Order
		return order
	}

	step(oms.CmdSubmitForRisk, svcActor(), []oms.Precondition{oms.PreRiskEvaluated})
	step(oms.CmdRecordRiskApproval, svcActor(),
		[]oms.Precondition{oms.PreRiskEvaluated, oms.PreRiskApproved})

	// A limit order needs a price.
	if order.LimitPrice == nil {
		t.Fatal("the fixture order should carry a limit price")
	}

	step(oms.CmdSubmitToVenue, svcActor(),
		[]oms.Precondition{oms.PreRiskApproved, oms.PreNoActiveHalt})

	outcome, err := oms.Observe(order, oms.Observation{
		Kind:             oms.ObsFilled,
		VenueOrderRef:    "VEX-7788",
		CumulativeFilled: mustQty(t, quantity),
		OccurredAt:       at,
		Evidence:         "venue execution report",
	})
	if err != nil {
		t.Fatalf("oms.Observe filled: %v", err)
	}
	order = outcome.Order
	if order.State != oms.StateFilled {
		t.Fatalf("the order is %s after a full fill observation, want FILLED", order.State)
	}
	return order
}

// fillFromOrder turns an OMS order that the state machine has validated into a ledger fill.
// This is the boundary the two authorities meet: the OMS says what executed, and the ledger
// records it.
func fillFromOrder(t *testing.T, order oms.Order, n int) ledger.Fill {
	t.Helper()
	side := ledger.SideBuy
	if order.Direction == oms.DirSell {
		side = ledger.SideSell
	}
	quantity := mustDec(t, order.CumulativeFilled.String())
	price := mustDec(t, order.LimitPrice.Amount().String())
	fee, err := quantity.Multiply(mustDec(t, "0.5"))
	if err != nil {
		t.Fatalf("computing the fee: %v", err)
	}
	return ledger.Fill{
		OrderID:         order.OrderID,
		Instrument:      order.Instrument,
		Side:            side,
		Quantity:        quantity,
		Price:           price,
		QuoteCurrency:   integrQuote,
		Fee:             fee,
		FeeCurrency:     integrQuote,
		Portfolio:       integrPortfolio,
		Venue:           order.Venue,
		VenueOrderRef:   order.VenueOrderRef,
		ExecutedAt:      order.UpdatedAt,
		SourceCommandID: order.CommandID,
		CorrelationID:   order.CommandID,
		IdempotencyKey:  "fill-" + order.OrderID.String(),
	}
}

// TestTheLedgerPositionEqualsTheOmsValidatedQuantity is WI-116 AC4 driven end to end.
func TestTheLedgerPositionEqualsTheOmsValidatedQuantity(t *testing.T) {
	order := driveToFilled(t, oms.DirBuy, "2.5")
	store := ledger.NewMemoryStore()

	fill := fillFromOrder(t, order, 1)
	entry, err := ledger.EntriesForFill(fill, mustID(t, contracts.PrefixLedger, 10),
		mustTS(t, "2026-09-28T10:00:01Z"))
	if err != nil {
		t.Fatalf("EntriesForFill: %v", err)
	}
	if _, err := store.Append(entry); err != nil {
		t.Fatalf("Append: %v", err)
	}

	position, err := ledger.Position(store, order.Instrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	cmp, err := position.Cmp(mustDec(t, "2.5"))
	if err != nil {
		t.Fatalf("Cmp: %v", err)
	}
	if cmp != 0 {
		t.Errorf("the ledger holds %s, the OMS validated %s", position, order.CumulativeFilled)
	}

	// And the reconciliation itself, run the way an operator would run it.
	differences, err := ledger.ReconcilePositions(store, map[string]contracts.Decimal{
		order.Instrument: mustDec(t, order.CumulativeFilled.String()),
	})
	if err != nil {
		t.Fatalf("ReconcilePositions: %v", err)
	}
	if err := ledger.RequireReconciled(differences); err != nil {
		t.Errorf("a ledger fed from the OMS's own validated fill reported a break: %v", err)
	}
}

// TestTheVenueReferenceNeverReplacesTheOmsIdentity proves the one-canonical-identity rule
// holds across the two authorities, which is where it would be most likely to break: the
// venue's reference is the one identifier both sides can see, and it is the wrong one.
func TestTheVenueReferenceNeverReplacesTheOmsIdentity(t *testing.T) {
	order := driveToFilled(t, oms.DirBuy, "1")
	if order.VenueOrderRef == "" {
		t.Fatal("the fixture order should carry the venue's reference")
	}
	store := ledger.NewMemoryStore()
	entry, err := ledger.EntriesForFill(fillFromOrder(t, order, 1),
		mustID(t, contracts.PrefixLedger, 11), mustTS(t, "2026-09-28T10:00:01Z"))
	if err != nil {
		t.Fatalf("EntriesForFill: %v", err)
	}
	stored, err := store.Append(entry)
	if err != nil {
		t.Fatalf("Append: %v", err)
	}
	if stored.EntryID.String() == order.VenueOrderRef {
		t.Error("the venue's reference became the ledger entry identity")
	}
	if stored.EntryID.Prefix() != contracts.PrefixLedger {
		t.Errorf("the ledger entry identity is %s, want a canonical ledger identity", stored.EntryID)
	}
}

// TestAShortValidatedFillReachesTheLedgerWithoutInvertingThePosition checks the sell side
// through the real state machine, because a position that can only grow is not a position.
func TestAShortValidatedFillReachesTheLedgerWithoutInvertingThePosition(t *testing.T) {
	order := driveToFilled(t, oms.DirSell, "3")
	store := ledger.NewMemoryStore()
	entry, err := ledger.EntriesForFill(fillFromOrder(t, order, 1),
		mustID(t, contracts.PrefixLedger, 12), mustTS(t, "2026-09-28T10:00:01Z"))
	if err != nil {
		t.Fatalf("EntriesForFill: %v", err)
	}
	if _, err := store.Append(entry); err != nil {
		t.Fatalf("Append: %v", err)
	}

	position, err := ledger.Position(store, order.Instrument)
	if err != nil {
		t.Fatalf("Position: %v", err)
	}
	if position.Sign() >= 0 {
		t.Errorf("a validated sell left a position of %s, want a short", position)
	}
	differences, err := ledger.ReconcilePositions(store, map[string]contracts.Decimal{
		order.Instrument: mustDec(t, "-3"),
	})
	if err != nil {
		t.Fatalf("ReconcilePositions: %v", err)
	}
	if len(differences) != 0 {
		t.Errorf("a ledger fed from a validated sell reported %v", differences)
	}
}

// TestARefusedOmsOrderNeverReachesTheLedger is the authority boundary from the other
// side. The ledger has no path that accepts an order the state machine has not driven to a
// terminal fill, because the fill type requires the OMS order identity and the OMS only
// reports a cumulative fill once it has validated one.
func TestARefusedOmsOrderNeverReachesTheLedger(t *testing.T) {
	// A rejected order carries no validated fill at all: the OMS gives it a rejection
	// reference and no cumulative quantity, and a ledger fill requires the latter.
	rejected, err := oms.Create(oms.NewOrderRequest{
		CommandID:      mustID(t, contracts.PrefixCommand, 21),
		AccountID:      mustID(t, contracts.PrefixPosition, 22),
		StrategyID:     mustID(t, contracts.PrefixStrategy, 23),
		Instrument:     integrInstrument,
		Venue:          integrVenue,
		Market:         "BTC-USD",
		Direction:      oms.DirBuy,
		OrderType:      "LIMIT",
		Quantity:       mustQty(t, "1"),
		IdempotencyKey: "oms-order-0002",
		RequestedAt:    mustTS(t, "2026-09-28T10:00:00Z"),
		Environment:    "paper",
	})
	if err != nil {
		t.Fatalf("oms.Create: %v", err)
	}
	outcome, err := oms.Apply(rejected, oms.Request{
		OrderID:                rejected.OrderID,
		ExpectedVersion:        rejected.Version,
		Command:                oms.CmdSubmitForRisk,
		Actor:                  svcActor(),
		PreconditionsSatisfied: []oms.Precondition{oms.PreRiskEvaluated},
		At:                     mustTS(t, "2026-09-28T10:00:00Z"),
	})
	if err != nil {
		t.Fatalf("oms.Apply: %v", err)
	}
	afterRisk, err := oms.Apply(outcome.Order, oms.Request{
		OrderID:                outcome.Order.OrderID,
		ExpectedVersion:        outcome.Order.Version,
		Command:                oms.CmdRecordRiskRejection,
		Actor:                  svcActor(),
		RiskReference:          "risk-decision-0002",
		PreconditionsSatisfied: []oms.Precondition{oms.PreRiskEvaluated, oms.PreRiskRejected},
		At:                     mustTS(t, "2026-09-28T10:00:00Z"),
	})
	if err != nil {
		t.Fatalf("oms.Apply record risk rejection: %v", err)
	}
	if afterRisk.Order.State != oms.StateRejected {
		t.Fatalf("the order is %s after a risk rejection, want REJECTED", afterRisk.Order.State)
	}
	if !afterRisk.Order.CumulativeFilled.Value().IsZero() {
		t.Errorf("a risk-rejected order reports a cumulative fill of %s; the Risk Engine "+
			"refused it, so nothing executed and there is nothing to post",
			afterRisk.Order.CumulativeFilled)
	}

	// The point that matters: a rejected order has no validated fill, so there is nothing
	// the ledger could be given. A fill carrying that zero quantity is refused outright,
	// because "the OMS says zero executed" and "nobody said" are different claims and only
	// one of them may become a financial fact.
	store := ledger.NewMemoryStore()
	_, err = ledger.EntriesForFill(ledger.Fill{
		OrderID:         afterRisk.Order.OrderID,
		Instrument:      integrInstrument,
		Side:            ledger.SideBuy,
		Quantity:        mustDec(t, "0"),
		Price:           mustDec(t, "30000"),
		QuoteCurrency:   integrQuote,
		Fee:             contracts.Zero(),
		Portfolio:       integrPortfolio,
		Venue:           integrVenue,
		ExecutedAt:      mustTS(t, "2026-09-28T10:00:00Z"),
		SourceCommandID: afterRisk.Order.CommandID,
		CorrelationID:   afterRisk.Order.CommandID,
		IdempotencyKey:  "fill-empty",
	}, mustID(t, contracts.PrefixLedger, 13), mustTS(t, "2026-09-28T10:00:01Z"))
	if err == nil {
		t.Error("a fill with no executed quantity must be refused; the OMS validated nothing")
	}
	if n, _ := store.Len(); n != 0 {
		t.Errorf("the ledger holds %d entries after a refused fill", n)
	}
}
