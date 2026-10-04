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

The gate refuses to pass when it finds nothing. A workflow whose jobs were emptied, whose steps
were renamed to `uses`, or which was edited into a mapping with no `run:` key at all, would
otherwise produce "PASS (0 run: blocks parsed)" - a green check that had examined nothing, and
therefore a green check that could not have found the syntax error it exists to find. The pytest
twin in tests/ci/test_ci_workflow.py already refused that case; this did not, which meant the
standalone CI step only failed closed as long as a sibling step happened to run first. Both now
take the rule from VACUITY below, so the two copies cannot drift apart on the one thing that
matters.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# The non-vacuity rule, as a constant, because it now has two callers: this script and the pytest
# twin. It is not restated in either. The twin used to carry its own copy of this assertion, and
# two copies of a rule is one more edit than it takes for them to disagree about whether an empty
# workflow is a failure - at which point the standalone CI step is green for having read nothing.
VACUITY = "no run: blocks were found; the check is not examining anything"

# Bounded so a wedged launcher is reported rather than hanging the gate. A syntax check of a CI step
# is not slow work; anything near this limit means bash is not answering, not that the block is long.
BASH_TIMEOUT_SECONDS = 60

# How long to wait before each re-attempt, and therefore how many re-attempts there are. A tuple of
# delays rather than a retry count, so the bound is visible as the thing it is - a schedule - and so
# the wait grows while the number of attempts stays small. Total worst-case added latency for a
# single block is the sum of these, and it is only ever spent when bash has already failed to answer.
#
# One retry was not enough, and the evidence is specific: the full tests/ci battery failed twice on
# this gate with 2 of 54 blocks reporting a silent non-zero, having exhausted a single retry on the
# same block, while the same 54 blocks passed 8 of 8 invocations taken one at a time on the same
# tree with no other load. The gate makes one launcher invocation per block, so it asks the Windows
# WSL launcher to start 54 times in a row, and under load the launcher intermittently fails to start
# more than twice in a row. A single retry turned a property of the host into a red test suite, which
# is the same defect as blaming the workflow: a host condition being reported as a finding. The
# depth is what removes it; the bound is what keeps the removal honest, because if bash cannot be run
# at all the gate must still fail and still must not claim to have checked anything.
LAUNCHER_RETRY_DELAYS_SECONDS = (0.2, 0.6, 1.5)


@dataclass(frozen=True)
class RunBlock:
    """One `run:` step, with enough context to name it in a failure message."""

    job: str
    label: str
    script: str


def collect_run_blocks(workflow: object) -> list[RunBlock]:
    """Every non-empty `run:` block in a parsed workflow, in file order.

    This is the single definition of what this gate examines, and it lives here rather than in
    both callers because the two are copies of one check: the pytest twin exists because a
    workflow GitHub cannot parse does not run its own CI step, so the same parse has to happen
    before the push as well as in it. Duplicated, the two would drift, and the drift that matters
    is in the non-vacuity guard in main() rather than in this loop.

    Anything that is not the expected shape - a workflow that parses to a list, a job that is not
    a mapping, a step with no script - yields no blocks rather than raising. That is deliberate:
    this function's job is to describe what there is to check, and a shape it cannot read is a
    shape whose emptiness the caller must be able to see rather than crash on.
    """
    if not isinstance(workflow, dict):
        return []

    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []

    blocks: list[RunBlock] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            script = step.get("run")
            if not isinstance(script, str) or not script.strip():
                continue
            label = step.get("name") or step.get("uses") or "(unnamed step)"
            blocks.append(RunBlock(job=str(job_name), label=str(label), script=script))
    return blocks


def bash_syntax_check(script: str) -> subprocess.CompletedProcess[bytes]:
    """`bash -n` over one block, without executing any of it.

    The script is piped to bash on stdin as bytes rather than as text, and rather than written to
    a temp file. Both of those details are load-bearing, and both were wrong in the first version
    of this check:

      A temp path is wrong on Windows, because the bash on PATH is the WSL bash, which cannot see
      a C:\\... path and reads the backslashes as escapes. Every block then failed with "No such
      file or directory" and the gate reported a broken workflow when the workflow was fine.

      A text-mode pipe is wrong on Windows for the opposite reason: Python translates "\\n" to
      "\\r\\n" on the way in, so bash receives carriage returns that it reads as part of the
      command. That produced nine phantom syntax errors - `done < modules.txt` and a stray $'\\r'
      - for a workflow whose run: blocks are all valid, and whose .gitattributes already pins
      *.yml to LF precisely so this cannot happen on the runner. Binary stdin removes the
      translation entirely.

    Both failures were the same error as the ones this repository keeps recording: a check
    reporting failure that established nothing about the thing it claimed to check, found only
    because the result was doubted and the cause established.
    """
    body = script if script.lstrip().startswith("#!") else "#!/usr/bin/env bash\n" + script
    payload = body.encode("utf-8")

    # A `bash -n` that reports a syntax error always writes to stderr, so stderr is the discriminator
    # between "this block is malformed" and "bash did not run". On Windows `bash` on PATH is the WSL
    # launcher, and under load it intermittently fails to start: non-zero exit, empty stderr, no
    # diagnostic. That is the launcher failing, not the workflow, and reporting it as a malformed
    # workflow asserts something about the workflow that was never established - which is the same
    # error this function already made twice, in a new disguise. So an empty-stderr failure is
    # retried, on the schedule in LAUNCHER_RETRY_DELAYS_SECONDS, before it is believed.
    #
    # The retry is keyed on the empty stderr and not on the exit code. A result carrying a diagnostic
    # is a verdict about a real block, and re-running it could only discard that verdict - turning a
    # genuine syntax error into a pass, which inverts the one signal that matters. So a diagnostic ends
    # the ladder immediately, and only silence buys another attempt.
    #
    # The gate still fails if bash cannot be run at all: it fails on the observation, with a message
    # that names the cause, rather than passing or blaming the workflow. A timeout is reported the
    # same way - as a non-zero with nothing on stderr - so a wedged launcher produces the honest
    # message instead of a traceback, and neither attempt can raise out of here. A timeout ends the
    # ladder rather than consuming it: bash declining to answer once is an answer, and spending three
    # more minutes of host time to be told the same thing is not resilience, it is delay.
    def attempt() -> subprocess.CompletedProcess[bytes] | None:
        try:
            return subprocess.run(
                ["bash", "-n"], input=payload, capture_output=True, timeout=BASH_TIMEOUT_SECONDS
            )
        except subprocess.TimeoutExpired:
            return None

    result = attempt()
    if result is None:
        return subprocess.CompletedProcess(["bash", "-n"], 124, b"", b"")

    for delay in LAUNCHER_RETRY_DELAYS_SECONDS:
        if result.returncode == 0 or result.stderr.strip():
            break
        time.sleep(delay)
        retry = attempt()
        if retry is None:
            return subprocess.CompletedProcess(["bash", "-n"], 124, b"", b"")
        result = retry
    return result


def main() -> int:
    if shutil.which("bash") is None:
        print("SKIP: no bash on PATH; the runner scripts were not syntax-checked")
        return 0

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    blocks = collect_run_blocks(workflow)
    # Refused before any block is parsed, so this is not reachable by a syntax error being counted
    # as the failure. A gate that finds nothing has not verified that the workflow's bash is valid;
    # it has verified that it could not look, and saying PASS would turn the difference invisible.
    if not blocks:
        print(f"::error::{VACUITY}")
        print(f"::error::{WORKFLOW} parsed but yielded no run: blocks, so no bash was checked; "
              "failing rather than passing vacuously")
        return 1

    failures = 0
    unchecked = 0

    for block in blocks:
        result = bash_syntax_check(block.script)
        if result.returncode == 0:
            print(f"  [ok]   {block.job}: {block.label}")
            continue
        failures += 1
        detail = result.stderr.decode("utf-8", "replace").strip()
        if not detail:
            # Non-zero with nothing on stderr means bash never parsed the block, so this run
            # established nothing about whether the block is valid. Saying otherwise would blame the
            # workflow for the host's launcher, and a re-run is how a team learns to ignore the gate.
            unchecked += 1
            print(f"  [FAIL] {block.job}: {block.label}")
            print(f"         bash exited non-zero without a diagnostic on all "
                  f"{1 + len(LAUNCHER_RETRY_DELAYS_SECONDS)} attempts: bash could not be run, "
                  "so this block was NOT checked. This is a host failure, not a workflow defect.")
            continue
        print(f"  [FAIL] {block.job}: {block.label}")
        print("         " + detail)

    print()
    if failures:
        if unchecked:
            print(f"::error::{failures} of {len(blocks)} run: block(s) failed, and {unchecked} of them "
                  "were not checked at all because bash could not be run. A host failure is not "
                  "evidence about the workflow.")
        else:
            print(f"::error::{failures} of {len(blocks)} run: block(s) are not valid bash")
        return 1
    print(f"bash syntax gate: PASS ({len(blocks)} run: blocks parsed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
