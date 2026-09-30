// Package controlplane is the authoritative control plane: identity context enforcement,
// policy integration, domain commands, configuration, risk, OMS, reconciliation, and ledger
// APIs.
//
// It is a modular monolith, not a set of network services (docs/01 section 5). Services are
// split only when load, fault isolation, or a security boundary justifies it; premature
// microservice fragmentation is prohibited.
//
// Authority boundary. This package owns the authoritative application layer. It must never
// delegate final financial authority to the operator UI, to Telegram, or to an AI or agent
// component. Those callers are untrusted: they may request actions and render authoritative
// responses, but every authorization, risk, order-state, and balance decision is made here
// (docs/25 section 2, docs/25 section 3.6).
package controlplane
