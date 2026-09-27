# Cryptography and Key Management Policy

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Principles

Cryptography SHALL protect secrets in transit, at rest, and in backups where applicable. Cryptographic choices must use maintained, industry-standard primitives and approved libraries. Security SHALL NOT depend on secrecy of algorithms.

## 2. Key separation

Keys SHALL be separated by:
- environment (development/test/demo/live);
- purpose (database, application, broker/API, signing, backup, telemetry);
- market/account boundary where risk warrants;
- operator/service identity.

Research and experimentation workloads SHALL never receive live execution keys.

## 3. Secret lifecycle

Secrets require creation, controlled distribution, rotation, revocation, expiry where supported, access logging, and emergency replacement. Credentials SHALL NOT be committed to source, images, logs, prompts, model context, or ordinary database records.

## 4. Signing and integrity

Security-sensitive artifacts and approvals SHOULD support cryptographic integrity or equivalent tamper-evident mechanisms. Verification SHALL occur before an artifact is accepted by a higher-trust component.

## 5. Emergency response

Suspected key compromise SHALL trigger credential revocation/rotation, affected-market containment, audit preservation, and incident handling before normal operation resumes.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
