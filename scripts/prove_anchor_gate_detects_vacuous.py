"""One-off: prove scripts/mutation_check_anchor.py fails when an anchor test goes vacuous.

A gate that has only ever been observed passing is the exact thing this repository keeps getting
wrong, so the gate is held to the same standard as the tests it protects. This makes the first
anchor test assert nothing - it skips immediately, which is exit 0 - and requires the gate to
report NOT DETECTED and exit non-zero.

The skip is the strongest form of the failure, because a skipped test is invisible in a green run
that reports "ok": it is the shape EV-064 recorded for the integration suite that skipped seventeen
tests. If this gate could not catch that, it would be certifying the same kind of coverage that
already fooled this repository once.

The original file is restored in a finally block and the restore is verified, because a
half-restored test file would be worse than no proof at all. The tree is then rebuilt
independently, so "restored" means something still compiles rather than merely byte-identical.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
TARGET = REPO / "services" / "control-plane" / "audit" / "sink_checkpoint_test.go"
MARKER = "func TestTheSinkWritesACheckpointCoveringTheRecordsItJustStored(t *testing.T) {"

sys.path.insert(0, str(REPO / "scripts"))
import mutation_check_anchor as gate  # noqa: E402

MODULE = gate.MODULE


def go_test(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", "test", "-count=1", "-run", f"^{name}$", "./audit/"],
        cwd=MODULE,
        capture_output=True,
        text=True,
    )


def build() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", "build", "./audit/"],
        cwd=MODULE,
        capture_output=True,
        text=True,
    )


def main() -> int:
    outcome = 0
    original = TARGET.read_bytes()
    try:
        # The tree must build before this proof touches it. A fixture that was already broken
        # would make a green or red gate explainable by something other than the gate.
        pristine = build()
        print(f"  sanity: the untouched audit package builds: {pristine.returncode == 0}")
        if pristine.returncode != 0:
            print(pristine.stdout[-800:], pristine.stderr[-800:])
            print("PROOF INCONCLUSIVE: the tree does not build independently of this fixture; "
                  "aborting rather than claiming a result")
            return 1

        text = original.decode("utf-8")
        if text.count(MARKER) != 1:
            print("SETUP FAILED: the anchor test signature was not found exactly once")
            return 1

        neutered = text.replace(
            MARKER,
            MARKER + '\n\tt.Skip("NEUTERED FOR GATE PROOF: this test asserts nothing")',
            1,
        )
        if neutered == text:
            print("SETUP FAILED: the neutered test did not land")
            return 1
        TARGET.write_text(neutered, encoding="utf-8")
        print("  neutered: the first anchor test now skips and asserts nothing")

        # The neutered file must still compile, or the gate's build-failure discrimination would
        # reject it for the wrong reason and this would be proving something else.
        sound = build()
        print(f"  sanity: the neutered package still builds:  {sound.returncode == 0}")
        if sound.returncode != 0:
            print(sound.stdout[-800:], sound.stderr[-800:])
            print("SETUP FAILED: the neutered fixture does not compile; proof aborted")
            outcome = 1

        # A skipped test exits 0 - the whole point. Established here directly so a gate result
        # cannot be explained by the fixture failing in some other way.
        skipped = go_test(gate.ANCHOR_TESTS[0])
        print(f"  the neutered test exits 0 (a skip):        {skipped.returncode == 0}")
        if skipped.returncode != 0:
            print(skipped.stdout[-800:], skipped.stderr[-800:])
            print("PROOF FAILED: the neutered test did not pass vacuously; the fixture is not "
                  "vacuous and this proves nothing")
            outcome = 1

        result = subprocess.run(
            [sys.executable, "scripts/mutation_check_anchor.py"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        print()
        print("=== gate run against a vacuous anchor test ===")
        print(result.stdout.strip())
        if result.stderr.strip():
            print("stderr:", result.stderr.strip()[:400])

        detected = "NOT DETECTED" in result.stdout
        nonzero = result.returncode != 0
        claimed_pass = "mutation gate: PASS" in result.stdout
        print()
        print(f"  gate reported NOT DETECTED:  {detected}")
        print(f"  gate exited non-zero:         {nonzero}")
        print(f"  gate claimed an overall PASS: {claimed_pass}")

        if detected and nonzero and not claimed_pass:
            print("PROOF HOLDS: the gate fails when an anchor test stops asserting anything.")
        else:
            print("PROOF FAILED: the gate passed a vacuous test, so it would not catch a real no-op.")
            outcome = 1
    finally:
        # No return here: a return inside finally discards both the return value and any exception
        # already in flight. The restore is checked after the try/finally instead.
        TARGET.write_bytes(original)

    restored = TARGET.read_bytes() == original
    print(f"\n  restored sink_checkpoint_test.go (byte-identical: {restored})")
    if not restored:
        return 1
    # An independent check that the restore left something that compiles, which is what "restored"
    # has to mean for the next person to run anything.
    after = build()
    print(f"  the restored package builds:                 {after.returncode == 0}")
    if after.returncode != 0:
        print(after.stdout[-800:], after.stderr[-800:])
        return 1
    return outcome


if __name__ == "__main__":
    sys.exit(main())