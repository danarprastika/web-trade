"""One-off: append EV-032 and record WI-140 as BLOCKED.

All three acceptance criteria of WI-140 hold mechanically, and each was shown to go red when its
control was removed rather than being marked satisfied by inspection. The item is nevertheless
recorded BLOCKED, for the same reason as WI-118: docs/11_EXECUTION_GATES.md makes a gate PASS
only when every listed criterion is satisfied, and forbids recording partial completion as a
pass. The G4 report requires a named human reviewer and a commit containing the work, and neither
can be produced by an automated agent. Recording COMPLETED would contradict the gate it points at.

Idempotent and auditable, like record_ev026.py through record_ev031.py, and written without a BOM
because a BOM at the start of a JSONL line corrupts the record.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-032"
STAMP = "2026-09-29T12:40:00Z"

BLOCKER = (
    "The two G4 report fields that docs/11_EXECUTION_GATES.md requires and that an automated "
    "agent cannot honestly produce are outstanding. (1) reviewer: a named human reviewer. An "
    "agent recording itself as the reviewer would satisfy the field and none of its purpose, and "
    "the same package already treats an unattested specification as not passed at G0.8. (2) "
    "commit: HEAD is 15d978ff5658c0646a63ce5ecc74b998e8bc05a4 and the entire workers/ tree, "
    "including every file this evidence covers, is untracked, so no commit contains the work "
    "being certified. No commit was requested or made. Both clear by human action: commit the "
    "working tree, then have a named reviewer attest."
)

CLAIM = (
    "All three acceptance criteria of WI-140 hold against the repository, each verified by "
    "running a command rather than by reading an artifact. Datasets are versioned by content "
    "address and cannot claim a fingerprint that does not match their bars. Backtests are "
    "deterministic: no clock, no ambient state, seeded randomness per decision, and decimal "
    "arithmetic with floats refused at the content-addressing boundary. Artifacts are "
    "reproducible, with lineage inside the digest rather than printed beside it. Neither worker "
    "holds financial authority, credentials, or a network, database, or process-spawning "
    "capability, and that is now verified structurally against both packages and both dependency "
    "sets. The backtest harness contains no lookahead bias, and the result carries the evidence "
    "of its own visibility so the claim can be re-derived by a reviewer."
)

METHOD = (
    "Mapped each acceptance criterion onto the module that implements it and tested the "
    "criterion rather than the implementation's intent. For versioning, "
    "workers/research/tests/test_dataset.py asserts that identical content yields an identical "
    "fingerprint, that a fingerprint cannot be supplied that does not match its bars, and that "
    "compute_fingerprint is order-independent. For determinism and no-lookahead, "
    "workers/backtest/tests/test_harness.py runs every strategy twice for byte equality, and "
    "asserts that a seed is load-bearing, that one decision's draws do not shift the next, and "
    "that no ambient state reaches a result. For artifacts, tests/test_artifacts.py asserts the "
    "digest is a function of content including every lineage field. For the authority boundary, "
    "workers/research/tests/test_authority_boundary.py parses both packages with ast rather than "
    "a text search, and asserts no forbidden import, no forbidden declared dependency, no "
    "credential-shaped literal, no console entry point, and that every dependency is pinned. "
    "Because a green suite proves nothing about whether its tests can fail, every property was "
    "then mutation-tested: thirteen deliberate defects were introduced across harness.py, "
    "artifacts.py, dataset.py, and the pyproject manifests, and each was required to turn the "
    "suite red, with every file restored and digest-checked afterwards."
)

RESULT = (
    "13 of 13 injected defects detected; 13 test files' worth of assertions re-verified after "
    "restore, with harness.py restored to SHA-256 D635B7DDC44DFBF96156D1F5A5E761A41D67FC45EC8F"
    "8EAB462B4387A19E16B5 and artifacts.py to FA78DA91F3F11C7D92EBB07700EA0006966B57E26C3E65F6C"
    "8D8291B33188DE5. Mutation coverage by control: harness.py, four defects (visibility sliced "
    "on event_time, a shared rather than per-decision random stream, a schedule derived from "
    "event_time, and a deadened fabricated-instant check), each caught by the test that names it, "
    "the first failing with the message 'saw (0, 1, 2) but only (0, 1) was available then; "
    "lookahead on [2]' so the verifier was shown to catch an engine bug through the second code "
    "path rather than by inspection. artifacts.py, three defects (a digest computed over the "
    "result but not the lineage, an added approved_by field, and the no-lookahead gate removed "
    "from build_artifact), caught by 4, 1, and 2 tests respectively. dataset.py, two defects (a "
    "disabled fingerprint verification and a removed sort in compute_fingerprint). The authority "
    "boundary, four defects (an import of requests, httpx added to dependencies, numpy loosened "
    "to a range, and a credential-shaped literal), each caught with the offending file named. "
    "Final state: 64 research tests, 39 backtest tests, and 113 repository CI tests all PASS; "
    "ruff and mypy strict clean on both workers; verify_toolchain.py reports 14 checks passed; "
    "verify_project_brain.py reports PASS; docs/ remains clean with the SHA-256 manifest intact."
)

DEFECTS = (
    "Five defects were found in the work and in the tests meant to certify it, and the first is "
    "the one worth carrying forward. First, and the only mutation that initially survived: "
    "removing the sort from Dataset.compute_fingerprint left all 63 tests green, because "
    "Dataset.create sorts before calling it, so the create path masked a compute_fingerprint that "
    "did not sort. The two entry points genuinely disagreed -- compute_fingerprint called "
    "directly with unsorted bars returned a different digest than create returned for the same "
    "bars -- and the method's own docstring claimed the sort happened there. The test that was "
    "supposed to cover this asserted the property only through create, so it was asserting the "
    "behaviour of the caller rather than of the function. A test can be green and still be "
    "testing the wrong thing, and only running the mutation revealed it. The test now asserts the "
    "property on the static method directly and cross-checks it against create, and the mutation "
    "is caught. Second, three defects in the no-lookahead tests made them unable to fail on the "
    "bugs they named: the seed test compared an unhashable list and raised TypeError instead of "
    "asserting; the per-decision-stream test asserted that two runs matched, which a shared "
    "generator would also have satisfied; and the lookahead 'leaker' tried to have the harness "
    "catch a strategy that closed over the dataset itself, which is not detectable, because the "
    "harness only knows what it showed. The adversarial fixture was also wrong in a way that made "
    "every lookahead test vacuous: its late bar fell in a window the decision schedule skipped, so "
    "an event_time-slicing harness produced the same result as a correct one. The fixture now "
    "places a revised bar so the two rules disagree at a decision instant, and one test asserts "
    "they still disagree, so the file cannot go quiet again. Third, mypy strict was silently not "
    "checking the cross-worker import at all: it could not resolve webtrade-research from the "
    "backtest worker, so the Any it produced suppressed a real typing error in dataset.py where "
    "utcoffset() was called three times with a None guard that mypy could not narrow across, and "
    "downgraded canonical_digest's return type to Any in artifacts.py. Pointing mypy_path at the "
    "sibling package exposed both. A type checker that cannot see the code it is checking is "
    "worse than none, because its success is reported as coverage. Fourth, workers/research/"
    "README.md contradicted the code on the two most safety-critical properties in the module: it "
    "stated that numerics are IEEE-754 float64 when canonical_digest refuses a float outright and "
    "Money rejects one at construction, and that the engine takes an injected clock when it "
    "reads no clock at all. Both were corrected, and a float64 note was kept for numpy where it "
    "is accurate. Fifth, two packaging and gating gaps: workers/backtest/pyproject.toml declared "
    "readme = README.md, which did not exist, so the build would have failed; and scripts/"
    "run_gates.py had a pytest-research gate but no pytest-backtest gate, leaving all 39 backtest "
    "tests outside the release sweep. See CAVEATS for the scope decision on the second."
)

SIGNIFICANCE = (
    "The authority boundary is the point that generalises. Both worker READMEs asserted that "
    "neither package holds credentials, submits anything, or has a write path to an "
    "authoritative table, and the original design enforced that by convention: ruff's bandit "
    "rules would catch some of it at review. Prose is not a control. It is read once and never "
    "again, whereas a dependency added in a later commit is read by nobody. The new test parses "
    "both packages and both manifests, and checks the dependency set explicitly because that is "
    "how a capability actually arrives: adding httpx would give the worker a full network stack "
    "while every source file stayed clean, and a source-only scan would have passed. The test "
    "that asserts the scanner actually finds the source exists because a structural check that "
    "silently scans nothing is the failure mode this whole approach invites, and it is the one "
    "that would not announce itself. The companion property is that BacktestArtifact has no "
    "approved_by, reviewer, or deployment_scope field at all, asserted against the real field "
    "names so that adding one later fails the suite rather than passing review: an empty field "
    "invites a later stage to fill it in, a missing one cannot be filled in."
)

CAVEATS = (
    "The item is BLOCKED, not COMPLETED: the G4 reviewer and commit fields need human action, "
    "and the evidence status is PARTIALLY_VERIFIED, which is the accurate description of three "
    "verified criteria attached to a report that is not a pass. Four further limitations are "
    "worth stating plainly. (1) Scope: WI-140's declared write_scope is workers/research and "
    "workers/backtest, and adding the pytest-backtest gate required editing scripts/run_gates.py, "
    "which is outside it. The change was made anyway because an acceptance criterion the release "
    "gate never runs is not enforced, and the alternative was to leave the work ungated and "
    "report it as a finding; it is a one-line Gate entry mirroring pytest-research, both gates "
    "were executed and pass, and it is called out here so a reviewer can revert it if the scope "
    "was meant to be strict. No other out-of-scope file was touched. (2) The determinism evidence "
    "covers the Python workers only; no Go module was changed, so the 801 tests reported for G1 "
    "are unaffected and were not re-run. (3) The no-lookahead guarantee is structural, not "
    "absolute: the harness cannot police a strategy that closes over the dataset itself, since it "
    "only knows what it showed. The control is that the MarketView is a frozen, slotted object with "
    "no lookup path to the dataset, asserted against its real attribute surface, so the only way "
    "to see more is to be given more. A strategy that deliberately ignores the view and reads a "
    "dataset it captured at construction is outside what any harness can detect, and is not "
    "claimed here. (4) Mutation coverage is a sample of thirteen defects chosen to break the "
    "specific controls named in the acceptance criteria, not an exhaustive search for every way "
    "the harness could be wrong; a mutation that breaks no test is evidence about the tests, not "
    "a bound on what remains untested. Separately, the deliberate random.Random use in "
    "harness.py carries a suppressed S311 with a stated reason: the generator is not a secret and "
    "substituting secrets would satisfy the linter by destroying reproducibility, and this is the "
    "one place where the project's usual float prohibition does not apply. No specification file "
    "was modified, docs/ remains clean, and no commit has been made."
)

ARTIFACTS = [
    "workers/research/src/webtrade_research/dataset.py",
    "workers/research/src/webtrade_research/content_address.py",
    "workers/research/src/webtrade_research/canonical.py",
    "workers/research/tests/test_dataset.py",
    "workers/research/tests/test_authority_boundary.py",
    "workers/backtest/src/webtrade_backtest/harness.py",
    "workers/backtest/src/webtrade_backtest/artifacts.py",
    "workers/backtest/tests/test_harness.py",
    "workers/backtest/tests/test_artifacts.py",
    "workers/backtest/README.md",
    "workers/research/README.md",
    "scripts/run_gates.py",
]

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-140",
    "claim": CLAIM,
    "status": "PARTIALLY_VERIFIED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECTS,
    "significance": SIGNIFICANCE,
    "caveats": CAVEATS,
    "exception": BLOCKER,
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-140-BLOCKED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-140",
    "event": "work_item_blocked",
    "status": "BLOCKED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "WI-140 dataset registry and deterministic backtest engine implemented and verified. "
        "All 3 acceptance criteria hold mechanically: content-addressed dataset versioning that "
        "cannot claim a fingerprint it does not have, a deterministic backtest harness with no "
        "clock and seeded per-decision randomness, and reproducible artifacts with lineage inside "
        "the digest. The authority boundary is now verified structurally against both packages "
        "and both dependency sets rather than asserted in prose, and the artifact has no field it "
        "could be approved with. 13 of 13 injected defects detected, with every file restored and "
        "digest-checked; 64 research, 39 backtest, 113 CI tests PASS; ruff and mypy strict clean. "
        "One mutation initially survived, revealing that compute_fingerprint and create disagreed "
        "on ordering and that the covering test asserted the caller rather than the function. "
        "mypy strict had silently not been checking the cross-worker import at all, masking a "
        "real typing error. Status is BLOCKED, not COMPLETED: the G4 reviewer and commit fields "
        "require human action and docs/11 forbids recording partial completion as a pass. A "
        "pytest-backtest gate was added to scripts/run_gates.py, which is outside the declared "
        "write scope and is flagged for review."
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
        if item["id"] == "WI-140":
            desired = {
                "status": "BLOCKED",
                "evidence_ref": [EVIDENCE_ID],
                "blocker": BLOCKER,
                # The mechanical results live on the item too, so a resume that reads only
                # work-items.json still learns the three criteria hold and that only the two
                # human-dependent fields are outstanding.
                "partial_results": (
                    "3 of 3 acceptance criteria verified; 13 of 13 injected defects detected "
                    "and every file restored byte-for-byte; 64 research, 39 backtest and 113 CI "
                    "tests PASS; ruff and mypy strict clean on both workers. Gate verdict FAIL "
                    "pending the reviewer and commit fields."
                ),
            }
            for key, value in desired.items():
                if item.get(key) != value:
                    item[key] = value
                    changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print("WI-140 -> BLOCKED")
    else:
        print("WI-140 already BLOCKED")

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
