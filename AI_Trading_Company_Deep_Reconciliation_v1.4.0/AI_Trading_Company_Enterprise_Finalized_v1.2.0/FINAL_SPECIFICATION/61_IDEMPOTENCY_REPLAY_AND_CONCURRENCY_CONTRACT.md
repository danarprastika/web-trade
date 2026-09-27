# Idempotency, Replay, and Concurrency Contract

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Idempotency

Every command that can cause a state transition or external side effect SHALL have a stable idempotency identity. Repeated delivery SHALL not create duplicate live orders, fills, approvals, or irreversible side effects.

## 2. Replay protection

Consumed approvals, commands, and security-sensitive tokens SHALL have bounded validity and replay protection. Event consumers SHALL tolerate duplicate delivery according to the event contract.

## 3. Concurrency

Critical state transitions SHALL use optimistic versioning, transactional locking, compare-and-swap semantics, or another explicit concurrency mechanism. Last-write-wins SHALL NOT be used for authoritative trading state without a documented justification.

## 4. Ordering

Where ordering matters, the contract SHALL define the ordering key and the behavior for gaps, late events, and out-of-order delivery.

## 5. Recovery

Recovery procedures SHALL be able to identify whether an external side effect occurred before an internal acknowledgment was persisted.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
