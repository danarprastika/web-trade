"""One-off: prove scripts/mutation_check_drain.py fails when a drain test goes vacuous.

A gate that has only ever been observed passing is the exact thing this repository keeps getting
wrong, so the gate gets held to the same standard as the tests it protects. This makes the first
drain test assert nothing - it skips immediately, which is exit 0 - and requires the gate to
report NOT DETECTED and exit non-zero.

The original file is restored in a finally block and the restore is verified, because a
half-restored test file would be worse than no proof at all.
"""

import pathlib
import subprocess
import sys

TARGET = pathlib.Path("services/control-plane/cmd/control-plane/main_test.go")
MARKER = "func TestTheDrainLetsAnInFlightRequestFinishBeforeItStopsAccepting(t *testing.T) {"


def main() -> int:
    original = TARGET.read_bytes()
    try:
        text = original.decode("utf-8")
        if MARKER not in text:
            print("SETUP FAILED: the drain test signature was not found")
            return 1

        neutered = text.replace(
            MARKER,
            MARKER + "\n\tt.Skip(\"NEUTERED FOR GATE PROOF: this test asserts nothing\")",
            1,
        )
        TARGET.write_text(neutered, encoding="utf-8")
        print("  neutered: the first drain test now skips and asserts nothing")

        result = subprocess.run(
            [sys.executable, "scripts/mutation_check_drain.py"],
            capture_output=True,
            text=True,
        )
        print("=== gate run against a vacuous test ===")
        print(result.stdout.strip())
        if result.stderr.strip():
            print("stderr:", result.stderr.strip()[:400])

        detected = "NOT DETECTED" in result.stdout
        nonzero = result.returncode != 0
        print()
        print(f"  gate reported NOT DETECTED: {detected}")
        print(f"  gate exited non-zero:        {nonzero}")

        if detected and nonzero:
            print("PROOF HOLDS: the gate fails when a drain test stops asserting anything.")
            return 0
        print("PROOF FAILED: the gate passed a vacuous test, so it would not catch a real no-op.")
        return 1
    finally:
        TARGET.write_bytes(original)
        restored = TARGET.read_bytes() == original
        print(f"  restored main_test.go (byte-identical: {restored})")


if __name__ == "__main__":
    sys.exit(main())
