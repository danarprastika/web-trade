# Backend Go Service Architecture Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Service ownership

Go backend services SHALL have single, explicit responsibilities. Suggested boundaries include:
- API Gateway;
- Authentication/Authorization;
- Command Service;
- OMS;
- Execution Gateway;
- Market Data Gateway;
- Reconciliation Service;
- Event/Workflow Orchestrator;
- Notification/Control Service.

Exact service decomposition may remain implementation-dependent if contracts and authority boundaries are preserved.

## 2. Rules

Each service SHALL define:
- owned data/state;
- inbound contracts;
- outbound contracts/events;
- authorization requirements;
- failure behavior;
- timeout/retry policy;
- observability;
- owner;
- test strategy.

## 3. Go backend does not override Risk

Go services may route, validate, and orchestrate risk decisions, but SHALL NOT fabricate or bypass an authoritative Risk approval.

## 4. External providers

Provider adapters SHALL isolate broker/exchange/provider-specific protocols from canonical domain contracts.

## 5. Concurrency

Go services SHALL explicitly handle idempotency, duplicate messages, timeouts, retries, cancellation, backpressure, and partial failure.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
