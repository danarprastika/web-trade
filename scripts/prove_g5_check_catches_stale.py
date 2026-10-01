"""One-off: prove scripts/generate_g5_gate_report.py --check catches a stale report.

The check mode exists because the G5 report was, until now, a snapshot with nothing tying it to
the code it describes: every digest was correct when written and went stale silently, while the
report kept asserting a PASS verdict and a per-criterion mechanically_verified flag. That is the
same defect the `sqlc is up to date` step catches for generated code, applied to a governance
artifact, where the failure is worse because a stale verdict still looks authoritative.

A check that has only ever been observed passing cannot be believed, so this changes a digested
file and requires the check to fail. Two cases, because the two failure modes are different and
only one is obvious:

  1. A digested file's contents change. The report is stale because a digest no longer matches.
  2. The report's verdict is edited by hand to something the code does not produce. The report
     is stale because its own content no longer matches what the generator emits - which is the
     case that a digest-only check would miss entirely, and the reason the comparison is
     byte-for-byte against a full regeneration rather than a digest recomputation.

Both files are restored byte-identically in a finally block, and the restore is verified.
"""

import json
import pathlib
import subprocess
import sys

ARTIFACT = pathlib.Path("services/control-plane/audit/chain.go")
REPORT = pathlib.Path("evidence/gates/G5-gate-report.json")
CHECK = ["python", "scripts/generate_g5_gate_report.py", "--check"]


def run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(CHECK, capture_output=True, text=True)


def main() -> int:
    outcome = 0
    artifact_orig = ARTIFACT.read_bytes()
    report_orig = REPORT.read_bytes()

    # Case 1: a digested file changes, so a recorded digest no longer matches.
    try:
        ARTIFACT.write_bytes(artifact_orig + b"\n// touched\n")
        result = run_check()
        detected = result.returncode != 0
        print(f"  case 1: a digested file changed -> exit {result.returncode} (expect non-zero)")
        print(f"          check detected it: {detected}")
        if not detected:
            print("          PROOF FAILED: a stale digest did not fail the check")
            outcome = 1
    finally:
        ARTIFACT.write_bytes(artifact_orig)

    # Case 2: the report itself is edited, so it no longer matches what the generator produces.
    try:
        tampered = json.loads(report_orig.decode("utf-8"))
        tampered["verdict"] = "PASS (hand-edited)"
        REPORT.write_text(json.dumps(tampered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result = run_check()
        detected = result.returncode != 0
        print(f"  case 2: the report was hand-edited  -> exit {result.returncode} (expect non-zero)")
        print(f"          check detected it: {detected}")
        if not detected:
            print("          PROOF FAILED: a hand-edited report passed the check")
            outcome = 1
    finally:
        REPORT.write_bytes(report_orig)

    # And a report that was left stale by case 1 must be reported stale, not silently accepted.
    stale = run_check()
    print(f"  after restore, the report is current -> exit {stale.returncode} (expect 0)")
    if stale.returncode != 0:
        print("  PROOF FAILED: the report is still stale after restoring the files")
        outcome = 1
    else:
        print("  PROOF HOLDS: the check fails on a stale report and passes on a current one.")
    return outcome


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        pass
