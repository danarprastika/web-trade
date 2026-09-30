"""One-off: append EV-033 correcting the untracked-path figure recorded in EV-031.

EV-031's blocker text states that "23 paths in the working tree are untracked or modified". The
repository says otherwise: 27 paths are tracked, all of them under docs/, and 236 paths are
untracked - the entire platform implementation, which has never been committed at all. Nothing
tracked is modified, so the second half of that phrase is wrong too.

The figure is not incidental. A reviewer sizing the outstanding commit from "23 paths" would
believe the work is nearly committed and that a small follow-up commit closes the blocker. In
fact the next commit is a first commit of the whole platform, and no diff exists against which
to review it. That difference changes what the reviewer is being asked to do, which is why the
error is corrected rather than left standing.

evidence.jsonl is append-only, so EV-031 is not rewritten. The correction is a new record that
names the superseded claim, which is the auditable form: the original reading and its correction
both remain visible. The mutable blocker field on the work item is updated to match.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-033"
STAMP = "2026-09-29T13:10:00Z"

WORK_ITEM = "WI-118"

CORRECTED_BLOCKER = (
    "Two of the six fields docs/11_EXECUTION_GATES.md requires in every gate report cannot be "
    "produced by an automated agent, and docs/11 forbids partial completion. (1) reviewer: a "
    "named human reviewer; an automated agent recording itself as the reviewer would satisfy the "
    "field and none of its purpose, and the same package already treats an unattested "
    "specification as not passed at G0.8. (2) commit: the repository has committed only the "
    "specification. HEAD is 15d978ff5658c0646a63ce5ecc74b998e8bc05a4 and its entire content is "
    "the 26 files under docs/ plus docs/MANIFEST.json, 27 tracked paths in total, of which zero "
    "are modified. All 236 implementation paths are untracked: services (66), contracts (31), "
    "components (28), scripts (23), apps (20), workers (19), .kilo (14), tests (8), db (7), "
    "adapters (3), infra (3), and the remaining top-level files. This corrects EV-031, which "
    "recorded the figure as 23 untracked-or-modified paths; the real figure is 236 untracked and "
    "0 modified, and the earlier text understated the outstanding commit by an order of "
    "magnitude while implying tracked files were modified, which none are. The practical "
    "consequence is that the next commit is a first commit of the entire platform rather than a "
    "small follow-up, so a reviewer has no baseline diff and is reviewing 236 new files against "
    "nothing. A pre-commit safety scan of all 237 candidate paths found no credential-shaped "
    "literal, no private key, no real environment file, and no build artefact, so the tree is "
    "safe to commit; scripts/precommit_scan.py reruns that scan. No commit was requested or "
    "made. Both fields clear by human action: commit the tree, then have a named reviewer attest."
)

CLAIM = (
    "The outstanding-commit blocker recorded against WI-118 materially understated the size and "
    "shape of the work left to do. The repository contains no implementation history at all: the "
    "only committed content is the specification under docs/. Everything built since - six Go "
    "modules, the contract package, three database migrations and their verification SQL, the "
    "gate and verification scripts, the CI workflow, the Python research and backtest workers, "
    "and the deployment topology - exists only in the working tree. The corrected figures are 27 "
    "tracked paths, all under docs/, zero of them modified, and 236 untracked implementation "
    "paths."
)

METHOD = (
    "Counted the paths with git rather than with a filesystem walk, so the figures reflect what "
    "git would actually stage and exclude the same paths .gitignore excludes. Ran "
    "git ls-files for tracked and modified paths, git ls-files --others --exclude-standard for "
    "untracked, and git log --oneline -1 for the current HEAD, then grouped the untracked paths by "
    "top-level area. The earlier figure was checked rather than assumed: it was not reproducible "
    "by any reading of the repository, and the coincidence that 23 is the size of the scripts "
    "directory suggested where it had come from without explaining it. Confirmed the staged set "
    "independently with git add -A --dry-run, which reported exactly the same 236 paths with no "
    "caches, virtual environments, or compiled binaries among them. Because a human is about to "
    "make a first commit of everything, scripts/precommit_scan.py was then written to scan all "
    "candidate paths for credential-shaped literals, private key blocks, forbidden environment "
    "filenames, and build artefacts, so that the safety of the action is checkable rather than "
    "asserted."
)

RESULT = (
    "27 tracked paths, all under docs/, zero modified. 236 untracked implementation paths, "
    "distributed as: services 66, contracts 31, components 28, scripts 23, apps 20, workers 19, "
    ".kilo 14, tests 8, db 7, adapters 3, infra 3, .github 2, evidence 2, and one each for "
    "toolchain, ops, .env.example, .gitattributes, .gitignore, Makefile, README.md, go.work, "
    "go.work.sum and sqlc.yaml. git add -A --dry-run stages exactly those 236 paths and no "
    "others. scripts/precommit_scan.py scanned 237 candidate paths and reported no "
    "credential-shaped literal, no private key block, no real environment file, and no build "
    "artefact; the only environment file present is .env.example, the sanctioned template that "
    ".gitignore explicitly re-admits. Separately, and to establish the state a reviewer would "
    "otherwise have to take on trust, all twelve release gates were run and all twelve pass: "
    "toolchain (14 checks), project-brain, pytest-ci (113 tests), pytest-research (64), "
    "pytest-backtest (39), db-0001-ledger (18 database assertions), db-0002-audit (20), "
    "db-0003-authz (54), migration-rehearsal (up, down to a clean catalog, and up again), "
    "go-test-control-plane, sqlc-generate, and sqlc-vet."
)

DEFECTS = (
    "One defect, in the record rather than in the code: EV-031's blocker text stated that 23 paths "
    "in the working tree were untracked or modified. Both halves are wrong. Nothing tracked is "
    "modified, so there is no modification to speak of, and the untracked count is 236 rather than "
    "23. A record that understates by an order of magnitude is worse than one that is merely "
    "incomplete, because the reader is not left to notice a gap - they are left with a confident "
    "figure that points the wrong way, sizing the outstanding commit at roughly a tenth of its "
    "real size and implying the implementation is already largely committed when in fact none of "
    "it is. The error survived a project-brain verification that reports PASS, which is itself "
    "worth noting: verify_project_brain.py checks that the required fields are present and "
    "non-empty, not that the prose inside them is accurate, so a wrong figure is indistinguishable "
    "from a right one to the gate. The correction is recorded as a new evidence record rather than "
    "by rewriting EV-031, because evidence.jsonl is append-only and an audit that is edited to "
    "look correct is not an audit."
)

SIGNIFICANCE = (
    "The general point is that a blocker description is load-bearing and decays without anyone "
    "noticing. EV-031 was accurate to the best of its knowledge when written, and became wrong as "
    "more work landed, because nothing recomputed the figure it asserted. Recorded facts about a "
    "moving repository need either recomputation or a statement of when they were true; a bare "
    "number carries an implied currency it cannot maintain. The same reasoning is why the "
    "pre-commit scan is a script rather than a sentence: 'the tree is safe to commit' is a claim "
    "about 237 files that a future file could invalidate, so it is expressed as a command that "
    "re-derives it."
)

CAVEATS = (
    "This record corrects a figure; it does not advance any work item. WI-118 and WI-140 remain "
    "BLOCKED on the same two human-dependent fields, and nothing here clears either. Three "
    "limitations are worth stating. First, the correction is verified by count rather than by "
    "review: the figures come from git and are reproducible, but the judgement that the EV-031 "
    "wording is misleading rather than merely stale is the recorder's. Second, the safety scan "
    "reports what its patterns recognise. It is deliberately narrow to avoid matching prose, and "
    "the worker docstrings discuss credentials at length, so a credential written in an unusual "
    "shape would not be found; a clean result means the tree is safe against the shapes checked, "
    "not that it is free of secrets. Third, running all twelve gates here establishes the current "
    "state of a tree that is not yet committed, so it says nothing about whether that state is "
    "reproducible from a clean checkout - which is exactly the question a first commit raises and "
    "which this work item cannot answer before the commit exists. No commit was made, no "
    "specification file was modified, and docs/ remains clean."
)

ARTIFACTS = [
    "scripts/untracked_census.py",
    "scripts/precommit_scan.py",
    "scripts/record_ev033.py",
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
    "supersedes": ["EV-031"],
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-118-BLOCKER-CORRECTED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "evidence_correction",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "Correction to EV-031's outstanding-commit blocker. The repository has committed only "
        "the specification: 27 tracked paths, all under docs/, zero modified, and 236 "
        "untracked implementation paths covering every Go module, the contract package, the "
        "migrations, the gate scripts, the CI workflow, and the Python workers. EV-031 recorded "
        "this as 23 untracked-or-modified paths, understating the outstanding commit by an order "
        "of magnitude and implying tracked files were modified when none are. The next commit is "
        "therefore a first commit of the entire platform, and no baseline diff exists for a "
        "reviewer. The tree was verified safe to commit: 237 candidate paths scanned, no "
        "credential-shaped literal, private key, real environment file, or build artefact, and "
        "all twelve release gates pass. WI-118 and WI-140 remain BLOCKED; both still need a "
        "human commit and a named reviewer."
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
        print(f"appended {EVIDENCE_ID} to {evidence_path.name}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] in ("WI-118", "WI-140"):
            refs = item.get("evidence_ref", [])
            if EVIDENCE_ID not in refs:
                item["evidence_ref"] = [*refs, EVIDENCE_ID]
                changed = True
            # The commit half of the blocker was wrong on both items. WI-140's own text was
            # closer to right, describing workers/ as untracked, but both now carry the
            # corrected repository-wide figure so a reader is not left with two different
            # descriptions of the same outstanding action.
            if item["id"] == "WI-118":
                if item.get("blocker") != CORRECTED_BLOCKER:
                    item["blocker"] = CORRECTED_BLOCKER
                    changed = True
            else:
                updated = item.get("blocker", "").replace(
                    "HEAD is 15d978ff5658c0646a63ce5ecc74b998e8bc05a4 and the entire workers/ "
                    "tree, including every file this evidence covers, is untracked, so no commit "
                    "contains the work being certified.",
                    "HEAD is 15d978ff5658c0646a63ce5ecc74b998e8bc05a4 and its entire content "
                    "is the 27 specification paths under docs/; all 236 implementation paths are "
                    "untracked, including the whole workers/ tree, so no commit contains the "
                    "work being certified. The next commit is a first commit of the platform "
                    "rather than a follow-up, so no baseline diff exists for a reviewer; see "
                    "EV-033 for the full census and a pre-commit safety scan.",
                )
                if updated != item.get("blocker"):
                    item["blocker"] = updated
                    changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print("WI-118 and WI-140 blockers corrected")
    else:
        print("blockers already corrected")

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
