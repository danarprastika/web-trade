# Failure Semantics

> Status: FINAL FROZEN BASELINE v1.0 — subordinate to FINAL_SPECIFICATION/.

## Purpose
Standardize how components fail.

## Classes

Retryable, non-retryable, transient, degraded, unknown-critical, data-invalid and policy-denied.

## Unknown-critical

Stops live mutation until state is verified.

## Recovery

Recovery is explicit; silent self-healing is not allowed to conceal material failures.
