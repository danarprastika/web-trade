# Database Transactional Integrity Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Authority

Canonical trading state SHALL have a clearly defined authoritative persistence model.

## 2. Transactions

State transitions that must be atomic SHALL occur within appropriate database transactions or equivalent transactional mechanisms.

## 3. Constraints

Database constraints SHALL enforce critical invariants where practical, including identity uniqueness, required relationships, valid status transitions, and immutable/audit properties.

## 4. Migrations

Schema changes require versioned migrations, backward-compatibility analysis, rollback/forward-recovery planning, and test evidence.

## 5. No direct mutation

AI/research components SHALL NOT directly mutate authoritative live trading tables outside approved service contracts.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
