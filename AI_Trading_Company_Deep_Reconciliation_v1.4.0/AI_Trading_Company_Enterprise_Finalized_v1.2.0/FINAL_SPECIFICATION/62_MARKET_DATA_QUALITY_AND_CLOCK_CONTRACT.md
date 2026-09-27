# Market Data Quality and Clock Contract

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Provider trust

External market data SHALL be treated as untrusted input until validated, normalized, versioned, and accepted by the market-data pipeline.

## 2. Quality dimensions

At minimum evaluate:
- schema validity;
- timestamp validity;
- freshness;
- sequence continuity where available;
- price/quantity sanity;
- duplicate detection;
- cross-source consistency where applicable;
- instrument identity;
- corporate-action/reference-data consistency for relevant markets.

## 3. Degraded operation

A provider may be marked degraded or unavailable. Strategies SHALL NOT silently continue as if data were healthy when freshness or integrity requirements are violated.

## 4. Clock discipline

Market events must preserve source timestamps and ingestion timestamps. Backtests and replay SHALL never substitute future knowledge for historical event-time information.

## 5. Certification

Each provider adapter SHALL have certification tests covering malformed input, stale input, disconnect/reconnect, duplicate messages, sequence gaps, rate limits, and recovery.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
