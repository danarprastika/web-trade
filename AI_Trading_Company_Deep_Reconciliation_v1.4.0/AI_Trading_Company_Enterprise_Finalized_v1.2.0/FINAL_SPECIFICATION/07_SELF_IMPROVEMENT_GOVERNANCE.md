# Self-Improvement Governance — Final

The system may generate hypotheses, features, models, strategies, prompts and execution improvements in Research/Shadow/Demo.

Every experiment records hypothesis, dataset versions, code version, model/prompt versions, parameters, random seeds where applicable, metrics, costs, failures and artifacts.

OOS data is frozen before evaluation and cannot be used for tuning the candidate under evaluation.

A candidate can progress only through the defined strategy state machine. No agent can grant itself approval. Live artifacts are immutable and cannot be modified in place.

Automatic rollback is allowed for operational safety when a predefined threshold is breached; it restores a previously approved artifact and records the decision. It does not promote a new artifact.
