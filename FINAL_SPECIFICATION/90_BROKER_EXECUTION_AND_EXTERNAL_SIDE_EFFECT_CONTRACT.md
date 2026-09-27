# Broker Execution and External Side-Effect Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Boundary

The broker/exchange is an external authority. Internal state SHALL not be treated as proof of external execution.

## 2. Submission

Only valid OMS instructions carrying required risk approval and live prerequisites may reach the execution boundary.

## 3. Ambiguity

Timeouts, connection loss, or uncertain acknowledgments require reconciliation rather than blind resubmission.

## 4. Idempotency

Provider-specific client IDs or equivalent mechanisms SHALL be used where supported to reduce duplicate side effects.

## 5. Reconciliation

External state SHALL be reconciled against internal state before unsafe progression after execution uncertainty.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
