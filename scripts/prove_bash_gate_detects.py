"""One-off: prove scripts/check_workflow_bash.py detects a real syntax error.

A gate that has only ever been observed passing is the thing this repository keeps getting wrong,
so this check gets the same treatment the drain tests got: break the input on purpose and require
the gate to notice. Both a negative control (malformed bash must be rejected) and a positive
control (well-formed bash must be accepted) are run, because a check that rejects everything is
just as useless as one that accepts everything.
"""

import subprocess
import sys

BROKEN = (
    "while read -r m; do\n"
    "  echo $m\n"
    "done < modules.txt\n"
    "if [ -n ]; then\n"
    "  exit 1\n"
)

VALID = (
    "set -euo pipefail\n"
    "while read -r m; do\n"
    "  go build \"./$m/...\"\n"
    "done < modules.txt\n"
)


def check(script: str) -> int:
    # Binary stdin, for the reason documented in check_workflow_bash.py: a text-mode pipe
    # translates "\n" to "\r\n" on Windows and every block then fails spuriously.
    return subprocess.run(["bash", "-n"], input=script.encode("utf-8"), capture_output=True).returncode


def main() -> int:
    broken_code = check(BROKEN)
    valid_code = check(VALID)

    print(f"  malformed script -> exit {broken_code} (expect non-zero)")
    print(f"  well-formed script -> exit {valid_code} (expect 0)")

    if broken_code == 0:
        print("PROOF FAILED: malformed bash was accepted, so the gate cannot detect a broken step")
        return 1
    if valid_code != 0:
        print("PROOF FAILED: well-formed bash was rejected, so the gate rejects everything")
        return 1
    print("PROOF HOLDS: the gate rejects malformed bash and accepts well-formed bash.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
