package riskengine

import (
	"fmt"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The arithmetic in this file is exact integer decimal arithmetic throughout, chosen over
// float because every one of these comparisons is a boundary decision. At a boundary a
// float and a decimal can disagree by a unit in the last place, and the disagreement lands
// exactly where a limit flips from pass to fail.

// notional is the order's own size: price times quantity.
//
// The engine computes it rather than accepting it from the caller. A caller-supplied
// notional would be a command asserting its own compliance with a limit, which is the
// control evaluating itself.
func (i Intent) notional() (contracts.Money, error) {
	if !i.HasPriceConstraint() {
		return contracts.Money{}, reject(contracts.CodeValidation,
			"a market order has no price, so its notional cannot be computed; a market order "+
				"must be priced against the venue before it can be notional-bounded")
	}
	// The product is exact integer decimal arithmetic: the coefficients multiply and the
	// scales add. No step converts through a float, because at a limit boundary a float can
	// disagree with the true value in the last place and flip a pass into a fail.
	product, err := i.LimitPrice.Amount().Multiply(i.Quantity.Value())
	if err != nil {
		return contracts.Money{}, err
	}
	return contracts.NewMoney(i.LimitPrice.Currency(), product)
}

// resultingPosition is the signed position after this order, in base units.
func resultingPosition(i Intent, current PositionSnapshot) (contracts.Quantity, error) {
	// The current quantity is a signed decimal. Applying the order's direction to the order
	// size gives the delta, and the delta is added rather than assigned, so a sell against a
	// long position reduces it instead of replacing it.
	delta, err := i.Quantity.Value().Multiply(decimalFromSign(i.Direction.Sign()))
	if err != nil {
		return contracts.Quantity{}, err
	}
	updated, err := current.Quantity.Value().Add(delta)
	if err != nil {
		return contracts.Quantity{}, err
	}
	return contracts.NewQuantity(updated, current.Quantity.Unit())
}

// netExposure applies the order to current net exposure.
//
// Net exposure is positive when the account is net long, so a buy increases it and a sell
// decreases it. That is why the notional is signed by the order's direction and then added:
//
//	resulting = current + notional * sign(direction)
//
// The sign is what makes a sell risk-reducing. Writing this as a subtraction of a signed
// notional inverts it, which would make a sell *increase* net exposure and would then reject
// precisely the trades that reduce risk, while admitting a long that the limit exists to
// prevent.
func netExposure(i Intent, current contracts.Money, notional contracts.Money) (contracts.Money, error) {
	if err := current.RequireSameCurrency(notional); err != nil {
		return contracts.Money{}, err
	}
	signed, err := notional.Amount().Multiply(decimalFromSign(i.Direction.Sign()))
	if err != nil {
		return contracts.Money{}, err
	}
	outbound, err := contracts.NewMoney(notional.Currency(), signed)
	if err != nil {
		return contracts.Money{}, err
	}
	return current.Add(outbound)
}

// moneyFromDecimal builds a Money from an exact decimal, refusing an unset value.
func moneyFromDecimal(currency string, d contracts.Decimal) (contracts.Money, error) {
	if !d.IsSet() {
		return contracts.Money{}, reject(contracts.CodeValidation, "cannot build money from an unset decimal")
	}
	return contracts.NewMoney(currency, d)
}

// absoluteMoney returns the absolute value of an amount, preserving the currency.
func absoluteMoney(m contracts.Money) contracts.Money {
	if m.Amount().Sign() < 0 {
		// Neg returns the same scale, so the construction cannot fail on scale grounds. An
		// error here would still mean the input was invalid, and returning zero makes every
		// downstream limit comparison fail, which is the safe direction.
		negated, err := moneyFromDecimal(m.Currency(), m.Amount().Neg())
		if err != nil {
			return contracts.Money{}
		}
		return negated
	}
	return m
}

// absoluteQuantity returns the magnitude of a position, preserving the unit.
func absoluteQuantity(q contracts.Quantity) contracts.Quantity {
	if q.Value().Sign() < 0 {
		negated, err := contracts.NewQuantity(q.Value().Neg(), q.Unit())
		if err != nil {
			// Returning the zero value here would compare as a valid empty position, so an
			// explicit failure marker is used instead: an unset Quantity is not set, and
			// callers must handle that. The controls treat an unset quantity as a rejection.
			return contracts.Quantity{}
		}
		return negated
	}
	return q
}

// decimalFromSign returns the exact decimal 1 or -1.
func decimalFromSign(sign int) contracts.Decimal {
	if sign < 0 {
		return contracts.MustParseDecimal("-1")
	}
	return contracts.MustParseDecimal("1")
}

// Binding is the fingerprint an approval is valid for.
//
// docs/17 section 4 requires a risk approval to be "bound to the exact command, instrument,
// quantity, price constraints, account, environment, and policy revision" and states that
// "any material change invalidates approval and requires reevaluation". Binding is that
// fingerprint. It is a value type with only comparable fields so two bindings can be compared
// directly, and it deliberately contains nothing a caller could vary without that being
// visible as a different binding.
type Binding struct {
	// CommandID is the exact command.
	CommandID contracts.Identifier
	// AccountID and StrategyID identify the actor of the order.
	AccountID  contracts.Identifier
	StrategyID contracts.Identifier
	// Instrument, Venue, and Market fix what is traded and where.
	Instrument string
	Venue      string
	Market     string
	// Direction, OrderType, Quantity, and Price fix the order itself.
	Direction Direction
	OrderType string
	Quantity  string
	// HasPrice records whether a price constraint was bound. An approval with no price
	// constraint must not authorise one that has a price, and the reverse is equally true,
	// so absence is recorded rather than inferred from an empty string.
	HasPrice bool
	Price    string
	PriceCur string
	// Environment and PolicyRevision fix the scope the decision was made in.
	Environment    string
	PolicyRevision string
}

// bind derives the binding for a command.
func (i Intent) bind(policy Policy) Binding {
	b := Binding{
		CommandID:      i.CommandID,
		AccountID:      i.AccountID,
		StrategyID:     i.StrategyID,
		Instrument:     i.Instrument,
		Venue:          i.Venue,
		Market:         i.Market,
		Direction:      i.Direction,
		OrderType:      i.OrderType,
		Quantity:       i.Quantity.String(),
		HasPrice:       i.HasPriceConstraint(),
		Environment:    i.Environment,
		PolicyRevision: policy.Revision,
	}
	if i.LimitPrice != nil {
		b.Price = i.LimitPrice.String()
		b.PriceCur = i.LimitPrice.Currency()
	}
	return b
}

// Equal reports whether two bindings are identical.
func (b Binding) Equal(other Binding) bool { return b == other }

// Diff returns the fields that differ, in a fixed order, so a refusal can name what changed
// without leaking the values themselves.
func (b Binding) Diff(other Binding) []string {
	var out []string
	if b.CommandID != other.CommandID {
		out = append(out, "command_id")
	}
	if b.AccountID != other.AccountID {
		out = append(out, "account_id")
	}
	if b.StrategyID != other.StrategyID {
		out = append(out, "strategy_id")
	}
	if b.Instrument != other.Instrument {
		out = append(out, "instrument")
	}
	if b.Venue != other.Venue {
		out = append(out, "venue")
	}
	if b.Market != other.Market {
		out = append(out, "market")
	}
	if b.Direction != other.Direction {
		out = append(out, "direction")
	}
	if b.OrderType != other.OrderType {
		out = append(out, "order_type")
	}
	if b.Quantity != other.Quantity {
		out = append(out, "quantity")
	}
	if b.HasPrice != other.HasPrice {
		out = append(out, "price_constraint_presence")
	}
	if b.Price != other.Price {
		out = append(out, "price")
	}
	if b.PriceCur != other.PriceCur {
		out = append(out, "price_currency")
	}
	if b.Environment != other.Environment {
		out = append(out, "environment")
	}
	if b.PolicyRevision != other.PolicyRevision {
		out = append(out, "policy_revision")
	}
	return out
}

// Approval is a short-lived risk approval for exactly one command.
type Approval struct {
	// Binding is the fingerprint the approval is valid for.
	Binding Binding
	// IssuedAt is when it was granted.
	IssuedAt contracts.Timestamp
	// ExpiresAt is when it stops being valid.
	ExpiresAt contracts.Timestamp
	// PolicyRevision is carried separately from the binding for the audit record, so a
	// reviewer does not have to know the binding layout to read the result.
	PolicyRevision string
	// EvaluatedFacts is a count of the controls that passed, for the audit record.
	EvaluatedFacts int
}

// issueApproval grants an approval for an evaluated command.
func issueApproval(ic Intent, facts Facts, policy Policy, lifetime time.Duration) (Approval, error) {
	expires := facts.Now.Time().Add(lifetime)
	if expires.Before(facts.Now.Time()) {
		// A lifetime so large that the expiry wraps would produce an approval that never
		// expires, which is the opposite of short-lived. Refusing beats clamping, because a
		// clamped expiry is a guess about a limit the policy author did not state.
		return Approval{}, reject(contracts.CodeValidation,
			"approval lifetime %s overflows the evaluation time; an approval that cannot "+
				"expire is not short-lived", lifetime)
	}
	return Approval{
		Binding:        ic.bind(policy),
		IssuedAt:       facts.Now,
		ExpiresAt:      contracts.TimestampFrom(expires),
		PolicyRevision: policy.Revision,
		EvaluatedFacts: len(mandatoryControls),
	}, nil
}

// ValidAt reports whether the approval is unexpired at the given time.
func (a Approval) ValidAt(at contracts.Timestamp) bool {
	return !a.IsZero() && !at.Before(a.IssuedAt) && at.Before(a.ExpiresAt)
}

// IsZero reports whether the approval is unset.
func (a Approval) IsZero() bool { return a.Binding.CommandID.IsZero() }

// Permits reports whether the approval authorises the given command, with a reason when it
// does not.
//
// Every condition is checked: the binding must match exactly, the approval must be
// unexpired, and the evaluation time must not precede issue. The binding comparison is what
// makes a material change require reevaluation rather than being silently carried over.
func (a Approval) Permits(ic Intent, policy Policy, at contracts.Timestamp) (bool, string) {
	if a.IsZero() {
		return false, "no risk approval exists for this command"
	}
	if at.Before(a.IssuedAt) {
		return false, fmt.Sprintf("approval was issued at %s, in the future relative to %s",
			a.IssuedAt, at)
	}
	if !at.Before(a.ExpiresAt) {
		return false, fmt.Sprintf("risk approval expired at %s; docs/17 section 4 requires a "+
			"short-lived approval", a.ExpiresAt)
	}
	if a.PolicyRevision != policy.Revision {
		return false, fmt.Sprintf("approval was issued against policy revision %s but the "+
			"active revision is %s", a.PolicyRevision, policy.Revision)
	}
	wanted := ic.bind(policy)
	if !a.Binding.Equal(wanted) {
		changed := a.Binding.Diff(wanted)
		return false, fmt.Sprintf("approval does not cover this command; %d field(s) differ: %v; "+
			"docs/17 section 4 requires reevaluation after a material change",
			len(changed), changed)
	}
	return true, ""
}

// Permit is the capability the submission path requires.
//
// It cannot be constructed except from a valid approval, so the OMS has nothing to accept
// unless the Risk Engine granted one. That is the mechanical form of "a risk-rejected
// command creates no live submission": a rejected evaluation returns a nil Approval, and a
// nil approval cannot produce a Permit.
type Permit struct {
	// Approval is the approval the permit was derived from, retained so the submission can
	// be audited back to the exact decision.
	Approval Approval
	// CommandID is the command the permit covers.
	CommandID contracts.Identifier
	// ExpiresAt bounds the permit itself, so a submission cannot be deferred past the
	// approval's lifetime.
	ExpiresAt contracts.Timestamp
}

// SubmissionRequest is a request to submit an order to a venue.
type SubmissionRequest struct {
	// CommandID is the command being submitted.
	CommandID contracts.Identifier
	// CorrelationID ties the submission to the request.
	CorrelationID contracts.Identifier
	// Venue is the target venue.
	Venue string
	// IssuedAt is when the submission was attempted.
	IssuedAt contracts.Timestamp
}

// GrantPermit derives a permit for a submission, or refuses.
//
// This is the only constructor of Permit. Everything it checks is a property the Risk Engine
// established: that the command was approved, that the approval is unexpired, that the
// approval covers this exact command, and that the policy revision has not moved.
func GrantPermit(result Result, ic Intent, policy Policy, at contracts.Timestamp) (Permit, error) {
	if result.Verdict != Approved {
		return Permit{}, reject(contracts.CodeRiskRejected,
			"command %s was rejected by %d control(s) and no permit can be granted",
			ic.CommandID, len(result.Failures))
	}
	if result.Approval == nil {
		return Permit{}, reject(contracts.CodeInternal,
			"result claims approval but carries no approval; the evaluation and the result "+
				"disagree, which is a defect rather than a risk decision")
	}
	ok, reason := result.Approval.Permits(ic, policy, at)
	if !ok {
		return Permit{}, reject(contracts.CodeRiskRejected, "%s", reason)
	}
	if result.CommandID != ic.CommandID {
		return Permit{}, reject(contracts.CodeInternal,
			"approval was issued for command %s but the submission is for %s",
			result.CommandID, ic.CommandID)
	}
	return Permit{
		Approval:  *result.Approval,
		CommandID: ic.CommandID,
		ExpiresAt: result.Approval.ExpiresAt,
	}, nil
}

// Admit reports whether a submission may proceed to a venue.
//
// It is the final gate and it is intentionally dull: it re-checks expiry and the permit's
// own command binding, and it requires the request to name the same command. A submission
// that arrives without a permit is refused, which is what makes the permit load-bearing
// rather than advisory.
func (p Permit) Admit(req SubmissionRequest, at contracts.Timestamp) error {
	if p.Approval.IsZero() {
		return reject(contracts.CodeRiskRejected,
			"no permit was presented, so the submission is refused; a live submission requires "+
				"a risk approval, and no other path creates one")
	}
	if req.CommandID != p.CommandID {
		return reject(contracts.CodeRiskRejected,
			"permit covers command %s but the submission names %s", p.CommandID, req.CommandID)
	}
	if req.Venue == "" {
		return reject(contracts.CodeValidation, "submission names no venue")
	}
	if req.CorrelationID.IsZero() {
		return reject(contracts.CodeValidation, "submission has no correlation id")
	}
	if !at.Before(p.ExpiresAt) {
		return reject(contracts.CodeRiskRejected,
			"permit expired at %s; a submission may not be deferred past the approval's lifetime",
			p.ExpiresAt)
	}
	return nil
}
