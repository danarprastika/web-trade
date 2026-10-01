"""One-off: append EV-055.

EV-054 recorded two compositions as resting on a probe that was then deleted. This closes that
caveat by making both permanent, and records an honest gate count: five of the thirteen gates
could not run today because the Docker daemon is down, and this record does not claim otherwise.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-055"
STAMP = "2026-10-01T01:12:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The two compositions EV-054 could only vouch for with a deleted probe are now permanent "
    "tests. The suite had refusal-then-retry coherence without a restart, and restarts without a "
    "refusal; the intersection - a restart taken while the chain holds a refusal and its "
    "resolution - was untested. Two tests cover it. Both pass, and both were mutation-checked "
    "against the specific property each exists to hold. This is a coverage change, not a defect "
    "fix: nothing in the code was wrong when it was written."
)

METHOD = (
    "Derived the gap by listing what each suite already covered rather than by reasoning about "
    "what should be covered, which is what made the gap visible: TestARefusedWriteThatIsRetried"
    "LeavesTheEvidenceCoherent covers refusal and resolution and no restart, while restore_test.go "
    "covered fifteen restart paths and no refusal. The first attempt did not compile - Register "
    "takes an actor type and an owner, not a bare record, and restore_test.go did not import the "
    "contracts package - which is the same class of mistake the EV-054 probe made four times and "
    "that this repository's tests invite because the helpers are not uniform: registeredModelN "
    "hides the Register call and step resolves the precondition from the real edge, so a test "
    "that avoids the helpers still has to know both signatures. Each test was then mutated at the "
    "one place its property is decided."
)

RESULT = (
    "TestARestartBetweenARefusalAndItsResolutionKeepsTheEvidenceCoherent asserts four things "
    "across the restart: the state the retried transition reached survived; exactly one refusal "
    "and exactly one resolution both survived, because a restart that kept the state but dropped "
    "the record explaining the failed write would leave the same unexplained gap EV-053 closed; "
    "and a client replaying the identical request after the restart is answered from the "
    "idempotency ledger - same audit identifier, and no record appended. "
    "TestARestartAfterARefusedRegistrationKeepsTheModel asserts the registration path separately, "
    "because it shares the commit path but derives its digests differently, and asserts the "
    "owner survived, which is what fixes the model to its audit partition. Mutations: emptying "
    "the idempotency ledger's restore loop fails the first test; dropping registered records "
    "during restore fails the second by name. Both reverted. 189 model tests, zero failures, race "
    "clean, vet and gofmt clean."
)

DEFECT_FOUND_AND_FIXED = (
    "None. The properties these tests assert were already true, which is the expected outcome for "
    "a coverage gap and is stated here plainly so the record is not mistaken for a defect report. "
    "The one thing found that is not a code defect: the first ledger mutation was detected, but "
    "not by the assertion written to detect it. Emptying the idempotency restore loop makes the "
    "replay a fresh request whose precondition no longer matches, so the test failed on the "
    "state guard - CONFLICT, the request claims EVALUATED while the model is VALIDATED - and "
    "never reached the audit-identifier comparison written for it. The mutation is caught either "
    "way, and the layered result is a fair one: losing the ledger does not double-apply a "
    "transition, because the state guard rejects the replay independently. But a test that is "
    "reached only after a guard upstream has already fired is not proving the thing its comment "
    "claims, and the audit-identifier assertion should be read as describing intent rather than "
    "as currently load-bearing."
)

SIGNIFICANCE = (
    "The gap was structural rather than accidental. A refusal record is the only record in the "
    "system saying a decision did not happen, and it is followed by one saying it did; every "
    "test written before today covered one side of that pair or the other, and rehydration was "
    "tested only against chains that never contained a contradiction. The window this project has "
    "now been bitten by three times - EV-052, EV-053, and the composition probe in EV-054 - is "
    "always a window where two correct facts are held by different components and neither is "
    "checked against the other. A restart landing between a refusal and its resolution is the "
    "narrowest such window in the registry, and it was the last one unguarded. The second point "
    "is about the ledger mutation being caught by a guard rather than by the intended assertion. "
    "That is not a defect in the code and not a defect in the test, but it is a fact about which "
    "property is load-bearing, and a reader who assumed the audit-identifier comparison was "
    "protecting it would be wrong. Recording the distinction is the difference between a coverage "
    "number that means something and one that does not."
)

CAVEATS = (
    "Four limitations, and the first is the one that matters most. Five of the thirteen project "
    "gates could not run today: db-0001-ledger, db-0002-audit, db-0003-authz, "
    "db-0004-model-registry, and migration-rehearsal. All five require a PostgreSQL instance "
    "provided by the Docker daemon, and the daemon is not running - the client reports version "
    "29.8.0 and no server. This is environmental and unrelated to this change: the three modified "
    "files under services/control-plane/db are sqlc-generated registry output from earlier work "
    "in this work item, and nothing in database/ or migrate/ was touched today. The eight gates "
    "that do not need a container all pass - toolchain, project-brain, pytest-ci, pytest-research, "
    "pytest-backtest, go-test-control-plane, sqlc-generate, sqlc-vet. EV-054 recorded thirteen of "
    "thirteen at 21:23Z, when the daemon was up; that record was accurate when written and is not "
    "amended, but it must not be read as a current gate status. Docker Desktop was not started to "
    "restore them, because the shell rules for this environment forbid launching background "
    "processes that way. Second: the composition EV-054 probed and found passing is now covered, "
    "so EV-054's second caveat is closed, but its other caveats stand - no Go process has ever "
    "connected to PostgreSQL, so none of the refusal, resolution, or restore paths has run against "
    "a live timestamptz or a real transaction. Third, the second new test is weaker than the "
    "first and is honestly weaker: restoring a registered record has no natural point to mutate "
    "short of dropping the record wholesale, so its mutation is closer to the property than the "
    "first test's, and its owner assertion guards partition assignment rather than anything the "
    "refusal path could disturb. Fourth, unchanged: no composition root constructs any rehydrated "
    "object, so rehydration is still explicit rather than automatic; atomicity between audit "
    "acceptance and registry persistence remains WI-121's; the EV-048 schema-version forward "
    "problem remains unresolved and human-owned; RISK-14's six deferred scaling findings are open; "
    "no specification file was modified; docs/ remains clean at zero changes; nothing was staged; "
    "and nothing was committed. WI-141 remains IN_PROGRESS pending human G4 review."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/model/restore_test.go",
    "scripts/record_ev055.py",
]

SUPERSEDES = []


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    line = json.dumps(
        {
            "schema": "ecc.project-brain/evidence/v7",
            "evidence_id": EVIDENCE_ID,
            "recorded_at": STAMP,
            "recorded_by": "team-lead",
            "work_item": WORK_ITEM,
            "claim": CLAIM,
            "status": "VERIFIED",
            "method": METHOD,
            "result": RESULT,
            "defect_found_and_fixed": DEFECT_FOUND_AND_FIXED,
            "significance": SIGNIFICANCE,
            "caveats": CAVEATS,
            "exception": EXCEPTION,
            "artifacts": ARTIFACTS,
            "supersedes": SUPERSEDES,
        },
        ensure_ascii=False,
    )

    if store.exists():
        for existing in store.read_text(encoding="utf-8").splitlines():
            if existing.strip() and json.loads(existing).get("evidence_id") == EVIDENCE_ID:
                print("unchanged: " + EVIDENCE_ID + " already recorded")
                return False

    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print("recorded " + EVIDENCE_ID)
    return True


if __name__ == "__main__":
    record()