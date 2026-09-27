# Strategy Lifecycle and Promotion Governance

> Status: ENTERPRISE DOCUMENTATION BASELINE v1.2.0 — controlled planning baseline; subordinate to the applicable Normative Core and approved contracts.

## Purpose
Formalize the path from idea to research, validation, simulation, paper/shadow and any future live promotion.

## Authority and interpretation
- This document defines control intent and operating expectations; it does not silently approve unresolved values, credentials, legal positions, capital limits, or live activation.
- Where a value is marked TBD, it requires explicit owner-approved decision evidence before implementation may depend on it.
- Same-tier conflicts are fail-closed and require a recorded change request or decision.

## Lifecycle
Idea → specification → research → backtest → robustness/stress → out-of-sample → simulation → paper/shadow → readiness review → controlled promotion. Exact state names must align with the canonical state machine.

## Evidence package
Strategy identity/version, hypothesis, datasets, feature versions, code/model/prompt dependencies, assumptions, costs, risk profile, results, failure analysis and reproducibility evidence.

## Promotion rules
Promotion is a governed decision, not an AI self-action. Required gates must pass and the applicable owner approval must be recorded.

## Rollback
Every promoted strategy version has a known prior version or safe disable path. Emergency disablement may occur without waiting for normal promotion workflow.

## No performance promise
Historical or simulated performance does not establish future profitability and must not be treated as a guarantee.
