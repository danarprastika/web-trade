"""Check that every `run:` block in the CI workflow is syntactically valid bash.

EV-066 left one caveat open: the workflow's steps were reproduced locally with local equivalents,
so the bash itself - as written, under `set -euo pipefail` on the runner - was never parsed. A
syntax error in a step is the cheapest possible CI failure and it is invisible until the step
runs, on a runner, minutes into a job.

This parses each block with `bash -n`, which checks syntax without executing anything. It cannot
verify behaviour: a block can be syntactically perfect and still do the wrong thing, and the
commands inside are not run here. What it removes is the specific, cheap, whole class of defect
where the step would have failed on the runner before reaching any of its logic.

It is a separate script rather than a test because it needs bash, which a Windows test run may not
have, and because failing to find bash is a skip rather than a pass: a check that silently stops
running is the failure mode this repository keeps recording.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def main() -> int:
    if shutil.which("bash") is None:
        print("SKIP: no bash on PATH; the runner scripts were not syntax-checked")
        return 0

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    failures = 0
    checked = 0

    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            script = step.get("run")
            if not isinstance(script, str) or not script.strip():
                continue

            label = step.get("name") or step.get("uses") or "(unnamed step)"
            checked += 1

            # The script is piped to bash on stdin as bytes rather than as text, and rather than
            # written to a temp file. Both of those details are load-bearing, and both were wrong
            # in the first version of this check:
            #
            #   A temp path is wrong on Windows, because the bash on PATH is the WSL bash, which
            #   cannot see a C:\... path and reads the backslashes as escapes. Every block then
            #   failed with "No such file or directory" and the gate reported a broken workflow
            #   when the workflow was fine.
            #
            #   A text-mode pipe is wrong on Windows for the opposite reason: Python translates
            #   "\n" to "\r\n" on the way in, so bash receives carriage returns that it reads as
            #   part of the command. That produced nine phantom syntax errors - `done < modules.txt`
            #   and a stray $'\r' - for a workflow whose run: blocks are all valid, and whose
            #   .gitattributes already pins *.yml to LF precisely so this cannot happen on the
            #   runner. Binary stdin removes the translation entirely.
            #
            # Both failures were the same error as the ones this repository keeps recording: a
            # check reporting failure that established nothing about the thing it claimed to
            # check, found only because the result was doubted and the cause established.
            body = script if script.lstrip().startswith("#!") else "#!/usr/bin/env bash\n" + script

            result = subprocess.run(
                ["bash", "-n"], input=body.encode("utf-8"), capture_output=True
            )
            if result.returncode == 0:
                print(f"  [ok]   {job_name}: {label}")
            else:
                failures += 1
                print(f"  [FAIL] {job_name}: {label}")
                print("         " + (result.stderr.decode("utf-8", "replace").strip() or "syntax error"))

    print()
    if failures:
        print(f"::error::{failures} of {checked} run: block(s) are not valid bash")
        return 1
    print(f"bash syntax gate: PASS ({checked} run: blocks parsed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
