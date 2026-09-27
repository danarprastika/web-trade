# Enterprise Risk Control Catalog

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Authority

Risk remains the mandatory hard gate. No AI component, strategy, OMS component, or operator interface may bypass the authoritative risk decision for a protected live action.

## 2. Minimum control families

The implementation SHALL support policy-driven controls for applicable markets:
- maximum order notional;
- maximum position/exposure;
- concentration;
- leverage;
- margin;
- loss limits;
- drawdown limits;
- daily/session limits;
- strategy limits;
- account/portfolio limits;
- market limits;
- liquidity/size constraints;
- stale-data protection;
- volatility/regime constraints;
- duplicate-order protection;
- kill-switch state;
- broker/account health;
- reconciliation health.

## 3. Fail-closed

If a required risk input is missing, stale, contradictory, or unavailable, the decision SHALL fail closed for the protected action.

## 4. Explainability

Every risk decision SHALL record the policy version, evaluated inputs, decision, reason codes, and correlation identity needed for audit and replay.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
