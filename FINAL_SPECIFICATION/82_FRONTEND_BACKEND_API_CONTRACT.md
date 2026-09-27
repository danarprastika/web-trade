# Frontend–Backend API Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. API source of truth

The backend API schema is authoritative for frontend integration. API contracts SHALL be versioned and machine-validatable.

## 2. Required properties

Every endpoint/command SHALL define:
- authentication;
- authorization;
- request schema;
- response schema;
- validation rules;
- error codes;
- idempotency behavior;
- rate limits;
- timeout expectations;
- audit requirements.

## 3. Command safety

Frontend requests SHALL express intent, not privileged implementation details. The backend determines whether the requested action is permitted.

## 4. Errors

Errors SHALL use stable machine-readable codes plus safe human-readable messages. Internal stack traces, credentials, and sensitive infrastructure details SHALL never be exposed to the frontend.

## 5. Real-time events

WebSocket/SSE or equivalent streams SHALL use versioned event schemas and reconnect/resynchronization rules. Clients must tolerate duplicate or missed notifications by reloading authoritative state.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
