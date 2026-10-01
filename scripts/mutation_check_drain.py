"""Mutation gate: prove the drain tests can fail.

This exists because of a specific, twice-repeated failure mode in this repository: a check that
reports success without having exercised anything. EV-064 recorded an integration suite that
skipped seventeen tests and still printed "ok". EV-065 recorded a drain test whose URL helper
omitted the scheme, so it would have passed on a request that was never sent. In both cases the
test was green and meaningless, and in both cases the fix was to run one more check rather than
to read harder.

The three tests in cmd/control-plane/main_test.go are load-bearing for G5.7's shutdown claim, and
nothing in the pipeline currently establishes that they can fail. A future refactor that changes
serve() could make all three vacuous - assert against a local variable, or wait on a channel
nobody closes - and the suite would stay green. This gate closes that by deliberately breaking
serve() and requiring the tests to notice.

The mutation replaces the graceful server.Shutdown with a hard server.Close, which is the exact
defect the drain exists to prevent: connections dropped rather than drained. The replacement also
consumes shutdownCtx with `_ =`, because leaving it unused would fail the build rather than the
assertion, and a gate that passes for the wrong reason teaches nothing.

Three properties matter for this gate to mean anything, and all three are enforced below rather
than assumed:

  1. The mutation must actually apply. If the target text is absent or appears more than once,
     the file is unchanged, the tests pass, and the gate would "succeed" while proving nothing -
     the same trap as the tests it protects. The mutation is therefore verified to have landed
     before the tests are run, and the gate fails loudly if it did not.

  2. The unmutated tree must be green first. The first version of this gate never ran a
     baseline, so a drain test that was already failing at HEAD - or that failed to compile
     because someone was mid-refactor - was indistinguishable from a drain test that noticed
     the mutation. Both are just a non-zero exit. The drain tests are therefore run unmutated
     before anything is changed, and if that baseline is not clean the gate refuses to interpret
     the mutated result at all rather than reporting it as coverage. This is the defect the
     review recorded against this script, and the sibling harness scripts/mutation_check_model.py
     already refused to score a mutation without one.

  3. The original file must be restored, whatever happens. The mutation is applied to the working
     tree, so an interrupted run would leave a broken serve() behind. Restoration is in a
     finally block and the restored bytes are compared against the bytes read before the
     mutation, so a partial restore is itself an error.

On the mutated run, only a genuine test failure counts as a detection. `go test` exiting
non-zero is not by itself evidence: a package that does not compile also exits non-zero, with no
test having run at all. That is the second half of the same defect, and it is the one the
`_ =` in the mutation above exists to avoid - the mutation is written so that it compiles, and
this gate verifies that it actually did. A `--- FAIL` line for the target test is the evidence
credited; a build failure is reported as its own outcome and fails the gate, because counting it
as a detection is exactly the claim this gate exists to stop making.

Run directly, or as the `drain tests can fail` step in the go job.

Idempotent in the sense that matters: it restores the file, so repeated runs are identical.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "services" / "control-plane"
TARGET = MODULE / "cmd" / "control-plane" / "main.go"

GRACEFUL = "if err := server.Shutdown(shutdownCtx); err != nil {"

# `_ = shutdownCtx` keeps the variable used so the mutation compiles. A build failure would make
# `go test` exit non-zero for a reason that has nothing to do with the assertion under test, and
# this gate has to be able to tell "the test detected a broken drain" apart from "the package does
# not build".
MUTATED = "_ = shutdownCtx\n\tif err := server.Close(); err != nil {"

# The tests that must notice. Listed explicitly rather than matching the whole package, because
# the other tests in the package do not exercise the drain and would dilute the signal.
DRAIN_TESTS = (
    "TestTheDrainLetsAnInFlightRequestFinishBeforeItStopsAccepting",
    "TestTheDrainGivesUpOnARequestThatOutlivesTheShutdownDeadline",
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
# package that did not compile; the rest are the compile errors that precede it. A verdict that
# is neither a pass nor one of these is INDETERMINATE rather than assumed benign: the gate does
# not get to guess which kind of not-passing it just watched.
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


def go(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", *args],
        cwd=MODULE,
        capture_output=True,
        text=True,
        env={**os.environ, "CGO_ENABLED": os.environ.get("CGO_ENABLED", "0")},
    )


def run_drain_test(name: str) -> subprocess.CompletedProcess[str]:
    return go("test", "-count=1", "-run", f"^{name}$", "./cmd/control-plane/")


def first_fail_line(output: str) -> str:
    """The `--- FAIL` line for the test that failed, or "" when no test ran."""
    for line in output.splitlines():
        if "--- FAIL" in line:
            return line.strip()
    return ""


def classify(result: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    """Score one `go test` run as (verdict, evidence).

    The discrimination is copied from scripts/mutation_check_model.py rather than invented here,
    because that harness already had to answer the same question about a different package and
    reached the same conclusion: a broken build satisfies "the tests did not pass" while
    exercising none of them, so a gate that reports both as detections is claiming coverage it
    never had.

    Evidence is the `--- FAIL` line for a detection, the build marker that matched for a build
    failure, and "" when there is nothing to point at.
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
    return INDETERMINATE, ""


def baseline_failure() -> str | None:
    """Run the drain tests unmutated; return why they cannot be interpreted, or None if green.

    A green baseline is what gives the mutated run its meaning. Without it, "the test failed" has
    two possible causes that look identical from the exit code, and only one of them is the drain
    test doing its job. The drain tests are run one at a time rather than as a package because
    that is how they are run under mutation, and a baseline measured differently would not be a
    baseline.
    """
    for name in DRAIN_TESTS:
        try:
            result = run_drain_test(name)
        except OSError as exc:
            return (f"::error::could not run go for the baseline ({exc}); refusing to interpret "
                    "the test result")
        if result.returncode != 0:
            return (f"::error::baseline FAIL: {name} is not green on the unmutated tree, so a "
                    "failure under mutation would prove nothing about the drain; refusing to "
                    "interpret the test result")
    return None


def main() -> int:
    if not TARGET.exists():
        print(f"::error::{TARGET} not found; the mutation has no target and would prove nothing")
        return 1

    original = TARGET.read_bytes()
    text = original.decode("utf-8")

    occurrences = text.count(GRACEFUL)
    if occurrences != 1:
        # Refusing here is the whole point. Silently proceeding would run the unmutated tests,
        # see them pass, and report that they can detect a broken drain when nothing was broken.
        print(f"::error::expected exactly one {GRACEFUL.strip()!r} in {TARGET.name}, found "
              f"{occurrences}. The mutation cannot be applied, so this gate would prove nothing; "
              "it is failing rather than passing vacuously.")
        return 1

    # The baseline runs before the try block, and therefore before the file is touched. Nothing has
    # been mutated yet, so there is nothing to restore if this refuses.
    print("baseline: running the drain tests against the unmutated tree")
    baseline_problem = baseline_failure()
    if baseline_problem is not None:
        print(baseline_problem)
        return 1
    print(f"baseline: PASS (all {len(DRAIN_TESTS)} drain tests green on the unmutated tree)")
    print()

    outcome = 0
    detail = ""
    try:
        TARGET.write_text(text.replace(GRACEFUL, MUTATED), encoding="utf-8")

        mutated = TARGET.read_text(encoding="utf-8")
        if MUTATED not in mutated or GRACEFUL in mutated:
            detail = ("::error::the mutation did not land in the file; refusing to interpret "
                      "the test result")
            outcome = 1
        else:
            undetected: list[str] = []
            # Anything here failed the gate on its own, whether or not another test detected the
            # mutation. A run that proves nothing cannot be offset by a run that proves
            # something.
            uncertified: list[tuple[str, str]] = []

            for name in DRAIN_TESTS:
                verdict, evidence = classify(run_drain_test(name))
                if verdict == PASSED:
                    undetected.append(name)
                    print(f"  [NOT DETECTED] {name} passed against a hard close")
                elif verdict == DETECTED:
                    print(f"  [detected]     {name} failed against a hard close")
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
                detail = ("::error::these drain tests pass against a hard server.Close, so they "
                          "do not actually test the drain: " + ", ".join(undetected))
                outcome = 1
            if uncertified:
                detail = ("::error::these drain test runs proved nothing, so they cannot be "
                          "credited as detections: "
                          + "; ".join(f"{name}: {why}" for name, why in uncertified))
                outcome = 1
            if not outcome:
                print(f"drain mutation gate: PASS (both drain tests detect a hard close, each by "
                      f"a failing assertion rather than a broken build)")

    finally:
        # Restore unconditionally, then verify the restore by comparing bytes. A silent partial
        # restore would leave production code subtly different from what was reviewed.
        #
        # The restore result is recorded rather than returned from inside the finally block: a
        # return there would discard both the return value and any exception already in flight,
        # so a restore failure could mask, or be masked by, the mutation result. Deciding the
        # exit code after the try/finally completes keeps the two outcomes independent.
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
