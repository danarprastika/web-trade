// Package reconciliation converges internal authoritative state with external observations.
//
// Authority boundary. Reconciliation is the sole authority for resolving a discrepancy
// between what the platform believes and what a venue reports. It resolves evidence; it
// does not set policy, and it does not decide risk (docs/01 section 3).
//
// An unknown submission outcome stays UNKNOWN until evidence resolves it. It is never
// treated as a confirmed rejection or a fill by timeout assumption, and no exposure-
// increasing retry is permitted while an outcome is unresolved (docs/01 section 10.3,
// docs/25 section 3.3).
package reconciliation
