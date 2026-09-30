// Package venues contains venue-specific translation and submission.
//
// Authority boundary. An adapter translates and submits; it reports what it observed. It
// must never modify policy, risk configuration, or ledger facts, and it must never become a
// second source of truth for order status (docs/01 section 9, docs/25 section 4).
//
// Every adapter is validated against the shared adapter contract test suite, including
// precision rules, rate limits, timeout handling, and venue-specific failure modes
// (docs/11, G8). Venue precision is validated before submission rather than rounded
// silently.
package venues
