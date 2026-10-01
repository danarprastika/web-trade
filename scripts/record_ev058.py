"""One-off: append EV-058.

Builds the composition root that WI-117 deferred to two items that do not cover it, which lets
the G5 restart criterion be met at the composition level. The gate verdict is still FAIL, for a
narrower reason.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-058"
STAMP = "2026-10-01T02:58:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The composition root exists, and it is the first code in this repository to construct an "
    "audit Exporter or a rehydrated journal. services/control-plane/bootstrap assembles the "
    "durable stack over its ports, in an order where each step is load-bearing, and rebuilding it "
    "over persisted state recovers what a previous stack registered. That closes WI-117's AC4 "
    "wiring gap and moves the G5 gate report from FAIL-on-restart to FAIL-on-startup: the "
    "mechanism now exists and is proven, and what remains is that no running process invokes it "
    "and no Go process has driven the SQL adapters behind its ports."
)

METHOD = (
    "Established ownership before building anything. WI-117's blocker said the missing composition "
    "root belonged to WI-164 and WI-165; checking showed WI-164 is deployment rehearsal and "
    "rollback and WI-165 is G10 release evidence, neither of which scopes service wiring, and "
    "that no item in the project brain mentions composing or bootstrapping anything except two "
    "that either do not need it or defer elsewhere. The dependency was dangling rather than "
    "owned, so building it was neither a duplicate nor a takeover. Then chose the seam by asking "
    "what would make the wiring testable: composing over the narrow ports the components already "
    "expose, rather than over the SQL querier interfaces, which would have required simulating a "
    "database to test assembly order. Wrote the tests before trusting the implementation and "
    "mutation-checked the two load-bearing properties rather than the package as a whole."
)

RESULT = (
    "bootstrap.Build composes chain, guard, exporter, sink, journal, registry and their durable "
    "ports. Seven tests, all passing. TestARebuiltStackRecoversWhatTheFirstStackRegistered is the "
    "one the gate turns on: it builds a stack, registers a model, exports its audit trail, then "
    "builds a second stack over the same durable state - fresh chain, fresh journal, fresh "
    "registry - and requires the model back with its owner intact. Two mutations confirm the test "
    "has teeth, and the second is the interesting one. Building the journal empty instead of "
    "rehydrating fails with 'did not survive the rebuild; a restarted control plane would report "
    "it as never registered'. Skipping the chain rehydration fails with CONFLICT, 'the registry "
    "has drifted from the evidence and cannot be restored' - the registry's own corroboration "
    "check catching an assembly-order mistake rather than corrupt data, which is the integrity "
    "guarantee doing exactly its job on a class of fault it was not written for. Ten further "
    "cases cover every missing dependency including a typed nil that a plain == nil waves "
    "through, and the empty-state first boot. 7 bootstrap tests, 189 model, race clean, vet and "
    "gofmt clean, all 13 gates pass. The G5 report now records G5.6 PASS and G5.7 FAIL across 58 "
    "artifacts."
)

DEFECT_FOUND_AND_FIXED = (
    "Two, neither in product behaviour. First, a dangling dependency: the composition root was "
    "required by WI-117, deferred by WI-117 to WI-164 and WI-165, and scoped by neither, so the "
    "thing standing between three gates and completion had no owner. Built it. Second, a "
    "corrupted record: WI-141's completion_note had grown a duplicated tail repeating the EV-044 "
    "rehydration summary and then the original closing sentence, which is the same sentence that "
    "carried the G4 error EV-057 corrected. The file therefore asserted the corrected gate in one "
    "place and the wrong one in another. Removed the duplicate and recorded the composition-root "
    "outcome in one guarded pass that verified, before keeping the edit, that the incorrect gate "
    "reference was gone, the EV-057 correction survived, and the rehydration summary appeared "
    "once. The duplicate predated this record's correction script and came from earlier work in "
    "this item; the script that should have caught it did refuse, because its guard required the "
    "note to end where it expected and it did not."
)

SIGNIFICANCE = (
    "The useful finding is about how a dependency goes missing without anyone noticing. Not one "
    "item claimed the composition root was nobody's business; one item said it was another item's, "
    "and that other item scopes deployment rehearsal and release evidence respectively. Each "
    "statement was locally reasonable and the pair is jointly wrong, which is the same shape as "
    "EV-052 and EV-053 - individually correct facts held by different components with nothing "
    "checking them against each other. What made it findable was refusing to copy WI-140's blocker "
    "onto G5 and instead searching docs/11 for the fields it actually requires, which is what put "
    "the G5 report in existence in the first place. The second point is that the composition root "
    "is now composed over ports rather than over query interfaces, and that choice is what made "
    "the assembly testable at all; the alternative would have required faking a database to test "
    "the one piece of code whose entire risk is being wrong in an order nobody notices."
)

CAVEATS = (
    "Five limitations. First, and the load-bearing one: bootstrap is not a process entrypoint. It "
    "opens no socket, reads no configuration, starts no server, and nothing in the repository "
    "calls it. It proves the stack can be assembled and rebuilt over durable state, which is what "
    "G5.6 now claims; it does not claim a running control plane does so, and G5.7 records that "
    "gap as FAIL rather than folding it into G5.6. Second, unchanged since EV-046: no Go process "
    "has connected to PostgreSQL. go.mod carries no driver, so the SQL sink, stores and readers "
    "behind these ports have never been driven by a live database; adding one is a dependency "
    "decision rather than a missing test, and EV-046 recorded a supply-chain concern about the "
    "pgx resolution. The bootstrap tests use the in-memory stores, which is why they can run at "
    "all and also why they prove less about the SQL path than their pass count suggests. Third, "
    "the audit records the test observes are produced by an in-memory sink, so the rebuilt chain "
    "is verified against a faithful reader rather than against PostgreSQL's timestamptz precision "
    "and real transaction semantics - the same boundary EV-048 onward has carried. Fourth, the "
    "composition root was not in WI-141's acceptance criteria, which say nothing about restart or "
    "composition; it was built because G5 could not otherwise pass and nothing else was chartered "
    "to build it, and it belongs in a work item that says so rather than being inferred from "
    "here. Fifth, unchanged: atomicity between audit acceptance and registry persistence remains "
    "WI-121's; the EV-048 schema-version forward problem remains unresolved and human-owned; "
    "RISK-14's six deferred scaling findings are open; no specification file was modified; docs/ "
    "remains clean at zero changes; nothing was staged; and nothing was committed. WI-141 remains "
    "IN_PROGRESS, the G5 gate verdict remains FAIL, and this record does not attest to either."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/bootstrap/bootstrap.go",
    "services/control-plane/bootstrap/bootstrap_test.go",
    "scripts/update_wi141_composition_root.py",
    "scripts/generate_g5_gate_report.py",
    "scripts/record_ev058.py",
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