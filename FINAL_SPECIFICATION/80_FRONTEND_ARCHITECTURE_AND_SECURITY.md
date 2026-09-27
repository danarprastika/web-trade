# Frontend Architecture and Security Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Architecture

The web application SHALL be a TypeScript application separated into:
- presentation/UI;
- client state;
- API client;
- event/stream client;
- authorization-aware route guards;
- validation;
- telemetry.

## 2. Security

The frontend SHALL:
- use secure transport;
- avoid storing long-lived secrets;
- never contain broker credentials;
- never contain authoritative risk logic;
- never construct privileged backend commands outside the defined API contract;
- protect against XSS, CSRF where applicable, injection, unsafe redirects, and insecure client-side storage.

## 3. Backend authority

Every security-sensitive operation SHALL be re-authorized and validated by the backend. Hiding a button is not authorization.

## 4. Operator safety

High-impact workflows SHALL clearly display:
- environment;
- market;
- account/portfolio;
- strategy/artifact version;
- approval status;
- risk status;
- action scope;
- confirmation requirements.

## 5. Failure behavior

If backend state is stale, disconnected, or ambiguous, the UI SHALL indicate the state and SHALL NOT imply that an action succeeded.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
