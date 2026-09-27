# Financial Control and Accounting Assurance

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Define controls around cash, positions, fills, P&L and financial records without selecting an accounting policy prematurely.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Authoritative facts
Broker/exchange fills are external execution facts; the portfolio ledger is derived from valid fills and governed accounting rules. Reconciliation detects divergence rather than silently rewriting history.

## Control objectives
Completeness, accuracy, cutoff, valuation traceability, segregation of duties, immutable evidence and reproducible period reporting.

## Close process
Period close must freeze the applicable dataset/configuration versions, run reconciliation, record exceptions, generate controlled reports and preserve evidence.

## Adjustments
Corrections are append-only adjustments with reason, authority, source evidence and linkage to the original record; destructive edits are prohibited for authoritative history.

## Policy dependencies
Accounting basis, valuation conventions, tax treatment, legal entity ownership and reporting currency are organization-specific and require approved policy artifacts.
