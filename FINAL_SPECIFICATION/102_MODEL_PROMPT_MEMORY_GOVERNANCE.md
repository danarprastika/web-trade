# Model, Prompt, and Memory Governance Contract

Status: FINAL TRUE-PRODUCTION BASELINE v1.0
Authority: FINAL_SPECIFICATION
Target: Kilo Code
Scope: Long-lived, production-capable AI-native proprietary trading system

## 1. Versioning

Models, prompts, system instructions, tools, agent policies, and relevant memory configurations SHALL be versioned.

## 2. Evaluation

A model/prompt change affecting trading intelligence requires evaluation against a fixed benchmark before promotion.

## 3. Memory

Memory SHALL be classified by trust and purpose. Untrusted external text must not silently become trusted agent memory.

## 4. Live boundary

A model/prompt/memory update SHALL NOT automatically modify live trading behavior without the required validation and promotion process.

## 5. Rollback

Every production AI artifact must have a known rollback target.

## Change control

This contract is frozen. Implementation-specific discoveries must use the project's Change Request process with impact analysis, review, tests, evidence, and traceability updates.
