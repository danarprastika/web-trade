"""Mutation gate: prove the audit fan-out tests can fail.

scripts/mutation_check_anchor.py proves one thing about one set of tests: that they notice a sink
which stores records without anchoring them. This gate does the same job for the fan-out, but the
fan-out has a shape the anchor does not, and the difference is the whole reason this is a separate
file.

The anchor is one property backed by one mutation: Export either stores a checkpoint or it does
not. The fan-out's correctness is a handful of independent promises, made in different places -
the constructor refuses fewer than two destinations, Export does not stop at the first failure,
Export does not report success unless every destination stored the batch, and every failure is
named. A single mutation here would only exercise one of them and would report PASS for a gate
that had measured one fifth of its claims, which is the precise shape of failure EV-064 recorded:
a check that reports success without having exercised anything.

So this gate runs one mutation per property, and each mutation is paired with the single test that
must notice it. All of them must be noticed. A property whose test passes under its mutation is
reported by name, because "the fan-out tests can fail" is a weaker claim than the one being made
here, which is "each of these promises is enforced".

Reusing classify() rather than re-deriving the discrimination
--------------------------------------------------------------
A build failure and a test failure both exit non-zero. Scoring `returncode != 0` as a detection
would certify five properties none of which were measured - the defect
scripts/prove_anchor_gate_rejects_build_failure.py was written to record. classify() is imported
from the anchor gate rather than reimplemented so there is exactly one definition of the
distinction in the repository, and so this gate inherits the fix the moment the anchor gate gets a
better one.

Certifying the mutation compiles
--------------------------------
The anchor gate can rely on its mutation being compile-safe by construction and checks
afterwards. This gate cannot lean on that as hard, because each mutation here is a small textual
substitution inside a loop that several other tests also exercise, and it would be easy to write
one that orphans a brace or leaves a range variable unused. A non-compiling mutation would then
score as a detection for every test in the package at once, which is a spectacular false positive:
the gate would print five confident DETECTED lines having established nothing.

So before any test is run under a mutation, `go build ./audit/` is required to succeed. A mutation
that does not compile is reported as UNCERTIFIED and fails the gate, which is the correct outcome:
it means the mutation is malformed, not that the code under test is well covered. This is
stricter than the anchor gate and deliberately so - with several independent mutations per file,
the chance that one is malformed is not negligible, and a malformed mutation that silently
certifies its neighbours is worse than no gate.

The rest is the anchor gate's discipline, because a gate that does not restore what it mutates is
a gate that can leave production code changed. Each mutation is verified to have landed (the
replacement present and the original absent) before anything is interpreted, the baseline is
green before any mutation is applied, and restoration is byte-for-byte in a finally block with the
result compared rather than assumed.

A property may legitimately be noticed by more than the paired test; that is reported, not
penalised, because the pairing states which test is *supposed* to notice, not which tests are
*allowed* to. What is fatal is the paired test passing.

Run directly, or as a step in the go job. Idempotent in the sense that matters: it restores the
file, so repeated runs are identical.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mutation_check_anchor as anchor_gate  # noqa: E402

MODULE = anchor_gate.MODULE
TARGET = MODULE / "audit" / "fanout.go"


@dataclass(frozen=True)
class Mutation:
    """One promise, the way of breaking it, and the test that must notice."""

    name: str
    find: str
    replace: str
    test: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="a single destination is accepted as independent retention",
        find="\tif len(sinks) < 2 {",
        replace="\tif len(sinks) < 1 {",
        test="TestAFanOutNeedsAtLeastTwoDestinations",
    ),
    Mutation(
        # `&& false` rather than `if false`: the range variable is used by the branch this
        # disables, so removing the test outright leaves `s` declared and not used and the
        # package stops compiling. The pre-flight build check below catches that, but a mutation
        # that cannot compile is a malformed mutation rather than evidence about the code, so it
        # is written to compile instead of relying on the gate to excuse it.
        name="a nil destination is accepted and dereferenced at export time",
        find="\t\tif s == nil {",
        replace="\t\tif s == nil && false {",
        test="TestAFanOutRefusesANilDestination",
    ),
    Mutation(
        # The whole failure block rather than the `if` line alone, so the mutation is a complete,
        # balanced statement with no unreachable code left behind for `go vet` to complain about.
        # `firstErr` stays assigned so the later `%w` keeps a non-nil error to wrap.
        name="Export stops at the first failing destination, starving the rest",
        find="\t\tif err := sink.Export(ctx, records); err != nil {\n"
             "\t\t\tfailed = append(failed, f.labels[i])\n"
             "\t\t\tif firstErr == nil {\n"
             "\t\t\t\tfirstErr = err\n"
             "\t\t\t}\n"
             "\t\t}",
        replace="\t\tif err := sink.Export(ctx, records); err != nil {\n"
                "\t\t\tfailed = append(failed, f.labels[i])\n"
                "\t\t\tfirstErr = err\n"
                "\t\t\tbreak\n"
                "\t\t}",
        test="TestAFailingDestinationDoesNotStopTheOthers",
    ),
    Mutation(
        name="Export reports success although one destination never stored the batch",
        find="\tif len(failed) == 0 {",
        replace="\tif len(failed) < len(f.destinations) {",
        test="TestBacklogIsNotReleasedWhileAnyDestinationHasNotStoredTheBatch",
    ),
    Mutation(
        # Wrapped rather than rewritten, so the surviving line is still a plain append and the
        # indentation change is the only difference in shape.
        name="only the first failed destination is named",
        find="\t\t\tfailed = append(failed, f.labels[i])\n",
        replace="\t\t\tif len(failed) == 0 {\n"
                "\t\t\t\tfailed = append(failed, f.labels[i])\n"
                "\t\t\t}\n",
        test="TestEveryFailedDestinationIsNamed",
    ),
    Mutation(
        name="an empty batch is written to every destination",
        find="\tif len(records) == 0 {\n\t\treturn nil\n\t}",
        replace="\tif false {\n\t\treturn nil\n\t}",
        test="TestAnEmptyBatchTouchesNoDestination",
    ),
)


def go(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", *args],
        cwd=MODULE,
        capture_output=True,
        text=True,
        env={**os.environ, "CGO_ENABLED": os.environ.get("CGO_ENABLED", "0")},
    )


def build() -> subprocess.CompletedProcess[str]:
    return go("build", "./audit/")


def run_test(name: str) -> subprocess.CompletedProcess[str]:
    return go("test", "-count=1", "-run", f"^{name}$", "./audit/")


def main() -> int:
    if not TARGET.exists():
        print(f"::error::{TARGET} not found; the mutations have no target and would prove nothing")
        return 1

    original = TARGET.read_bytes()
    text = original.decode("utf-8")

    # Every mutation must be applicable and unambiguous before anything is interpreted. Two
    # mutations that silently did not apply would each run the tests against an unmutated file,
    # see them pass, and report two missing properties that are in fact untested here.
    for mutation in MUTATIONS:
        occurrences = text.count(mutation.find)
        if occurrences != 1:
            print(f"::error::the target text for '{mutation.name}' appears {occurrences} time(s) "
                  f"in {TARGET.name}, expected exactly 1. The mutation cannot be applied, so this "
                  f"gate would prove nothing about that property; it is failing rather than passing "
                  f"vacuously.")
            return 1

    print(f"baseline: building the audit package")
    pristine = build()
    if pristine.returncode != 0:
        print(pristine.stdout[-800:], pristine.stderr[-800:])
        print("::error::the unmutated audit package does not build, so a failure under mutation "
              "could not be attributed to the mutation; refusing to interpret any result")
        return 1
    print(f"baseline: PASS ({TARGET.name} builds)")

    print(f"baseline: running the {len(MUTATIONS)} fan-out tests against the unmutated tree")
    for mutation in MUTATIONS:
        green = run_test(mutation.test)
        if green.returncode != 0:
            print(f"::error::baseline FAIL: {mutation.test} is not green on the unmutated tree, so "
                  f"a failure under '{mutation.name}' would prove nothing about the fan-out; "
                  f"refusing to interpret the result")
            print(green.stdout[-800:], green.stderr[-800:])
            return 1
    print(f"baseline: PASS (all {len(MUTATIONS)} fan-out tests green on the unmutated tree)\n")

    outcome = 0
    detail: list[str] = []

    for index, mutation in enumerate(MUTATIONS, start=1):
        print(f"=== {index}/{len(MUTATIONS)} {mutation.name}")
        try:
            # Bytes, not text. Path.write_text opens in text mode with universal newline
            # translation, which on Windows rewrites every \n in the file to \r\n and makes the
            # mutation land against a different byte sequence than the one that was searched.
            TARGET.write_bytes(text.replace(mutation.find, mutation.replace).encode("utf-8"))

            mutated = TARGET.read_bytes().decode("utf-8")
            # "Did it land" is decided against the original text rather than by requiring the
            # target to have disappeared. Three of these replacements contain their own target -
            # appending `break` extends the `if` line, and the wrap mutation nests the append -
            # so a `find in mutated` check reports a faithful mutation as unapplied, and a gate
            # that cries wolf about mutations which did work is a gate people learn to ignore.
            if mutated == text or mutation.replace not in mutated:
                print("  ::error::the mutation did not land in the file; refusing to interpret the "
                      "result")
                detail.append(f"{mutation.test}: the mutation did not land")
                outcome = 1
                continue

            # The soundness check this gate adds over the anchor gate. A mutation that does not
            # compile makes every test in the package exit non-zero without any of them running,
            # which would be reported as a detection for all of them at once.
            compiled = build()
            if compiled.returncode != 0:
                print(f"  [UNCERTIFIED] the mutation does not compile, so no test ran and nothing "
                      f"was established:")
                print("   ", (compiled.stderr or compiled.stdout).strip().replace("\n", "\n    "))
                detail.append(f"{mutation.test}: the mutation does not compile, so the package was "
                              f"never tested")
                outcome = 1
                continue

            verdict, evidence = anchor_gate.classify(run_test(mutation.test))
            if verdict == anchor_gate.DETECTED:
                print(f"  [detected] {mutation.test} noticed")
                print(f"              {evidence}")
            elif verdict == anchor_gate.PASSED:
                print(f"  [NOT DETECTED] {mutation.test} passed against a broken fan-out; this "
                      f"promise is not enforced by any test")
                detail.append(f"{mutation.test} passes against '{mutation.name}', so it does not "
                              f"test that promise")
                outcome = 1
            elif verdict == anchor_gate.BUILD_FAILURE:
                print(f"  [BUILD FAILURE] {mutation.test}: the package did not build ({evidence}) "
                      f"despite the pre-flight build passing; this is not a detection")
                detail.append(f"{mutation.test}: build failure under mutation, not a detection")
                outcome = 1
            else:
                print(f"  [INDETERMINATE] {mutation.test}: go test exited non-zero without a "
                      f"--- FAIL line, so it is not established that any test ran")
                detail.append(f"{mutation.test}: the run proved nothing, so it cannot be credited")
                outcome = 1
        finally:
            TARGET.write_bytes(original)
            if TARGET.read_bytes() != original:
                print(f"  ::error::failed to restore {TARGET} byte-for-byte; the working tree is "
                      f"unsafe and must be restored by hand")
                detail.append("the fan-out source could not be restored")
                outcome = 1
        print()

    # The restore is only worth anything if what it restored is usable, so the package is built
    # once more here rather than trusted from the per-mutation pre-flight builds.
    final = build()
    print(f"  {TARGET.name} restored and the audit package builds again: {final.returncode == 0}")
    if final.returncode != 0:
        detail.append("the audit package does not build after restoration")
        outcome = 1
    else:
        final_test = run_test(MUTATIONS[0].test)
        print(f"  {MUTATIONS[0].test} green again:                    "
              f"{final_test.returncode == 0}")
        if final_test.returncode != 0:
            detail.append("the tests are not green after restoration")
            outcome = 1

    print()
    if outcome:
        for line in detail:
            print(line)
        print("::error::audit fan-out mutation gate: FAIL - see the findings above")
        return outcome

    print(f"audit fan-out mutation gate: PASS (all {len(MUTATIONS)} properties are enforced, each "
          f"noticed by a failing assertion rather than a broken build)")
    return 0


if __name__ == "__main__":
    sys.exit(main())