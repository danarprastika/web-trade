# Human Approval and Dual-Control Contract

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. High-impact actions

The system SHALL identify actions requiring human approval or dual control, especially production promotion, material risk-policy changes, credential operations, and emergency recovery actions.

## 2. Separation

Where dual control is required, the same identity SHALL not both request and independently approve the protected action.

## 3. Evidence

Approval records SHALL contain actor identity, action identity, artifact/version, scope, timestamp, reason, and outcome.

## 4. Emergency path

The existing human emergency authority remains available. Emergency actions SHALL be logged, bounded, and reviewed after the event.

## 5. No model substitution

An AI agent may prepare evidence or recommend an action but SHALL NOT impersonate a required human approval.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
