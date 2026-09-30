// Package contracts contains the Go binding of the canonical contract package.
//
// It is generated from, or validated against, the language-neutral schemas in
// ../../schema and the shared corpus in ../../fixtures/conformance.json. No type in this
// package may be redefined "locally for convenience": if a value crosses a language or
// process boundary, its definition belongs to the canonical contract repository
// (docs/02_POLYGLOT_ENGINEERING_STANDARD.md, "Contract-first interoperability").
//
// The two rules this package exists to make impossible to violate by accident:
//
//  1. No IEEE-754 floating point crosses a financial contract. Money and quantities are
//     base-10 decimal strings (docs/03_CANONICAL_CONTRACTS.md).
//  2. A mutating command without an idempotency key is not representable.
package contracts
