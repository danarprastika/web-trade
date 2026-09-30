package config

import (
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// ---------------------------------------------------------------------------
// Fixtures
//
// Two mutation routes are used deliberately, because they exercise different pipeline
// steps and conflating them would make the tests assert less than they appear to.
//
//   - mutateBody signs a valid body, then swaps in a mutated copy. The signature therefore
//     no longer matches, so a rejection proves the pipeline caught the change either at
//     validation (step 3) or at the digest (step 5).
//   - removePolicyField deletes a field from the document JSON outright. This is the real
//     attack shape for a completeness failure: an attacker strips a limit. It needs no
//     valid signature, because validation runs before signature verification, so a
//     rejection proves validation alone is sufficient to stop it.
// ---------------------------------------------------------------------------

func mustMoney(t *testing.T, amount, currency string) *contracts.Money {
	t.Helper()
	m, err := contracts.NewMoney(currency, contracts.MustParseDecimal(amount))
	if err != nil {
		t.Fatalf("NewMoney(%s, %s): %v", amount, currency, err)
	}
	return &m
}

func mustQuantity(t *testing.T, value string, unit contracts.QuantityUnit) *contracts.Quantity {
	t.Helper()
	q, err := contracts.NewQuantity(contracts.MustParseDecimal(value), unit)
	if err != nil {
		t.Fatalf("NewQuantity(%s, %s): %v", value, unit, err)
	}
	return &q
}

func mustTime(t *testing.T, s string) contracts.Timestamp {
	t.Helper()
	ts, err := contracts.ParseTimestamp(s)
	if err != nil {
		t.Fatalf("ParseTimestamp(%s): %v", s, err)
	}
	return ts
}

func mustStrategyID(t *testing.T) contracts.Identifier {
	t.Helper()
	id, err := contracts.ParseIdentifier("str_01hq3k7m9x2f5rb8n0v6c4tqwx")
	if err != nil {
		t.Fatalf("ParseIdentifier: %v", err)
	}
	return id
}

func moneyLimit(t *testing.T, id, amount, currency string) Limit {
	t.Helper()
	return Limit{
		ID:          id,
		Amount:      mustMoney(t, amount, currency),
		Aggregation: ScopePerOrder,
		Window:      time.Minute,
		Boundary:    BoundaryExclusive,
		Source:      SourceOMS,
		OnMissing:   MissingDataReject,
		Description: "bounds a single order so a fat finger cannot reach a venue",
	}
}

func quantityLimit(t *testing.T, id, value string, unit contracts.QuantityUnit) Limit {
	t.Helper()
	return Limit{
		ID:          id,
		Quantity:    mustQuantity(t, value, unit),
		Aggregation: ScopePerAccount,
		Window:      time.Minute,
		Boundary:    BoundaryInclusive,
		Source:      SourceLedger,
		OnMissing:   MissingDataUseLastKnown,
		Description: "bounds total position size across the account",
	}
}

func validPolicy(t *testing.T) Policy {
	t.Helper()
	qty := mustQuantity(t, "0.5", contracts.UnitBaseAsset)
	return Policy{
		PermittedMarkets:      []string{"CRYPTO"},
		PermittedVenues:       []string{"sim-venue"},
		PermittedInstruments:  []string{"BTC/USD"},
		PermittedOrderTypes:   []string{"LIMIT"},
		PermittedDirections:   []string{"BUY", "SELL"},
		MaxOrderNotional:      *mustMoney(t, "1000.00", "USD"),
		MaxOrderQuantity:      *qty,
		MaxGrossExposure:      *mustMoney(t, "5000.00", "USD"),
		MaxNetExposure:        *mustMoney(t, "2000.00", "USD"),
		MaxLeverage:           contracts.MustParseDecimal("3"),
		MaxConcentration:      contracts.MustParseDecimal("0.40"),
		MaxOpenOrders:         contracts.MustParseDecimal("20"),
		LossThreshold:         *mustMoney(t, "250.00", "USD"),
		LossWindow:            time.Hour,
		DrawdownThreshold:     contracts.MustParseDecimal("0.10"),
		DrawdownWindow:        24 * time.Hour,
		DrawdownSource:        SourceLedger,
		MarketDataMaxAge:      2 * time.Second,
		MaxPriceDeviation:     contracts.MustParseDecimal("0.02"),
		OrderRateLimit:        contracts.MustParseDecimal("20"),
		CancelRateLimit:       contracts.MustParseDecimal("40"),
		RateWindow:            time.Minute,
		OperatingModes:        []string{"continuous"},
		HaltAuthority:         contracts.ActorHuman,
		ReEnableAuthority:     contracts.ActorService,
		EscalationContacts:    []string{"oncall-risk@example.invalid"},
		SettlementAssumptions: "venue paper settlement assumed T+0; fees excluded from exposure",
		Limits: []Limit{
			moneyLimit(t, "max_order_notional", "1000.00", "USD"),
			quantityLimit(t, "max_position_size", "2.5", contracts.UnitBaseAsset),
		},
	}
}

func validBody(t *testing.T) Body {
	t.Helper()
	created := mustTime(t, "2026-03-01T00:00:00Z")
	return Body{
		SchemaVersion: SchemaVersion,
		Revision:      "1.0.0",
		Environment:   EnvDev,
		Supersedes:    "0.9.0",
		CreatedAt:     created,
		ActivatedAt:   created,
		Approval: Approval{
			ApproverID:   "risk-owner-1",
			ApproverType: contracts.ActorHuman,
			AuthorizedAt: created,
			Reason:       "initial baseline reviewed against the account mandate",
			Checks: []string{
				"schema_validation", "boundary_tests", "scenario_tests",
				"authorization_review", "audit_verification", "dry_run_comparison",
			},
			RollbackRevision: "0.8.0",
		},
		Policy: validPolicy(t),
		Freshness: Freshness{
			MaxAge:              15 * time.Minute,
			MaxLastKnownGoodAge: 5 * time.Minute,
		},
		Flags: map[string]bool{string(FlagSimulatedExecution): true},
	}
}

var (
	testPublic  ed25519.PublicKey
	testPrivate ed25519.PrivateKey
)

func TestMain(m *testing.M) {
	var err error
	testPublic, testPrivate, err = ed25519.GenerateKey(nil)
	if err != nil {
		panic("generate test signing key: " + err.Error())
	}
	m.Run()
}

func testTrust(t *testing.T) *TrustStore {
	t.Helper()
	store, err := NewTrustStore(map[string]ed25519.PublicKey{KeyIDFor(testPublic): testPublic})
	if err != nil {
		t.Fatalf("NewTrustStore: %v", err)
	}
	return store
}

// now is the evaluation time for tests that do not exercise staleness: one minute after
// the fixture's activation, comfortably inside the 15 minute window.
func now() time.Time {
	ts, err := contracts.ParseTimestamp("2026-03-01T00:01:00Z")
	if err != nil {
		panic("fixture timestamp is invalid: " + err.Error())
	}
	return ts.Time()
}

func envelopeBytes(t *testing.T, env Envelope) []byte {
	t.Helper()
	raw, err := json.Marshal(env)
	if err != nil {
		t.Fatalf("marshal envelope: %v", err)
	}
	return raw
}

func signedDocument(t *testing.T, b Body) []byte {
	t.Helper()
	env, err := Sign(b, testPrivate)
	if err != nil {
		t.Fatalf("Sign: %v", err)
	}
	return envelopeBytes(t, env)
}

// mutateBody signs a valid body and then swaps in a mutated copy without re-signing.
func mutateBody(t *testing.T, mutate func(*Body)) []byte {
	t.Helper()
	env, err := Sign(validBody(t), testPrivate)
	if err != nil {
		t.Fatalf("Sign: %v", err)
	}
	mutate(&env.Body)
	return envelopeBytes(t, env)
}

// validDocumentJSON decodes the valid signed document into a generic map so a test can
// delete or inject a field without going through the typed structs.
func validDocumentJSON(t *testing.T) map[string]any {
	t.Helper()
	var generic map[string]any
	if err := json.Unmarshal(signedDocument(t, validBody(t)), &generic); err != nil {
		t.Fatalf("decode valid document: %v", err)
	}
	return generic
}

// removePolicyField deletes a field from body.policy. The result needs no valid signature,
// because structural validation runs before signature verification.
func removePolicyField(t *testing.T, field string) []byte {
	t.Helper()
	generic := validDocumentJSON(t)
	policy, ok := generic["body"].(map[string]any)["policy"].(map[string]any)
	if !ok {
		t.Fatal("valid document has no body.policy object")
	}
	if _, present := policy[field]; !present {
		t.Fatalf("fixture policy has no field %q to remove", field)
	}
	delete(policy, field)
	raw, err := json.Marshal(generic)
	if err != nil {
		t.Fatalf("marshal mutated document: %v", err)
	}
	return raw
}

func loadOK(t *testing.T, doc []byte, opts LoadOptions) Snapshot {
	t.Helper()
	if opts.Trust == nil {
		opts.Trust = testTrust(t)
	}
	if opts.Now.IsZero() {
		opts.Now = now()
	}
	snap, err := Load(doc, opts)
	if err != nil {
		t.Fatalf("a valid configuration was refused: %v", err)
	}
	return snap
}

func mustRefuse(t *testing.T, doc []byte, opts LoadOptions, wantSubstring string) {
	t.Helper()
	if opts.Trust == nil {
		opts.Trust = testTrust(t)
	}
	if opts.Now.IsZero() {
		opts.Now = now()
	}
	_, err := Load(doc, opts)
	if err == nil {
		t.Fatalf("configuration was accepted but should have been refused: %s", wantSubstring)
	}
	if wantSubstring != "" && !strings.Contains(err.Error(), wantSubstring) {
		t.Errorf("refusal %q does not mention %q", err.Error(), wantSubstring)
	}
}

// ---------------------------------------------------------------------------
// Baseline
// ---------------------------------------------------------------------------

// TestValidConfigurationIsAccepted comes first because if it fails, every refusal test is
// suspect: they would all be passing for the wrong reason.
func TestValidConfigurationIsAccepted(t *testing.T) {
	snap := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	if snap.Revision() != "1.0.0" {
		t.Errorf("revision = %s, want 1.0.0", snap.Revision())
	}
	if snap.Environment != EnvDev {
		t.Errorf("environment = %s, want dev", snap.Environment)
	}
	if !strings.HasPrefix(snap.Digest, DigestPrefix) {
		t.Errorf("digest %q lacks the %s prefix", snap.Digest, DigestPrefix)
	}
	// The policy must survive the round trip intact, or the digest would be signing
	// something other than the limits that get enforced.
	limits := snap.Body.Policy.LimitIDs()
	if len(limits) != 2 || limits[0] != "max_order_notional" || limits[1] != "max_position_size" {
		t.Errorf("limit ids = %v, want sorted [max_order_notional max_position_size]", limits)
	}
	got, ok := snap.Body.Policy.Limit("max_position_size")
	if !ok {
		t.Fatal("max_position_size did not survive the round trip")
	}
	if !got.IsQuantity() || got.Quantity.Unit() != contracts.UnitBaseAsset {
		t.Errorf("quantity limit lost its unit: %+v", got)
	}
	if got.Describe() != "2.5 BASE_ASSET" {
		t.Errorf("Describe() = %q, want \"2.5 BASE_ASSET\"", got.Describe())
	}
}

// ---------------------------------------------------------------------------
// AC1: Invalid, stale, and unsigned configuration is rejected.
// ---------------------------------------------------------------------------

func TestUnsignedConfigurationIsRejected(t *testing.T) {
	env, err := Sign(validBody(t), testPrivate)
	if err != nil {
		t.Fatalf("Sign: %v", err)
	}
	env.Signature = ""
	mustRefuse(t, envelopeBytes(t, env), LoadOptions{}, "signature")
}

func TestSignatureFromUntrustedKeyIsRejected(t *testing.T) {
	_, otherPriv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatalf("GenerateKey: %v", err)
	}
	env, err := Sign(validBody(t), otherPriv)
	if err != nil {
		t.Fatalf("Sign: %v", err)
	}
	mustRefuse(t, envelopeBytes(t, env), LoadOptions{}, "trusted key")
}

func TestRevokedKeyIsRejected(t *testing.T) {
	// A revoked key must fail as revoked rather than as unknown, because the operational
	// question is usually "was this signed while the key was valid".
	store := testTrust(t)
	store.Revoke(KeyIDFor(testPublic))
	mustRefuse(t, signedDocument(t, validBody(t)), LoadOptions{Trust: store}, "revoked")
}

func TestTamperedLimitIsRejected(t *testing.T) {
	// The highest-value test in this file: an attacker raises a financial limit and leaves
	// the signature in place. Only the digest check can catch it.
	doc := mutateBody(t, func(b *Body) {
		b.Policy.Limits[0].Amount = mustMoney(t, "999999.00", "USD")
		b.Policy.MaxOrderNotional = *mustMoney(t, "999999.00", "USD")
	})
	mustRefuse(t, doc, LoadOptions{}, "modified after signing")
}

func TestTamperedAuthorityIsRejected(t *testing.T) {
	// A prettier attack: change nothing numeric, only who is allowed to halt. Only one
	// authority is changed, because changing both would trip the separation rule first and
	// this test is meant to prove the digest check catches an otherwise-valid document.
	doc := mutateBody(t, func(b *Body) {
		b.Policy.HaltAuthority = contracts.ActorSystem
	})
	mustRefuse(t, doc, LoadOptions{}, "modified after signing")
}

func TestStaleConfigurationIsRejected(t *testing.T) {
	// Activated 00:00:00 with a 15 minute window, evaluated at 00:20:00.
	eval := mustTime(t, "2026-03-01T00:20:00Z").Time()
	_, err := Load(signedDocument(t, validBody(t)), LoadOptions{Trust: testTrust(t), Now: eval})
	if err == nil {
		t.Fatal("stale configuration was accepted")
	}
	if !strings.Contains(err.Error(), "freshness") {
		t.Errorf("refusal does not identify staleness: %v", err)
	}
	// The code must be DATA_STALE so a caller can distinguish staleness from invalidity.
	var rej Rejection
	if !errors.As(err, &rej) || rej.Code != contracts.CodeDataStale {
		t.Errorf("code = %v, want %s", rej.Code, contracts.CodeDataStale)
	}
}

func TestConfigurationAtItsFreshnessBoundaryIsAccepted(t *testing.T) {
	// The other side of the boundary. A test that only checks the refusing side cannot tell
	// a correct freshness check from one that refuses everything.
	b := validBody(t)
	eval := mustTime(t, "2026-03-01T00:15:00Z").Time()
	snap := loadOK(t, signedDocument(t, b), LoadOptions{Now: eval})
	if snap.Revision() != "1.0.0" {
		t.Errorf("revision = %s, want 1.0.0", snap.Revision())
	}
}

func TestFutureActivationIsRejected(t *testing.T) {
	eval := mustTime(t, "2026-02-01T00:00:00Z").Time()
	_, err := Load(signedDocument(t, validBody(t)), LoadOptions{Trust: testTrust(t), Now: eval})
	if err == nil {
		t.Fatal("a configuration activated in the future was accepted")
	}
	if !strings.Contains(err.Error(), "future") {
		t.Errorf("refusal does not identify the clock problem: %v", err)
	}
}

func TestMissingPolicyDimensionIsRejected(t *testing.T) {
	// Each of these is the attack of stripping a control from an otherwise valid
	// document. Validation must reject before the signature is even examined, which is why
	// these documents carry a now-mismatched signature and are still refused.
	for _, field := range []string{
		"permitted_markets", "permitted_venues", "permitted_instruments",
		"permitted_order_types", "permitted_directions", "operating_modes",
		"escalation_contacts", "max_order_notional", "max_order_quantity",
		"max_gross_exposure", "max_net_exposure", "max_leverage",
		"max_concentration", "max_open_orders", "loss_threshold",
		"drawdown_threshold", "max_price_deviation", "order_rate_limit",
		"cancel_rate_limit", "limits", "settlement_assumptions",
	} {
		t.Run(field, func(t *testing.T) {
			mustRefuse(t, removePolicyField(t, field), LoadOptions{}, "")
		})
	}
}

func TestMissingPolicyDimensionIsReportedByName(t *testing.T) {
	// A caller should learn every missing dimension in one refusal, and should learn which
	// one, rather than discovering them one round trip at a time.
	var generic = validDocumentJSON(t)
	policy := generic["body"].(map[string]any)["policy"].(map[string]any)
	delete(policy, "max_gross_exposure")
	delete(policy, "permitted_venues")
	raw, err := json.Marshal(generic)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	_, loadErr := Load(raw, LoadOptions{Trust: testTrust(t), Now: now()})
	if loadErr == nil {
		t.Fatal("an incomplete policy was accepted")
	}
	for _, want := range []string{"max_gross_exposure", "permitted_venues", "live activation is blocked"} {
		if !strings.Contains(loadErr.Error(), want) {
			t.Errorf("refusal does not name %q: %v", want, loadErr)
		}
	}
}

func TestInvalidPolicyDimensionIsRejected(t *testing.T) {
	cases := map[string]func(*Policy){
		"zero market data max age": func(p *Policy) { p.MarketDataMaxAge = 0 },
		"zero loss window":         func(p *Policy) { p.LossWindow = 0 },
		"zero drawdown window":     func(p *Policy) { p.DrawdownWindow = 0 },
		"zero rate window":         func(p *Policy) { p.RateWindow = 0 },
		"unknown drawdown source":  func(p *Policy) { p.DrawdownSource = "GUESS" },
		"unknown halt authority":   func(p *Policy) { p.HaltAuthority = "SOMEONE" },
		"duplicate limit id":       func(p *Policy) { p.Limits[1].ID = p.Limits[0].ID },
		// An absent currency cannot be expressed as a Go value here, because
		// contracts.Money refuses to encode an unset amount. It is covered instead by
		// TestMissingPolicyDimensionIsRejected, which removes max_order_notional from the
		// document so the field is genuinely absent rather than malformed.
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			doc := mutateBody(t, func(b *Body) { mutate(&b.Policy) })
			mustRefuse(t, doc, LoadOptions{}, "")
		})
	}
}

func TestInvalidLimitDimensionIsRejected(t *testing.T) {
	cases := map[string]func(*Limit){
		"no value":        func(l *Limit) { l.Amount, l.Quantity = nil, nil },
		"both values":     func(l *Limit) { l.Quantity = mustQuantity(t, "1", contracts.UnitBaseAsset) },
		"no scope":        func(l *Limit) { l.Aggregation = "" },
		"unknown scope":   func(l *Limit) { l.Aggregation = "PER_MOON" },
		"no window":       func(l *Limit) { l.Window = 0 },
		"negative window": func(l *Limit) { l.Window = -time.Second },
		"no boundary":     func(l *Limit) { l.Boundary = "" },
		"no source":       func(l *Limit) { l.Source = "" },
		"no on_missing":   func(l *Limit) { l.OnMissing = "" },
		"no description":  func(l *Limit) { l.Description = "   " },
		"blank id":        func(l *Limit) { l.ID = " " },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			doc := mutateBody(t, func(b *Body) { mutate(&b.Policy.Limits[0]) })
			mustRefuse(t, doc, LoadOptions{}, "")
		})
	}
}

func TestSelfGrantedAuthorityIsRejected(t *testing.T) {
	// docs/17 section 6: no model or strategy may modify its own policy or grant itself
	// permission.
	for _, field := range []string{"halt", "re_enable"} {
		t.Run(field, func(t *testing.T) {
			doc := mutateBody(t, func(b *Body) {
				if field == "halt" {
					b.Policy.HaltAuthority = contracts.ActorAgent
				} else {
					b.Policy.ReEnableAuthority = contracts.ActorAgent
				}
			})
			mustRefuse(t, doc, LoadOptions{}, "agent")
		})
	}
}

func TestHaltAndReEnableAuthorityMustBeSeparated(t *testing.T) {
	// One actor holding both can raise a halt and immediately clear it.
	doc := mutateBody(t, func(b *Body) {
		b.Policy.HaltAuthority = contracts.ActorHuman
		b.Policy.ReEnableAuthority = contracts.ActorHuman
	})
	mustRefuse(t, doc, LoadOptions{}, "separated")
}

func TestIncompleteApprovalIsRejected(t *testing.T) {
	// These mutations all leave the body marshallable, so they reach the approval checks
	// with a mismatched signature. The checks run before the digest, so the refusal
	// attributes to the approval rather than to the signature.
	cases := map[string]func(*Approval){
		"no approver":      func(a *Approval) { a.ApproverID = "" },
		"service approver": func(a *Approval) { a.ApproverType = contracts.ActorService },
		"agent approver":   func(a *Approval) { a.ApproverType = contracts.ActorAgent },
		"no reason":        func(a *Approval) { a.Reason = "" },
		"a check removed":  func(a *Approval) { a.Checks = a.Checks[:len(a.Checks)-1] },
		"a check renamed":  func(a *Approval) { a.Checks = append(a.Checks, "we did some tests") },
		"checks replaced":  func(a *Approval) { a.Checks = []string{"schema_validation"} },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			doc := mutateBody(t, func(b *Body) { mutate(&b.Approval) })
			mustRefuse(t, doc, LoadOptions{}, "")
		})
	}
}

func TestMissingApprovalFieldIsRejected(t *testing.T) {
	// Removing the field is the only way to express an absent timestamp, because
	// contracts.Timestamp deliberately refuses to encode an unset value. That refusal is
	// correct for a wire type, and the consequence is that absence has to be tested through
	// a document that omits the field rather than through a Go zero value.
	for _, field := range []string{
		"approver_id", "approver_type", "authorized_at", "reason", "checks",
	} {
		t.Run(field, func(t *testing.T) {
			generic := validDocumentJSON(t)
			approval, ok := generic["body"].(map[string]any)["approval"].(map[string]any)
			if !ok {
				t.Fatal("valid document has no body.approval object")
			}
			if _, present := approval[field]; !present {
				t.Fatalf("fixture approval has no field %q", field)
			}
			delete(approval, field)
			raw, err := json.Marshal(generic)
			if err != nil {
				t.Fatalf("marshal: %v", err)
			}
			mustRefuse(t, raw, LoadOptions{}, "")
		})
	}
}

func TestEveryRequiredApprovalCheckIsEnforced(t *testing.T) {
	// Proves the check-name list is not vacuous: removing any single one is a rejection.
	for i := range requiredChecks {
		check := requiredChecks[i]
		t.Run(check, func(t *testing.T) {
			doc := mutateBody(t, func(b *Body) {
				var kept []string
				for _, c := range b.Approval.Checks {
					if c != check {
						kept = append(kept, c)
					}
				}
				b.Approval.Checks = kept
			})
			mustRefuse(t, doc, LoadOptions{}, check)
		})
	}
}

// ---------------------------------------------------------------------------
// AC2: No undocumented configuration can enter the live snapshot.
// ---------------------------------------------------------------------------

func TestUnknownTopLevelFieldIsRejected(t *testing.T) {
	// The direct expression of the criterion. The document is signed correctly, so the
	// only thing that can catch the injected field is strict decoding.
	generic := validDocumentJSON(t)
	generic["live_override"] = "allow_all"
	raw, err := json.Marshal(generic)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	mustRefuse(t, raw, LoadOptions{}, "does not match the schema")
}

func TestUnknownNestedFieldIsRejected(t *testing.T) {
	// The more likely smuggling shape, because it sits next to fields a reviewer is
	// reading. A field that decoded silently would contribute nothing to the digest while
	// still being present, and the document would then assert a configuration the signature
	// does not cover.
	generic := validDocumentJSON(t)
	policy := generic["body"].(map[string]any)["policy"].(map[string]any)
	policy["max_order_notional_override"] = "1000000"
	policy["permitted_venues"] = append(policy["permitted_venues"].([]any), "live-venue")
	raw, err := json.Marshal(generic)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	mustRefuse(t, raw, LoadOptions{}, "does not match the schema")
}

func TestUnknownFieldInALimitIsRejected(t *testing.T) {
	generic := validDocumentJSON(t)
	limits, ok := generic["body"].(map[string]any)["policy"].(map[string]any)["limits"].([]any)
	if !ok || len(limits) == 0 {
		t.Fatal("valid document has no policy.limits array")
	}
	firstLimit, ok := limits[0].(map[string]any)
	if !ok {
		t.Fatal("policy.limits[0] is not an object")
	}
	firstLimit["emergency_override"] = true
	raw, err := json.Marshal(generic)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	mustRefuse(t, raw, LoadOptions{}, "does not match the schema")
}

func TestTrailingContentIsRejected(t *testing.T) {
	// Two documents in one stream is the same hazard as an unknown field: the canonical
	// bytes describe the first, and the second rides along unaudited.
	raw := append(append([]byte{}, signedDocument(t, validBody(t))...),
		[]byte(`{"body":{"revision":"9.9.9"}}`)...)
	mustRefuse(t, raw, LoadOptions{}, "trailing")
}

func TestSchemaVersionMismatchIsRejected(t *testing.T) {
	// A signature that verified under a different field layout would otherwise be treated
	// as covering fields this build does not have.
	doc := mutateBody(t, func(b *Body) { b.SchemaVersion = "2.0.0" })
	mustRefuse(t, doc, LoadOptions{}, "refused rather than reinterpreted")
}

func TestUndocumentedFeatureFlagIsRejected(t *testing.T) {
	doc := mutateBody(t, func(b *Body) { b.Flags["disable_all_risk_checks"] = true })
	mustRefuse(t, doc, LoadOptions{}, "undocumented feature flag")
}

func TestDocumentedFlagSetIsClosed(t *testing.T) {
	// A guard on the guard: this table is the only record of what each flag may authorise,
	// so if it is not the authority, "unknown flags never grant authority" is unenforced.
	if len(AllFlags()) != len(documentedFlags) {
		t.Fatalf("AllFlags returned %d names for %d documented flags", len(AllFlags()), len(documentedFlags))
	}
	for _, name := range []string{"disable_all_risk_checks", "shadow_live_bypass", "", "  "} {
		if Documented(name) {
			t.Errorf("undocumented flag name %q reported itself as documented", name)
		}
	}
	names := AllFlags()
	for i, name := range names {
		if strings.TrimSpace(name) == "" {
			t.Error("a documented flag has a blank name")
		}
		if i > 0 && names[i-1] >= name {
			t.Errorf("AllFlags is not strictly sorted: %q then %q", names[i-1], name)
		}
	}
}

// ---------------------------------------------------------------------------
// AC3: Drift detection alert path implemented.
// ---------------------------------------------------------------------------

// cleanObserved builds the observed state that matches a snapshot exactly.
func cleanObserved(snap Snapshot) ObservedState {
	return ObservedState{
		PolicyDigest:      snap.Digest,
		FeatureFlags:      map[string]bool{string(FlagSimulatedExecution): true},
		HaltAuthority:     snap.Body.Policy.HaltAuthority,
		ReEnableAuthority: snap.Body.Policy.ReEnableAuthority,
	}
}

func assertAlertHalts(t *testing.T, r DriftReport) {
	t.Helper()
	alert, raised := AlertFrom(r)
	if !raised {
		t.Fatal("drift raised no alert")
	}
	if !alert.RequiresOperator {
		t.Error("a halting alert does not require an operator")
	}
	if !r.Severity.HaltsRiskIncreasing() {
		t.Errorf("severity %s does not halt risk-increasing actions", r.Severity)
	}
	if alert.Summary == "" {
		t.Error("alert carries no summary")
	}
	if len(alert.Findings) == 0 {
		t.Error("alert carries no evidence: a halt with no explanation is not actionable")
	}
	if alert.ID == "" {
		t.Error("alert carries no id, so a notification system cannot deduplicate it")
	}
}

func TestCleanStateRaisesNoDrift(t *testing.T) {
	snap := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	report := DetectDrift(snap, cleanObserved(snap), now())
	if report.Severity != DriftNone {
		t.Fatalf("clean state reported drift: %+v", report.Findings)
	}
	if len(report.Findings) != 0 {
		t.Errorf("clean state reported %d findings", len(report.Findings))
	}
	if _, raised := AlertFrom(report); raised {
		t.Fatal("a clean state raised an alert")
	}
}

func TestDriftIsDetectedAndAlerts(t *testing.T) {
	snap := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})

	t.Run("policy digest divergence is structural", func(t *testing.T) {
		observed := cleanObserved(snap)
		observed.PolicyDigest = DigestPrefix + strings.Repeat("0", 64)
		report := DetectDrift(snap, observed, now())
		if report.Severity != DriftStructural {
			t.Fatalf("severity = %s, want STRUCTURAL", report.Severity)
		}
		assertAlertHalts(t, report)
	})

	t.Run("absent policy digest is structural", func(t *testing.T) {
		observed := cleanObserved(snap)
		observed.PolicyDigest = ""
		report := DetectDrift(snap, observed, now())
		if report.Severity != DriftStructural {
			t.Fatalf("severity = %s, want STRUCTURAL", report.Severity)
		}
		if !strings.Contains(report.Findings[0].Detail, "no policy digest") {
			t.Errorf("detail does not identify the absent digest: %+v", report.Findings[0])
		}
		assertAlertHalts(t, report)
	})

	t.Run("halt authority divergence is limit severity", func(t *testing.T) {
		observed := cleanObserved(snap)
		observed.HaltAuthority = contracts.ActorSystem
		report := DetectDrift(snap, observed, now())
		if report.Severity != DriftLimit {
			t.Fatalf("severity = %s, want LIMIT", report.Severity)
		}
		assertAlertHalts(t, report)
	})

	t.Run("re-enable authority divergence is limit severity", func(t *testing.T) {
		observed := cleanObserved(snap)
		observed.ReEnableAuthority = contracts.ActorAgent
		report := DetectDrift(snap, observed, now())
		if report.Severity != DriftLimit {
			t.Fatalf("severity = %s, want LIMIT", report.Severity)
		}
		assertAlertHalts(t, report)
	})

	t.Run("runtime-only flag is structural", func(t *testing.T) {
		// An unrecognised flag that is on is unaccounted authority, and it is
		// undocumented configuration one level above the document.
		observed := cleanObserved(snap)
		observed.FeatureFlags["shadow_live_bypass"] = true
		report := DetectDrift(snap, observed, now())
		if report.Severity != DriftStructural {
			t.Fatalf("severity = %s, want STRUCTURAL", report.Severity)
		}
		if !strings.Contains(report.Findings[0].Path, "shadow_live_bypass") {
			t.Errorf("findings do not name the undocumented flag: %+v", report.Findings)
		}
		assertAlertHalts(t, report)
	})

	t.Run("flag value divergence is limit severity", func(t *testing.T) {
		observed := cleanObserved(snap)
		observed.FeatureFlags[string(FlagSimulatedExecution)] = false
		report := DetectDrift(snap, observed, now())
		if report.Severity != DriftLimit {
			t.Fatalf("severity = %s, want LIMIT", report.Severity)
		}
		assertAlertHalts(t, report)
	})

	t.Run("flag missing from runtime is limit severity", func(t *testing.T) {
		observed := cleanObserved(snap)
		observed.FeatureFlags = map[string]bool{}
		report := DetectDrift(snap, observed, now())
		if report.Severity != DriftLimit {
			t.Fatalf("severity = %s, want LIMIT", report.Severity)
		}
		assertAlertHalts(t, report)
	})
}

func TestDriftAlertIDIsStableForUnchangedDrift(t *testing.T) {
	// Repeated detection of an unchanged condition must be idempotent, or a polling loop
	// pages an operator on every tick for a condition that has not moved.
	snap := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	observed := cleanObserved(snap)
	observed.PolicyDigest = DigestPrefix + strings.Repeat("0", 64)

	first, _ := AlertFrom(DetectDrift(snap, observed, now()))
	second, _ := AlertFrom(DetectDrift(snap, observed, now()))
	if first.ID != second.ID {
		t.Errorf("alert id changed for unchanged drift: %s then %s", first.ID, second.ID)
	}

	// A changed condition must produce a different id, or deduplication would suppress a
	// genuinely new divergence.
	observed.HaltAuthority = contracts.ActorSystem
	third, _ := AlertFrom(DetectDrift(snap, observed, now()))
	if third.ID == first.ID {
		t.Error("a new divergence reused the previous alert id")
	}
}

func TestDriftSeverityIsRankedAndMonotonic(t *testing.T) {
	// docs/25 line 41: a halt is monotonic in severity, so a lower-severity finding may
	// never clear a higher one. The ordering itself is the mechanism.
	if !DriftStructural.HaltsRiskIncreasing() {
		t.Error("STRUCTURAL does not halt")
	}
	if !DriftLimit.HaltsRiskIncreasing() {
		t.Error("LIMIT does not halt")
	}
	if DriftAdvisory.HaltsRiskIncreasing() {
		t.Error("ADVISORY halts, which is stricter than the rule requires")
	}
	if DriftNone.HaltsRiskIncreasing() {
		t.Error("NONE halts")
	}
	if !(DriftNone < DriftAdvisory && DriftAdvisory < DriftLimit && DriftLimit < DriftStructural) {
		t.Error("severities are not ordered as documented")
	}
	for sev, want := range map[DriftSeverity]string{
		DriftNone: "NONE", DriftAdvisory: "ADVISORY",
		DriftLimit: "LIMIT", DriftStructural: "STRUCTURAL",
	} {
		if sev.String() != want {
			t.Errorf("String() = %s, want %s", sev.String(), want)
		}
	}
	if DriftSeverity(99).String() != "UNKNOWN" {
		t.Error("an unknown severity did not render as UNKNOWN")
	}
}

func TestDriftReportIsDeterministic(t *testing.T) {
	// Map iteration order is random in Go, so an unsorted report would differ between runs
	// and an alert id derived from it would churn.
	snap := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	observed := ObservedState{
		PolicyDigest:      snap.Digest,
		FeatureFlags:      map[string]bool{"alpha": true, "beta": false, "gamma": true},
		HaltAuthority:     contracts.ActorSystem,
		ReEnableAuthority: contracts.ActorAgent,
	}
	first := DetectDrift(snap, observed, now())
	if len(first.Findings) < 4 {
		t.Fatalf("expected several findings, got %d", len(first.Findings))
	}
	for i := 0; i < 25; i++ {
		again := DetectDrift(snap, observed, now())
		if len(again.Findings) != len(first.Findings) {
			t.Fatalf("finding count changed on run %d: %d then %d", i, len(first.Findings), len(again.Findings))
		}
		for j := range again.Findings {
			if again.Findings[j] != first.Findings[j] {
				t.Fatalf("run %d finding %d = %+v, first = %+v", i, j, again.Findings[j], first.Findings[j])
			}
		}
	}
}

// ---------------------------------------------------------------------------
// AC4: Unknown flags never grant authority; last verified safe only within freshness.
// ---------------------------------------------------------------------------

func TestUnknownFlagNeverGrantsAuthority(t *testing.T) {
	// The call-site property, independent of whether ResolveFlags was consulted: an
	// undocumented name is always off at every entry point.
	flags, err := ResolveFlags(map[string]bool{string(FlagSimulatedExecution): true})
	if err != nil {
		t.Fatalf("ResolveFlags: %v", err)
	}
	for _, name := range []string{"disable_all_risk_checks", "shadow_live_bypass", "", "  "} {
		if flags.Enabled(name) {
			t.Errorf("undocumented flag %q reported itself enabled", name)
		}
	}
	if !flags.Enabled(string(FlagSimulatedExecution)) {
		t.Error("a documented enabled flag reported itself disabled")
	}
}

func TestRefusedFlagResolutionIsFailClosed(t *testing.T) {
	// A refused resolution must enable nothing at all. Returning the flags it did
	// understand would mean a caller ignoring the error still gets partial authority.
	refused, err := ResolveFlags(map[string]bool{
		string(FlagSimulatedExecution): true,
		"shadow_live_bypass":           true,
	})
	if err == nil {
		t.Fatal("ResolveFlags accepted an undocumented flag")
	}
	if got := refused.EnabledFlags(); len(got) != 0 {
		t.Errorf("a refused resolution still enabled %v", got)
	}
	if refused.Enabled(string(FlagSimulatedExecution)) {
		t.Error("a refused resolution enabled a documented flag")
	}
}

func TestAbsentFlagIsOffNotOn(t *testing.T) {
	flags, err := ResolveFlags(map[string]bool{})
	if err != nil {
		t.Fatalf("ResolveFlags: %v", err)
	}
	for _, name := range AllFlags() {
		if flags.Enabled(name) {
			t.Errorf("flag %q is enabled without being declared", name)
		}
	}
	if got := len(flags.EnabledFlags()); got != 0 {
		t.Errorf("%d flags are enabled from an empty declaration", got)
	}
}

func TestDocumentedFlagsResolveAsDeclared(t *testing.T) {
	declared := map[string]bool{}
	for _, name := range AllFlags() {
		declared[name] = true
	}
	flags, err := ResolveFlags(declared)
	if err != nil {
		t.Fatalf("ResolveFlags: %v", err)
	}
	for _, name := range AllFlags() {
		if !flags.Enabled(name) {
			t.Errorf("declared flag %q did not resolve as enabled", name)
		}
	}
	if got := len(flags.EnabledFlags()); got != len(AllFlags()) {
		t.Errorf("%d of %d flags enabled", got, len(AllFlags()))
	}
}

func TestExecutionFlagsAreMutuallyExclusive(t *testing.T) {
	flags, err := ResolveFlags(map[string]bool{
		string(FlagSimulatedExecution): true,
		string(FlagPaperExecution):     true,
	})
	if err != nil {
		t.Fatalf("ResolveFlags: %v", err)
	}
	mustFlagRefusal(t, flags.RequireRiskIncreasingPath(EnvDev), "mutually exclusive")
}

func TestNoExecutionFlagMeansNoSubmissionPath(t *testing.T) {
	flags, err := ResolveFlags(map[string]bool{})
	if err != nil {
		t.Fatalf("ResolveFlags: %v", err)
	}
	// The fail-safe direction has to be stated in the message, because this refusal is what
	// an operator will read when nothing works and needs to know nothing failed open.
	mustFlagRefusal(t, flags.RequireRiskIncreasingPath(EnvDev), "not a default to the live path")
}

func TestExecutionFlagMustMatchEnvironment(t *testing.T) {
	// A paper environment with only the simulator on is a misconfiguration that would let
	// an operator believe a paper capability exists when it does not.
	flags, err := ResolveFlags(map[string]bool{string(FlagSimulatedExecution): true})
	if err != nil {
		t.Fatalf("ResolveFlags: %v", err)
	}
	mustFlagRefusal(t, flags.RequireRiskIncreasingPath(EnvPaper), "requires execution flag")
	if gotErr := flags.RequireRiskIncreasingPath(EnvDev); gotErr != nil {
		t.Errorf("dev rejected the simulated execution flag: %v", gotErr)
	}
}

func TestLiveEnvironmentHasNoExecutionFlagRequirement(t *testing.T) {
	// Live is authorised by approval and controls, not by a flag, so no flag is required
	// and none can grant it.
	flags, err := ResolveFlags(map[string]bool{})
	if err != nil {
		t.Fatalf("ResolveFlags: %v", err)
	}
	if gotErr := flags.RequireRiskIncreasingPath(EnvLive); gotErr != nil {
		t.Errorf("live environment required an execution flag: %v", gotErr)
	}
}

func mustFlagRefusal(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected a refusal mentioning %q", want)
	}
	if !strings.Contains(err.Error(), want) {
		t.Errorf("refusal %q does not mention %q", err.Error(), want)
	}
	var rej Rejection
	if !errors.As(err, &rej) {
		t.Errorf("error is not a Rejection: %T", err)
	}
}

func TestLastVerifiedSafeOnlyWithinFreshness(t *testing.T) {
	snap := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})

	t.Run("inside the window", func(t *testing.T) {
		// Window is 5 minutes; 3 minutes elapsed.
		at := mustTime(t, "2026-03-01T00:03:00Z").Time()
		res := LastVerifiedSafe(&snap, at)
		if res.Halted {
			t.Fatalf("halted inside the last-known-good window: %s", res.Reason)
		}
		if res.Snapshot == nil {
			t.Fatal("no snapshot returned inside the window")
		}
		if !strings.Contains(res.Reason, "within") {
			t.Errorf("reason does not record the window check: %s", res.Reason)
		}
	})

	t.Run("at the window boundary", func(t *testing.T) {
		at := mustTime(t, "2026-03-01T00:05:00Z").Time()
		if res := LastVerifiedSafe(&snap, at); res.Halted {
			t.Fatalf("halted exactly at the last-known-good boundary: %s", res.Reason)
		}
	})

	t.Run("outside the window halts", func(t *testing.T) {
		// 30 minutes is past both the 5 minute fallback window and the 15 minute max age.
		at := mustTime(t, "2026-03-01T00:30:00Z").Time()
		res := LastVerifiedSafe(&snap, at)
		if !res.Halted {
			t.Fatal("a snapshot beyond its last-known-good window was served")
		}
		if res.Snapshot != nil {
			t.Error("a halted result still returned a snapshot")
		}
		if !strings.Contains(res.Reason, "last-known-good") {
			t.Errorf("reason does not identify the exceeded window: %s", res.Reason)
		}
	})

	t.Run("no snapshot halts", func(t *testing.T) {
		res := LastVerifiedSafe(nil, now())
		if !res.Halted {
			t.Fatal("a cold start served configuration")
		}
		if !strings.Contains(res.Reason, "cold start") {
			t.Errorf("reason does not identify the cold start: %s", res.Reason)
		}
	})

	t.Run("unverified snapshot halts", func(t *testing.T) {
		// A snapshot with no digest was never verified, so calling it "last verified safe"
		// would be a lie. The gate is on the digest rather than on a boolean flag, because a
		// flag can be set by anything holding the struct.
		raw := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
		raw.Digest = ""
		res := LastVerifiedSafe(&raw, now())
		if !res.Halted {
			t.Fatal("a snapshot with no verified digest was served")
		}
		if !strings.Contains(res.Reason, "never verified") {
			t.Errorf("reason does not explain the missing verification: %s", res.Reason)
		}
	})

	t.Run("future activation halts", func(t *testing.T) {
		raw := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
		raw.ActivatedAt = mustTime(t, "2026-06-01T00:00:00Z").Time()
		res := LastVerifiedSafe(&raw, now())
		if !res.Halted {
			t.Fatal("a snapshot activated in the future was served")
		}
	})
}

func TestFreshnessFallbackWindowMayNotExceedMaxAge(t *testing.T) {
	// A fallback window longer than the revision's own lifetime would let a snapshot serve
	// after the point where it must be considered stale.
	doc := mutateBody(t, func(b *Body) {
		b.Freshness.MaxLastKnownGoodAge = b.Freshness.MaxAge + time.Minute
	})
	mustRefuse(t, doc, LoadOptions{}, "outlive")
}

func TestFreshnessMustBePositive(t *testing.T) {
	for name, mutate := range map[string]func(*Freshness){
		"zero max age":         func(f *Freshness) { f.MaxAge = 0 },
		"negative max age":     func(f *Freshness) { f.MaxAge = -time.Minute },
		"zero fallback window": func(f *Freshness) { f.MaxLastKnownGoodAge = 0 },
		"negative fallback":    func(f *Freshness) { f.MaxLastKnownGoodAge = -time.Minute },
	} {
		t.Run(name, func(t *testing.T) {
			doc := mutateBody(t, func(b *Body) { mutate(&b.Freshness) })
			mustRefuse(t, doc, LoadOptions{}, "")
		})
	}
}

func TestSubjectStartsDisabledForRiskIncreasing(t *testing.T) {
	// docs/17 section 2. The zero value is the restrictive one, so a subject nobody
	// configured is disabled rather than enabled.
	var s SubjectState
	s.SubjectID = mustStrategyID(t)
	ok, reason := s.PermitsRiskIncreasing(map[string]struct{}{s.SubjectID.String(): {}})
	if ok {
		t.Fatal("an unconfigured subject was permitted to increase risk")
	}
	if !strings.Contains(reason, "not enabled") {
		t.Errorf("reason does not identify the disabled state: %s", reason)
	}
}

func TestGrantOutsidePolicyIsRefused(t *testing.T) {
	// A grant recorded against a subject the policy does not cover is a grant no reviewer
	// approved.
	s := SubjectState{SubjectID: mustStrategyID(t), RiskIncreasingEnabled: true, GrantedByRevision: "1.0.0"}
	ok, reason := s.PermitsRiskIncreasing(map[string]struct{}{})
	if ok {
		t.Fatal("a grant outside the policy's permitted set was honoured")
	}
	if !strings.Contains(reason, "no reviewer approved") {
		t.Errorf("reason does not identify the policy mismatch: %s", reason)
	}
}

func TestGrantWithinPolicyIsHonoured(t *testing.T) {
	s := SubjectState{SubjectID: mustStrategyID(t), RiskIncreasingEnabled: true, GrantedByRevision: "1.0.0"}
	ok, reason := s.PermitsRiskIncreasing(map[string]struct{}{s.SubjectID.String(): {}})
	if !ok {
		t.Fatalf("a covered grant was refused: %s", reason)
	}
}

// ---------------------------------------------------------------------------
// Promotion ladder: docs/17 section 1.
// ---------------------------------------------------------------------------

func TestEnvironmentLadderIsClosedAndOrdered(t *testing.T) {
	want := []Environment{EnvDev, EnvTest, EnvStaging, EnvPaper, EnvShadow, EnvLive}
	if len(AllEnvironments()) != len(want) {
		t.Fatalf("ladder has %d stages, want %d", len(AllEnvironments()), len(want))
	}
	for i, env := range want {
		if AllEnvironments()[i] != env {
			t.Errorf("stage %d = %s, want %s", i, AllEnvironments()[i], env)
		}
		if env.Rank() != i {
			t.Errorf("%s has rank %d, want %d", env, env.Rank(), i)
		}
	}
	// Every declared constant must be on the ladder. EnvPaper is the case that would break
	// silently if a constant were added without a rank, because Valid and Rank both derive
	// from the ladder rather than from the constant list.
	for _, env := range []Environment{EnvDev, EnvTest, EnvStaging, EnvPaper, EnvShadow, EnvLive} {
		if !env.Valid() {
			t.Errorf("declared environment %s is not on the ladder", env)
		}
	}
	if Environment("prod").Valid() {
		t.Error("an undeclared environment reported itself valid")
	}
	if _, err := ParseEnvironment("prod"); err == nil {
		t.Error("ParseEnvironment accepted an environment off the ladder")
	}
	got, err := ParseEnvironment("paper")
	if err != nil || got != EnvPaper {
		t.Errorf("ParseEnvironment(paper) = %s, %v", got, err)
	}
}

// testPromotionChain builds the verified dev -> test -> staging -> paper -> shadow chain a
// live promotion must build on.
func testPromotionChain(t *testing.T) Snapshot {
	t.Helper()
	prev := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	for _, env := range []Environment{EnvTest, EnvStaging, EnvPaper, EnvShadow} {
		body := promotedFrom(t, prev, env)
		prev = loadOK(t, signedDocument(t, body), LoadOptions{Previous: &prev})
	}
	return prev
}

// promotedFrom returns the body one promotion step ahead of prev, with the revision and
// supersedes fields made coherent and the execution flag matching the target environment.
func promotedFrom(t *testing.T, prev Snapshot, env Environment) Body {
	t.Helper()
	b := prev.Body
	b.Environment = env
	b.Revision = fmt.Sprintf("%d.0.0", prev.Environment.Rank()+1)
	b.Supersedes = prev.Body.Revision
	// A revision for an environment must carry the execution flag that environment maps to,
	// so the fixture stays a configuration a reviewer could plausibly have signed.
	switch executionFlagFor(env) {
	case FlagSimulatedExecution:
		b.Flags = map[string]bool{string(FlagSimulatedExecution): true}
	case FlagPaperExecution:
		b.Flags = map[string]bool{string(FlagPaperExecution): true}
	case FlagShadowExecution:
		b.Flags = map[string]bool{string(FlagShadowExecution): true}
	default:
		b.Flags = map[string]bool{}
	}
	return b
}

func TestFullPromotionChainReachesLive(t *testing.T) {
	// The positive end of the ladder: every step verified, in order.
	snap := testPromotionChain(t)
	if snap.Environment != EnvShadow {
		t.Fatalf("chain ended at %s, want shadow", snap.Environment)
	}
	live := promotedFrom(t, snap, EnvLive)
	live.Approval.SecondApproverID = "risk-owner-2"

	final := loadOK(t, signedDocument(t, live), LoadOptions{Previous: &snap})
	if final.Environment != EnvLive {
		t.Errorf("environment = %s, want live", final.Environment)
	}
	if final.Body.Supersedes != snap.Body.Revision {
		t.Errorf("supersedes = %s, want %s", final.Body.Supersedes, snap.Body.Revision)
	}
}

func TestLiveCannotBeCopiedFromLowerEnvironment(t *testing.T) {
	// docs/17 section 1: live configuration cannot be copied automatically from lower
	// environments.
	dev := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	live := promotedFrom(t, dev, EnvLive)
	live.Approval.SecondApproverID = "risk-owner-2"

	mustRefuse(t, signedDocument(t, live), LoadOptions{Previous: &dev}, "single promotion step")
}

func TestLiveSkippingAStageIsRejected(t *testing.T) {
	// A genuine skip: a verified test-stage snapshot is offered as the predecessor of a live
	// revision, so the ladder step is two rather than one.
	dev := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	testStage := promotedFrom(t, dev, EnvTest)
	verifiedTest := loadOK(t, signedDocument(t, testStage), LoadOptions{Previous: &dev})

	live := promotedFrom(t, verifiedTest, EnvLive)
	live.Approval.SecondApproverID = "risk-owner-2"
	mustRefuse(t, signedDocument(t, live), LoadOptions{Previous: &verifiedTest}, "single promotion step")
}

func TestLiveRevisionRequiresTwoPersonApproval(t *testing.T) {
	prev := testPromotionChain(t)
	live := promotedFrom(t, prev, EnvLive)

	t.Run("second approver missing", func(t *testing.T) {
		mustRefuse(t, signedDocument(t, live), LoadOptions{Previous: &prev}, "second approver")
	})
	t.Run("second approver is the same person", func(t *testing.T) {
		body := live
		body.Approval.SecondApproverID = body.Approval.ApproverID
		mustRefuse(t, signedDocument(t, body), LoadOptions{Previous: &prev}, "different person")
	})
	t.Run("rollback revision missing", func(t *testing.T) {
		body := live
		body.Approval.RollbackRevision = ""
		mustRefuse(t, signedDocument(t, body), LoadOptions{Previous: &prev}, "rollback revision")
	})
}

func TestNonLiveRevisionDoesNotRequireTwoApprovers(t *testing.T) {
	// The rule is scoped to live. Applying it everywhere would mean a dev fixture can never
	// be built, and a rule that is always on is a rule nobody checks.
	dev := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	testStage := promotedFrom(t, dev, EnvTest)
	snap := loadOK(t, signedDocument(t, testStage), LoadOptions{Previous: &dev})
	if snap.Body.Approval.SecondApproverID != "" {
		t.Error("fixture unexpectedly carries a second approver")
	}
}

func TestDeploymentMayRequireTwoApproversEverywhere(t *testing.T) {
	// A deployment that wants the stricter rule everywhere gets it, so the stricter posture
	// is available without editing the policy.
	mustRefuse(t, signedDocument(t, validBody(t)),
		LoadOptions{RequireTwoPersonApproval: true}, "second approver")
}

func TestPromotionRequiresPredecessor(t *testing.T) {
	// Signed properly and with no predecessor, so the promotion check is what refuses it.
	// Reaching this through a mutation would trip the digest check first and prove nothing
	// about the ladder.
	dev := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	testStage := promotedFrom(t, dev, EnvTest)
	mustRefuse(t, signedDocument(t, testStage), LoadOptions{}, "one step at a time")
}

func TestDevNeedsNoPredecessor(t *testing.T) {
	// The origin of the ladder is the one environment with nothing to be promoted from.
	snap := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	if snap.Environment != EnvDev {
		t.Errorf("environment = %s, want dev", snap.Environment)
	}
}

func TestPromotionChainMustAgreeWithSupersedes(t *testing.T) {
	dev := loadOK(t, signedDocument(t, validBody(t)), LoadOptions{})
	body := promotedFrom(t, dev, EnvTest)
	body.Supersedes = "7.7.7"
	mustRefuse(t, signedDocument(t, body), LoadOptions{Previous: &dev}, "disagree")
}

func TestRevisionMustBePresent(t *testing.T) {
	doc := mutateBody(t, func(b *Body) { b.Revision = "  " })
	mustRefuse(t, doc, LoadOptions{}, "no revision")
}

func TestSupersedesMustBePresent(t *testing.T) {
	doc := mutateBody(t, func(b *Body) { b.Supersedes = "" })
	mustRefuse(t, doc, LoadOptions{}, "supersedes nothing")
}

func TestActivationBeforeCreationIsRejected(t *testing.T) {
	doc := mutateBody(t, func(b *Body) {
		b.ActivatedAt = mustTime(t, "2026-02-01T00:00:00Z")
	})
	mustRefuse(t, doc, LoadOptions{}, "precedes created_at")
}

func TestUnattributedRequestIsRejected(t *testing.T) {
	doc := mutateBody(t, func(b *Body) { b.Approval.ApproverID = "" })
	mustRefuse(t, doc, LoadOptions{}, "no approver")
}

// ---------------------------------------------------------------------------
// Canonicalisation, determinism, and malformed input.
// ---------------------------------------------------------------------------

func TestCanonicalFormIsIndependentOfKeyOrderAndWhitespace(t *testing.T) {
	// The signature must cover semantic content. If it covered formatting, a legitimate
	// re-serialisation by a different tool would fail verification for no good reason.
	var generic map[string]any
	if err := json.Unmarshal(signedDocument(t, validBody(t)), &generic); err != nil {
		t.Fatalf("decode: %v", err)
	}
	reordered, _ := json.Marshal(generic)
	indented, _ := json.MarshalIndent(generic, "", "    ")

	store := testTrust(t)
	first := loadOK(t, reordered, LoadOptions{Trust: store})
	second := loadOK(t, indented, LoadOptions{Trust: store})
	if first.Digest != second.Digest {
		t.Errorf("digest depends on formatting: %s then %s", first.Digest, second.Digest)
	}
}

func TestLoadIsDeterministic(t *testing.T) {
	// docs/17 section 4 requires deterministic evaluation for a fixed policy revision,
	// account state, and command, so that a decision is auditable and replayable.
	doc := signedDocument(t, validBody(t))
	first := loadOK(t, doc, LoadOptions{})
	for i := 0; i < 25; i++ {
		again := loadOK(t, doc, LoadOptions{})
		if again.Digest != first.Digest {
			t.Fatalf("digest changed on run %d", i)
		}
		if again.Body.Revision != first.Body.Revision {
			t.Fatalf("revision changed on run %d", i)
		}
	}
}

func TestDigestDetectsASingleFieldChange(t *testing.T) {
	// Fault injection on the digest itself. A digest that ignored a field would make every
	// signature check in this file vacuous.
	canonical, err := CanonicalBytes(validBody(t))
	if err != nil {
		t.Fatalf("CanonicalBytes: %v", err)
	}
	base := ComputeDigest(canonical)

	b := validBody(t)
	b.Policy.Limits[0].Amount = mustMoney(t, "1000.01", "USD")
	changed, _ := CanonicalBytes(b)
	if ComputeDigest(changed) == base {
		t.Error("a one-cent change in a limit did not change the digest")
	}

	b = validBody(t)
	b.Policy.Limits[0].Description += " (revised)"
	changed, _ = CanonicalBytes(b)
	if ComputeDigest(changed) == base {
		t.Error("a limit description change did not change the digest")
	}

	b = validBody(t)
	b.Policy.MaxOpenOrders = contracts.MustParseDecimal("21")
	changed, _ = CanonicalBytes(b)
	if ComputeDigest(changed) == base {
		t.Error("a change to max_open_orders did not change the digest")
	}
}

func TestDigestPolicyMatchesLoadDigest(t *testing.T) {
	// A runtime records DigestPolicy of what it enforced; drift compares it to the digest
	// Load computed. If these two disagreed, every runtime would report structural drift.
	body := validBody(t)
	fromHelper, err := DigestPolicy(body)
	if err != nil {
		t.Fatalf("DigestPolicy: %v", err)
	}
	snap := loadOK(t, signedDocument(t, body), LoadOptions{})
	if fromHelper != snap.Digest {
		t.Errorf("DigestPolicy = %s, Load digest = %s", fromHelper, snap.Digest)
	}
}

func TestSignRefusesAKeyOfTheWrongSize(t *testing.T) {
	if _, err := Sign(validBody(t), ed25519.PrivateKey("too short")); err == nil {
		t.Fatal("Sign accepted a malformed private key")
	}
}

func TestTrustStoreValidatesItsKeys(t *testing.T) {
	if _, err := NewTrustStore(map[string]ed25519.PublicKey{"": testPublic}); err == nil {
		t.Error("a trust store accepted an empty key id")
	}
	if _, err := NewTrustStore(map[string]ed25519.PublicKey{"k": ed25519.PublicKey("short")}); err == nil {
		t.Error("a trust store accepted a malformed public key")
	}
}

func TestTrustStoreLookupIsDeterministic(t *testing.T) {
	store := testTrust(t)
	id, ok := store.SignatureFor(testPublic)
	if !ok {
		t.Fatal("the signing key is not in its own trust store")
	}
	if id != KeyIDFor(testPublic) {
		t.Errorf("lookup id = %s, want %s", id, KeyIDFor(testPublic))
	}
	_, otherPriv, err := ed25519.GenerateKey(nil)
	if err != nil {
		t.Fatalf("GenerateKey: %v", err)
	}
	if _, ok := store.SignatureFor(otherPriv.Public().(ed25519.PublicKey)); ok {
		t.Error("an untrusted key was found in the trust store")
	}
}

func TestEmptyTrustStoreRefusesEverything(t *testing.T) {
	// A service configured with no trust anchors must fail closed. Silently accepting
	// anything would turn a deployment mistake into an open door.
	empty, err := NewTrustStore(nil)
	if err != nil {
		t.Fatalf("NewTrustStore: %v", err)
	}
	mustRefuse(t, signedDocument(t, validBody(t)), LoadOptions{Trust: empty}, "trust store is empty")
}

func TestNilTrustStoreIsRefused(t *testing.T) {
	// Deliberately not routed through mustRefuse, which supplies a trust store when the
	// caller omits one, because omitting it is the thing under test here.
	if _, err := Load(signedDocument(t, validBody(t)), LoadOptions{Now: now()}); err == nil {
		t.Fatal("a load with no trust store was accepted")
	}
}

func TestMalformedDocumentIsRefused(t *testing.T) {
	for _, doc := range [][]byte{nil, {}, []byte("   "), []byte("not json"), []byte("{"), []byte("[]")} {
		if _, err := Load(doc, LoadOptions{Trust: testTrust(t), Now: now()}); err == nil {
			t.Errorf("malformed document %q was accepted", string(doc))
		}
	}
}

func TestMalformedSignatureEncodingIsRefused(t *testing.T) {
	// Each of these would otherwise be a panic in the verifier rather than a refusal.
	for _, sig := range []string{"not base64!!", "", "AAAA"} {
		env, err := Sign(validBody(t), testPrivate)
		if err != nil {
			t.Fatalf("Sign: %v", err)
		}
		env.Signature = sig
		mustRefuse(t, envelopeBytes(t, env), LoadOptions{}, "")
	}
}

func TestMalformedDigestEncodingIsRefused(t *testing.T) {
	for _, digest := range []string{"nohash", DigestPrefix + "zz", DigestPrefix + "abcd", DigestPrefix} {
		env, err := Sign(validBody(t), testPrivate)
		if err != nil {
			t.Fatalf("Sign: %v", err)
		}
		env.Digest = digest
		mustRefuse(t, envelopeBytes(t, env), LoadOptions{}, "")
	}
}

func TestRejectionCarriesCodeAndCause(t *testing.T) {
	// The same contract the strategy package keeps: a canonical code for the wire and a
	// sentinel for errors.Is.
	_, err := Load([]byte("{}"), LoadOptions{Trust: testTrust(t), Now: now()})
	var rej Rejection
	if !errors.As(err, &rej) {
		t.Fatalf("error is not a Rejection: %T", err)
	}
	if !errors.Is(err, ErrInvalidConfig) {
		t.Error("Rejection does not unwrap to ErrInvalidConfig")
	}
	if !strings.HasPrefix(err.Error(), rej.Code.String()+":") {
		t.Errorf("error text %q does not lead with the code", err.Error())
	}
}

func TestStaleRejectionUsesTheStaleCode(t *testing.T) {
	// A caller must be able to tell staleness from invalidity: one is worth retrying after
	// a refresh, the other is a defect that needs a human.
	eval := mustTime(t, "2026-03-01T01:00:00Z").Time()
	_, err := Load(signedDocument(t, validBody(t)), LoadOptions{Trust: testTrust(t), Now: eval})
	var rej Rejection
	if !errors.As(err, &rej) {
		t.Fatalf("error is not a Rejection: %T", err)
	}
	if rej.Code != contracts.CodeDataStale {
		t.Errorf("code = %s, want %s", rej.Code, contracts.CodeDataStale)
	}
	if rej.Cause != ErrInvalidConfig {
		t.Errorf("cause = %v, want ErrInvalidConfig", rej.Cause)
	}
}

func TestNoIEEEFloatInThisPackage(t *testing.T) {
	// A limit expressed as a float would reintroduce the rounding problem the canonical
	// decimal type exists to prevent, at exactly the point where a financial limit is
	// compared against a notional. This mirrors contracts/go/no_float_test.go.
	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatalf("read source dir: %v", err)
	}
	checked := 0
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() || !strings.HasSuffix(name, ".go") {
			continue
		}
		checked++
		src, err := os.ReadFile(name)
		if err != nil {
			t.Fatalf("read %s: %v", name, err)
		}
		for i, line := range strings.Split(string(src), "\n") {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "//") {
				continue
			}
			for _, banned := range []string{"float64", "float32"} {
				if !strings.Contains(line, banned) {
					continue
				}
				// A mention inside a string literal is how this file names the banned
				// types in its own message, and is not a use.
				if strings.Contains(trimmed, "\""+banned) || strings.Contains(trimmed, banned+"\"") {
					continue
				}
				t.Errorf("%s:%d uses %s: %s", name, i+1, banned, trimmed)
			}
		}
	}
	if checked < 5 {
		t.Errorf("only %d source files were scanned; the guard is not covering the package", checked)
	}
}
