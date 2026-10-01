"""One-off: prove scripts/mutation_check_drain.py refuses to credit a build failure.

The gate's whole claim is that the drain tests notice a hard server.Close. Its first version
established that claim by reading one integer: `if result.returncode == 0`. That integer is
non-zero for a package that does not compile as well as for a test that noticed, so a drain test
broken by an unrelated compile error - or a mutation that broke the build rather than the
assertion - was reported as `[detected]` and the step passed. It certified drain coverage it had
never measured, which is the same defect EV-064 and EV-065 recorded in the tests the gate protects.

Proving a gate means breaking its input on purpose and requiring it to fail, so this breaks the
input in exactly that way: it rewrites the shutdown site so that the gate's own mutation makes
the package fail to parse. The graceful branch is moved onto an `else if`, which is valid Go
before the mutation and a syntax error after it, because the replacement text begins with a
statement (`_ = shutdownCtx`) where the grammar requires a block or an if statement.

Two things make this a proof rather than a demonstration:

  * The crafted file is confirmed to build BEFORE the mutation. Without that, a green gate could
    be explained by a fixture that was already broken, which is the mistake
    scripts/prove_run_block_test_detects.py recorded in this repository's own history - an
    injection that was not actually an injection.

  * The old rule is run against the same evidence. The mutated tree is compiled and tested here
    directly, using the gate's own GRACEFUL/MUTATED constants and its own classify(), and the
    `returncode != 0` verdict is printed next to what the gate now says about the same output. A
    proof that only shows the new code failing cannot tell a fixed gate from a gate that fails for
    an unrelated reason; this one shows what changed.

The target file is restored byte-for-byte in a finally block and the restore is verified, because
a half-restored main.go would be worse than no proof at all. The tree is rebuilt afterwards as an
independent check that the restore left something that compiles.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TARGET = REPO / "services" / "control-plane" / "cmd" / "control-plane" / "main.go"

# The gate's own constants, imported rather than copied. A proof that restates the mutation is a
# proof about the copy; importing it keeps the two from drifting, which is the same concern that
# made the pre-existing bash gate's duplicated copy worth consolidating.
sys.path.insert(0, str(REPO / "scripts"))
import mutation_check_drain as gate  # noqa: E402

MODULE = gate.MODULE

# The unmutated form. Valid Go: `else if` is a nested IfStmt, exactly as `if` is.
CRAFTED = (
    "\tif shutdownCtx.Err() != nil {\n"
    '\t\tfmt.Fprintln(os.Stderr, "control-plane: gate proof fixture: the drain deadline is '
    'already spent")\n'
    "\t\treturn 1\n"
    f"\t}} else {gate.GRACEFUL}\n"
)

FIRST_TEST = gate.DRAIN_TESTS[0]


def build() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", "build", "./cmd/control-plane/"],
        cwd=MODULE,
        capture_output=True,
        text=True,
    )


def go_test(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", "test", "-count=1", "-run", f"^{name}$", "./cmd/control-plane/"],
        cwd=MODULE,
        capture_output=True,
        text=True,
    )


def main() -> int:
    outcome = 0
    original = TARGET.read_bytes()
    try:
        # Step 0: the tree must build before this proof touches it. Other work in this repository
        # edits the same Go packages, and a tree that is temporarily broken for an unrelated reason
        # would produce a build failure here - the gate would correctly refuse to credit it, and
        # this proof would report a pass for a build failure it did not cause. Establishing the
        # starting state first is what separates "the gate is non-vacuous" from "something else was
        # broken".
        pristine = build()
        print(f"  sanity: the untouched tree builds:            {pristine.returncode == 0}")
        if pristine.returncode != 0:
            print(pristine.stdout[-800:], pristine.stderr[-800:])
            print("PROOF INCONCLUSIVE: the tree does not build independently of this fixture; "
                  "aborting rather than claiming a result")
            return 1

        text = original.decode("utf-8")
        if text.count(gate.GRACEFUL) != 1:
            print("SETUP FAILED: the shutdown site was not found exactly once")
            return 1

        crafted = text.replace(f"\t{gate.GRACEFUL}\n", CRAFTED, 1)
        if crafted == text or gate.GRACEFUL not in crafted:
            print("SETUP FAILED: the crafted shutdown site did not land")
            return 1
        TARGET.write_bytes(crafted.encode("utf-8"))

        # Step 1: the fixture must be sound before anything is mutated. If this fails, the gate
        # result below would be about the fixture rather than about the gate.
        clean = build()
        print(f"  sanity: the crafted unmutated tree builds: {clean.returncode == 0}")
        if clean.returncode != 0:
            print(clean.stdout[-800:], clean.stderr[-800:])
            print("SETUP FAILED: the fixture does not compile unmutated; proof aborted")
            return 1

        # Step 2: what the old rule would have concluded from the same evidence.
        mutated_text = crafted.replace(gate.GRACEFUL, gate.MUTATED, 1)
        TARGET.write_bytes(mutated_text.encode("utf-8"))
        evidence = go_test(FIRST_TEST)
        output = evidence.stdout + evidence.stderr
        old_verdict = "detected" if evidence.returncode != 0 else "NOT detected"
        new_verdict, marker = gate.classify(evidence)
        print()
        print("=== the same mutated run, scored both ways ===")
        print(f"  go test exit code:                    {evidence.returncode} (non-zero)")
        print(f"  a `--- FAIL` line for the test:       {'--- FAIL' in output}")
        print(f"  old rule (returncode != 0):          {old_verdict}")
        print(f"  classify() now says:                  {new_verdict} ({marker or 'no marker'})")
        if evidence.returncode == 0:
            print("PROOF FAILED: the mutated tree compiled; the fixture no longer breaks the build")
            outcome = 1
        elif "--- FAIL" in output:
            print("PROOF FAILED: a test actually ran and failed, so this is not a build failure")
            outcome = 1
        elif new_verdict != gate.BUILD_FAILURE:
            print("PROOF FAILED: classify() did not recognise a build failure; the gate would still "
                  "credit it")
            outcome = 1

        # Step 3: the gate itself, against that fixture.
        TARGET.write_bytes(crafted.encode("utf-8"))
        result = subprocess.run(
            [sys.executable, "scripts/mutation_check_drain.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        print()
        print("=== gate run against a build-failure mutation ===")
        print(result.stdout.strip())
        if result.stderr.strip():
            print("stderr:", result.stderr.strip()[:400])

        baseline_green = "baseline: PASS" in result.stdout
        claimed_detection = "[detected]" in result.stdout
        called_build_failure = "BUILD FAILURE" in result.stdout
        refused = "cannot be credited as detections" in result.stdout
        nonzero = result.returncode != 0
        print()
        print(f"  baseline ran and was green:           {baseline_green}")
        print(f"  gate claimed a detection:             {claimed_detection}")
        print(f"  gate called it a build failure:       {called_build_failure}")
        print(f"  gate refused to credit it:            {refused}")
        print(f"  gate exited non-zero:                 {nonzero}")

        if not baseline_green:
            # Without a green baseline the gate never reached the mutated run, so the refusal
            # above is not evidence about the build-failure path. Saying so is the whole point.
            print("PROOF INCONCLUSIVE: the gate stopped at the baseline and never scored the "
                  "mutated run")
            outcome = 1
        elif claimed_detection or not called_build_failure or not refused or not nonzero:
            print("PROOF FAILED: the gate accepted a run where no test executed")
            outcome = 1
        else:
            print("PROOF HOLDS: a build failure is not a detection. The gate reports it as "
                  "uncertified and fails instead of certifying drain coverage.")

        # Step 4: put the fixture back before the finally block restores the real file, so a
        # failure in the gate's own restore is not conflated with the proof's restore.
        TARGET.write_bytes(crafted.encode("utf-8"))
    finally:
        # No return here: a return inside finally discards both the return value and any
        # exception already in flight, so a restore problem could mask, or mask, the proof
        # result. The restore is checked after the try/finally instead.
        TARGET.write_bytes(original)

    restored = TARGET.read_bytes() == original
    print(f"\n  restored main.go (byte-identical: {restored})")
    if not restored:
        return 1
    # An independent check that the tree is not merely byte-identical but actually compilable,
    # which is what "restored" has to mean for the next person to run anything.
    after = build()
    print(f"  the restored tree builds:              {after.returncode == 0}")
    if after.returncode != 0:
        print(after.stdout[-800:], after.stderr[-800:])
        return 1
    return outcome


if __name__ == "__main__":
    sys.exit(main())
