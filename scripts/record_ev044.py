"""One-off: append EV-044 recording that WI-117's AC4 is not implemented, and reopen it.

Found while assessing whether the rehydration blocker recorded in EV-042 and EV-043 was
really a blocker. It was traced to its owner rather than left as a caveat on someone else's
work item: the durable audit sink that rehydration would depend on is WI-117's AC4, and
WI-117 is marked COMPLETED. It is not implemented. This record states that, reopens the item,
and narrows the claim so it does not overreach into wiring that later phases legitimately own.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-044"
STAMP = "2026-09-30T07:40:00Z"

AUDIT_ITEM = "WI-117"
MODEL_ITEM = "WI-141"

CLAIM = (
    "WI-117's fourth acceptance criterion - bounded durable buffering, blocking sensitive "
    "operations before evidence can be lost, and never silently dropping audit events - is not "
    "implemented, and the work item is marked COMPLETED. The Guard that would implement it is "
    "correct in isolation, but it is un-wirable as it stands: its backlog is reduced by exactly "
    "one function, Exported, and nothing in the repository calls it outside its own test. There "
    "is no audit sink. A repository-wide search finds no production construction of "
    "audit.Chain, audit.Guard, or model.NewJournal; the only callers are tests."
)

METHOD = (
    "Started from the rehydration caveat recorded in EV-042 and EV-043, which asserted that "
    "restoring a restarted journal is blocked because the audit chain is in-memory. That claim "
    "had been carried for two evidence records without its owner being identified, which is "
    "itself a defect in how the caveat was written: a limitation attributed to the wrong work "
    "item will not be closed when the right one is. Read WI-141's acceptance criteria and "
    "confirmed they say nothing about restart or recovery, then read WI-117's and found AC4 "
    "describing precisely the missing system property. Read services/control-plane/audit/"
    "guard.go in full, then searched the whole repository for NewGuard, .Accept, .Exported, "
    "audit.NewChain and model.NewJournal, and for package main, to establish whether the gap "
    "is a missing sink or a missing composition root. Wrote a temporary test in the audit "
    "package to observe the consequence rather than assert it from reading, captured its "
    "output, and deleted the file."
)

RESULT = (
    "The distinction that the search forced is between three things that a fast reading "
    "conflates. First, the Guard's policy is implemented and tested: a bounded backlog, a "
    "latched fail-closed halt, explicit Clear, no drop, no overwrite-oldest, no truncate, and "
    "a correct class split that keeps read-only and risk-reducing operations available while "
    "halting. Observed in the temporary run: at a limit of 3, the fourth Accept returns "
    "DEPENDENCY_UNAVAILABLE with cause EVIDENCE_BACKLOG, risk-increasing operations are then "
    "refused, and risk-reducing operations continue to be permitted. Second, the durable "
    "buffering half does not exist. audit_records, audit_checkpoints and audit_deletion_events "
    "are created by db/migrations/0002_audit.sql and db/dbgen/audit.sql.go is generated, but "
    "no Go code writes to them; Chain holds records in a map and the comment at chain.go:13 "
    "defers the archive to a store that was never written. Third, the consequence: because "
    "Exported is the only thing that reduces pending, and nothing calls it, a guard wired today "
    "would accept exactly its limit and then halt permanently, with the backlog still at the "
    "limit and recovery possible only through a manual privileged Clear(). Observed in the same "
    "run: pending=3, halted=true, recovery requires a manual Clear(). That is not a wiring gap "
    "deferred to a later phase, because no later wiring can satisfy the guard's exit condition; "
    "the exit condition has no producer. The absence of a composition root is a separate and "
    "legitimate deferral: the only package main in the repository is a parked artefact under "
    ".kilo/ecc/project-brain/evidence/wi-106/, and deployment and production-readiness are "
    "WI-164 and WI-165, both PENDING. This record therefore reopens WI-117 for the missing "
    "sink and the guard's unsatisfiable exit condition, and explicitly does not charge WI-117 "
    "with the missing entrypoint."
)

DEFECTS = (
    "Three defects, in the code and in my own records. First, a completed work item asserts "
    "an acceptance criterion that does not hold. The repository contains a well-built Guard, a "
    "migrations file, and generated queries, and the natural reading - which the status field "
    "actively invites - is that the audit subsystem is finished. AC4 is not finished; roughly "
    "the policy half exists and the durability half does not. A status of COMPLETED on an "
    "unmet criterion is the specific failure this project brain exists to prevent, and it is "
    "worse here than a not-started item, because it removes the work from the outstanding set. "
    "Second, and this one is mine: EV-042 and EV-043 both recorded rehydration as a limitation "
    "of WI-141 without identifying that the blocker belongs to WI-117. Two evidence records "
    "described a gap on the wrong work item, which means closing WI-141 would never have closed "
    "it, and a reviewer reading only WI-141 would not have known to look. The general form is "
    "that a caveat recorded against the convenient work item stops being anyone's job. Third, "
    "the demonstration was written as a passing test and then deliberately deleted rather than "
    "committed, because it asserts the current behaviour - a permanent halt - without asserting "
    "the required behaviour, and committing it would encode the defect as the specification. "
    "The observed output is recorded here instead. The honest place for that assertion is "
    "alongside the sink implementation, where it can fail until the sink exists."
)

SIGNIFICANCE = (
    "The general form is that a control's completeness is a property of the system, not of the "
    "component. Guard is a correct implementation of a policy and it would pass any review "
    "conducted on the file, because within guard.go every rule is honoured and every edge is "
    "tested. What it does not contain is the thing that makes the policy reachable: a counter "
    "whose only decrement path has no caller is an absorbing state, and a component whose "
    "correct behaviour depends on a collaborator that does not exist will look finished right up "
    "until the moment it is connected. The second general form is about the evidence records "
    "themselves. A limitation attached to the wrong work item is worse than an unrecorded one, "
    "because it is discoverable, appears resolved by the closing of the item it was attached "
    "to, and will not be re-examined. When a blocker resists solution, the question worth "
    "asking is not how to work around it but whose acceptance criterion it is failing, and that "
    "question has an answer that was sitting in the project brain the whole time."
)

CAVEATS = (
    "Four limitations on this record. First, this is a static and behavioural finding, not a "
    "runtime one: no process was started, because there is no entrypoint to start. The absence "
    "of production wiring is established by search over the whole repository and not by "
    "observation of a running system. Second, the finding covers the audit sink and the guard's "
    "exit condition only. It does not assert that WI-117's other criteria are unmet: the hash "
    "chain, checkpoints, retention, key rotation, and the in-memory verifier are implemented "
    "and tested, and nothing here disputes them. Third, no specification file was modified, "
    "docs/ remains clean, and no status was changed without an evidence record attached to the "
    "affected item. The status change is reversible: WI-117's previous COMPLETED state and its "
    "completed_at stamp are preserved in this record and in the item's own completion_note, so "
    "a reviewer who disagrees with the reading can restore it. Fourth, the missing composition "
    "root is real but is deliberately not charged to WI-117; it belongs with WI-164 and WI-165, "
    "and recording it here would have been the same category of error as attributing the sink "
    "gap to WI-141. Also unchanged from earlier records: the mutation harness remains a "
    "verification activity rather than a release gate, consistent with EV-032, EV-034, EV-037, "
    "EV-039, EV-040, EV-041, EV-042 and EV-043. Nothing was staged and nothing was committed."
)

ARTIFACTS = [
    "services/control-plane/audit/guard.go",
    "services/control-plane/audit/chain.go",
    "db/migrations/0002_audit.sql",
    "services/control-plane/db/dbgen/audit.sql.go",
    "scripts/record_ev044.py",
]

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": AUDIT_ITEM,
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
    "event_id": "EVT-WI-117-AUDIT-SINK-NOT-IMPLEMENTED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": AUDIT_ITEM,
    "event": "work_item_reopened",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "WI-117's AC4 - bounded durable buffering, block sensitive operations before evidence "
        "can be lost, never silently drop audit events - is not implemented, and the item was "
        "marked COMPLETED. Reopened as IN_PROGRESS. Found by finally asking whose acceptance "
        "criterion the EV-042/EV-043 rehydration blocker was failing, after carrying it as a "
        "WI-141 caveat for two evidence records without identifying the owner. The Guard's "
        "policy is implemented and tested - bounded backlog, latched fail-closed halt, explicit "
        "Clear, no drop, no overwrite-oldest, no truncate, and a class split that keeps "
        "read-only and risk-reducing operations available. Observed: at limit 3 the fourth "
        "Accept returns DEPENDENCY_UNAVAILABLE with EVIDENCE_BACKLOG, risk-increasing is then "
        "refused, risk-reducing still permitted. The durability half does not exist: 0002_audit "
        "creates audit_records, audit_checkpoints and audit_deletion_events, dbgen/audit.sql.go "
        "is generated, and no Go code writes to any of them; Chain keeps records in a map and "
        "its own comment defers the archive to a store that was never written. The sharp "
        "consequence is that Exported is the only thing that reduces the backlog and nothing "
        "outside its own test calls it, so a guard wired today would accept exactly its limit "
        "and halt permanently with pending still at the limit, recoverable only by a manual "
        "privileged Clear - observed as pending=3, halted=true. No later wiring can satisfy "
        "that exit condition, because it has no producer; this is not a deferral. Separately, "
        "and NOT charged to this item: there is no composition root anywhere - the only package "
        "main is a parked artefact under .kilo/ecc/project-brain/evidence/wi-106/, and no "
        "production code constructs audit.Chain, audit.Guard, or model.NewJournal - but that "
        "belongs with WI-164 and WI-165, both PENDING, and charging it here would repeat the "
        "error this record exists to correct. Two of the three defects are in my own records: "
        "EV-042 and EV-043 both attributed the blocker to WI-141, so closing WI-141 would never "
        "have closed it and a reviewer reading only WI-141 would not have known to look. A "
        "caveat attached to the convenient work item stops being anyone's job. The third is "
        "that the demonstration was written as a passing test and then deleted rather than "
        "committed, because it asserts the current permanent halt without asserting the "
        "required behaviour and would have encoded the defect as the specification; the "
        "observed output is recorded here instead. This does not dispute WI-117's other "
        "criteria - chain, checkpoints, retention, key rotation and the in-memory verifier are "
        "implemented and tested. The prior COMPLETED state and completed_at stamp are preserved "
        "so the change is reversible."
    ),
}

WI117_BLOCKER = (
    "Reopened by EV-044: AC4 is not implemented, so the COMPLETED status overstated the state. "
    "The Guard that would implement it is correct in isolation and tested - bounded backlog, "
    "latched fail-closed halt, explicit Clear, no drop, no overwrite-oldest, no truncate, and a "
    "class split that keeps read-only and risk-reducing operations available - but its backlog "
    "is reduced by exactly one function, Exported, and nothing outside guard_test.go calls it. "
    "There is no audit sink: db/migrations/0002_audit.sql creates audit_records, "
    "audit_checkpoints and audit_deletion_events and db/dbgen/audit.sql.go is generated, but no "
    "Go code writes to them, so the durable-buffering half of AC4 does not exist. Observed "
    "consequence: with a limit of 3 the fourth Accept halts with DEPENDENCY_UNAVAILABLE and "
    "pending still at 3, and recovery is possible only through a manual privileged Clear. A "
    "guard wired in its current state would therefore latch permanently at its limit, and no "
    "wiring can fix that because the exit condition has no producer. To close: implement a "
    "durable audit sink that exports accepted records and calls Exported, and add the assertion "
    "that a guard whose sink recovers drains its backlog and un-halts without a manual Clear. "
    "NOT part of this item: the absence of a composition root, which belongs to WI-164 and "
    "WI-165. Not disputed: the hash chain, checkpoints, retention, key rotation and the "
    "in-memory verifier, which are implemented and tested. The previous COMPLETED state and its "
    "completed_at stamp are preserved in the item's completion_note and in EV-044, so a reviewer "
    "who disagrees with this reading can restore the status."
)

MODEL_NOTE = (
    " EV-044 traced this item's rehydration blocker to its owner: the in-memory audit chain "
    "that prevents rehydrating a restarted journal is WI-117's AC4, and that criterion is not "
    "implemented, so rehydration is blocked by unmet work on another item rather than by "
    "anything left to do here. WI-141's own acceptance criteria say nothing about restart or "
    "recovery, and the audit-before-state ordering this item claims is verified for the writes "
    "that happen in-process, which is what the tests exercise."
)


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
        if item["id"] == AUDIT_ITEM:
            # Preserve the prior terminal state so the change is reversible and auditable
            # rather than a quiet overwrite of a completion claim.
            prior = item.get("completion_note", "")
            marker = "Status was COMPLETED until EV-044; completed_at " + str(
                item.get("completed_at", "unknown")
            ) + "."
            if marker not in prior:
                item["completion_note"] = (prior + " " + marker).strip()
            refs = item.get("evidence_ref", [])
            if EVIDENCE_ID not in refs:
                item["evidence_ref"] = [*refs, EVIDENCE_ID]
            if item.get("status") != "IN_PROGRESS":
                item["status"] = "IN_PROGRESS"
                changed = True
            if item.get("blocker") != WI117_BLOCKER:
                item["blocker"] = WI117_BLOCKER
                changed = True
        elif item["id"] == MODEL_ITEM:
            note = item.get("completion_note", "") or ""
            if "EV-044 traced" not in note:
                item["completion_note"] = (note + MODEL_NOTE).strip()
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print(f"{AUDIT_ITEM} reopened and {MODEL_ITEM} annotated")
    else:
        print("work items already up to date")

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
