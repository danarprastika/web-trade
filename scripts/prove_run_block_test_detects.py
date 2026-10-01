"""One-off: prove the new run-block bash test detects a genuinely invalid step.

The previous attempt to prove this was itself a false negative: the injection used
`done <<< modules.txt`, which is a valid herestring, so the test was right to pass and my
"break" was not a break. That is the same class of error this whole session keeps recording -
a check that was doubted, and the doubt was correct, and the cause was in the setup rather than
in the check - so it is worth doing properly and recording the difference.

This injects an unterminated double quote into a real run block, which is unambiguously invalid
bash, and requires pytest to fail. The injection is independently confirmed invalid before the
pytest result is trusted, so a passing test cannot be explained away by a second bad setup.
"""

import pathlib
import subprocess
import sys

WORKFLOW = pathlib.Path(".github/workflows/ci.yml")
TARGET = 'echo "::group::integration $m"'


def main() -> int:
    original = WORKFLOW.read_bytes()
    outcome = 0
    try:
        text = original.decode("utf-8")
        if TARGET not in text:
            print("SETUP FAILED: the target run-block line was not found")
            return 1

        # Drop the closing quote. Unterminated, so bash cannot parse it.
        broken = text.replace(TARGET, TARGET[:-1], 1)
        WORKFLOW.write_bytes(broken.encode("utf-8"))

        # Establish independently that this is invalid bash, so a green pytest below cannot be
        # blamed on an injection that was not actually broken.
        sanity = subprocess.run(
            ["bash", "-n"], input=('echo "unterminated\n').encode("utf-8"), capture_output=True
        )
        print(f"  sanity: an unterminated quote is invalid bash: {sanity.returncode != 0}")
        if sanity.returncode == 0:
            print("SETUP FAILED: the injected construct is actually valid; proof aborted")
            outcome = 1
        else:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/ci/test_ci_workflow.py",
                    "-q",
                    "-k",
                    "run_block",
                ],
                capture_output=True,
                text=True,
            )
            summary = [l for l in result.stdout.splitlines() if "passed" in l or "failed" in l]
            print(f"  pytest exit = {result.returncode} (expect non-zero)")
            print(f"  {summary[-1] if summary else '(no summary line)'}")

            if result.returncode != 0:
                print("PROOF HOLDS: the test detects an invalid run block.")
            else:
                print("PROOF FAILED: the test passed an invalid run block, so it checks nothing.")
                outcome = 1
    finally:
        # No return here: a return inside finally discards both the return value and any
        # exception already in flight, so a restore problem could be masked by, or mask, the
        # proof result. The restore is checked after the try/finally instead.
        WORKFLOW.write_bytes(original)

    restored = WORKFLOW.read_bytes() == original
    print(f"  restored ci.yml (byte-identical: {restored})")
    if not restored:
        return 1
    return outcome


if __name__ == "__main__":
    sys.exit(main())
