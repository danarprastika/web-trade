# Enterprise RACI and Accountability Matrix

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Human owner

The human owner retains ultimate emergency authority and accountability for the proprietary trading system.

## 2. Lead/Orchestrator

Coordinates work and evidence but has no special authority to bypass architecture or risk controls.

## 3. Architect

Owns architectural consistency and change-impact analysis.

## 4. Planner

Turns approved specifications into bounded implementation plans and gate-scoped work.

## 5. Implementer

Implements approved contracts without changing frozen authority semantics.

## 6. Reviewer/Tester

Independently validates behavior, tests, invariants, and evidence.

## 7. Security

Owns security review, trust boundaries, secrets, threat-model findings, and security gates.

## 8. Risk

Owns authoritative risk-policy evaluation and veto semantics.

## 9. Execution

May execute only valid OMS instructions carrying required risk approval and all live prerequisites.

## 10. AI agents

Agents are subordinate workers. They may research, analyze, generate candidates, test, summarize, or coordinate within permissions, but cannot grant themselves authority.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
