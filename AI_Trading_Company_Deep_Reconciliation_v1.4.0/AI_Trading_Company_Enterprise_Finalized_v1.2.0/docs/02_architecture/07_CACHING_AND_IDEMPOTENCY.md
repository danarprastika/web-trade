# Caching & Idempotency

> Status: FINAL FROZEN BASELINE v1.0 — subordinate to FINAL_SPECIFICATION/.

## Purpose
Prevent duplicate actions and stale state.

## Idempotency

Order submission, command execution, event handling, reconciliation and financial mutations require explicit idempotency strategy.

## Caching

Caches are never authoritative for risk, balances, positions or broker state.

## Staleness

Every cache has freshness policy and invalidation semantics.
