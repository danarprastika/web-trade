# Identity Lifecycle and Access Review

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Control human and machine identities from provisioning through retirement.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Lifecycle
Request → approval → provisioning → periodic review → modification → suspension → revocation.

## Least privilege
Permissions are role/capability based, environment scoped and deny-by-default. Production credentials are never copied into lower-trust environments.

## Machine identities
Agents and services receive dedicated identities with explicit tool/API scopes, expiration/rotation rules and auditable ownership.

## Review
Critical production permissions require periodic review and immediate review after role change, incident or suspected compromise.
