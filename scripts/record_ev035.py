"""One-off: append EV-035 recording the coverage-completeness tests.

EV-032 and EV-034 each found, and fixed, the same class of omission: workers/backtest was absent
from the release gate script, and then from every touchpoint in the CI workflow. Both were found
by going looking after the first was fixed, and neither was caught by any existing check, because
every check in tests/ci asked a question about the workflow that is present and none asked which
code the workflow is supposed to cover.

This record adds the two tests that ask that question, and records that the first version of them
did not work.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-035"
STAMP = "2026-09-29T16:20:00Z"

WORK_ITEM = "WI-140"

CLAIM = (
    "The coverage gap that produced two separate findings is now an enforced invariant rather than "
    "a remembered lesson. tests/ci now asserts that every Python worker under workers/ is "
    "installed, tested, dependency-scanned, and licence-scanned in the CI workflow, and that "
    "every Python worker is exercised by a gate in scripts/run_gates.py. Both assertions "
    "discover workers from the tree rather than from a list, so a worker added tomorrow is "
    "covered without anyone updating a constant."
)

METHOD = (
    "First established what drifted and what could not. The Go modules are enumerated from "
    "go.work at run time by every Go step in the workflow, so a new Go module is picked up without "
    "touching the workflow and cannot fall out of coverage; that is the right design and no test "
    "is needed for it. The Python workers are named literally in the workflow, which is what made "
    "the omission possible, so that is where the invariant belongs. Read all run and "
    "working-directory lines in ci.yml to enumerate the actual touchpoints rather than guessing "
    "at them, and confirmed there are exactly four obligations for a worker: an install, a pytest "
    "invocation over its tests, inclusion in the pip-audit step, and a liccheck invocation naming "
    "its project. Added both tests to tests/ci/test_ci_workflow.py, then mutation-tested them by "
    "removing the backtest steps and licence scan from the workflow and requiring the tests to go "
    "red, restoring ci.yml by SHA-256 digest afterwards."
)

RESULT = (
    "Two tests added to tests/ci/test_ci_workflow.py, taking that file from 16 checks to 18 and "
    "the repository CI suite from 113 tests to 115. Both are proven to fail on the exact omission "
    "they exist to catch: removing the backtest test step produces "
    "'workers/backtest is not tested anywhere in ci.yml. A worker that is only partially covered is "
    "a worker that looks covered', and removing the backtest liccheck invocation produces "
    "'workers/backtest is not licence-scanned anywhere in ci.yml'. ci.yml was restored to "
    "SHA-256 406BF06DB71DEE01BCAED67424627F59BE52063896400399E13CEF63D61CDC86 and retains 6 "
    "references to workers/backtest. All 12 release gates pass, with the repository group at 115, "
    "64, and 47 tests. docs/ remains clean, nothing is staged, and scripts/precommit_scan.py still "
    "reports the tree safe to commit."
)

DEFECTS = (
    "One defect, in the test written to prevent a defect. The first version of the workflow "
    "coverage test asserted only that each worker's name appeared somewhere in the workflow text. "
    "Removing the backtest test step left every one of the 18 checks green, because the worker was "
    "still named in the lint step, so a substring assertion was satisfied by an unrelated "
    "reference. The test would have passed on a workflow that installed and mentioned the worker "
    "while never running its tests, which is the precise failure it was written to catch. It was "
    "restated to assert the four obligations separately, each against the command that discharges "
    "it, and both the test-step and licence-scan removals were then required to fail with a "
    "message naming the missing obligation. The lesson generalises past this file: a coverage "
    "check that greps for a name is not a coverage check, and it is most dangerous precisely when "
    "the thing it greps for is mentioned nearby for an unrelated reason - a lint step, a comment, "
    "a second scan - because that is exactly when the name is present and the coverage is not."
)

SIGNIFICANCE = (
    "The general point is that coverage of the *checker* is a different problem from coverage of "
    "the code, and only the first one degrades silently. Every existing check in "
    "tests/ci/test_ci_workflow.py asks a question about the workflow document: does it parse, is "
    "every action SHA-pinned, does every job have a timeout. All of those were satisfied while a "
    "whole worker went untested, because the question they ask is never 'does this workflow cover "
    "the code that exists'. Discovering this required a coincidence - noticing one omission and "
    "then asking where else it occurred - and the second omission was in the file that decides "
    "whether a change is merged. Encoding the invariant closes the coincidence: the next worker "
    "is covered or the suite fails, and the failure names which obligation is missing."
)

CAVEATS = (
    "Three limitations are worth stating. First, scope: tests/ci is outside WI-140's declared "
    "write_scope, which names workers/research and workers/backtest, and this is the third "
    "out-of-scope file changed in this sequence after scripts/run_gates.py and "
    ".github/workflows/ci.yml. The justification is the same and the disclosure is the same: these "
    "are verification and wiring changes that make the work item's own acceptance criteria "
    "enforceable, they are individually revertable, and the alternative was to fix the omission "
    "and leave nothing to prevent the next one. Second, the tests are as good as their discovery "
    "heuristic: they enumerate directories under workers/ containing a pyproject.toml. A Python "
    "distribution placed elsewhere in the tree would not be discovered, and the assertion that at "
    "least one worker is found would still pass, so the discovery is a convention rather than a "
    "proof. The Go side is deliberately not covered by these tests because it enumerates itself "
    "from go.work at run time, and asserting on that would be testing the mechanism rather than a "
    "gap. Third, these tests verify the workflow document, not the workflow's execution. Whether "
    "the CI steps actually pass is unverified here, because WI-107 established that there is no "
    "remote push available in this environment; that limitation is unchanged and was recorded in "
    "EV-034. No specification file was modified, docs/ remains clean, and nothing was committed."
)

ARTIFACTS = [
    "tests/ci/test_ci_workflow.py",
    ".github/workflows/ci.yml",
    "scripts/run_gates.py",
    "scripts/record_ev035.py",
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
    "event_id": "EVT-WI-140-COVERAGE-COMPLETENESS",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_hardened",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "The class of omission behind two separate findings is now an enforced invariant. Go "
        "modules are enumerated from go.work at run time and cannot drift out of coverage; the "
        "Python workers are named literally and could, and workers/backtest was absent from the "
        "gate script and from every CI touchpoint. tests/ci now asserts that every Python worker "
        "is installed, tested, dependency-scanned, and licence-scanned in ci.yml, and that every "
        "worker is exercised by a gate in run_gates.py, discovering workers from the tree rather "
        "than a list. The first version of the test asserted only that a worker's name appeared in "
        "the workflow, and removing the backtest test step left it green because the worker was "
        "still named in the lint step; it was restated to assert each obligation separately and "
        "both the test-step and licence-scan removals were then required to fail, naming the "
        "missing obligation. tests/ci grows from 16 checks to 18 and the CI suite from 113 to 115. "
        "All 12 release gates pass."
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
            updated = (
                "3 of 3 acceptance criteria verified; every injected defect detected and every "
                "file restored byte-for-byte; 64 research, 47 backtest (8 property-based) and 115 "
                "CI tests PASS; ruff and mypy strict clean on both workers; all 12 release gates "
                "PASS. Both workers are covered by CI, the gate script, and the dependency and "
                "licence scans, and that coverage is now an enforced invariant rather than a "
                "convention. Gate verdict FAIL pending the reviewer and commit fields."
            )
            if item.get("partial_results") != updated:
                item["partial_results"] = updated
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
