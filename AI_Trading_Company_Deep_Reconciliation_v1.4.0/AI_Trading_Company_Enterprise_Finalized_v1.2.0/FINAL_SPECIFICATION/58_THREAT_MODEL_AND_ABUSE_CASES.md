# Threat Model and Abuse-Case Contract

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Objective

The system SHALL model threats against the complete trading lifecycle, not only the web application. Threat analysis covers users, AI agents, models, prompts, tools, market data, news, providers, brokers, APIs, infrastructure, CI/CD, dependencies, credentials, databases, event streams, and operational interfaces.

## 2. Required threat categories

At minimum assess:
- identity compromise and privilege escalation;
- unauthorized live-order creation;
- risk-gate bypass;
- replay, duplication, tampering, and event reordering;
- malicious or corrupted market data;
- prompt injection and hostile external text;
- malicious model/tool behavior;
- supply-chain compromise;
- secret exfiltration;
- broker/API impersonation;
- database corruption or unauthorized mutation;
- denial of service and resource exhaustion;
- insider/operator misuse;
- compromised CI/CD artifacts;
- clock/time manipulation;
- backup compromise and destructive recovery;
- cross-market or cross-environment isolation failure.

## 3. Required controls

Every threat SHALL map to preventive, detective, and recovery controls where technically applicable. High-impact paths SHALL have an explicit fail-closed behavior and an audit event.

## 4. Abuse-case testing

Before live authorization, security testing SHALL demonstrate that an attacker cannot:
1. create a valid live order without the required risk approval;
2. reuse an expired or already-consumed approval;
3. alter immutable live artifacts;
4. cross market/environment trust boundaries;
5. obtain research-only credentials;
6. turn external text into executable authority;
7. suppress reconciliation mismatches;
8. bypass kill switches through alternate interfaces.

Threat-model findings SHALL be linked to implementation gates and remediation tickets.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
