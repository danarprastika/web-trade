"""One-off: append EV-039 recording the WI-141 G5 audit-trail closure.

Records the first acceptance criterion as verified, and records the four defects the work
surfaced: registration was outside the declared transition set, the declaration rules were
untestable, one declaration check was narrower than the comment stating it, and the
concurrency gaps recorded as caveats in EV-038 are closed.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-039"
STAMP = "2026-09-29T17:44:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The first acceptance criterion of gate G5 - that identity, model registry, decision "
    "ledger, tool permissions, and governance workflows operate with complete audit trails - is "
    "now a property of the registry rather than an instruction to its callers. "
    "services/control-plane/model/journal.go is the registry's only write path: it validates a "
    "transition, appends the audit record describing it, and writes the lifecycle state only if "
    "the audit chain accepted that record."
)

METHOD = (
    "Started from the acceptance criteria in the project brain rather than from the code, which "
    "is what surfaced that AC1 had never been satisfiable: the audit package at "
    "services/control-plane/audit is complete and mutation-tested, and grep for audit.NewRecord, "
    "audit.Chain and audit.Record across services/control-plane returned nothing, so no component "
    "in the control plane wrote to it. Read audit/record.go, audit/chain.go and audit/verify.go to "
    "establish the record contract, the staging behaviour of Append, and the Verifier, then read "
    "model/lifecycle.go and model/record.go for the pieces the journal had to compose. Wrote "
    "journal.go, then journal_test.go, then extended the lifecycle table with the registration "
    "edge the journal exposed as missing, then parameterised the declaration verifier and wrote "
    "declaration_test.go, then closed the two concurrency gaps EV-038 recorded as caveats. "
    "Mutation-tested throughout with scripts/mutation_check_model.py, and treated a surviving "
    "mutation as a defect to diagnose rather than a number to report."
)

RESULT = (
    "journal.go adds Journal, the registry's only write path. NewJournal requires an audit chain, "
    "a clock, and a non-empty environment, refusing each rather than defaulting, because a "
    "Journal buildable without a chain is a registry whose audit trail is optional and that is "
    "the exact condition the gate excludes. Register places a model in REGISTERED and emits an "
    "audit record for it, on the reasoning that a model existing in the registry but absent from "
    "the audit chain could be promoted out of a history that does not contain its own existence. "
    "Transact runs four steps in a fixed order: Apply validates the request purely; the "
    "idempotency key is resolved before the state check, so a retry returns its recorded outcome "
    "rather than being rejected as stale; the current state is checked against the request's "
    "claimed source state, which is the check the transition table structurally cannot perform; "
    "and only then is the audit record appended, with the state write and the idempotency entry "
    "following the append. The audit partition is the model Owner, so one owner's governance "
    "activity is not usable to reason about another's. Each record carries the previous record's "
    "identity as CausationID, and the audit identity is derived from partition, model, action and "
    "destination state with the timestamp deliberately excluded, so a retry produces the same "
    "identity and the chain's duplicate-delivery path recognises it as the same record. "
    "lifecycle.go gains a declared registration edge with an empty source state, the command "
    "CommandRegister, the precondition PreconditionModelRecord, event type model.registered and "
    "scope model/lifecycle/register, bringing the table to eighteen declared edges. The "
    "allowance for an empty source is narrow and checked: only CommandRegister, only into "
    "REGISTERED. WorkloadRegistry gained a sync.Mutex held for the whole of each of its eight "
    "methods, and Journal holds one for the same reason. 118 model tests including 15 declaration "
    "cases, race-detector clean, go vet clean, gofmt clean, and all 12 release gates PASS. The "
    "mutation check is now 29 of 29 applied, 29 detected, 0 survived, 0 skipped, with every file "
    "restored byte-for-byte."
)

DEFECTS = (
    "Four defects. First, and the reason AC1 could not have been satisfied as written: the "
    "lifecycle table had no edge into REGISTERED. Registration was therefore not a declared "
    "transition at all - it had no event type, no precondition, no idempotency scope, and nothing "
    "VerifyDeclaration said anything about. A model could enter the registry outside the "
    "declared, audit-emitting transition set entirely, which is a gap in the same set the gate's "
    "first criterion is about, and it was not visible from the code because the absence of an "
    "edge looks exactly like the absence of a feature. The fix declares the edge rather than "
    "hardcoding an event type in the journal, so registration inherits the same treatment as every "
    "other state change and VerifyDeclaration can see it. Second, and found by a mutation that "
    "survived: the declaration rules in VerifyDeclaration were untestable. Every guard in that "
    "function is satisfied by the real table, so deleting any of them changed nothing observable "
    "and the rule it protected was written down but not enforced. The empty-source guard was "
    "provably deletable - the mutation applied, the full suite passed, and the guard was gone. "
    "The fix is to split the function into verifyDeclaration, which takes the table and the state "
    "universe, and VerifyDeclaration, which passes the package's own. A rule about a data "
    "structure can only be tested by handing that structure something malformed, and this one "
    "could not be handed anything. Third, a check narrower than the comment above it: the rule "
    "against leaving quarantine for a non-terminal state tested only the specific pair "
    "QUARANTINED -> EVALUATED, by hardcoded lookup, so a forged edge from QUARANTINED to "
    "MONITORED, PAPER or PROMOTED satisfied the check as written. The comment said no transition "
    "may leave quarantine for a non-terminal state; the code enforced one of the non-terminal "
    "destinations. It is now a range over every edge out of quarantine, tested by a forged edge "
    "to MONITORED. That check also read the global byFromTo map rather than the table under "
    "verification, so it was doubly untestable. Fourth, the two concurrency gaps that EV-037 and "
    "EV-038 recorded as caveats are now closed: WorkloadRegistry's eight methods each take a "
    "mutex for the whole method, and Journal holds one, both with concurrency tests that the race "
    "detector runs."
)

SIGNIFICANCE = (
    "The second defect is the one worth carrying forward, and it generalises beyond this package. "
    "A rule expressed as a check over the package's own data structure is only enforced if "
    "something can violate it, and here the only thing that could feed the checker was the real "
    "data, which was correct by construction. The mutation did not reveal a weak test; it "
    "revealed that the property was structurally unfalsifiable, because every test of "
    "VerifyDeclaration was in effect a test that the real table is well formed, which is a "
    "different claim from the one the function is named for. The general form: when a checker "
    "validates a structure, the tests that exercise the checker must supply structures the "
    "checker is meant to reject. Writing those tests required changing the checker's signature, "
    "which is the tell - a checker that cannot be handed a bad input is not really checking "
    "anything, it is asserting. The same shape is the third defect: a check narrower than the "
    "property named beside it, where the comment was the specification and the code was a "
    "handful of examples of it, and every green signal in the repository confirmed the examples."
)

CAVEATS = (
    "Six limitations, stated rather than buried. First, the journal is in-memory, as is the audit "
    "chain it writes to and the registry whose state it commits. A restart loses the model "
    "registry, every audit record, and the idempotency ledger together, and this is a persistence "
    "gap rather than a design choice: audit records that do not survive a restart cannot serve as "
    "evidence, and the model lifecycle that depends on them has the same lifetime. This remains "
    "the single largest gap and it is not closed by any of the work in this record. Second, "
    "Journa's atomicity guarantee is process-local. The append and the state commit are ordered "
    "under one mutex, which makes them atomic with respect to other goroutines in this process "
    "and not with respect to a crash: a process that dies between the append and the state write "
    "leaves an audit record describing a transition the registry does not reflect. The correct "
    "resolution is one database transaction spanning the audit insert and the state update, which "
    "requires the sqlc schema for a model registry that does not exist yet. Third, the audit chain "
    "itself is in-memory and its records are unkeyed, so Verify is called here with an empty key "
    "ring and no checkpoints; the hash chain is verified, the signatures are not, because there "
    "are none. A reader should not take the passing verifier as evidence of tamper-evidence "
    "against a privileged writer. Fourth, WorkloadRegistry is now safe for concurrent use but is "
    "still process-local, so the restart gap applies to revocations too: a revoked workload can "
    "re-mint itself after a restart, and that remains the most serious open item from EV-038. "
    "Fifth, ContainedModelVersions still has no caller, so no compromise is automatically widened "
    "to sibling identities serving the same model version. Sixth, Authenticate still performs no "
    "cryptographic verification, so what is enforced is the binding of a principal to one model "
    "version with a one-hour life and immediate revocation, not proof that the presenter is that "
    "principal. AC2, AC3 and AC4 were verified in EV-037 and are unchanged by this record; AC1 is "
    "verified as far as an in-process implementation can be, and the caveats above are the "
    "distance between it and a verdict. No specification file was modified, docs/ remains clean, "
    "nothing was staged, and nothing was committed."
)

ARTIFACTS = [
    "services/control-plane/model/journal.go",
    "services/control-plane/model/journal_test.go",
    "services/control-plane/model/declaration_test.go",
    "services/control-plane/model/lifecycle.go",
    "services/control-plane/model/identity.go",
    "services/control-plane/model/identity_test.go",
    "scripts/mutation_check_model.py",
]

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "claim": CLAIM,
    "status": "VERIFIED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECTS,
    "significance": SIGNIFICANCE,
    "caveats": CAVEATS,
    "exception": "",
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-141-AUDIT-TRAIL",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_implemented",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "AC1 of gate G5 closed as far as an in-process implementation allows: "
        "services/control-plane/model/journal.go is now the model registry's only write path, "
        "and it writes the lifecycle state only after the audit chain has accepted the record "
        "describing that state. The audit package existed, was complete, and had no consumer "
        "anywhere in the control plane. Four defects found and fixed. The lifecycle table had no "
        "edge into REGISTERED, so registration was outside the declared transition set with no "
        "event type, precondition, or idempotency scope, and the edge is now declared rather than "
        "hardcoded in the journal. The declaration rules in VerifyDeclaration were structurally "
        "untestable, so deleting the empty-source guard passed the entire suite; the function now "
        "takes the table and the state universe, and fifteen malformed tables are each refused. "
        "The check against leaving quarantine for a non-terminal state tested only the pair "
        "QUARANTINED to EVALUATED, so a forged edge to any other non-terminal state satisfied a "
        "comment promising otherwise; it is now a range over every such edge. The two "
        "concurrency gaps recorded in EV-037 and EV-038 are closed with mutexes and race-detector "
        "tests. 118 model tests, race clean, 29 of 29 mutations detected with byte-for-byte "
        "restore, all 12 gates PASS. The registry, the audit chain, and the idempotency ledger "
        "are all in-memory: a restart loses them together, which remains the largest open gap. "
        "WI-141 stays IN_PROGRESS; gate verdict FAIL."
    ),
}


def append_jsonl(path: Path, record: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def main() -> int:
    evidence_path = BRAIN / "evidence.jsonl"
    existing = [
        json.loads(line)
        for line in io.open(evidence_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(r.get("evidence_id") == EVIDENCE_ID for r in existing):
        print(f"{EVIDENCE_ID} already recorded; nothing appended.")
    else:
        append_jsonl(evidence_path, RECORD)
        print(f"appended {EVIDENCE_ID}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] == WORK_ITEM:
            refs = item.get("evidence_ref", [])
            if EVIDENCE_ID not in refs:
                item["evidence_ref"] = [*refs, EVIDENCE_ID]
                item["partial_results"] = (
                    "AC1 registry/audit/idempotency verified: journal.go is the registry's only "
                    "write path and writes the lifecycle state only after the audit chain accepts "
                    "the record describing it, verified by a test that poisons the chain and "
                    "requires the state to be unchanged. AC2 no model authorizes its own "
                    "execution verified. AC3 tool permission-denial, model rollback, and lineage "
                    "verified. AC4 all four compromise actions verified with the revocation now "
                    "performed rather than asserted. Identity: short-lived workload identity "
                    "bound to one exact model version, with immediate idempotent revocation that "
                    "carries reason and evidence into the refusal and blocks re-minting. "
                    "118 model tests race-clean, 109 research tests, 29 of 29 mutations detected "
                    "with byte-for-byte restore, all 12 gates PASS. Defects found and fixed: "
                    "registration was outside the declared transition set; VerifyDeclaration's "
                    "rules were structurally untestable so its empty-source guard could be "
                    "deleted with the suite green; the quarantine-exit check was narrower than "
                    "the comment stating it and only tested one of the non-terminal "
                    "destinations; Contain accepted a caller boolean asserting revocation had "
                    "happened; the mutation harness applied mutations cumulatively and could not "
                    "attribute its own verdicts. REMAINING: the registry, the audit chain, and "
                    "the idempotency ledger are all in-memory, so a restart loses them together "
                    "and the append-then-state sequence is not crash-atomic; the audit records "
                    "are unkeyed so the passing verifier is not evidence of tamper-evidence "
                    "against a privileged writer; WorkloadRegistry is concurrent-safe but still "
                    "process-local so a revoked workload can re-mint after a restart; "
                    "ContainedModelVersions has no caller; Authenticate performs no cryptographic "
                    "verification. Gate verdict FAIL; work item remains IN_PROGRESS."
                )
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print(f"{WORK_ITEM} evidence and partial_results updated")
    else:
        print(f"{WORK_ITEM} already up to date")

    events_path = BRAIN / "events.jsonl"
    seen = [
        json.loads(line)
        for line in io.open(events_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(e.get("event_id") == EVENT["event_id"] for e in seen):
        print(f"{EVENT['event_id']} already recorded; nothing appended.")
    else:
        append_jsonl(events_path, EVENT)
        print(f"appended {EVENT['event_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
