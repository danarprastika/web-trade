"""One-off: append EV-036 recording the .gitignore gap found while auditing the commit baseline.

Checking the untracked census before recommending a commit exposed a defect: 751 untracked paths
where 242 were expected. 509 of them were machine-generated Hypothesis caches that no ignore rule
covered, so the instruction in WI-140's blocker ("commit the working tree") would have swept a
quarter of a megabyte of environment-specific test cache into the initial platform commit.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-036"
STAMP = "2026-09-29T16:32:00Z"

WORK_ITEM = "WI-140"

CLAIM = (
    "The working tree was audited for what a commit would actually contain before that commit was "
    "recommended, and it was found to be unfit: 509 of 751 untracked paths were generated cache "
    "output that no ignore rule excluded. .gitignore now covers Hypothesis's example database, and "
    "the tree contains 242 untracked source paths and zero cache artifacts, so the initial "
    "platform commit can be made from a tree whose contents were verified rather than assumed."
)

METHOD = (
    "Ran scripts/untracked_census.py before recommending the commit and got 751 untracked paths "
    "against the 236 recorded in EV-033. That is too large a jump to be explained by the few files "
    "added since, so it was investigated rather than reconciled by editing the recorded number. "
    "Classified every untracked path against cache patterns (__pycache__, .pytest_cache, "
    ".mypy_cache, .ruff_cache, .hypothesis, egg-info, .pyc) using git status "
    "--untracked-files=all, which respects .gitignore and so cannot mask an unignored path. 509 "
    "paths matched: 255 under workers/backtest/.hypothesis and 254 under a root .hypothesis. "
    "Confirmed the cause with git check-ignore -v on both locations, which reported a matching rule "
    "for __pycache__ and no match for .hypothesis, then added the missing rule and re-verified."
)

RESULT = (
    ".gitignore gains a .hypothesis/ rule under the Python section, with a comment recording why it "
    "is safe to exclude: the backtest properties run with derandomize=True, so the example "
    "database can never improve a future run's shrinking and is a pure cache. After the change "
    "git check-ignore -v attributes both the root and per-test-directory .hypothesis trees to "
    "line 46, the census reports 242 untracked and 0 modified, and a re-scan for cache patterns "
    "returns 0 remaining cache paths. All 12 release gates still pass and precommit_scan.py still "
    "reports the tree safe to commit. The 242 paths are 236 recorded in EV-033 plus 6 added since, "
    "and every one is source."
)

DEFECTS = (
    "The defect was in .gitignore, and it was latent rather than visible: every other tool in the "
    "repository reported a clean state, because the caches are untracked and no check treats "
    "untracked as a problem. The census was the only instrument that could see it, and it was "
    "being run to confirm a number rather than to look for a change. The specific failure mode is "
    "worth stating, because it recurs: .gitignore grew incrementally, each Python tool added when "
    "it was introduced, and the entry added for Hypothesis was missed because the properties that "
    "produce the cache were written after the ignore file was last extended. Nothing failed. The "
    "cache would simply have been committed, once, into the first commit of the platform, where it "
    "is most expensive to remove because it establishes a tracked baseline. The compensating "
    "observation is that the census number changing without an explanation was treated as a finding "
    "rather than as noise; had the recorded 236 been treated as correct, the discrepancy would have "
    "been written over and 509 generated files would have entered history unexamined."
)

SIGNIFICANCE = (
    "This is the second time in this sequence that an instrument built for one purpose caught "
    "something it was not built for: scripts/untracked_census.py exists to count paths, and "
    "counting them is how the ignore gap surfaced. The pattern is that safety instruments drift "
    "out of date in exactly the place where the codebase has moved, because the thing they "
    "enumerate grows without them being revisited. A census run immediately before a commit is "
    "therefore not a formality to be repeated from the previous run's number; it is the check most "
    "likely to reveal a stale assumption, which is why this one was run against the live tree and "
    "the discrepancy investigated rather than reconciled."
)

CAVEATS = (
    "Four limitations. First, the ignore rule is correct for this repository as configured but is "
    "not universally correct: Hypothesis's own documentation recommends committing .hypothesis/"
    "examples in some CI setups so that a failing example is preserved across machines. That "
    "practice applies when the database is a cross-run regression corpus; here derandomize=True "
    "makes it environment-specific and unusable for that purpose, so excluding it is the right "
    "call and would be the wrong call under a different Hypothesis configuration. Second, the "
    "census now reports 242 rather than the 236 recorded in EV-033 and in WI-140's blocker text, "
    "which still cites 236; that number is stale by six files added since and should be read as "
    "the 236 baseline plus subsequent additions, not as a current count. Third, the underlying "
    "blocker is unchanged: the commit is a human action, was not requested, and was not made, and "
    "a named human reviewer is still required. Fourth, this was found incidentally rather than by "
    "design, so there is no check that would fail if a future tool introduced an unignored cache "
    "directory; a census-delta assertion against recorded expectations would be the natural "
    "instrument, and it is not built. No specification file was modified and docs/ remains clean."
)

ARTIFACTS = [
    ".gitignore",
    "scripts/untracked_census.py",
    "scripts/record_ev036.py",
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
    "event_id": "EVT-WI-140-COMMIT-BASELINE-AUDIT",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "commit_baseline_audited",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "Auditing the tree before recommending the initial platform commit found it unfit: 751 "
        "untracked paths where 242 were expected, 509 of them machine-generated Hypothesis caches "
        "that no ignore rule covered. __pycache__ and the other Python caches were already "
        "ignored; the .hypothesis example database was not, because the properties that produce it "
        "were written after .gitignore was last extended and the cache is produced by a test run, "
        "so no check had ever seen it fail. .gitignore now excludes it, justified by "
        "derandomize=True making the database an environment-specific cache that cannot help a "
        "future run. The census reports 242 untracked, 0 modified, 0 cache artifacts, all 12 gates "
        "pass, and the tree is safe to commit. The two remaining G4 fields, a named human reviewer "
        "and the commit itself, are unchanged and still require human action."
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
        if item["id"] == WORK_ITEM:
            refs = item.get("evidence_ref", [])
            if EVIDENCE_ID not in refs:
                item["evidence_ref"] = [*refs, EVIDENCE_ID]
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print(f"{WORK_ITEM} evidence updated")
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
