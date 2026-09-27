# Configuration Governance

> Status: FINAL FROZEN BASELINE v1.0 — subordinate to FINAL_SPECIFICATION/.

## Purpose
Make configuration a versioned and auditable artifact.

## Scope

Risk limits, market enablement, provider selection, model routing, schedules, feature flags, execution parameters and UI/Telegram permissions.

## Rule

No hidden environment variable may silently change live behavior. Effective configuration is resolved, versioned and traceable.

## Validation

Configuration schema, semantic validation, approval and rollback are required for live-impacting changes.
