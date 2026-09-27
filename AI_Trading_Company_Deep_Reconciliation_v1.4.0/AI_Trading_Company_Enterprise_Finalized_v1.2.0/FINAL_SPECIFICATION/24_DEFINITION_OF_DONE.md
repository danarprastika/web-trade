# IMPLEMENTATION DEFINITION OF DONE
## Gate-Level and Feature-Level Completion

Status: NORMATIVE

## 1. Feature DoD

A feature is done only when:
- requirement mapped;
- implementation complete;
- valid path tested;
- invalid path tested where applicable;
- security boundary tested where applicable;
- observability added where required;
- documentation/evidence updated;
- no known contract violation remains.

## 2. Gate DoD

A gate is done only when:
- all in-scope requirements implemented;
- all mandatory tests pass;
- relevant regression tests pass;
- static/security checks pass where applicable;
- evidence report exists;
- no unresolved blocker remains;
- deviations are documented;
- next gate is explicitly authorized by the gate result.

## 3. Not Done

The following do not constitute completion:
- code compiles;
- one happy-path test passes;
- an LLM says implementation is complete;
- TODOs are hidden;
- tests are deleted or weakened;
- behavior is manually demonstrated without reproducible evidence;
- a later-gate feature is partially implemented without being declared.

## 4. Live DoD

Live trading has an additional definition of done governed by:
- live gate prerequisites;
- Risk/live gate;
- security;
- operations;
- reconciliation;
- approvals;
- human emergency authority.

Implementation completion alone can never satisfy live activation.


## Long-lived production requirement
This implementation is NOT an MVP exercise. Kilo Code must implement production-capable foundations, failure paths, security, observability, upgradeability, and maintainability rather than optimizing for a demo or happy-path success.
