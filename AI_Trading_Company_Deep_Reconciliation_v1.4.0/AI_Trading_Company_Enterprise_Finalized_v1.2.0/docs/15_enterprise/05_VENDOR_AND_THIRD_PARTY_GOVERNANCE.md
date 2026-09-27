# Vendor and Third-Party Governance

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Control external providers whose failure or behavior can affect market data, AI models, infrastructure, brokers or security.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Provider classes
Market data; broker/exchange; cloud/hosting; AI model/API; observability; identity; messaging; security; developer tooling.

## Due diligence
Capture provider identity, service scope, data access, security evidence, availability commitments, contractual constraints, pricing model, exit path and accountable owner.

## Certification
Critical providers require functional certification, failure-mode testing, version pinning/compatibility evidence and rollback or alternate-provider planning where feasible.

## Change control
Provider changes that can alter trading behavior, data semantics, security posture or availability require impact assessment and controlled rollout.

## Exit
Maintain a documented offboarding path, credential revocation, data disposition and replacement strategy for critical providers.
