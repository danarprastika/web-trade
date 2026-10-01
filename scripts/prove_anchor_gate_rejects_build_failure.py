"""One-off: prove scripts/mutation_check_anchor.py refuses to credit a build failure.

The gate's headline claim is that the anchor tests notice a sink which stores records without
checkpointing them, and it is careful in the second half of that claim: a detection is credited
only when a `--- FAIL` line names the test. That care is load-bearing, because `go test` exits
non-zero for a package that does not compile just as readily as for a test that noticed. A rule of
`if returncode != 0` would certify anchor coverage it had never measured - the same defect EV-064
and EV-065 recorded in the tests this gate protects, and the defect review recorded against the
first version of the sibling drain gate.

Why this proves classify() rather than driving the whole gate
--------------------------------------------------------------
The obvious proof shape is to craft a fixture that compiles before the gate's mutation and fails to
compile after, then run the gate against it. That shape does not exist for this gate, and the reason
is worth recording rather than working around.

The gate's mutation replaces a complete, balanced `for` statement with one simple statement. For a
fixture to compile beforehand and break afterwards, the mutation would have to remove something
whose *only* use was inside the deleted text - a variable declared inside the loop and used
outside it, which cannot compile in the first place, or a construct whose validity depends on the
loop's shape, such as making the loop the body of an `else`. gc requires an `else` branch to be an
`if` statement or a block, so `else for ... {}` is rejected, which was confirmed by running it: the
attempt produced `syntax error: else must be followed by if or statement block` on the *unmutated*
tree, and the proof's soundness check correctly refused to continue rather than reporting a result.

That is the same property that makes the gate trustworthy from the other side: the mutation is
compile-safe by construction, so a non-zero exit under it genuinely reflects a test noticing
something. A build-failure fixture would have to break that property in order to exist, and
building one would mean proving the gate against a mutation shape it will never use.

So the discrimination is proved where it actually lives - in classify() - against evidence produced
by the real toolchain rather than a hand-written string. A compile error is injected into the audit
package as a temporary test file, the resulting `go test` output is captured, and classify() is
required to call it a build failure while the naive `returncode != 0` rule calls it a detection.
Both verdicts are printed from the same evidence, so the proof shows what changed rather than only
that the new code fails.

The evidence is genuine rather than fabricated: the temporary file really is compiled and really is
rejected, and the exit code is checked to be non-zero before the verdict is trusted. A run that
failed for some other reason would not carry a `.go:line:col:` diagnostic, and classify() is
required to find that diagnostic specifically - it would report INDETERMINATE rather than
BUILD_FAILURE on output that merely happened to be non-zero, which is itself part of what is being
shown.

The temporary file is removed in a finally block and the removal is verified, and the package is
then built independently, so the proof cannot leave the audit package uncompilable for the next
person. Nothing in the repository is modified: unlike the drain gate's proof, this one never writes
to a production file, because it never needs to.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO / "scripts"))
import mutation_check_anchor as gate  # noqa: E402

MODULE = gate.MODULE

# The injected compile error. `this is not Go` is not a valid statement, so the package cannot
# compile while the file exists. It is a _test.go file so that the failure surfaces through
# `go test`, which is exactly the surface the gate reads - the same surface a genuine mid-refactor
# compile break would arrive on.
INJECTED = REPO / "services" / "control-plane" / "audit" / "zz_gate_build_failure_probe_test.go"

INJECTED_SOURCE = (
    "package audit\n"
    "\n"
    "// Injected by scripts/prove_anchor_gate_rejects_build_failure.py to produce a genuine\n"
    "// compile failure for classify() to score. Deleted before this script exits.\n"
    "func gateBuildFailureProbe() {\n"
    "\tthis is not Go\n"
    "}\n"
)

FIRST_TEST = gate.ANCHOR_TESTS[0]


def build() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", "build", "./audit/"],
        cwd=MODULE,
        capture_output=True,
        text=True,
    )


def go_test(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", "test", "-count=1", "-run", f"^{name}$", "./audit/"],
        cwd=MODULE,
        capture_output=True,
        text=True,
    )


def main() -> int:
    outcome = 0
    existed = INJECTED.exists()
    if existed:
        print(f"SETUP FAILED: {INJECTED.name} already exists; refusing to overwrite a file this "
              "proof does not own")
        return 1

    try:
        # Step 0: the tree must build before anything is injected. A tree already broken for an
        # unrelated reason would make the diagnostic below explainable by something other than the
        # injection, which is the mistake scripts/prove_run_block_test_detects.py recorded in this
        # repository's own history - an injection that was not actually an injection still produced
        # a clean result.
        pristine = build()
        print(f"  sanity: the untouched audit package builds: {pristine.returncode == 0}")
        if pristine.returncode != 0:
            print(pristine.stdout[-800:], pristine.stderr[-800:])
            print("PROOF INCONCLUSIVE: the tree does not build independently of this injection; "
                  "aborting rather than claiming a result")
            return 1

        # Step 1: the gate's own target test is green beforehand, so the only thing that changes
        # between the two runs below is the injected compile error.
        green = go_test(FIRST_TEST)
        print(f"  sanity: {FIRST_TEST} passes beforehand:   {green.returncode == 0}")
        if green.returncode != 0:
            print(green.stdout[-800:], green.stderr[-800:])
            print("PROOF INCONCLUSIVE: the target test is not green independently of the injection")
            return 1

        # Step 2: inject a genuine compile error and capture what the toolchain actually says.
        INJECTED.write_text(INJECTED_SOURCE, encoding="utf-8")
        evidence = go_test(FIRST_TEST)
        output = evidence.stdout + evidence.stderr

        # A real `--- FAIL` line would mean a test ran, and the whole point is that none did.
        fail_line = gate.first_fail_line(output)
        diagnostic = gate.COMPILE_DIAGNOSTIC.search(output)

        old_verdict = "detected" if evidence.returncode != 0 else "NOT detected"
        new_verdict, marker = gate.classify(evidence)

        print()
        print("=== the same non-zero run, scored both ways ===")
        print(f"  go test exit code:                 {evidence.returncode} (non-zero)")
        print(f"  a `--- FAIL` line for the test:    {bool(fail_line)}")
        print(f"  a `.go:line:col:` diagnostic:      {bool(diagnostic)}")
        if diagnostic:
            print(f"  the diagnostic was:                {diagnostic.group(0).strip()}")
        print(f"  naive rule (returncode != 0):      {old_verdict}")
        print(f"  classify() now says:               {new_verdict} ({marker or 'no marker'})")

        # The evidence must be what it claims to be before the verdict means anything.
        if evidence.returncode == 0:
            print("PROOF FAILED: the injected compile error did not fail the run")
            outcome = 1
        elif fail_line:
            print(f"PROOF FAILED: a test actually ran and failed ({fail_line}), so this is not a "
                  "build failure")
            outcome = 1
        elif not diagnostic:
            print("PROOF FAILED: the failure carried no compile diagnostic, so this is not the "
                  "evidence this proof set out to produce")
            outcome = 1
        elif old_verdict != "detected":
            print("PROOF FAILED: the naive rule did not claim a detection, so there is no behaviour "
                  "to distinguish")
            outcome = 1
        elif new_verdict != gate.BUILD_FAILURE:
            print("PROOF FAILED: classify() did not recognise a build failure; the gate would still "
                  "credit it")
            outcome = 1
        else:
            print()
            print("PROOF HOLDS: a build failure is not a detection. classify() reports it as a "
                  "build failure, which the gate prints as BUILD FAILURE and refuses to credit, "
                  "instead of certifying anchor coverage it never measured.")

        # Step 3: INDETERMINATE is the other half of the claim. Output that is non-zero, has no
        # `--- FAIL` line, and carries no compile diagnostic must not be credited either - it is
        # the case where the toolchain failed for a reason the gate cannot read, and reporting it
        # as coverage is the failure this whole design exists to prevent.
        synthetic = subprocess.CompletedProcess(
            args=["go", "test"], returncode=1, stdout="", stderr="something went wrong\n",
        )
        synthetic_verdict, _ = gate.classify(synthetic)
        print()
        print("=== an unreadable non-zero run ===")
        print("  output: 'something went wrong' (no FAIL line, no diagnostic)")
        print(f"  classify() says:                  {synthetic_verdict}")
        if synthetic_verdict != gate.INDETERMINATE:
            print("PROOF FAILED: an unreadable non-zero run was credited; the gate would report "
                  "coverage it has not established")
            outcome = 1
        else:
            print("  correctly INDETERMINATE: it is neither credited as a detection nor misread as a "
                  "build failure.")
    finally:
        # No return here: a return inside finally discards both the return value and any exception
        # already in flight, so a removal problem could mask, or mask, the proof result.
        if not existed and INJECTED.exists():
            INJECTED.unlink()

    removed = not INJECTED.exists()
    print(f"\n  removed the injected file:            {removed}")
    if not removed:
        return 1
    # An independent check that the tree is not merely free of the probe file but actually
    # compilable, which is what "restored" has to mean for the next person to run anything.
    after = build()
    print(f"  the audit package builds again:       {after.returncode == 0}")
    if after.returncode != 0:
        print(after.stdout[-800:], after.stderr[-800:])
        return 1
    # And the gate itself still passes against the real tree, so the proof did not leave anything
    # behind that would make the next run of it misleading.
    final = go_test(FIRST_TEST)
    print(f"  {FIRST_TEST} green again:          {final.returncode == 0}")
    if final.returncode != 0:
        print(final.stdout[-800:], final.stderr[-800:])
        return 1
    return outcome


if __name__ == "__main__":
    sys.exit(main())