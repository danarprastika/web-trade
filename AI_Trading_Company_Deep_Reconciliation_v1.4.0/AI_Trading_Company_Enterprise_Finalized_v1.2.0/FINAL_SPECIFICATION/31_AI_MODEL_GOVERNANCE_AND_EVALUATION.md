# AI MODEL GOVERNANCE AND EVALUATION
## Production AI Control Contract

Status: NORMATIVE IMPLEMENTATION CONTROL

## Model lifecycle

Every model/provider used by the AI layer must have:
- identity/version;
- intended role;
- allowed tools;
- allowed data;
- prompt/configuration version;
- evaluation evidence;
- fallback behavior;
- resource limits;
- failure behavior;
- audit identity.

## Evaluation

Evaluation must cover, as applicable:
- factual reliability for the task;
- structured-output compliance;
- tool-use safety;
- prompt-injection resistance;
- refusal/failure behavior;
- latency/resource constraints;
- regression;
- deterministic behavior where required.

## Trading boundary

Model output is not trading authority.

AI output must remain subordinate to the frozen authority chain and cannot bypass Risk, authorization, reconciliation or live gates.

## Model changes

Changing a production-bound model, prompt, tool permission or routing policy must be versioned and evaluated.
