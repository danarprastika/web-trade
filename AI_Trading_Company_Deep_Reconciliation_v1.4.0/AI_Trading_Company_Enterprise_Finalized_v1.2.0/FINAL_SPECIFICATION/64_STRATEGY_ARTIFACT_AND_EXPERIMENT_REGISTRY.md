# Strategy Artifact and Experiment Registry Contract

Status: FINAL ENTERPRISE GAP-CLOSURE BASELINE v1.0
Authority: FINAL_SPECIFICATION + Enterprise Implementation Controls
Scope: Personal-use AI-native proprietary trading system; company-ready architecture
Implementation rule: Kilo Code MUST treat this document as normative unless a higher-priority document explicitly conflicts.

## 1. Immutable identity

Every strategy, model, feature set, dataset snapshot, prompt version, configuration, and experiment SHALL have immutable identity/version metadata.

## 2. Evidence chain

A candidate SHALL trace to:
research hypothesis → dataset/version → code/artifact version → experiment → backtest → walk-forward → OOS result → stress result → shadow/demo result → approval → deployment artifact.

## 3. No hidden state

A promoted artifact SHALL not depend on undocumented local files, mutable notebooks, undeclared environment variables, or untracked model state.

## 4. Reproducibility

A reviewer SHALL be able to reconstruct the evidence used for promotion from retained artifacts and metadata.

## 5. Promotion

Self-improvement may generate candidates and evidence but SHALL NOT self-authorize production promotion. Promotion authority follows the frozen governance chain.

## Change control

This document is frozen for implementation. Any change requires a documented Change Request, impact analysis, affected-test identification, reviewer approval, and traceability update. No implementation may silently reinterpret a frozen contract.
