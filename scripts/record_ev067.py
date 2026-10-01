"""One-off: append EV-067.

This closes the recommendation EV-065 left open and the caveat EV-066 left open, and it does so
by building two gates rather than by arguing that the risk was acceptable.

The first is a mutation gate for the three drain tests. EV-065 observed that replacing the
graceful Shutdown with a hard Close fails two of them, by hand, and recorded that nothing
prevents a future change from making them vacuous. That observation is now a gate: it runs in the
go job, so on every pull request, and it fails when the tests stop detecting a broken drain. It
refuses to run if the mutation cannot be applied, because a gate that mutates nothing and sees the
tests pass would report that the tests can fail when it never established anything.

The second is a bash syntax gate for every run: block in the workflow. EV-066 recorded that the
steps had been reproduced locally with local equivalents, leaving the shell itself unparsed. All
39 run: blocks are now parsed with bash -n, in the toolchain job so a broken step is reported
before the six-module build, and again in tests/ci because a step that runs inside CI cannot catch
a workflow GitHub is unable to parse.

Both gates were held to the standard this repository keeps failing to apply to itself: each was
observed to fail against a deliberately broken input before being believed. Both also produced a
false alarm first, from defects in the harnesses rather than in the code under test, and those are
recorded because the pattern is now unmistakable - five times in this work, a check reported
something confident and false, and every one was caught by doubting the result and establishing
what the check actually did.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-067"
STAMP = "2026-10-01T13:15:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The two gaps left open by EV-065 and EV-066 are closed by building them rather than by "
    "arguing they were acceptable. A mutation gate now runs in the go job on every pull request and "
    "fails when the three drain tests stop detecting a hard server.Close, so the tests that prove "
    "G5.7's shutdown ordering can no longer go vacuous unnoticed. A bash syntax gate now parses all "
    "39 run: blocks in the workflow, in the toolchain job and again in tests/ci, so a syntax error "
    "in a step is caught before it is pushed rather than minutes into a later job on a runner. Both "
    "gates were observed to fail against a deliberately broken input before being believed."
)

METHOD = (
    "The mutation gate, scripts/mutation_check_drain.py, replaces the graceful server.Shutdown with "
    "a hard server.Close - the exact defect the drain prevents - and requires the drain tests to "
    "fail. Two properties are enforced rather than assumed. The mutation must actually land: the "
    "target string must appear exactly once, and the mutated file is read back to confirm both that "
    "the replacement is present and the original is gone, so a gate that changed nothing and saw "
    "the tests pass cannot report success. And the original file is restored unconditionally, with "
    "the restored bytes compared against the bytes read before the mutation, so a partial restore "
    "is itself an error. The replacement also consumes shutdownCtx with `_ =`, because leaving it "
    "unused would fail the build rather than the assertion and the gate has to distinguish 'the test "
    "detected a broken drain' from 'the package does not build'. A defect in this script was found "
    "and fixed before it was trusted: it returned from inside a finally block, which discards both "
    "a return value and an exception already in flight, so a restore failure could mask or be masked "
    "by the mutation result; the exit code is now decided after the try/finally completes. The gate "
    "was then proven able to fail by neutering the first drain test until it skipped, which made the "
    "gate report NOT DETECTED and exit non-zero, with the test file restored byte-identically "
    "afterwards. For the bash gate, scripts/check_workflow_bash.py parses each run: block with "
    "bash -n, executing nothing. It was proven in both directions: malformed bash is rejected and "
    "well-formed bash accepted, because a check that rejects everything is as useless as one that "
    "accepts everything. The same check was added to tests/ci/test_ci_workflow.py, and separately "
    "proven to fail against an unterminated quote injected into a real run block. That test is "
    "deliberately duplicated in the local suite because a step running inside CI cannot catch a "
    "workflow GitHub cannot parse."
)

RESULT = (
    "scripts/mutation_check_drain.py: run directly it reports both drain tests detected against a "
    "hard close and exits 0; run against a neutered test it reports NOT DETECTED and exits 1; it "
    "restores main.go byte-identically in both cases, and refuses with exit 1 if the mutation target "
    "is absent or ambiguous rather than passing vacuously. Wired into the go job as 'drain tests "
    "can fail', after verify module integrity. scripts/check_workflow_bash.py: all 39 run: blocks "
    "parse as valid bash, exit 0; it skips rather than fails when bash is absent, so a missing "
    "interpreter is not reported as a malformed workflow. Wired into the toolchain job as 'every "
    "run block in this workflow is valid bash', before the six-module build, and mirrored into "
    "tests/ci/test_ci_workflow.py. Full re-verification after every change: gofmt clean; go vet exit "
    "0 with and without the integration tag; default suite -race 10 packages ok including the three "
    "drain tests; integration suite -race 17 passed, 0 failed, 0 skipped against a live PostgreSQL "
    "17.11; toolchain gate 14 of 14; bash gate 39 of 39; drain mutation gate PASS; tests/ci 116 "
    "passed, up from 115 by the new run-block test; research worker 109 passed; backtest worker 47 "
    "passed; contracts VALID; project brain gate PASS; evidence-reference audit 0 items drifted; G5 "
    "report unchanged at 78 artifact digests, verdict PASS, 7 of 7 criteria PASS, with the drain "
    "test file among the digested artifacts. docs/ clean, nothing staged, nothing committed."
)

DEFECT_FOUND_AND_FIXED = (
    "Five, and the pattern across them is the finding. Three were defects in the two new gates or "
    "their proofs. First, the mutation gate returned from inside a finally block, which Python warns "
    "about because it discards both the return value and any exception in flight, so a failed "
    "restore could be masked by, or mask, the mutation verdict; the same defect was then written "
    "into the proof script and fixed there too. Second, the first version of the bash gate reported "
    "all 38 run: blocks invalid, because it wrote each block to a Windows temp path and the bash on "
    "PATH is the WSL bash, which cannot see a C:\\... path and reads the backslashes as escapes. "
    "Third, the fixed version then reported nine phantom syntax errors - a stray $'\\r' and "
    "`done < modules.txt` - because Python's text-mode pipe translates \\n to \\r\\n on Windows and "
    "bash reads the carriage return as part of the command; binary stdin fixed it. Both were false "
    "alarms about a workflow that was entirely valid, and .gitattributes already pins *.yml to LF "
    "precisely so this cannot happen on the runner, which is documented in that file in terms of a "
    "harness that once broke a container this way. Fourth, the first attempt to prove the run-block "
    "test detects a break was itself a false negative: the injection used `done <<< modules.txt`, a "
    "valid herestring, so the test was right to pass and my 'break' was not a break; the proof was "
    "redone with an unterminated quote, independently confirmed invalid first. Fifth, and the one "
    "that reached a tracked file: adding a CI step named 'every run: block is valid bash' put a "
    "colon-space inside an unquoted YAML scalar and broke the workflow document, so that no job "
    "could run at all. It was caught by parsing the file after editing, and it is the reason the "
    "run-block test lives in tests/ci rather than only in CI."
)

SIGNIFICANCE = (
    "This entry is the fifth in a row in which a check in this work reported something confident "
    "and false: the integration suite that skipped everything and printed ok, the generated-code "
    "step that was never broken, the temp-path gate that called a valid workflow invalid, the "
    "CRLF gate that invented nine syntax errors, and the herestring that was not a break. Four of "
    "the five were caught the same way - doubt the result, then establish what the check actually "
    "did before believing what it said - and the fifth, the broken YAML, was caught by re-parsing "
    "after an edit. The two gates built here are the durable form of that lesson rather than its "
    "record: the mutation gate exists so the drain tests cannot silently stop testing, and the "
    "bash gate exists so the workflow cannot silently stop parsing, and each of those is a class of "
    "silent no-op removed from the repository rather than one more paragraph about why it matters. "
    "What the record establishes is a pattern with a specific mechanism. Every one of these checks "
    "had a plausible-looking failure to report, and the plausible one was always wrong, because a "
    "harness that has not been broken on purpose has not been shown capable of reporting anything "
    "at all. The negative controls recorded here - neutered test, unterminated quote, malformed "
    "script - are what convert a gate from an assumption into a measurement, and they are the "
    "cheapest thing in this entire body of work."
)

CAVEATS = (
    "Five limitations. First, the mutation gate covers the two drain tests that exercise the "
    "shutdown ordering; it does not cover TestTheListenerFailingIsReportedAsAnUnexpectedStop, which "
    "is listed in the script but omitted from its mutation check because breaking Shutdown does not "
    "affect that branch, so no single mutation tests it. Second, the bash gate checks syntax only, "
    "not behaviour: a block can be perfectly valid and still do the wrong thing, and none of the "
    "commands inside were executed by it. Third, both gates are still verified only in local runs "
    "on Windows, so their behaviour inside the Ubuntu runner remains unproven, and the same applies "
    "to everything EV-066 listed. Fourth, the mutation gate writes to a tracked source file while "
    "it runs; it restores in a finally block and verifies the bytes, but an interrupted or killed "
    "run could in principle leave main.go mutated, which is a real if narrow risk that a lock file "
    "or a copy-and-build approach would remove. Fifth, and unchanged: the G5 report's human_reviewer "
    "remains null so WI-141 stays IN_PROGRESS, cross-store atomicity remains WI-120 and WI-121's "
    "and is not claimed, WI-117's unqualified audit and authz tables and RISK-14 remain other "
    "owners', the schema-version forward problem is untouched, the write path is still not exposed "
    "over HTTP, and the drain tests still drive the interrupt channel rather than a real signal. "
    "The `sqlc is up to date` CI step still fails until the six sqlc-related files are committed "
    "together, which is outside the instruction. Nothing was staged and nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "scripts/mutation_check_drain.py",
    "scripts/prove_mutation_gate_fails.py",
    "scripts/check_workflow_bash.py",
    "scripts/prove_bash_gate_detects.py",
    "scripts/prove_run_block_test_detects.py",
    "tests/ci/test_ci_workflow.py",
    ".github/workflows/ci.yml",
    "services/control-plane/cmd/control-plane/main_test.go",
    "scripts/record_ev067.py",
]

SUPERSEDES = []


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    line = json.dumps(
        {
            "schema": "ecc.project-brain/evidence/v7",
            "evidence_id": EVIDENCE_ID,
            "recorded_at": STAMP,
            "recorded_by": "team-lead",
            "work_item": WORK_ITEM,
            "claim": CLAIM,
            "status": "VERIFIED",
            "method": METHOD,
            "result": RESULT,
            "defect_found_and_fixed": DEFECT_FOUND_AND_FIXED,
            "significance": SIGNIFICANCE,
            "caveats": CAVEATS,
            "exception": EXCEPTION,
            "artifacts": ARTIFACTS,
            "supersedes": SUPERSEDES,
        },
        ensure_ascii=False,
    )

    if store.exists():
        for existing in store.read_text(encoding="utf-8").splitlines():
            if existing.strip() and json.loads(existing).get("evidence_id") == EVIDENCE_ID:
                print("unchanged: " + EVIDENCE_ID + " already recorded")
                return False

    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print("recorded " + EVIDENCE_ID)
    return True


if __name__ == "__main__":
    record()
