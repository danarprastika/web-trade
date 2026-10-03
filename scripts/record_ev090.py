"""Record WI-189 and EV-090: Project Brain asserted a verified G0 that its own gate report contradicts.

Found by reading `.kilo/ecc/project-brain/project.json` against
`evidence/gates/G0-gate-report.json` while closing out fa2156f. Two of its fields were not merely
stale, they claimed the opposite of what the gate reports.

No attestation is asserted anywhere in this file, and none is implied by the change it records.
G0.8 remains REQUIRES_HUMAN_ATTESTATION and `verify_spec_gate.py` still exits 1.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-03T20:05:00Z"

ARTIFACTS = [
    ".kilo/ecc/project-brain/project.json",
    ".kilo/ecc/project-brain/work-items.json",
    ".kilo/ecc/project-brain/evidence.jsonl",
    "evidence/gates/G0-gate-report.json",
    "scripts/record_ev090.py",
]

WI_189 = {
    "id": "WI-189",
    "phase": 2,
    "title": (
        "Project Brain claimed G0 was verified and that the repository held no executable code, "
        "while the gate report it sits beside says G0 is pending a human signature and the tree "
        "holds 322 source files"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "No field in project.json claims the G0 gate passed, and the mechanical checks and the "
        "gate verdict are stated separately",
        "The gate verdict recorded in project.json names the report it was read from and the commit "
        "that report is stamped against",
        "current_state carries an as_of commit and file counts measured from that commit, and the "
        "counts are reproducible with git ls-files",
        "The historical baseline statement in the scale rationale is dated to the commit it was "
        "true at, so it cannot be read as a present-tense claim",
        "plan.current_work_item names the most recently completed item",
    ],
    "source": (
        "Reading project.json against evidence/gates/G0-gate-report.json while closing out fa2156f, "
        "after scripts/verify_spec_gate.py had just reported G0.1-G0.7 PASS, G0.8 "
        "REQUIRES_HUMAN_ATTESTATION and a verdict of PENDING_HUMAN_ATTESTATION."
    ),
    "reproduction": (
        "source_of_truth carried `\"g0_verified\": true` two lines above a method describing a "
        "SHA-256 and byte-length recompute, which establishes G0.1 through G0.7 and says nothing "
        "about G0.8. The same object carried `current_state.gates_passed: []`, so the file "
        "contradicted itself: the gate was verified and it had not passed. current_state also "
        "reported 27 tracked files and zero executable code, which were the counts at "
        "baseline_commit 15d978f, not at HEAD - the tree at 7733977 holds 445 tracked files "
        "including 171 Go, 147 Python, 4 TypeScript/JavaScript and 11 SQL sources. Nothing read "
        "any of these fields: a repository-wide grep for g0_verified, tracked_files_at_head, "
        "executable_code_at_head, gates_passed and current_work_item matched only project.json "
        "itself, which is why the contradiction survived every gate in the repository."
    ),
    "notes": (
        "The overclaim is the finding. `g0_verified: true` is the one field in the repository that "
        "would let a reader conclude a human attestation exists when none does, and it sits in the "
        "first file anyone opens. Replacing it with `g0_mechanical_checks_verified` plus an explicit "
        "`g0_gate_verdict` of PENDING_HUMAN_ATTESTATION, a source naming the report and commit it was "
        "read from, and a caveat stating the gate is not passed is the smallest change that makes the "
        "field mean what it can honestly mean.\n\n"
        "current_state was not simply wrong but structurally unable to be right: it carried no "
        "as_of, so any update to it would immediately become a stale present-tense claim. It now "
        "carries as_of_commit and as_of, and the file counts are reproducible with the git ls-files "
        "invocation recorded in EV-090 rather than asserted. SQL migrations are counted separately "
        "and explicitly excluded from executable_code_at_head, because 'executable code' should not "
        "silently include DDL.\n\n"
        "detected_toolchain still records go1.26.2 windows/amd64 and was deliberately left alone. It "
        "carries observed_at 2026-09-28 and is a dated observation rather than a live claim, so "
        "rewriting it would falsify the record rather than correct it. The same reasoning applies to "
        "the scale rationale's baseline statement, except that one used the present tense - 'Repo "
        "currently contains ZERO executable code' - and so could be read as a claim about today. It "
        "is now dated to baseline_commit rather than deleted, because it is the stated basis for the "
        "XXL rating and the rating must keep its justification."
    ),
    "dependencies": ["WI-188"],
    "evidence_ref": ["EV-090"],
}

EV_090 = {
    "evidence_id": "EV-090",
    "work_item": "WI-189",
    "claim": (
        "No file in Project Brain claims the G0 gate passed. The gate report is the source of that "
        "verdict, project.json agrees with it, and the state it records is dated and reproducible."
    ),
    "method": (
        "project.json was read against the gate report re-stamped from the same commit. The "
        "repository was searched for any reader of the fields in question - g0_verified, "
        "tracked_files_at_head, executable_code_at_head, gates_passed and current_work_item - and the "
        "only match is project.json itself. File counts were measured rather than estimated, with "
        "`git ls-files` filtered by extension, at commit 7733977."
    ),
    "result": (
        "project.json parses as valid JSON. source_of_truth now carries "
        "g0_mechanical_checks_verified, g0_mechanical_method, g0_gate_verdict "
        "PENDING_HUMAN_ATTESTATION, g0_gate_verdict_as_of 2026-10-03T19:09:59Z, "
        "g0_gate_verdict_source naming evidence/gates/G0-gate-report.json as stamped against "
        "fa2156f, and a caveat stating the gate is NOT passed. current_state carries as_of_commit "
        "7733977 with tracked_files_at_head 445, executable_code_at_head 322 and a breakdown of go "
        "171, python 147, typescript_javascript 4 and sql_migrations 11. plan.current_work_item is "
        "WI-188. The scale rationale's baseline statement is dated to baseline_commit 15d978f and "
        "points at current_state. `grep -r g0_verified` over the repository returns nothing."
    ),
    "defect_found_and_fixed": (
        "1. `source_of_truth.g0_verified: true` asserted a verified gate three lines from "
        "`current_state.gates_passed: []`. Renamed to g0_mechanical_checks_verified and paired with "
        "the gate verdict, its source and its caveat. "
        "2. `current_state` reported 27 tracked files and zero executable code, the counts at "
        "baseline_commit 15d978f, with no as_of to mark them historical. Now dated and measured. "
        "3. `scale.rationale` stated 'Repo currently contains ZERO executable code; all 8 phases are "
        "unstarted' in the present tense, which reads as a claim about HEAD. Dated to the baseline "
        "commit instead of removed, because it is the stated basis for the XXL rating. "
        "4. `plan.current_work_item` was still WI-101 while WI-188 had been completed. Moved to "
        "WI-188."
    ),
    "significance": (
        "This repository has now recorded green-but-vacuous gates nine times, and every one of them "
        "was a gate reporting something it had not measured. This is the same class pointed the "
        "other way: a state file asserting something nobody had verified. `g0_verified: true` next "
        "to `gates_passed: []` is a document that disagrees with itself about the single fact a "
        "reviewer most needs, and a reader who trusted it would conclude a named human had signed "
        "the specification package when nobody has. It survived because no gate reads Project Brain "
        "state - which is also why correcting the field is the whole of the fix, and why this record "
        "asserts no reader behaviour that was not searched for and found absent."
    ),
    "caveats": (
        "Nothing here attests to the specification package. G0.8 remains "
        "REQUIRES_HUMAN_ATTESTATION, evidence/gates/G0-gate-report.json still carries "
        "human_reviewer: null, and `python scripts/verify_spec_gate.py` still exits 1.\n\n"
        "The counts in current_state are a snapshot, accurate at 7733977 and stale the moment "
        "anything is committed - which is the reason as_of_commit is a required field of the block "
        "rather than an optional one. They are recorded as a snapshot, not as a claim to be "
        "maintained.\n\n"
        "detected_toolchain.go still reads go1.26.2 windows/amd64. That is left deliberately: the "
        "field carries observed_at 2026-09-28 and is a dated observation, and the Go toolchain was "
        "subsequently bumped to 1.26.8 (EV-080). Rewriting a historical observation would falsify "
        "it. The distinction is that detected_toolchain never used the present tense."
    ),
    "exception": "No exception. Nothing was softened to make a gate pass.",
    "artifacts": ARTIFACTS,
    "supersedes": [],
}


def record_work_item() -> bool:
    doc = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = doc["items"]
    existing = next((i for i in items if i["id"] == WI_189["id"]), None)

    if existing == WI_189:
        print("unchanged: WI-189 already recorded")
        item_changed = False
    else:
        if existing is None:
            items.append(WI_189)
        else:
            items[items.index(existing)] = WI_189
        with io.open(ITEMS, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        print("recorded WI-189")
        item_changed = True

    recorded = set()
    if EVIDENCE.exists():
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                recorded.add(json.loads(line).get("evidence_id"))

    if EV_090["evidence_id"] in recorded:
        print("unchanged: EV-090 already recorded")
        return item_changed

    with io.open(EVIDENCE, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "schema": "ecc.project-brain/evidence/v7",
                    "evidence_id": EV_090["evidence_id"],
                    "recorded_at": STAMP,
                    "recorded_by": "team-lead",
                    "work_item": EV_090["work_item"],
                    "claim": EV_090["claim"],
                    "status": "RESOLVED",
                    "method": EV_090["method"],
                    "result": EV_090["result"],
                    "defect_found_and_fixed": EV_090["defect_found_and_fixed"],
                    "significance": EV_090["significance"],
                    "caveats": EV_090["caveats"],
                    "exception": EV_090["exception"],
                    "artifacts": EV_090["artifacts"],
                    "supersedes": EV_090["supersedes"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    print("recorded EV-090")
    return True


if __name__ == "__main__":
    record_work_item()
