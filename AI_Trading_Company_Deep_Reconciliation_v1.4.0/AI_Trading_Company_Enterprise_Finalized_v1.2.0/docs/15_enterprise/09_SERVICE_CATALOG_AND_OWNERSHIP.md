# Enterprise Service Catalog and Ownership

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Make the production system understandable as a set of owned services/capabilities.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Required fields
Service ID, name, purpose, owner, tier/criticality, dependencies, interfaces, data classes, deployment unit, SLOs, runbooks, alerts, recovery method and lifecycle state.

## Critical services
Risk Engine, OMS, Execution, Reconciliation, Portfolio/Accounting, Market Data, Identity/Auth, Audit Ledger and Control Plane require explicit ownership and operational coverage.

## Dependency mapping
Dependencies are versioned and reviewed. A service must not silently depend on an ungoverned production capability.

## Lifecycle
Proposed, active, degraded, maintenance, deprecated, retired. Retirement requires migration and evidence preservation.
