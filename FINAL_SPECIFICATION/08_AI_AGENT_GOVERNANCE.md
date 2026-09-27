# AI Agent Governance — Final

Each agent contract contains: identity, mission, allowed environments, input schemas, output schemas, tools, resource budget, permissions, forbidden actions, escalation rules, evaluation metrics, memory scopes and failure policy.

AI output is never authoritative for accounting, risk limits, broker state or authorization. Structured outputs are validated before use. Model/tool failures result in rejection, fallback or quarantine according to policy.

Research agents have no live credentials. Risk agents can evaluate/veto but cannot submit orders. Execution agents can submit only OMS instructions carrying valid risk approval. Master AI coordinates but has no direct live-order authority.
