# External Security Assessment and Red-Team Standard

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Assessment layers

Before live authorization, conduct proportionate assessment of:
- application/API security;
- identity and privilege boundaries;
- AI-agent/tool security;
- prompt-injection resistance;
- dependency and supply-chain security;
- network segmentation;
- broker/execution boundaries;
- operational recovery.

## 2. Red-team objectives

The red team SHALL attempt to demonstrate realistic paths to unauthorized live execution, risk bypass, secret theft, data tampering, cross-environment access, or suppression of safety controls.

## 3. Findings

Findings SHALL have severity, affected assets, reproducibility evidence, remediation, owner, and retest result.

## 4. Release rule

Critical unresolved findings affecting live authority SHALL block live authorization.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
