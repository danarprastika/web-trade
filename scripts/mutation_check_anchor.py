"""Mutation gate: prove the audit anchor tests can fail.

The drain gate (scripts/mutation_check_drain.py) exists because of a failure mode this repository
has now hit three times: a check that reports success without having exercised anything. EV-064 was
a suite that skipped seventeen tests and still printed "ok". EV-065 was a drain test whose URL
helper omitted the scheme. This gate is the same instrument pointed at the newest load-bearing
tests in the tree.

The tests in audit/sink_checkpoint_test.go are what prove that the audit sink has an anchor
producer. That producer is recent, and it exists because the first version of the truncation fix
was a check nothing could fire: Rehydrate read a partition's latest checkpoint and refused an
archive whose head fell behind it, but no code path wrote that table. Every test of the fix
inserted its own checkpoint by hand, so the whole suite was green while a real database would
have restored a truncated archive as VERIFIED. The sink tests were written specifically to close
that hole - they drive Export and then read back what it actually wrote - so they are the only
tests in the repository that can distinguish "the anchor is produced" from "the anchor is
assumed".

Nothing in the pipeline establishes that they can fail. A refactor that dropped the
AppendAuditCheckpoint call from Export's transaction, or moved it outside the transaction, would
leave the tests either passing vacuously or failing for the wrong reason, and in both cases the
G5 audit-anchoring claim would keep reading as verified.

The mutation makes the sink store its records unanchored: the checkpoint loop still iterates, so
the code compiles and every variable stays used, but each anchor is discarded instead of being
appended. That is the exact defect the checkpoint exists to prevent - records committed that
nothing says how far they reach - and a discarded tail would restore as verified.

Three properties make this gate mean something, all enforced rather than assumed:

  1. The mutation must actually apply. If the target text is absent or appears more than once the
     file is unchanged, the tests pass, and the gate would "succeed" while proving nothing. The
     mutation is verified to have landed before any test runs, and the gate fails loudly if it did
     not.

  2. The unmutated tree must be green first. Without a baseline, "the test failed" has two causes
     that look identical from the exit code: a test that noticed the mutation, and a test that was
     already broken at HEAD or mid-refactor. The baseline runs before anything is written, and a
     dirty baseline makes the gate refuse to interpret the mutated result rather than reporting it
     as coverage. This is the defect review recorded against the drain gate, and
     scripts/mutation_check_model.py already refused to score a mutation without one.

  3. The original file must be restored, whatever happens. The mutation is applied to the working
     tree, so an interrupted run would leave an unanchored sink behind. Restoration is in a
     finally block and the restored bytes are compared against the bytes read before the
     mutation, so a partial restore is itself an error.

On the mutated run, only a genuine test failure counts as a detection. `go test` exiting non-zero
is not by itself evidence: a package that does not compile also exits non-zero with no test having
run. The mutation is written to compile - `_ = anchor` keeps the variable used - precisely so that
a compile failure cannot be mistaken for a detection, and the classification still verifies rather
than assumes it.

Note which tests are deliberately absent from the list. TestABatchThatCannotBeAnchoredIsRefused-
BeforeAnyRecordIsStored exercises the pre-transaction refusal in checkpoints(), which this
mutation does not touch, so it correctly keeps passing under mutation. Listing it would fail the
gate for a test that was never going to notice. The five listed tests are the ones that assert on
what the sink actually stored.

Run directly, or as the `audit anchor tests can fail` step in the go job.

Idempotent in the sense that matters: it restores the file, so repeated runs are identical.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "services" / "control-plane"
TARGET = MODULE / "audit" / "sink.go"

ANCHOR_LOOP = (
    "\t\tfor _, anchor := range anchors {\n"
    "\t\t\tif _, err := q.AppendAuditCheckpoint(ctx, anchor); err != nil {\n"
    "\t\t\t\treturn fmt.Errorf(\"recording the audit checkpoint for partition %s \"+\n"
    "\t\t\t\t\t\"(sequences %d..%d): %w\",\n"
    "\t\t\t\t\tanchor.Partition, anchor.FirstSequence, anchor.LastSequence, err)\n"
    "\t\t\t}\n"
    "\t\t}\n"
)

# The whole loop is replaced rather than a line inside it, because replacing the `if` alone would
# orphan the closing braces and the package would not compile - which is precisely the mistake this
# gate has to avoid crediting. `_ = anchors` keeps the local used so the mutation compiles, and it
# leaves the checkpoints computed and signed but never stored: the sink commits records and nothing
# says how far they reach, which is the exact defect the anchor exists to prevent.
MUTATED = "\t\t_ = anchors // MUTATED: signed checkpoints computed but never stored\n"

# The tests that must notice. Listed explicitly rather than matching the package, because the
# other tests in it do not assert that the sink anchored its batch and would dilute the signal.
ANCHOR_TESTS = (
    "TestTheSinkWritesACheckpointCoveringTheRecordsItJustStored",
    "TestTheSinkCheckpointsEveryPartitionOfAMultiPartitionExport",
    "TestASecondExportAdvancesThePartitionAnchor",
    "TestACheckpointThatCannotBeWrittenFailsTheWholeExport",
    "TestAFailedAnchorStopsTheRestOfTheBatch",
)

# The verdicts a single `go test` run can produce. They are named rather than folded into a
# boolean because the middle one and the last two have to stay distinguishable: "the test failed"
# is coverage, and the other two are silence.
PASSED = "passed"
DETECTED = "detected"
BUILD_FAILURE = "build failure"
INDETERMINATE = "indeterminate"

# Substrings that mark the go toolchain's own compile diagnostics rather than a test assertion.
# Matched only when no `--- FAIL` line was found, so a test that genuinely failed is never
# reclassified as a build problem. "[build failed]" is the summary line `go test` prints for a
# package that did not compile; the rest are the compile errors that precede it. A verdict that is
# neither a pass nor one of these is INDETERMINATE rather than assumed benign: the gate does not
# get to guess which kind of not-passing it just watched.
BUILD_MARKERS = (
    "[build failed]",
    "build failed",
    "syntax error",
    "undefined:",
    "declared and not used",
    "declared but not used",
    "imported and not used",
    "build constraints exclude",
    "no Go files in",
    "is not a type",
)

# The go toolchain's compile diagnostics carry a source position - `sink.go:228:12: syntax error` -
# and they appear whether or not any of the markers above are present in the message text. Matching
# the position directly is what keeps this gate correct as the toolchain's wording changes: an
# enumerated list of English error strings is a claim about today's compiler output, and a gate that
# quietly falls through to INDETERMINATE when a new diagnostic is phrased differently would report
# silence where there was a build failure. The shape of the diagnostic - a .go file, a line and a
# column - is far more stable than its wording, so it is the last resort before giving up.
#
# This can only ever be reached when no `--- FAIL` line was found, so a test that genuinely failed
# is never reclassified as a build problem.
COMPILE_DIAGNOSTIC = re.compile(r"^\s*[\w./\\-]+\.go:\d+:\d+:", re.MULTILINE)


def go(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", *args],
        cwd=MODULE,
        capture_output=True,
        text=True,
        env={**os.environ, "CGO_ENABLED": os.environ.get("CGO_ENABLED", "0")},
    )


def run_anchor_test(name: str) -> subprocess.CompletedProcess[str]:
    return go("test", "-count=1", "-run", f"^{name}$", "./audit/")


def first_fail_line(output: str) -> str:
    """The `--- FAIL` line for the test that failed, or "" when no test ran."""
    for line in output.splitlines():
        if "--- FAIL" in line:
            return line.strip()
    return ""


def classify(result: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    """Score one `go test` run as (verdict, evidence).

    The discrimination is copied from scripts/mutation_check_drain.py rather than invented here,
    because that gate already had to answer the same question about a different package and
    reached the same conclusion: a broken build satisfies "the tests did not pass" while
    exercising none of them, so a gate that reports both as detections is claiming coverage it
    never had.

    Evidence is the `--- FAIL` line for a detection, the build marker or source position that
    matched for a build failure, and "" when there is nothing to point at.
    """
    if result.returncode == 0:
        return PASSED, ""

    output = result.stdout + result.stderr
    failed = first_fail_line(output)
    if failed:
        return DETECTED, failed

    for marker in BUILD_MARKERS:
        if marker in output:
            return BUILD_FAILURE, marker

    diagnostic = COMPILE_DIAGNOSTIC.search(output)
    if diagnostic:
        return BUILD_FAILURE, diagnostic.group(0).strip()

    return INDETERMINATE, ""


def baseline_failure() -> str | None:
    """Run the anchor tests unmutated; return why they cannot be interpreted, or None if green.

    A green baseline is what gives the mutated run its meaning. Without it, "the test failed" has
    two possible causes that look identical from the exit code, and only one of them is an anchor
    test doing its job. The tests are run one at a time rather than as a package because that is
    how they are run under mutation, and a baseline measured differently would not be a baseline.
    """
    for name in ANCHOR_TESTS:
        try:
            result = run_anchor_test(name)
        except OSError as exc:
            return (f"::error::could not run go for the baseline ({exc}); refusing to interpret "
                    "the test result")
        if result.returncode != 0:
            return (f"::error::baseline FAIL: {name} is not green on the unmutated tree, so a "
                    "failure under mutation would prove nothing about the anchor; refusing to "
                    "interpret the test result")
    return None


def main() -> int:
    if not TARGET.exists():
        print(f"::error::{TARGET} not found; the mutation has no target and would prove nothing")
        return 1

    original = TARGET.read_bytes()
    text = original.decode("utf-8")

    occurrences = text.count(ANCHOR_LOOP)
    if occurrences != 1:
        # Refusing here is the whole point. Silently proceeding would run the unmutated tests,
        # see them pass, and report that they can detect an unanchored sink when nothing was
        # broken.
        print(f"::error::expected exactly one AppendAuditCheckpoint loop in {TARGET.name}, found "
              f"{occurrences}. The mutation cannot be applied, so this gate would prove nothing; "
              "it is failing rather than passing vacuously.")
        return 1

    # The baseline runs before the try block, and therefore before the file is touched. Nothing has
    # been mutated yet, so there is nothing to restore if this refuses.
    print("baseline: running the anchor tests against the unmutated tree")
    baseline_problem = baseline_failure()
    if baseline_problem is not None:
        print(baseline_problem)
        return 1
    print(f"baseline: PASS (all {len(ANCHOR_TESTS)} anchor tests green on the unmutated tree)")
    print()

    outcome = 0
    detail = ""
    try:
        TARGET.write_text(text.replace(ANCHOR_LOOP, MUTATED), encoding="utf-8")

        mutated = TARGET.read_text(encoding="utf-8")
        if MUTATED not in mutated or ANCHOR_LOOP in mutated:
            detail = ("::error::the mutation did not land in the file; refusing to interpret "
                      "the test result")
            outcome = 1
        else:
            undetected: list[str] = []
            # Anything here failed the gate on its own, whether or not another test detected the
            # mutation. A run that proves nothing cannot be offset by a run that proves something.
            uncertified: list[tuple[str, str]] = []

            for name in ANCHOR_TESTS:
                verdict, evidence = classify(run_anchor_test(name))
                if verdict == PASSED:
                    undetected.append(name)
                    print(f"  [NOT DETECTED] {name} passed against an unanchored sink")
                elif verdict == DETECTED:
                    print(f"  [detected]     {name} failed against an unanchored sink")
                    print(f"                {evidence}")
                elif verdict == BUILD_FAILURE:
                    reason = f"the package did not build ({evidence}), so no test ran"
                    uncertified.append((name, reason))
                    print(f"  [BUILD FAILURE] {name}: {reason}; this is not a detection")
                else:
                    reason = ("go test exited non-zero without a --- FAIL line, so it is not "
                              "established that any test ran")
                    uncertified.append((name, reason))
                    print(f"  [INDETERMINATE] {name}: {reason}")

            if undetected:
                detail = ("::error::these anchor tests pass against a sink that stores records "
                          "without checkpointing them, so they do not actually test the anchor: "
                          + ", ".join(undetected))
                outcome = 1
            if uncertified:
                detail = ("::error::these anchor test runs proved nothing, so they cannot be "
                          "credited as detections: "
                          + "; ".join(f"{name}: {why}" for name, why in uncertified))
                outcome = 1
            if not outcome:
                print(f"audit anchor mutation gate: PASS (all {len(ANCHOR_TESTS)} anchor tests "
                      f"detect an unanchored sink, each by a failing assertion rather than a "
                      f"broken build)")

    finally:
        # Restore unconditionally, then verify the restore by comparing bytes. A silent partial
        # restore would leave production code subtly different from what was reviewed.
        #
        # The restore result is recorded rather than returned from inside the finally block: a
        # return there would discard both the return value and any exception already in flight, so
        # a restore failure could mask, or be masked by, the mutation result. Deciding the exit
        # code after the try/finally completes keeps the two outcomes independent.
        TARGET.write_bytes(original)
        if TARGET.read_bytes() != original:
            restore_failure = ("::error::failed to restore " + str(TARGET) + " byte-for-byte; the "
                               "working tree is unsafe and must be restored by hand")
            print(restore_failure)
            detail = restore_failure
            outcome = 1
        else:
            print(f"  restored {TARGET.name} ({len(original)} bytes)")

    if detail:
        print(detail)
    return outcome


if __name__ == "__main__":
    sys.exit(main())