# Market Isolation and Cross-Market Guard Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Independent markets

Crypto, Forex, Stocks, and Commodities SHALL be independently enableable and isolatable.

## 2. Scope

Each market may have independent:
- strategies;
- data providers;
- adapters;
- risk policies;
- demo/paper portfolios;
- live credentials;
- execution venues;
- kill switch;
- configuration;
- failure state.

## 3. Cross-market access

Cross-market portfolio aggregation or intelligence requires explicit authorization and must not accidentally grant execution authority.

## 4. Failure containment

A market outage or quarantine SHALL not automatically disable or modify another market unless a higher-level portfolio/system policy explicitly requires it.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
