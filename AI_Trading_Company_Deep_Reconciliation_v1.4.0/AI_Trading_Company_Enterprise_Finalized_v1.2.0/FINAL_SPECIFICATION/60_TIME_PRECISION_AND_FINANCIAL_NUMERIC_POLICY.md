# Time, Precision, and Financial Numeric Policy

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Money and quantities

Financial calculations SHALL NOT use binary floating-point as the authoritative representation for monetary amounts, fees, balances, or quantities where exactness matters. Use decimal/fixed-point representations with explicit scale and rounding rules.

## 2. Rounding

Every financial calculation that rounds SHALL identify:
- source precision;
- target precision;
- rounding mode;
- currency/instrument-specific rules;
- whether rounding occurs before or after aggregation.

## 3. Time

All persisted timestamps SHALL be unambiguous and timezone-aware. The system SHALL distinguish:
- event time;
- ingestion time;
- processing time;
- broker/server time;
- database time.

Clock synchronization health SHALL be observable. Significant clock drift SHALL be a controlled failure condition for time-sensitive operations.

## 4. Determinism

Backtests, replay, reconciliation, and financial calculations SHALL use deterministic inputs and explicit versions of numeric/time policies.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
