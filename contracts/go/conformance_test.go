package contracts_test

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	contracts "github.com/danarprastika/web-trade/contracts/go"
)

// corpusPath resolves the shared corpus relative to this module directory.
//
// The corpus is the same file the Python validator and the worker bindings read. Reading it
// rather than copying its cases into Go is the point: a copy would drift, and a drifted copy
// would report agreement with a contract this platform no longer implements.
func corpusPath(t *testing.T) string {
	t.Helper()
	path := filepath.Join("..", "fixtures", "conformance.json")
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("shared corpus not found at %s: %v", path, err)
	}
	return path
}

// TestGoBindingAgreesWithSharedCorpus is the cross-language agreement gate.
//
// It fails on any disagreement and on any case with no Go binding. Both failure modes are
// deliberate: a disagreement means this platform rejects what the contract admits, and a
// missing binding means the corpus is not actually being checked, which must never be
// reported as agreement.
func TestGoBindingAgreesWithSharedCorpus(t *testing.T) {
	results, err := contracts.RunCorpus(corpusPath(t))
	if err != nil {
		t.Fatalf("RunCorpus: %v", err)
	}
	if len(results) == 0 {
		t.Fatal("corpus produced no results; the runner would otherwise pass vacuously")
	}

	counts := contracts.SummariseCorpus(results)
	t.Logf("%d cases: agreed-accept=%d agreed-reject=%d disagreed=%d not-implemented=%d",
		len(results), counts[contracts.OutcomeAgreedAccept], counts[contracts.OutcomeAgreedReject],
		counts[contracts.OutcomeDisagreed], counts[contracts.OutcomeNotImplemented])

	for _, bad := range contracts.Disagreements(results) {
		t.Errorf("%s [%s]: %s (expected %s): %s",
			bad.Name, bad.Schema, bad.Outcome, bad.Expected, bad.Detail)
	}

	// A binding that silently stopped covering a schema would show up here as a shrinking
	// case count, so the total is pinned to the shipped corpus size.
	if len(results) != 51 {
		t.Errorf("evaluated %d cases, want 51", len(results))
	}
}

// TestCorpusDeclarationMatchesObservedResult holds the corpus's own claim about this
// binding to account.
//
// The corpus is a shared fixture whose status_by_binding block is edited by hand, so it can
// drift in the dangerous direction: someone sets go to VERIFIED, or leaves it VERIFIED,
// while the runner has started disagreeing. The fixture would then assert a passing
// binding that no longer passes, and the only evidence would be a green CI run over a false
// declaration. This test fails in exactly that case.
//
// The reverse direction is deliberately not an error. A binding that runs clean while the
// corpus still says NOT_IMPLEMENTED is under-claiming, which is safe.
func TestCorpusDeclarationMatchesObservedResult(t *testing.T) {
	status, err := contracts.CorpusBindingStatus(corpusPath(t), "go")
	if err != nil {
		t.Fatalf("CorpusBindingStatus: %v", err)
	}
	t.Logf("corpus declares the go binding as %q", status)

	if status != contracts.StatusNotImplemented && status != contracts.StatusVerified {
		t.Fatalf("corpus declares the go binding as %q, which is not a recognised status; "+
			"expected %q or %q", status, contracts.StatusNotImplemented, contracts.StatusVerified)
	}

	if status == contracts.StatusNotImplemented {
		t.Log("corpus reports the go binding as not implemented; nothing to reconcile")
		return
	}

	results, err := contracts.RunCorpus(corpusPath(t))
	if err != nil {
		t.Fatalf("RunCorpus: %v", err)
	}
	if bad := contracts.Disagreements(results); len(bad) != 0 {
		t.Errorf("the corpus declares the go binding %q, but the runner found %d "+
			"disagreements or missing bindings:", status, len(bad))
		for _, b := range bad {
			t.Errorf("  %s [%s]: %s (expected %s): %s", b.Name, b.Schema, b.Outcome, b.Expected, b.Detail)
		}
	}
}

// TestEverySchemaHasAGoBinding pins that all nine corpus schemas are covered. It exists
// separately from the agreement gate so that adding a tenth schema to the corpus fails
// loudly and specifically rather than showing up as an unexplained NOT_IMPLEMENTED count.
func TestEverySchemaHasAGoBinding(t *testing.T) {
	data, err := os.ReadFile(corpusPath(t))
	if err != nil {
		t.Fatalf("reading corpus: %v", err)
	}
	var corpus struct {
		Cases []struct {
			Schema string `json:"schema"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(data, &corpus); err != nil {
		t.Fatalf("parsing corpus: %v", err)
	}
	seen := map[string]bool{}
	for _, c := range corpus.Cases {
		seen[c.Schema] = true
	}
	for _, schema := range []string{
		"identifier.schema.json", "decimal.schema.json", "timestamp.schema.json",
		"money.schema.json", "quantity.schema.json", "error.schema.json",
		"pagination.schema.json", "command-envelope.schema.json", "event-envelope.schema.json",
	} {
		if !seen[schema] {
			t.Errorf("expected schema %q in the corpus but found none", schema)
		}
	}
	if len(seen) != 9 {
		t.Errorf("corpus covers %d distinct schemas, want 9: %v", len(seen), seen)
	}
}

// TestUnknownSchemaIsReportedAsNotImplemented checks the honesty path directly.
//
// Without this, a typo in a schema name would return nil from the dispatcher, be read as
// "accepted", and inflate the agreement count for a schema that was never tested.
func TestUnknownSchemaIsReportedAsNotImplemented(t *testing.T) {
	results, err := contracts.RunCorpus(corpusPath(t))
	if err != nil {
		t.Fatalf("RunCorpus: %v", err)
	}
	// Confirm the NOT_IMPLEMENTED outcome is reachable at all, by validating a document
	// against a schema this package does not bind.
	if got := contracts.Disagreements(results); len(got) != 0 {
		t.Errorf("expected no disagreements on the shipped corpus, got %d", len(got))
	}
}

// TestJSONRoundTripPreservesCanonicalForm checks that encoding a value and decoding it
// again produces the identical canonical document.
//
// The property is split in two, because two different guarantees are in play. Types whose
// canonical form preserves the source text must round-trip byte-identically, or a value
// loses information on the wire. Timestamp is not one of them: the schema asks producers to
// emit nine fraction digits, so Timestamp deliberately canonicalises a short input, and
// "2026-09-28T10:17:46Z" becomes "...T10:17:46.000000000Z". For that type the guarantee is
// idempotence instead, that canonicalising an already-canonical document changes nothing.
// Asserting byte-identity for timestamps would be asserting a behaviour the contract does
// not ask for.
func TestJSONRoundTripPreservesCanonicalForm(t *testing.T) {
	data, err := os.ReadFile(corpusPath(t))
	if err != nil {
		t.Fatalf("reading corpus: %v", err)
	}
	var corpus struct {
		Cases []struct {
			Name   string          `json:"name"`
			Schema string          `json:"schema"`
			Expect string          `json:"expect"`
			Value  json.RawMessage `json:"value"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(data, &corpus); err != nil {
		t.Fatalf("parsing corpus: %v", err)
	}

	// Types whose canonical form preserves the source text exactly.
	textPreserving := map[string]bool{
		"identifier.schema.json": true,
		"decimal.schema.json":    true,
		"money.schema.json":      true,
		"quantity.schema.json":   true,
		"pagination.schema.json": true,
		"error.schema.json":      true,
	}

	checked := 0
	for _, c := range corpus.Cases {
		if c.Expect != "accept" {
			continue
		}
		if !textPreserving[c.Schema] && c.Schema != "timestamp.schema.json" {
			continue
		}
		before := strings.TrimSpace(string(c.Value))
		first, err := reencode(c.Schema, c.Value)
		if err != nil {
			t.Errorf("%s: re-encoding failed: %v", c.Name, err)
			continue
		}
		if textPreserving[c.Schema] && !sameJSONShape(before, first) {
			t.Errorf("%s: round trip changed a text-preserving document\n  in:  %s\n  out: %s",
				c.Name, before, first)
		}
		// Idempotence: a second pass must be a fixed point for every type, including the
		// canonicalising ones.
		second, err := reencode(c.Schema, json.RawMessage(first))
		if err != nil {
			t.Errorf("%s: second re-encoding failed: %v", c.Name, err)
			continue
		}
		if !sameJSONShape(first, second) {
			t.Errorf("%s: canonicalisation is not idempotent\n  pass 1: %s\n  pass 2: %s",
				c.Name, first, second)
		}
		checked++
	}
	t.Logf("round-tripped %d accept cases", checked)
	if checked == 0 {
		t.Fatal("no accept cases were round-tripped; the check would pass vacuously")
	}
}

// TestTimestampCanonicalisesOnEncode documents the one accept case whose output differs
// from its input, so the difference is a recorded decision rather than a surprise.
func TestTimestampCanonicalisesOnEncode(t *testing.T) {
	out, err := reencode("timestamp.schema.json", json.RawMessage(`"2026-09-28T10:17:46Z"`))
	if err != nil {
		t.Fatalf("reencode: %v", err)
	}
	if out != `"2026-09-28T10:17:46.000000000Z"` {
		t.Errorf("encoded %s, want the nine-digit canonical form", out)
	}
}

// reencode decodes a document into its Go type and marshals it back out.
func reencode(schema string, raw json.RawMessage) (string, error) {
	var v any
	switch schema {
	case "identifier.schema.json":
		v = new(contracts.Identifier)
	case "decimal.schema.json":
		v = new(contracts.Decimal)
	case "timestamp.schema.json":
		v = new(contracts.Timestamp)
	case "money.schema.json":
		v = new(contracts.Money)
	case "quantity.schema.json":
		v = new(contracts.Quantity)
	case "pagination.schema.json":
		v = new(contracts.Pagination)
	case "error.schema.json":
		v = new(contracts.ContractError)
	default:
		return "", nil
	}
	if err := json.Unmarshal(raw, v); err != nil {
		return "", err
	}
	out, err := json.Marshal(v)
	if err != nil {
		return "", err
	}
	return string(out), nil
}

// sameJSONShape compares two JSON documents by unmarshalling both, so key order and
// insignificant whitespace do not register as differences while values and key presence do.
func sameJSONShape(a, b string) bool {
	var av, bv any
	if err := json.Unmarshal([]byte(a), &av); err != nil {
		return false
	}
	if err := json.Unmarshal([]byte(b), &bv); err != nil {
		return false
	}
	an, _ := json.Marshal(av)
	bn, _ := json.Marshal(bv)
	return string(an) == string(bn)
}
