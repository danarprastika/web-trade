package contracts

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
)

// ErrBindingNotImplemented means this Go binding has no type for the named schema.
//
// It exists so an absent binding is reported as absent. The corpus states that a binding
// that is not present "is reported as NOT_IMPLEMENTED, never as PASS", which means the
// distinction has to survive into the result type. Returning nil from validateDocument for
// an unknown schema would report a schema with no Go type as one this binding accepts,
// which is the exact failure the corpus was built to prevent.
var ErrBindingNotImplemented = errors.New("no Go binding for this schema")

// Outcome is a per-case verdict from comparing a binding against the corpus.
type Outcome string

// The possible outcomes. The names describe agreement with the corpus rather than the
// document's validity, because "a rejected document" is a successful result for a reject
// case and a failing one for an accept case.
const (
	// OutcomeAgreedAccept means the binding accepted a document the corpus expects to accept.
	OutcomeAgreedAccept Outcome = "AGREED_ACCEPT"
	// OutcomeAgreedReject means the binding rejected a document the corpus expects to reject.
	OutcomeAgreedReject Outcome = "AGREED_REJECT"
	// OutcomeDisagreed means the binding's verdict differed from the corpus expectation.
	OutcomeDisagreed Outcome = "DISAGREED"
	// OutcomeNotImplemented means no Go binding exists for the case's schema.
	OutcomeNotImplemented Outcome = "NOT_IMPLEMENTED"
)

// CaseResult is the outcome for one corpus case.
type CaseResult struct {
	Name     string
	Schema   string
	Expected string
	Outcome  Outcome
	// Detail carries the reason for a rejection or a disagreement, so a failing run says
	// what the binding objected to rather than only that it objected.
	Detail string
}

// corpusFile mirrors the shared conformance corpus.
type corpusFile struct {
	ContractPackageVersion string `json:"contract_package_version"`
	Cases                  []struct {
		Name   string          `json:"name"`
		Schema string          `json:"schema"`
		Expect string          `json:"expect"`
		Value  json.RawMessage `json:"value"`
		Note   string          `json:"note"`
	} `json:"cases"`
	BindingConformance struct {
		Description     string            `json:"description"`
		StatusByBinding map[string]string `json:"status_by_binding"`
		Note            string            `json:"note"`
	} `json:"binding_conformance"`
}

// validateDocument decodes and validates one JSON document against the named schema.
//
// A nil return means the document satisfies the schema. A non-nil return means it does
// not. ErrBindingNotImplemented means this package cannot judge the schema at all, which
// the caller must report separately rather than treating as either verdict.
func validateDocument(schema string, raw json.RawMessage) error {
	switch schema {
	case "identifier.schema.json":
		var id Identifier
		return json.Unmarshal(raw, &id)
	case "decimal.schema.json":
		var d Decimal
		return json.Unmarshal(raw, &d)
	case "timestamp.schema.json":
		var ts Timestamp
		return json.Unmarshal(raw, &ts)
	case "money.schema.json":
		var m Money
		return json.Unmarshal(raw, &m)
	case "quantity.schema.json":
		var q Quantity
		return json.Unmarshal(raw, &q)
	case "error.schema.json":
		var e ContractError
		return json.Unmarshal(raw, &e)
	case "pagination.schema.json":
		var p Pagination
		return json.Unmarshal(raw, &p)
	case "command-envelope.schema.json":
		var c CommandEnvelope
		return json.Unmarshal(raw, &c)
	case "event-envelope.schema.json":
		var e EventEnvelope
		return json.Unmarshal(raw, &e)
	default:
		return fmt.Errorf("%w: %s", ErrBindingNotImplemented, schema)
	}
}

// RunCorpus evaluates every case in the shared conformance corpus against this binding and
// returns one result per case, in corpus order.
//
// The corpus is the shared contract between languages, so this runner deliberately does not
// trust the case's own expectation for anything except comparison. It decodes the document
// with the same Go types the services use, which is the only way the result says something
// about the binding rather than about a parallel test harness.
func RunCorpus(corpusPath string) ([]CaseResult, error) {
	data, err := os.ReadFile(corpusPath)
	if err != nil {
		return nil, fmt.Errorf("reading corpus %s: %w", corpusPath, err)
	}
	var corpus corpusFile
	if err := json.Unmarshal(data, &corpus); err != nil {
		return nil, fmt.Errorf("parsing corpus %s: %w", corpusPath, err)
	}
	if len(corpus.Cases) == 0 {
		return nil, fmt.Errorf("corpus %s declares no cases", corpusPath)
	}

	results := make([]CaseResult, 0, len(corpus.Cases))
	for _, c := range corpus.Cases {
		result := CaseResult{Name: c.Name, Schema: c.Schema, Expected: c.Expect}
		switch c.Expect {
		case "accept", "reject":
		default:
			// A corpus with an unrecognised expectation is a corpus defect, not a binding
			// failure. Reporting it as a disagreement would blame the wrong component.
			result.Outcome = OutcomeDisagreed
			result.Detail = fmt.Sprintf("corpus declares unknown expectation %q", c.Expect)
			results = append(results, result)
			continue
		}

		err := validateDocument(c.Schema, c.Value)
		if errors.Is(err, ErrBindingNotImplemented) {
			result.Outcome = OutcomeNotImplemented
			result.Detail = err.Error()
			results = append(results, result)
			continue
		}

		accepted := err == nil
		switch {
		case c.Expect == "accept" && accepted:
			result.Outcome = OutcomeAgreedAccept
		case c.Expect == "reject" && !accepted:
			result.Outcome = OutcomeAgreedReject
		case c.Expect == "accept":
			result.Outcome = OutcomeDisagreed
			result.Detail = fmt.Sprintf("binding rejected a document expected to accept: %v", err)
		default:
			result.Outcome = OutcomeDisagreed
			result.Detail = "binding accepted a document expected to reject"
		}
		results = append(results, result)
	}
	return results, nil
}

// SummariseCorpus counts results by outcome, returning a stable map for reporting.
func SummariseCorpus(results []CaseResult) map[Outcome]int {
	counts := map[Outcome]int{}
	for _, r := range results {
		counts[r.Outcome]++
	}
	return counts
}

// CorpusBindingStatus returns the status the corpus declares for a language binding.
//
// The corpus records which bindings exist so a reader can tell an unimplemented binding
// from a passing one. Exposing it here lets the Go test suite hold that declaration to
// account, rather than leaving a hand-edited "VERIFIED" in a fixture that nothing checks.
func CorpusBindingStatus(corpusPath, binding string) (string, error) {
	data, err := os.ReadFile(corpusPath)
	if err != nil {
		return "", fmt.Errorf("reading corpus %s: %w", corpusPath, err)
	}
	var corpus corpusFile
	if err := json.Unmarshal(data, &corpus); err != nil {
		return "", fmt.Errorf("parsing corpus %s: %w", corpusPath, err)
	}
	status, ok := corpus.BindingConformance.StatusByBinding[binding]
	if !ok {
		return "", fmt.Errorf("corpus %s declares no status for binding %q", corpusPath, binding)
	}
	return status, nil
}

// The recognised vocabulary for a declared binding status. NOT_IMPLEMENTED is the only
// permitted negative value: an absent or unrecognised binding is reported as absent rather
// than as a default, matching the rule docs/03 sets for every other enum in this package.
const (
	StatusNotImplemented = "NOT_IMPLEMENTED"
	StatusVerified       = "VERIFIED"
)

// Disagreements returns the results where the binding and the corpus differ, or where the
// binding does not exist. Callers fail on this set, so a missing binding can never be
// counted as agreement.
func Disagreements(results []CaseResult) []CaseResult {
	var out []CaseResult
	for _, r := range results {
		if r.Outcome == OutcomeDisagreed || r.Outcome == OutcomeNotImplemented {
			out = append(out, r)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}
