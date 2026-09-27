# Operator Control Center Safety Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Single control plane

The web application is the primary operator control center. Telegram is a secondary control/monitoring console and SHALL respect the same authorization and backend authority.

## 2. Visibility

The operator must be able to distinguish:
- research;
- shadow;
- demo/paper;
- live;
- halted/quarantined;
- degraded;
- reconciliation-uncertain states.

## 3. Dangerous actions

Live-sensitive operations SHALL require explicit scope confirmation and appropriate approval.

## 4. No false success

UI and Telegram SHALL report an action as successful only when the backend has a definitive accepted result.

## 5. Audit

Operator actions from web and Telegram SHALL enter the same audit/correlation model.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
