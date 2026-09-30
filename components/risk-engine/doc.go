// Package riskengine implements the deterministic Risk Engine: the authoritative financial
// veto for every risk-increasing domain command.
//
// The contract is narrow and absolute. AI output, model confidence, operator UI state,
// feature-flag state, and venue response cannot override a risk decision. A veto here is
// final, not advisory, and a risk-rejected command must never produce a live submission
// (docs/25 section 3.1, docs/09 mandatory financial invariant 1).
//
// Every rule must be a deterministic, unit-testable function. A rule that depends on
// wall-clock time, ambient configuration read at decision time, or network state is a
// design defect: the same command and the same policy snapshot must always produce the
// same decision, or the decision cannot be audited or replayed.
package riskengine
