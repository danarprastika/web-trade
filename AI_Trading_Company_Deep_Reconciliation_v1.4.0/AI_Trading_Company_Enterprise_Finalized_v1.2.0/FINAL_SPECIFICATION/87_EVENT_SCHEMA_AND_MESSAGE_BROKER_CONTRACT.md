# Event Schema and Message Broker Contract

Status: FINAL CODING BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code implementation
Scope: AI-native proprietary trading system

## 1. Canonical events

The canonical event catalog remains authoritative. New events require contract review and traceability.

## 2. Event envelope

Every event SHALL include the required canonical metadata: event identity/type/version, timestamps, correlation/causation information, producer, schema version, and payload according to the frozen runtime contract.

## 3. Delivery semantics

Consumers SHALL explicitly declare expected delivery semantics and handle duplicates, retries, poison messages, and ordering requirements.

## 4. Poison messages

Malformed or repeatedly failing messages SHALL be quarantined without blocking unrelated safety-critical processing.

## 5. Compatibility

Consumers SHALL tolerate approved schema evolution according to the versioning policy.

## Change control

This document is frozen for implementation. Any change requires a formal Change Request with impact analysis, affected contracts/tests, approval, implementation evidence, and traceability updates.
