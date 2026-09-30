package riskengine

import (
	"fmt"
	"strings"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// The fifteen mandatory controls from docs/04 section "Risk gate".
//
// Each one is fail-closed. Where a source cannot be read, the control consults the policy's
// OnMissing for that control rather than assuming either answer, and the default state of
// every Fact is unavailable, so a caller that forgets to measure something gets a rejection.

// threshold renders a control's configured limit, for the report.
func threshold(policy Policy, id ControlID) string {
	c, ok := policy.Lookup(id)
	if !ok {
		return "unset"
	}
	return c.Describe()
}

// resolve applies a control's missing-data policy to a fact.
//
// It returns the value and whether the control may proceed. A control that may not proceed
// still has to produce a result, so the caller supplies the reason. The split exists so
// that "the source was unreadable" and "the source was read and said no" stay distinguishable
// in the report.
func resolve[T any](c Control, fact Fact[T]) (T, bool, string) {
	if fact.Available {
		return fact.Value, true, ""
	}
	if c.OnMissing == OnMissingUseLastKnown {
		// The last known value is the value that was last recorded, which is the same value
		// the fact carries. Proceeding here is therefore not a permission: it only says the
		// control is evaluating against a value that is no longer being confirmed.
		return fact.Value, true, ""
	}
	var zero T
	return zero, false, "source is unavailable and the control requires a live source"
}

// checkAccountAuthorization covers "account and environment authorization".
func checkAccountAuthorization(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlAccountAuthorization
	if facts.Account.Available && !facts.Account.Value.SubjectEnabled {
		return fail(id, "account is not enabled for risk-increasing actions; a new account "+
			"starts disabled", "disabled", "enabled")
	}
	if facts.Account.Available && facts.Account.Value.SubjectEnabled {
		// The environment must match the policy's own environment. A command minted for one
		// environment and evaluated against a policy for another is a confused deputy, and
		// the mismatch is what a cross-environment replay looks like.
		if ic.Environment != policy.Environment {
			return fail(id, fmt.Sprintf(
				"command targets environment %s but policy revision %s is scoped to %s",
				ic.Environment, policy.Revision, policy.Environment), ic.Environment, policy.Environment)
		}
		return pass(id, "authorized", policy.Environment)
	}
	// The account state is the source for this control, and the control's own missing-data
	// policy is not consulted for an authorization fact: docs/25 invariant 10 requires
	// denying new risk-increasing activity when authoritative state cannot be established.
	// An authorization control that could be satisfied by an unreadable account is not an
	// authorization control.
	return unavailable(id, "account state could not be read; authoritative state is "+
		"unavailable so new risk is denied", "enabled")
}

// checkStrategyDeployment covers "strategy deployment status".
func checkStrategyDeployment(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlStrategyDeployment
	switch facts.StrategyStatus {
	case StatusDeployed:
		return pass(id, "deployed", "deployed")
	case StatusUnknown:
		// An unknown status is a rejection rather than an optimistic default, which is the
		// fail-safe reading of a lifecycle state the platform has lost.
		return fail(id, "strategy deployment status could not be established; an unknown "+
			"status is not treated as deployed", "unknown", "deployed")
	case StatusNotDeployed, StatusPaused, StatusRetired:
		return fail(id, fmt.Sprintf("strategy is %s, not deployed", facts.StrategyStatus),
			string(facts.StrategyStatus), "deployed")
	default:
		return fail(id, fmt.Sprintf("unknown deployment status %q", facts.StrategyStatus),
			string(facts.StrategyStatus), "deployed")
	}
}

// checkInstrumentEligibility covers "instrument eligibility".
func checkInstrumentEligibility(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlInstrumentEligibility
	if !facts.Instrument.Available {
		return unavailable(id, "instrument state could not be read", "eligible")
	}
	if !facts.Instrument.Value.Eligible {
		return fail(id, fmt.Sprintf("instrument %s is not eligible", ic.Instrument),
			"not eligible", "eligible")
	}
	if !permitsListed(policy.PermittedInstruments, ic.Instrument) {
		return fail(id, fmt.Sprintf("instrument %s is not in the policy's permitted instruments",
			ic.Instrument), ic.Instrument, strings.Join(policy.PermittedInstruments, ","))
	}
	if !permitsListed(policy.PermittedMarkets, ic.Market) {
		return fail(id, fmt.Sprintf("market %s is not in the policy's permitted markets",
			ic.Market), ic.Market, strings.Join(policy.PermittedMarkets, ","))
	}
	if !permitsListed(policy.PermittedOrderTypes, ic.OrderType) {
		return fail(id, fmt.Sprintf("order type %s is not permitted", ic.OrderType),
			ic.OrderType, strings.Join(policy.PermittedOrderTypes, ","))
	}
	if !permitsListed(policy.PermittedDirections, string(ic.Direction)) {
		return fail(id, fmt.Sprintf("direction %s is not permitted", ic.Direction),
			string(ic.Direction), strings.Join(policy.PermittedDirections, ","))
	}
	return pass(id, "eligible", "eligible")
}

// checkVenueAvailability covers "venue availability".
func checkVenueAvailability(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlVenueAvailability
	switch facts.Venue {
	case VenueAvailable:
	case VenueHalted:
		return fail(id, fmt.Sprintf("venue %s is halted", ic.Venue), "halted", "available")
	case VenueUnavailable:
		return unavailable(id, fmt.Sprintf("venue %s is unavailable", ic.Venue), "available")
	default:
		return fail(id, fmt.Sprintf("unknown venue status %q", facts.Venue),
			string(facts.Venue), "available")
	}
	// A venue the policy does not list is refused even when it is technically reachable.
	// Reachability is not authorisation, and conflating them is how an unlisted venue
	// receives live orders.
	if !permitsListed(policy.PermittedVenues, ic.Venue) {
		return fail(id, fmt.Sprintf("venue %s is not in the policy's permitted venues", ic.Venue),
			ic.Venue, strings.Join(policy.PermittedVenues, ","))
	}
	if !facts.VenueListed {
		return fail(id, fmt.Sprintf("venue %s is listed in policy but not known to the platform",
			ic.Venue), ic.Venue, "known")
	}
	return pass(id, "available", "available")
}

// checkPricePrecision covers "price and quantity precision".
//
// Precision is compared against the instrument's declared scales using the canonical
// validators, rather than by reading a scale field off the command. The command's own decimal
// already carries its scale, so a separate declared-scale field would be a second statement of
// the same thing that could disagree with the first.
func checkPricePrecision(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlPricePrecision
	if !facts.Market.Available || !facts.Instrument.Available {
		return unavailable(id, "market or instrument state could not be read", "declared precision")
	}
	instrument := facts.Instrument.Value
	if instrument.PricePrecision < 0 || instrument.QuantityPrecision < 0 {
		return fail(id, fmt.Sprintf(
			"instrument declares negative precision (price %d, quantity %d); unknown "+
				"precision cannot be assumed", instrument.PricePrecision, instrument.QuantityPrecision),
			fmt.Sprintf("price %d, quantity %d", instrument.PricePrecision, instrument.QuantityPrecision),
			"non-negative")
	}

	// A market order carries no price constraint, so there is no price precision to check.
	// That is a legitimate pass rather than a skipped check, and it is recorded as such.
	if ic.LimitPrice != nil {
		if err := ic.LimitPrice.ValidatePrecisionAgainst(instrument.PricePrecision); err != nil {
			return fail(id, fmt.Sprintf("limit price precision does not match the instrument: %v", err),
				ic.LimitPrice.String(), fmt.Sprintf("scale %d", instrument.PricePrecision))
		}
	}

	if err := ic.Quantity.ValidateVenuePrecision(instrument.QuantityPrecision); err != nil {
		return fail(id, fmt.Sprintf("order quantity precision does not match the instrument: %v", err),
			ic.Quantity.String(), fmt.Sprintf("scale %d", instrument.QuantityPrecision))
	}

	// The venue's declared precision is a second, independent statement of the same thing.
	// Disagreement between the instrument and the venue is a data problem, and applying
	// either one silently would decide rounding on the venue's behalf.
	if instrument.PricePrecision != facts.Market.Value.Precision {
		return fail(id, fmt.Sprintf(
			"instrument declares price scale %d but the venue declares %d; disagreeing "+
				"precision is a rejection, not a choice of one",
			instrument.PricePrecision, facts.Market.Value.Precision),
			fmt.Sprintf("venue scale %d", facts.Market.Value.Precision),
			fmt.Sprintf("instrument scale %d", instrument.PricePrecision))
	}
	return pass(id, fmt.Sprintf("price scale %d, quantity scale %d",
		instrument.PricePrecision, instrument.QuantityPrecision),
		fmt.Sprintf("instrument price %d, quantity %d",
			instrument.PricePrecision, instrument.QuantityPrecision))
}

// checkNotionalLimits covers "notional limits".
func checkNotionalLimits(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlNotionalLimits
	control := policy.Controls[id]
	limit := threshold(policy, id)

	// The notional is the command's own size, which the engine computes rather than accepts
	// from the caller. Accepting a caller-supplied notional would let a command assert its
	// own compliance with a limit, which is the control evaluating itself.
	notional, err := ic.notional()
	if err != nil {
		return fail(id, fmt.Sprintf("command notional could not be computed: %v", err),
			"uncomputable", limit)
	}
	if !facts.Market.Available {
		if control.OnMissing != OnMissingUseLastKnown {
			return unavailable(id, "market price could not be read", limit)
		}
		// Without a price there is no notional, and the last known notional is not
		// something the command carries. There is nothing to fall back to.
		return unavailable(id, "market price could not be read, so the notional cannot be "+
			"computed even from a last known price", limit)
	}
	ok, err := control.permitsAmount(notional)
	if err != nil {
		return fail(id, err.Error(), notional.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("order notional exceeds the %s control", id),
			notional.String(), limit)
	}
	return pass(id, notional.String(), limit)
}

// checkPositionLimits covers "position limits".
func checkPositionLimits(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlPositionLimits
	control := policy.Controls[id]
	limit := threshold(policy, id)
	value, proceed, reason := resolve(control, facts.Position)
	if !proceed {
		return unavailable(id, reason, limit)
	}

	// The resulting position is the current position plus the signed order. Comparing the
	// current position against the limit would let an order that brings the account back
	// inside the limit be refused, and would let one that pushes it outside pass.
	resulting, err := resultingPosition(ic, value)
	if err != nil {
		return fail(id, fmt.Sprintf("resulting position could not be computed: %v", err),
			"uncomputable", limit)
	}
	absolute := absoluteQuantity(resulting)
	ok, err := control.permitsQuantity(absolute)
	if err != nil {
		return fail(id, err.Error(), absolute.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("resulting position %s exceeds the %s control",
			absolute.String(), id), absolute.String(), limit)
	}
	return pass(id, absolute.String(), limit)
}

// checkExposureLimits covers "exposure limits".
func checkExposureLimits(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlExposureLimits
	control := policy.Controls[id]
	limit := threshold(policy, id)
	value, proceed, reason := resolve(control, facts.Position)
	if !proceed {
		return unavailable(id, reason, limit)
	}
	notional, err := ic.notional()
	if err != nil {
		return fail(id, fmt.Sprintf("command notional could not be computed: %v", err),
			"uncomputable", limit)
	}
	// Gross exposure only grows, so the resulting gross is the sum regardless of direction.
	gross, err := value.GrossExposure.Add(notional)
	if err != nil {
		return fail(id, fmt.Sprintf("resulting gross exposure could not be computed: %v", err),
			"uncomputable", limit)
	}
	ok, err := control.permitsAmount(gross)
	if err != nil {
		return fail(id, err.Error(), gross.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("resulting gross exposure %s exceeds the %s control",
			gross.String(), id), gross.String(), limit)
	}
	// Net exposure is signed, so a sell against a long position reduces it. This is the one
	// control where the direction changes the arithmetic, and getting it wrong would either
	// block risk-reducing trades or permit a net increase from a sell.
	net, err := netExposure(ic, value.NetExposure, notional)
	if err != nil {
		return fail(id, fmt.Sprintf("resulting net exposure could not be computed: %v", err),
			"uncomputable", limit)
	}
	absolute := absoluteMoney(net)
	ok, err = control.permitsAmount(absolute)
	if err != nil {
		return fail(id, err.Error(), absolute.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("resulting net exposure %s exceeds the %s control",
			absolute.String(), id), absolute.String(), limit)
	}
	return pass(id, "gross "+gross.String()+", net "+absolute.String(), limit)
}

// checkConcentrationLimits covers "concentration limits".
func checkConcentrationLimits(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlConcentrationLimits
	control := policy.Controls[id]
	limit := threshold(policy, id)
	value, proceed, reason := resolve(control, facts.Position)
	if !proceed {
		return unavailable(id, reason, limit)
	}
	observed := value.Concentration
	ok, err := permitsDecimal(control, observed)
	if err != nil {
		return fail(id, err.Error(), observed.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("concentration %s exceeds the %s control", observed, id),
			observed.String(), limit)
	}
	return pass(id, observed.String(), limit)
}

// checkLeverageLimits covers "leverage limits".
func checkLeverageLimits(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlLeverageLimits
	control := policy.Controls[id]
	limit := threshold(policy, id)
	value, proceed, reason := resolve(control, facts.Position)
	if !proceed {
		return unavailable(id, reason, limit)
	}
	ok, err := permitsDecimal(control, value.Leverage)
	if err != nil {
		return fail(id, err.Error(), value.Leverage.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("leverage %s exceeds the %s control", value.Leverage, id),
			value.Leverage.String(), limit)
	}
	return pass(id, value.Leverage.String(), limit)
}

// checkLossDrawdown covers "loss and drawdown controls".
func checkLossDrawdown(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlLossDrawdown
	control := policy.Controls[id]
	limit := threshold(policy, id)
	value, proceed, reason := resolve(control, facts.Position)
	if !proceed {
		return unavailable(id, reason, limit)
	}

	// The control is amount-denominated, so it bounds realised loss. Realised loss is
	// recorded as a negative contribution, so the amount compared is the absolute value of
	// a loss and a positive balance contributes nothing rather than offsetting a loss.
	loss := absoluteMoney(value.RealisedLossInWindow)
	ok, err := control.permitsAmount(loss)
	if err != nil {
		return fail(id, err.Error(), loss.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("realised loss %s exceeds the %s control", loss, id),
			loss.String(), limit)
	}

	// Drawdown is a separate ratio with its own policy-level threshold, because realised
	// loss and drawdown share one mandatory control id while being denominated differently.
	ok, err = permitsRatio(value.Drawdown, policy.DrawdownThreshold)
	if err != nil {
		return fail(id, err.Error(), value.Drawdown.String(), "drawdown threshold "+policy.DrawdownThreshold.String())
	}
	if !ok {
		return fail(id, fmt.Sprintf("drawdown %s exceeds the policy drawdown threshold %s",
			value.Drawdown, policy.DrawdownThreshold), value.Drawdown.String(),
			"drawdown threshold "+policy.DrawdownThreshold.String())
	}
	return pass(id, "loss "+loss.String()+", drawdown "+value.Drawdown.String(), limit)
}

// checkMarketDataStale covers "stale market-data controls".
func checkMarketDataStale(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlMarketDataStale
	limit := threshold(policy, id)
	if !facts.Market.Available {
		return unavailable(id, "market snapshot could not be read", limit)
	}
	// Age is measured from when the venue reported the price, not from when the command was
	// issued. A freshly issued command quoting a stale price is still a stale price, and
	// measuring from the command would let an attacker refresh the age by re-issuing.
	age := facts.Now.Time().Sub(facts.Market.Value.ObservedAt.Time())
	if age < 0 {
		return fail(id, "market snapshot is dated in the future relative to evaluation time; "+
			"a clock that disagrees with itself cannot establish freshness",
			"future", fmt.Sprintf("max age %s", policy.MarketDataMaxAge))
	}
	if age > policy.MarketDataMaxAge {
		return fail(id, fmt.Sprintf("market data is %s old, beyond the %s freshness limit",
			age, policy.MarketDataMaxAge), age.String(),
			fmt.Sprintf("max age %s", policy.MarketDataMaxAge))
	}
	return pass(id, age.String(), fmt.Sprintf("max age %s", policy.MarketDataMaxAge))
}

// checkDuplicateOrder covers "duplicate-order detection".
func checkDuplicateOrder(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlDuplicateOrder
	limit := threshold(policy, id)
	if facts.DuplicateOf != "" {
		return fail(id, fmt.Sprintf("command duplicates open order %s; docs/04 requires "+
			"reconciliation before any retry that could duplicate exposure", facts.DuplicateOf),
			facts.DuplicateOf, "no duplicate")
	}
	// An unresolved material reconciliation case means the platform cannot establish
	// whether a prior submission took effect, which is exactly the ambiguity docs/04 forbids
	// retrying through.
	if facts.ReconciliationOpen {
		return fail(id, "a material reconciliation case is unresolved, so it cannot be "+
			"established that this order is not a duplicate", "unresolved", "resolved")
	}
	return pass(id, "no duplicate", limit)
}

// checkRateLimits covers "rate and throttle limits".
func checkRateLimits(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlRateLimits
	control := policy.Controls[id]
	limit := threshold(policy, id)
	value, proceed, reason := resolve(control, facts.Account)
	if !proceed {
		return unavailable(id, reason, limit)
	}
	// The order being evaluated counts toward the rate, so the comparison is against the
	// count including this command. Comparing against the count before it would permit one
	// order past every boundary.
	orders, err := value.OrdersInWindow.Add(contracts.MustParseDecimal("1"))
	if err != nil {
		return fail(id, fmt.Sprintf("order count could not be computed: %v", err), "uncomputable", limit)
	}
	ok, err := permitsDecimal(control, orders)
	if err != nil {
		return fail(id, err.Error(), orders.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("order rate %s within %s exceeds the %s control",
			orders, policy.RateWindow, id), orders.String(), limit)
	}
	ok, err = permitsDecimal(control, value.CancelsInWindow)
	if err != nil {
		return fail(id, err.Error(), value.CancelsInWindow.String(), limit)
	}
	if !ok {
		return fail(id, fmt.Sprintf("cancel rate %s within %s exceeds the %s control",
			value.CancelsInWindow, policy.RateWindow, id), value.CancelsInWindow.String(), limit)
	}
	return pass(id, "orders "+orders.String()+", cancels "+value.CancelsInWindow.String(), limit)
}

// checkHaltState covers "kill/halt state".
func checkHaltState(ic Intent, facts Facts, policy Policy) ControlResult {
	id := ControlHaltState
	limit := threshold(policy, id)

	// The command is evaluated in the scope of the account it trades for, and a halt at that
	// scope or any broader one stops it. docs/04 states the hierarchy
	// SYSTEM > VENUE > MARKET > STRATEGY > ACCOUNT and docs/25 invariant 9 requires a halt
	// to be monotonic, so this compares ranks rather than testing a single scope.
	blocking := facts.Halts.Blocking(HaltAccount)
	if len(blocking) == 0 {
		return pass(id, "no active halt", limit)
	}
	highest, _ := facts.Halts.Highest()
	names := make([]string, 0, len(blocking))
	for _, r := range blocking {
		names = append(names, string(r.Scope))
	}
	return fail(id, fmt.Sprintf("halt active at %s (%s), which blocks or outranks this command's "+
		"account scope; active halts: %s", highest.Scope, highest.Reason, strings.Join(names, ", ")),
		strings.Join(names, ","), limit)
}

// permitsDecimal compares an observed ratio against a ratio-denominated control.
//
// Concentration and leverage are ratios, and the policy expresses their thresholds as exact
// decimals rather than as percentages, so the comparison never converts through a float.
func permitsDecimal(c Control, observed contracts.Decimal) (bool, error) {
	if c.Ratio == nil {
		return false, reject(contracts.CodeValidation,
			"control %s is not ratio-denominated but the observation is a ratio", c.ID)
	}
	cmp, err := observed.Cmp(*c.Ratio)
	if err != nil {
		return false, err
	}
	// A ratio control is bounded above, so equality passes. The Boundary field on a ratio
	// control is not consulted because an exclusive boundary on a risk ratio would make the
	// documented threshold itself a failing value, which is a confusing way to state a limit.
	return cmp <= 0, nil
}

// permitsRatio compares an observed ratio against a threshold held outside the control
// registry. Every ratio comparison in the engine goes through one exact comparison.
func permitsRatio(observed contracts.Decimal, thresholdRatio contracts.Decimal) (bool, error) {
	if !observed.IsSet() {
		return false, reject(contracts.CodeValidation, "observed ratio is unset")
	}
	if !thresholdRatio.IsSet() {
		return false, reject(contracts.CodeValidation, "ratio threshold is unset")
	}
	cmp, err := observed.Cmp(thresholdRatio)
	if err != nil {
		return false, err
	}
	return cmp <= 0, nil
}
