# Authentication, Authorization, and Session Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Identity

All privileged operations require authenticated identity and explicit authorization.

## 2. RBAC/ABAC

Permissions SHALL be evaluated using role and applicable resource/environment/market/account scope. Least privilege and deny-by-default are mandatory.

## 3. Sessions

Sessions/tokens SHALL have controlled lifetime, revocation behavior, secure transport, and auditability.

## 4. Privileged actions

High-impact actions require stronger controls as defined by the human-approval and dual-control policy.

## 5. Service identities

Machine identities SHALL be separate from human identities and scoped to required services/resources only.

## 6. Emergency authority

Emergency human controls remain available but are audited and bounded.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
