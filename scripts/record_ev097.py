"""Record EV-097 and correct WI-118's blocker, which stopped being true when the repository was committed.

WI-118 has been BLOCKED with the same blocker text since before any code existed. Half of that
blocker is now false: it records HEAD as a specification-only commit with 236 untracked
implementation paths, and says a reviewer would have no baseline diff. The repository has 58
commits and the whole platform is tracked and pushed.

The other half is true and is the reason this file cannot claim the item unblocked: docs/11 requires
a named human reviewer in every gate report, and an agent recording itself as that reviewer would
satisfy the field and none of its purpose.

So the blocker text is corrected in place with a dated note rather than deleted, because the record
of why the item was blocked at the time is worth keeping and the correction is worth being able to
date. EV-097 points at .kilo/plans/program-status-2026-10-04.md, which holds the sequencing.

No attestation is asserted anywhere in this file. G0.8 and G1 both remain unsigned.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"
PROJECT = BRAIN / "project.json"

STAMP = "2026-10-04T09:00:00Z"
STATUS_DOC = ".kilo/plans/program-status-2026-10-04.md"
CORRECTION_MARKER = "CORRECTION 2026-10-04"

ARTIFACTS = [
    STATUS_DOC,
    "scripts/record_ev097.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    ".kilo/ecc/project-brain/project.json",
]

BLOCKER_CORRECTION = (
    "\n\n"
    "CORRECTION 2026-10-04: half of this blocker stopped being true when the platform was committed, "
    "and the item stays BLOCKED only because of the other half. The commit half is now false: HEAD "
    "was 15d978f with 236 untracked implementation paths and no baseline for a reviewer, and the "
    "repository now has 58 commits with the platform tracked and pushed to origin/main, so a "
    "reviewer has a real diff to read. The reviewer half is unchanged and is the whole of what "
    "remains: docs/11 requires a named human reviewer in every gate report, and an automated agent "
    "recording itself as that reviewer would satisfy the field and none of its purpose. So the "
    "practical consequence recorded above - no baseline diff to review - no longer holds, while the "
    "signature requirement does. Sequencing for what runs next, and the state of every remaining "
    f"item, is in {STATUS_DOC}."
)

EV_097 = {
    "evidence_id": "EV-097",
    "work_item": "WI-118",
    "claim": (
        "WI-118 is blocked on a named human reviewer and nothing else, and the remaining program is "
        "sequenced against that rather than against a stale reading of the repository"
    ),
    "status": "PARTIALLY_VERIFIED",
    "method": (
        "The blocker text was compared against the repository rather than against its own date: "
        "git rev-list --count HEAD, the tracked-file count, and the current status counts in "
        "work-items.json were all read before anything was written. The four defects reported by "
        "review on earlier commits were re-inspected in the current tree, each located in code."
    ),
    "result": (
        "Verified: the blocker is half false and half true, and the item remains BLOCKED. False: "
        "HEAD was a specification-only commit with 236 untracked implementation paths and no "
        "baseline for a reviewer. Now: 58 commits, the platform tracked and pushed, a real diff. "
        "True and unchanged: docs/11 requires a named human reviewer, which an agent cannot "
        "supply. The four earlier review findings - the migrate -to bound destroying the audit "
        "schema, the incomplete idempotency Outcome rebuilt on restore, a duplicate audit_id "
        "accepted within one batch, and the halt latch hiding a SEV-1 cause behind a backlog cause "
        "- were each located in the current code as fixed. NOT verified and not verifiable here: "
        "the reviewer field itself, which is why the status is partial rather than VERIFIED."
    ),
    "defect_found_and_fixed": (
        "1. WI-118's blocker described a repository that no longer exists: a specification-only HEAD "
        "and 236 untracked paths. Left in place it would have had the next reader believe a review "
        "baseline was still missing, and treated a solved problem as the reason work could not "
        "start. Corrected with a dated note that keeps the original text intact.\n"
        "2. project.json's plan.current_work_item still named WI-193 after WI-194 and WI-195 "
        "completed, so the brain pointed at a work item three behind the ledger."
    ),
    "significance": (
        "A blocker that has stopped being true is worse than no blocker, because it is believed. "
        "This repository's own record is that corrections travel in dated appends rather than "
        "silent rewrites - EV-091's scan result was corrected that way in WI-193 - and this is the "
        "same failure on a status field rather than on an evidence record."
    ),
    "caveats": (
        "The sequencing in the status document is a reading of the dependency graph, not a "
        "commitment on behalf of the reviewer. G0.8 and G1 both need a named human, so the gate "
        "reports cannot be completed and the platform cannot be declared operational regardless of "
        "how much engineering lands. Not verified: GitHub Actions, unreadable with an unauthenticated "
        "gh."
    ),
    "exception": (
        "None. A blocker was neither removed nor downgraded: WI-118 is still BLOCKED, and the "
        "correction narrows the stated reason rather than clearing it."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EV_097_FIELDS = (
    "claim",
    "status",
    "method",
    "result",
    "defect_found_and_fixed",
    "significance",
    "caveats",
    "exception",
    "artifacts",
    "supersedes",
)


def _read_records() -> list[dict]:
    if not EVIDENCE.exists():
        return []
    return [
        json.loads(line)
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_records(records: list[dict]) -> None:
    with io.open(EVIDENCE, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> bool:
    changed = False

    doc = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = doc["items"]
    target = next((i for i in items if i["id"] == "WI-118"), None)
    if target is None:
        raise SystemExit("record_ev097: WI-118 is not in the ledger; refusing to record a correction")
    blocker = str(target.get("blocker") or "")
    if CORRECTION_MARKER in blocker:
        print("unchanged: WI-118 correction already present")
    else:
        # Appended, never overwritten. The original text is what the item was blocked on at the
        # time, and a reader deciding whether the block still holds needs both halves.
        target["blocker"] = blocker + BLOCKER_CORRECTION
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        changed = True
        print("corrected WI-118 blocker")

    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    plan = project.get("plan") or {}
    if plan.get("current_work_item") == "WI-195":
        print("unchanged: plan.current_work_item")
    else:
        plan["current_work_item"] = "WI-195"
        project["plan"] = plan
        PROJECT.write_text(
            json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        changed = True
        print("updated plan.current_work_item")

    records = _read_records()
    appended: list[str] = []
    recorded = {record.get("evidence_id") for record in records}
    if EV_097["evidence_id"] not in recorded:
        records.append(
            {
                "schema": "ecc.project-brain/evidence/v7",
                "evidence_id": EV_097["evidence_id"],
                "recorded_at": STAMP,
                "recorded_by": "team-lead",
                **EV_097,
            }
        )
        appended.append(EV_097["evidence_id"])
    else:
        index = next(
            i for i, record in enumerate(records) if record.get("evidence_id") == EV_097["evidence_id"]
        )
        current = {key: records[index].get(key) for key in EV_097_FIELDS}
        wanted = {key: EV_097[key] for key in EV_097_FIELDS}
        if current != wanted:
            records[index].update(EV_097)
            appended.append(f"{EV_097['evidence_id']} (updated)")
            print(f"updated {EV_097['evidence_id']}")
        else:
            print(f"unchanged: {EV_097['evidence_id']}")
    _write_records(records)

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()