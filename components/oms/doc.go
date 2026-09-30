// Package oms implements the Order Management System: the single owner of canonical
// internal order lifecycle state.
//
// Authority boundary. The OMS owns internal order state. A venue adapter reports
// observations; it never rewrites the OMS state machine (docs/25 section 3.2). A timeout
// produces an UNKNOWN outcome that is reconciled, never a rejection or a fill inferred
// from the absence of a response (docs/25 section 3.3).
//
// Halt is monotonic. A halt may only be cleared by an explicitly authorised command, and
// never by a lower-privilege action, stale configuration, a feature flag, or recovery
// automation (docs/25 section 3.9).
package oms
