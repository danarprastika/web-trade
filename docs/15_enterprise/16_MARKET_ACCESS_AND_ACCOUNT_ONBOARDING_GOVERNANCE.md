# Market Access and Account Onboarding Governance

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Control onboarding of brokers, exchanges, venues and accounts before any live interaction.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Onboarding record
Venue/provider identity, account identity, supported instruments, environment, permissions, connectivity, settlement assumptions, limits, owner and certification status.

## Certification
Connectivity, authentication, order semantics, fill semantics, cancellation behavior, rate limits, error handling, reconciliation and outage behavior are tested before live enablement.

## Isolation
Each market/account has explicit configuration and credentials. Cross-market/account leakage is prohibited.

## Enablement
Live enablement requires completion of applicable technical, security, risk, compliance/legal and owner approvals. No document here grants activation.
