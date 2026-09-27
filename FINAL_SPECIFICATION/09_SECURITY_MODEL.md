# Security Model — Final

Trust zones: external world → ingestion boundary → normalized data → research/AI sandbox → governed core → execution boundary → broker/venue.

Secrets are never passed through prompts, logs, telemetry, agent memory or decision explanations. Live secrets are isolated from research/test environments.

External text is treated as potentially adversarial and cannot redefine system instructions or permissions. Prompt injection, tool misuse, dependency compromise, credential theft and supply-chain risks are tested.

Audit records are append-only, hash-linked and access-controlled. Security incidents can force system/market freezes and credential revocation.
