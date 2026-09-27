# SRE Service Levels and Error Budgets

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Translate reliability requirements into measurable service objectives without inventing final numerical targets.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## SLO dimensions
Availability, latency, freshness, correctness, recovery time, reconciliation timeliness, queue health and control-plane responsiveness.

## Error budget principle
When an approved SLO is materially exceeded, feature velocity may be constrained in favor of reliability remediation. Critical safety controls are never disabled to preserve an error budget.

## Measurement
SLOs must define population, measurement source, window, exclusions, aggregation and owner.

## Target ownership
Final numerical targets are service-specific and require approval; this document defines the method, not the values.
