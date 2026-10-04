"""Record WI-198 and EV-100: the bash syntax gate reported its own host failure as a broken workflow.

While running the battery for WI-197, pytest-ci failed naming `python: install backtest worker is not
valid bash:` with nothing after the colon. The same test passed alone, and 216 consecutive invocations
over the workflow's 54 run: blocks - four full trials - produced zero failures.

A `bash -n` that reports a syntax error always writes to stderr. Non-zero with an empty stderr is the
interpreter not answering, which on Windows means the WSL launcher at C:\\WINDOWS\\system32\\bash.EXE
failed to start under load. The check could not tell those apart, so it reported the launcher failing as
a claim about the workflow - asserting something about ci.yml that the run had not established.

That is the same error scripts/check_workflow_bash.py already documents twice in its own docstring, in
a new disguise: a check reporting failure that established nothing about the thing it claimed to check.
The first two versions were a temp-file path WSL could not read, and CRLF arriving through a text pipe.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-04T11:35:00Z"

ARTIFACTS = [
    "scripts/check_workflow_bash.py",
    "tests/ci/test_ci_workflow.py",
    "scripts/record_ev100.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_198 = {
    "id": "WI-198",
    "phase": 3,
    "title": (
        "The bash syntax gate reported its own host failure as a malformed workflow, so an "
        "intermittent WSL launcher looked like a defect in ci.yml"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "A non-zero bash exit that carries a diagnostic is reported as a syntax error, unchanged",
        "A non-zero bash exit with no diagnostic is retried once, and only believed after the retry",
        "A block that could not be checked is reported as unchecked and named a host failure, not as "
        "a malformed run: block - while the gate still fails, because an unchecked block is not a pass",
        "The gate is bounded, so a wedged launcher is reported as unchecked rather than hanging the "
        "run or raising a traceback out of the check",
        "A launcher blip that clears is reported as a pass, so the retry cannot have been satisfied "
        "by a gate that simply always failed",
        "Each of the four behaviours above has a control, and the controls fail against the "
        "pre-fix implementation",
    ],
    "source": (
        "Running the WI-197 battery, which is the first time this check has been exercised while the "
        "full tests/ci suite was in flight. The failure named a step that is a three-line pip install, "
        "with an empty diagnostic - which is the detail that mattered, and which the message format "
        "rendered as a sentence with nothing in it."
    ),
    "reproduction": (
        "Intermittent, and that is the finding. `python -m pytest tests/ci -q` fails "
        "test_every_run_block_is_valid_bash with `python: install backtest worker is not valid bash: ` "
        "and no diagnostic. The same test alone passes. Driving the gate's own function over all 54 "
        "run: blocks, four consecutive trials - 216 invocations - produced zero failures, so the "
        "workflow is not malformed and re-running proves nothing about which it was."
    ),
    "notes": (
        "The discriminator is stderr, and it is exact rather than heuristic: `bash -n` reports a parse "
        "error on stderr, so a non-zero exit carrying a diagnostic is a verdict about a real block and "
        "a non-zero exit without one never parsed anything. Keying the retry on the exit code alone "
        "would have been the obvious implementation and would have been a defect - a flaky launcher "
        "could then turn a genuine syntax error into a pass, discarding the one signal that matters in "
        "order to add resilience. The control for that is the reason the retry is trustworthy: it "
        "asserts a diagnosed failure is attempted exactly once.\n\n"
        "The gate still fails when bash cannot be run at all. It could not: the blocks were not "
        "checked, and a check that could not look has verified nothing. What changed is the message - "
        "it names the host failure instead of blaming ci.yml, and separates the count of malformed "
        "blocks from the count never examined, so the two cannot be read as one number.\n\n"
        "The controls drive the gate's subprocess seam rather than the real binary. The defect is an "
        "intermittent property of one launcher, so a control that shelled out would pass on a good day "
        "and prove nothing, and standing in a genuinely malformed block for a genuinely absent "
        "interpreter is precisely the conflation being removed. Non-vacuity was confirmed by running "
        "the pre-fix implementation against the same assertions: it attempts once where the control "
        "requires two."
    ),
    "dependencies": ["WI-197"],
    "evidence_ref": ["EV-100"],
}

EV_100 = {
    "evidence_id": "EV-100",
    "work_item": "WI-198",
    "claim": (
        "The bash syntax gate distinguishes a malformed run: block from a launcher that did not run, "
        "and never reports the second as the first"
    ),
    "status": "VERIFIED",
    "method": (
        "The failure was reproduced in the full suite and then characterised rather than re-run: the "
        "test passes alone, and 216 consecutive invocations over all 54 run: blocks across four trials "
        "produced no failure, which is what established that the workflow was not at fault and that "
        "the observation was about the host. `bash` was then resolved on PATH and identified as the "
        "WSL launcher. Four controls then drive the gate's subprocess seam to fix the behaviour "
        "deterministically: a diagnosed failure attempted exactly once and keeping bash's message; a "
        "silent non-zero attempted twice and reported as unchecked while still failing; a silent "
        "non-zero that clears on retry reported as a pass; and a launcher that never answers reported "
        "as unchecked from a single attempt, with no exception escaping the check. Non-vacuity was "
        "checked by running the pre-fix implementation against the same assertions."
    ),
    "result": (
        "Before: an intermittent `python: install backtest worker is not valid bash: ` with an empty "
        "diagnostic, in a suite that otherwise passed, naming a step that is not malformed. After: a "
        "diagnosed syntax error is still reported as a syntax error on the first attempt, a silent "
        "non-zero is retried once and then reported as `bash exited non-zero without a diagnostic, "
        "twice: bash could not be run, so this block was NOT checked. This is a host failure, not a "
        "workflow defect.`, and the gate still exits 1. The four controls pass; 18 bash-related tests "
        "pass; the battery is 15 of 15 with 244 tests in tests/ci. Against the pre-fix implementation "
        "the retry control requires two attempts and the old code makes one, so the controls "
        "discriminate."
    ),
    "defect_found_and_fixed": (
        "1. A non-zero `bash -n` was reported as 'not valid bash' whatever its stderr, so a launcher "
        "that failed to start became a claim about ci.yml. Now discriminated on stderr.\n"
        "2. The failure message rendered as `... is not valid bash: ` with nothing after it, because "
        "the empty-stderr case fell through to a bare string. The message now names the real cause and "
        "the gate reports malformed and unchecked counts separately.\n"
        "3. The call was unbounded, so a wedged launcher would hang the gate rather than fail it. "
        "Bounded at 60 seconds, and a timeout is reported through the same empty-stderr path as a "
        "launcher that failed to start - a bound that raised TimeoutExpired out of the check would have "
        "moved the failure rather than fixed it, since the caller would see a stack trace where the "
        "finding belongs. A timed-out first attempt is not retried: the timeout is already an answer."
    ),
    "significance": (
        "A gate that cries wolf is worse than no gate, because it spends the credibility that makes "
        "people read the real findings. This one failed on a step that was perfectly valid, named a "
        "file that was perfectly valid, and could not be distinguished from a true positive by "
        "re-running - which is exactly the state in which a team's rational response is to re-run until "
        "it goes green and stop reading the output. The workflow it guards is the one whose syntax "
        "errors surface minutes into a later CI job, after the cache is warm and the developer has "
        "moved on, so the signal being quietly untrustworthy removes most of the value of having it. "
        "The general shape is the repository's recurring one and this is its eighth instance: not a "
        "check that passes having checked nothing, but a check that fails having established nothing, "
        "which is harder to see because a red test looks like it is working."
    ),
    "caveats": (
        "The underlying intermittency is a property of the WSL launcher on this host and is mitigated, "
        "not fixed: the retry makes one silent failure recoverable, and a persistently broken launcher "
        "is still reported as unchecked rather than resolved. The distinction is that the report is now "
        "true about what was observed.\n\n"
        "The 216 clean invocations establish that this tree's 54 run: blocks are not malformed. They "
        "do not establish that the launcher never fails again; they are the evidence that the observed "
        "failure was not about the workflow.\n\n"
        "A genuine syntax error with empty stderr is treated as unchecked rather than as a defect. That "
        "is the conservative direction - it fails the gate and blames the host - and is why the retry is "
        "keyed on stderr rather than on the exit code.\n\n"
        "Not verified: GitHub Actions, unreadable with the unauthenticated gh that EV-091 records. All "
        "measurements were taken on this Windows host. The change is host-independent logic, but the "
        "launcher it defends against is not observed on the runner."
    ),
    "exception": (
        "No exception. Nothing is skipped or weakened: a checked block that is malformed still fails, "
        "and an unchecked block still fails too. The only relaxation is that a single silent launcher "
        "failure is retried once before it is believed, which cannot convert a diagnosed syntax error "
        "into a pass - asserted by a control."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EV_100_FIELDS = (
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
    doc = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = doc["items"]
    by_id = {i["id"]: i for i in items}

    changed = False
    existing = by_id.get(WI_198["id"])
    if existing is None:
        items.append(WI_198)
        changed = True
        print(f"recorded {WI_198['id']}")
    elif existing != WI_198:
        items[items.index(existing)] = WI_198
        changed = True
        print(f"updated {WI_198['id']}")
    else:
        print(f"unchanged: {WI_198['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    records = _read_records()
    appended: list[str] = []
    recorded = {record.get("evidence_id") for record in records}
    if EV_100["evidence_id"] not in recorded:
        records.append(
            {
                "schema": "ecc.project-brain/evidence/v7",
                "evidence_id": EV_100["evidence_id"],
                "recorded_at": STAMP,
                "recorded_by": "team-lead",
                **EV_100,
            }
        )
        appended.append(EV_100["evidence_id"])
    else:
        index = next(
            i for i, record in enumerate(records) if record.get("evidence_id") == EV_100["evidence_id"]
        )
        current = {key: records[index].get(key) for key in EV_100_FIELDS}
        wanted = {key: EV_100[key] for key in EV_100_FIELDS}
        if current != wanted:
            records[index].update(EV_100)
            appended.append(f"{EV_100['evidence_id']} (updated)")
            print(f"updated {EV_100['evidence_id']}")
        else:
            print(f"unchanged: {EV_100['evidence_id']}")
    _write_records(records)

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()
