# Privacy and Sensitive Data Governance

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Data classification

Classify secrets, credentials, account identifiers, personal data, operational telemetry, research data, and public market data separately.

## 2. Minimization

Collect and retain only data required for system operation, audit, security, or documented research purposes.

## 3. AI context

Sensitive data SHALL NOT be inserted into model prompts or external AI services unless explicitly authorized by the security/data policy and required safeguards are present.

## 4. Logs

Logs SHALL avoid secrets and unnecessary personal/account information. Redaction and access controls are mandatory.

## 5. Lifecycle

Retention, archival, deletion, and backup behavior SHALL follow the existing data-lifecycle contract and any applicable legal obligations.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
