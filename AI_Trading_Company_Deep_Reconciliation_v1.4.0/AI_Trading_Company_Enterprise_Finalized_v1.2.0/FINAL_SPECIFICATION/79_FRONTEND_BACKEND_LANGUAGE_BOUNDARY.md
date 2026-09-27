# Frontend / Backend Language Boundary Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Mandatory separation

Frontend and backend SHALL use different primary implementation languages.

- Frontend: TypeScript.
- Backend: Go.
- Safety-critical core components: Rust where justified.
- AI/research/backtesting: Python.
- Persistence: SQL.
- Infrastructure: IaC.

The frontend SHALL NOT become a second backend and the backend SHALL NOT embed frontend business logic.

## 2. Frontend responsibilities

TypeScript owns:
- web control center;
- dashboards;
- operator workflows;
- authentication/session presentation;
- client-side validation for usability only;
- API/event-stream clients;
- visualization;
- configuration UX;
- approval UX;
- Telegram/web presentation integration where appropriate.

Frontend validation is never authoritative for risk, permissions, accounting, order validity, or live authorization.

## 3. Backend responsibilities

Go owns:
- authenticated API boundary;
- command handling;
- orchestration;
- service-to-service communication;
- OMS workflows;
- execution gateway orchestration;
- event publication/consumption;
- reconciliation orchestration;
- authorization enforcement;
- rate limiting;
- backend validation;
- audit integration.

## 4. Rust boundary

Rust is reserved for explicitly justified safety-sensitive or deterministic components. It must expose stable, versioned contracts to Go and must not become an alternate authority.

## 5. Python boundary

Python is isolated primarily to research, experimentation, model evaluation, feature work, backtesting, and offline/self-improvement workflows. Python workloads SHALL NOT receive live execution credentials.

## 6. Contract rule

Communication between languages SHALL use explicit schemas/contracts, versioning, validation, timeouts, error semantics, and observability. No component may depend on undocumented internal structures of another language runtime.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
