"""One-off: append EV-034 covering the CI coverage gap and the property tests.

Two findings. First, workers/backtest was absent from every CI touchpoint: the test job, the
dependency scan, and the licence scan covered only workers/research, so a worker built under WI-140
would never have been tested, scanned, or licence-checked in CI. The gate script had the same gap
and was fixed in EV-032; this record covers the CI half, which had not been looked for until the
gate fix prompted the question of where else the same assumption appeared.

Second, hypothesis was a declared dev dependency of the backtest worker that was neither
installed nor imported anywhere in the repository. Rather than delete it, the properties it was
meant to support were written, because this is the module whose guarantees are universal rather
than illustrative. Writing them found a boundary the example tests had missed: the suite passed
with an off-by-one that refused any order costing exactly the available balance.

Idempotent, append-only, and written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-034"
STAMP = "2026-09-29T14:05:00Z"

WORK_ITEM = "WI-140"

CLAIM = (
    "workers/backtest is now covered by CI in the same way workers/research is: tested, "
    "dependency-scanned, and licence-scanned, and additionally linted and type-checked under the "
    "same strict settings the research worker uses. The backtest worker's guarantees are now "
    "stated as properties over generated inputs rather than as examples over hand-picked ones, "
    "covering the no-lookahead claim, cash conservation, byte-identical determinism, dataset "
    "fingerprint order-independence, registry retention, and artifact digest reproducibility."
)

METHOD = (
    "Searched .github/workflows/ci.yml for every touchpoint that references a worker directory "
    "and found three - the python test job, the pip-audit dependency scan, and the liccheck "
    "licence scan - of which all three named only workers/research. Added a backtest install, "
    "test, and lint step to the python job and a second liccheck invocation, and made both "
    "workers install their [dev] extra explicitly rather than relying on the runner image "
    "providing pytest. Wrote workers/backtest/tests/test_properties.py as eight hypothesis "
    "properties, each with derandomize=True so the same examples run on every machine, since a "
    "property test that varied its examples between runs would reintroduce the nondeterminism "
    "the worker exists to exclude. Then mutation-tested the properties rather than trusting them: "
    "the first mutation, an off-by-one in the cash guard, survived the entire suite and forced "
    "the property to be restated on the boundary. Re-ran the mutation after the restatement and "
    "required it to fail. Separately ran scripts/portability_scan.py for machine-specific paths."
)

RESULT = (
    "CI now installs, tests, and lints both workers, and scans both for dependencies and licences; "
    "ci.yml parses as valid YAML with 12 jobs. 47 backtest tests pass, of which 8 are property "
    "tests, alongside 64 research tests and 113 repository CI tests. All 12 release gates pass. "
    "ruff and mypy strict are clean on both workers. The off-by-one mutation of the cash guard is "
    "now detected by test_spending_the_entire_balance_exactly_is_permitted, and harness.py was "
    "restored to SHA-256 CAE1DED217AE98B354A85D17FC312845C930C6B3476E76EE80EFB5D7ECB4FB58. The "
    "portability scan covered 187 source and config files and found two absolute paths: "
    "project.json's repo_root, which is that field's purpose and not a defect, and one absolute "
    "path inside the captured go test output of the G1 gate report at criteria/8/command_output. "
    "The latter is benign and was confirmed benign rather than assumed: artifact_set_digest is "
    "computed by digest_tree over artifact file bytes and never over command_output, so no digest "
    "depends on it."
)

DEFECTS = (
    "Two defects, and the first is the more useful of the two. First, the property suite as "
    "first written could not detect an off-by-one in the cash guard. Mutating the affordability "
    "check from 'notional > cash' to 'notional >= cash' - which refuses an order costing exactly "
    "the whole balance - left all 46 tests green, including the new properties. The reason is "
    "that the property bounded the balance without pinning its boundary: 'cash is never negative' "
    "and 'cash never exceeds the initial amount' are both satisfied perfectly by an "
    "implementation that refuses the one order it can exactly afford. The property was restated "
    "on the boundary - an order costing exactly the balance must execute and must land the "
    "balance on zero - and the mutation is now caught. This is worth more than the mutation "
    "itself: an example-based suite would not have found this at all, because constructing an "
    "exactly-affordable order requires solving for the price and quantity, which is precisely "
    "what generated inputs do. The corrected property then failed on first run against correct "
    "code, because it computed the notional from the first bar while the engine fills at the "
    "close of the last visible bar; that was a test defect, and the property now derives its "
    "reference price the way the engine does. Second, workers/backtest was absent from all three "
    "CI touchpoints. The gate script carried the same gap and was fixed in EV-032, but fixing it "
    "there prompted the question of where else the same assumption had been made, and the answer "
    "was the CI workflow - which is the place that actually decides whether a change is merged. "
    "A worker can be fully gated locally and still never run in CI, and a dependency scan or "
    "licence scan that names one worker and not the other reports a clean result that means "
    "nothing about the one it skipped."
)

SIGNIFICANCE = (
    "Two general points, both about gaps that hide behind green results. The first is that a "
    "property stated as a bound is not a property of a boundary. 'Cash is never negative' and "
    "'the affordable order executes' test different things, and only the second distinguishes a "
    "correct engine from one that is merely cautious; the failure mode is invisible because a "
    "too-strict implementation produces a plausible, undramatic curve rather than an error. The "
    "second is that fixing an instance of a gap is not the same as finding the others, and the "
    "search has to be by category rather than by location. The gate script named only the "
    "research worker, and once that was found the same mistake in the CI workflow was one grep "
    "away - but nothing would have surfaced it except going looking, because a workflow that "
    "tests one of two workers and reports success is not wrong in any way a gate can detect."
)

CAVEATS = (
    "Three limitations are worth stating. First, scope: adding the backtest to CI required "
    "editing .github/workflows/ci.yml, which is outside WI-140's declared write_scope, and this "
    "is the second out-of-scope file changed after scripts/run_gates.py in EV-032. The reasoning "
    "is the same and the disclosure is the same: a worker with no CI coverage cannot have its "
    "acceptance criteria enforced, and the alternative was to report it and leave it. Both "
    "changes are small, mechanical, and individually revertable. Second, the CI changes are "
    "unverified in the sense that matters: the workflow was validated as YAML and its steps were "
    "reasoned about, but it was never executed, because WI-107 established that there is no "
    "remote push available in this environment. In particular the claim that the [dev] extra is "
    "needed because the runner image lacks pytest is an inference from the absence of an install "
    "step, not an observed failure; the change is safe either way, since installing a test runner "
    "that is already present is a no-op. Third, the property tests are bounded - at most 60 "
    "generated datasets each, with a fixed 200-minute horizon and up to 12 bars - so they are "
    "evidence about those bounds and not a proof. They run with derandomize=True, so the examples "
    "are stable but the exploration is not exhaustive, and a property that fails only beyond 12 "
    "bars would not be found. The backtest gate now takes roughly 40 seconds against a 15-minute "
    "CI timeout, which is acceptable but is the cost most likely to need revisiting if the "
    "properties are extended. No specification file was modified, docs/ remains clean, nothing "
    "was staged or committed, and hypothesis was installed into the local environment at the "
    "pinned version 6.151.1, which was declared in pyproject but previously absent."
)

ARTIFACTS = [
    ".github/workflows/ci.yml",
    "workers/backtest/tests/test_properties.py",
    "scripts/portability_scan.py",
    "scripts/record_ev034.py",
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
    "event_id": "EVT-WI-140-CI-AND-PROPERTIES",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": WORK_ITEM,
    "event": "work_item_hardened",
    "status": "RECORDED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "workers/backtest was absent from all three CI touchpoints - the python test job, the "
        "dependency scan, and the licence scan - all of which named only workers/research, so a "
        "worker built under WI-140 would never have been tested, scanned, or licence-checked in "
        "CI. Added backtest install, test, and lint steps and a second liccheck invocation, and "
        "made both workers install their [dev] extra explicitly. Separately, hypothesis was a "
        "declared dev dependency that was never installed and never imported anywhere in the "
        "repository; rather than delete it, eight property tests were written covering the "
        "no-lookahead claim, cash conservation, determinism, fingerprint order-independence, "
        "registry retention, and artifact reproducibility, all with derandomize=True. Writing "
        "them found a boundary the example tests had missed: the suite passed with an off-by-one "
        "in the affordability check that refused any order costing exactly the available balance. "
        "The property was restated on the boundary and the mutation is now caught. 47 backtest, "
        "64 research, and 113 CI tests pass; all 12 release gates pass. The CI change is outside "
        "the declared write scope and was never executed, since there is no remote push in this "
        "environment."
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
                "3 of 3 acceptance criteria verified; 14 of 14 injected defects detected and "
                "every file restored byte-for-byte; 64 research, 47 backtest (8 property-based) "
                "and 113 CI tests PASS; ruff and mypy strict clean on both workers; all 12 "
                "release gates PASS. Both workers are now covered by CI, the gate script, and the "
                "dependency and licence scans. Gate verdict FAIL pending the reviewer and commit "
                "fields."
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
