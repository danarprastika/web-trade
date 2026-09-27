# Data Lineage and Reproducibility Contract

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

## 1. Lineage

Every research or production-relevant dataset must be traceable to:
source → ingestion → validation → normalization → transformation → feature generation → artifact/experiment.

## 2. Reproducibility

A research result used for promotion must identify the exact dataset, code, configuration, feature versions, model/prompt versions, and environment required to reproduce it.

## 3. Live data

Live trading must record enough metadata to reconstruct the inputs and decisions without requiring mutable external state that cannot be recovered.

## 4. Data correction

Corrections to historical data must be versioned. Historical results must not silently change without a new dataset version.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
