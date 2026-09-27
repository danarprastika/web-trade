# Enterprise Architecture Principles

## Status
Controlled architecture guidance. No unresolved implementation choice is approved by this document.

## Principles
1. Domain authority is explicit and bounded.
2. Financial authority is separated from intelligence and presentation layers.
3. Risk controls are authoritative and fail closed.
4. Market environments are isolated.
5. Commands are validated before execution; events provide durable evidence.
6. Data lineage is preserved from acquisition through research, decision, execution, and reporting.
7. Every material state transition is observable and auditable.
8. Security controls are enforced by architecture and authorization, not by obscurity.
9. Polyglot components require a documented reason, ownership boundary, and operational contract.
10. External providers are treated as untrusted dependencies and must be certified before production use.
11. Human approval remains explicit for owner-controlled production actions.
12. The system must remain deterministic where deterministic behavior is a stated contract.

## Architecture Review Trigger
A review is required for changes affecting authority, trust boundaries, market isolation, financial state, canonical contracts, persistence semantics, security boundaries, model authority, or production gates.
