#!/usr/bin/env python3
"""Prove the CI Go vulnerability scan can actually fail.

This is not a claim about the real scanner's findings, and it never scans the repository's own
code for the properties under test. It is a claim about the STEP. A vulnerability gate can be
wired to govulncheck perfectly and still exit 0 when the scanner reports something, and no amount
of reading the workflow distinguishes those two cases. Only executing the committed step does.

The gate that failed here was worse than vacuous, which is why it survived review. The
dependency-scan job drove the scanner through `golang/govulncheck-action`, which runs
`govulncheck -C . <patterns>` at the checkout root. This repository has go.work at the root and no
root go.mod, so govulncheck refused to start with "no go.mod file" on every run and no Go code was
ever scanned. The step never produced a finding to review, so it never looked wrong; it only
looked like a job nobody was reading. EV-014 recorded it as configuration-only and never observed,
which is exactly the caveat a broken gate generates about itself.

What is executed is the `run:` block extracted from the committed workflow, unmodified, under bash,
with a fake govulncheck first on PATH. Nothing is reimplemented: if the block stops failing on a
finding, this fails.

Exit codes:
    0  every executed property held
    1  at least one property was violated, or the fake scanner never ran
    2  the proof could not run (no bash, workflow unreadable, step renamed)

Usage:
    python scripts/prove_vuln_scan_gate.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# The fake workspace the committed step is executed against. It is not the repository: the step
# calls `exit`, and running it against real modules would mean the proof shared state with the
# thing it is proving.
SANDBOX = Path(tempfile.gettempdir()) / "kilo" / "prove_vuln_scan_gate"

# The module list the fake scanner is given. Six, so a gate that accidentally hardcodes one module
# or scans only the first entry is distinguishable from one that iterates the whole list.
MODULES = (
    "contracts/go",
    "services/control-plane",
    "components/risk-engine",
    "components/oms",
    "components/reconciliation",
    "adapters/venues",
)

# govulncheck's exit code when it finds a reachable vulnerability. The fake uses the same value, so
# the step is proved against the real contract rather than against "some non-zero".
VULN_EXIT = 3

# govulncheck's exit code when it cannot run at all, which is what the broken configuration
# produced. Kept distinct from VULN_EXIT because conflating them would hide the original defect.
TOOL_ERROR_EXIT = 1


@dataclass
class Outcome:
    """One executed scenario: what the step did, and whether that was correct."""

    name: str
    passed: bool
    detail: str


def _step_script(job: dict, name: str) -> str:
    """The `run:` text of a named step, or raise if it is missing or is not a script.

    Raising rather than returning empty is deliberate. A workflow that renames a step must fail
    this proof loudly; if the lookup quietly yielded "", every scenario below would execute
    nothing and pass, which is the same class of defect this script exists to catch.
    """
    for step in (job.get("steps") or []):
        if isinstance(step, dict) and step.get("name") == name:
            script = step.get("run")
            if isinstance(script, str) and script.strip():
                return script
    raise SystemExit(f"prove_vuln_scan_gate: step {name!r} not found or has no run: block")


def _write_exec(path: Path, body: bytes) -> None:
    """Write a script and mark it executable, in BYTES.

    Byte mode is load-bearing, not stylistic. Text mode on Windows translates every "\\n" to
    "\\r\\n", which turns the shebang into `#!/usr/bin/env bash\\r`; the kernel then looks for a
    program literally named `bash\\r`, the shim silently never runs, and every scenario reports a
    scanner failure. The proof would then pass for entirely the wrong reason - the same CRLF trap
    check_workflow_bash.py documents, reintroduced through the back door. Each scenario
    independently asserts that the shim ran and how many times, so that failure is caught rather
    than believed.
    """
    path.write_bytes(body)
    path.chmod(0o755)


def _write_fake_scanner(bin_dir: Path, finding_module: str | None) -> None:
    """Install a fake govulncheck that records its argument list and optionally reports a finding.

    The module to report a finding for is BAKED INTO THE SCRIPT, not passed in an environment
    variable. Custom environment variables do not survive the Windows-to-Linux boundary when the
    bash on PATH is WSL: WSL translates PATH and a small set of well-known names and drops the
    rest, so a shim configured through the environment silently sees an empty variable, never
    reports its finding, and the scenarios that must fail report success. That was observed here
    while writing this script. A fixture that only works on a Linux runner is not a fixture.

    The `-C` value is located by scanning the arguments rather than by reading `$2`, so the fake
    stays honest if the step's flag order changes, and stops reporting a finding - loudly, as a
    scenario failure - if `-C` is dropped entirely.
    """
    if finding_module is None:
        body = (
            b"#!/usr/bin/env bash\n"
            b'echo "$*" >> scan.log\n'
            b"exit 0\n"
        )
    else:
        body = (
            b"#!/usr/bin/env bash\n"
            b'echo "$*" >> scan.log\n'
            b"want=\n"
            b'target=\n'
            b'for arg in "$@"; do\n'
            b'  if [ -n "$want" ]; then target="$arg"; break; fi\n'
            b'  if [ "$arg" = "-C" ]; then want=1; fi\n'
            b"done\n"
            b'if [ "$target" = "' + finding_module.encode("utf-8") + b'" ]; then\n'
            b'  echo "Vulnerability #1: GO-2026-0000 (test fixture)"\n'
            b"  exit " + str(VULN_EXIT).encode("ascii") + b"\n"
            b"fi\n"
            b"exit 0\n"
        )
    _write_exec(bin_dir / "govulncheck", body)


def _write_fake_go(bin_dir: Path, modules: tuple[str, ...]) -> None:
    """Install a fake `go` that answers `work edit -json` with a workspace listing.

    Only the resolve block shells out to `go work edit -json`. The payload is real JSON so the
    block's own jq filter is exercised rather than replaced; only the module list is fabricated.
    As with the scanner, the list is baked in rather than passed through the environment.
    """
    if modules:
        entries = ",".join('{"DiskPath":"%s"}' % m for m in modules)
    else:
        entries = ""
    body = (
        b"#!/usr/bin/env bash\n"
        b'if [ "$1" = "work" ] && [ "$2" = "edit" ]; then\n'
        b'  printf \'{"Use":[' + entries.encode("utf-8") + b"]}\\n\"\n"
        b"  exit 0\n"
        b"fi\n"
        b"exit 0\n"
    )
    _write_exec(bin_dir / "go", body)


def _build_sandbox(*, with_go: bool, modules: tuple[str, ...] = (), finding_module: str | None = None) -> tuple[Path, Path]:
    """A fake workspace: a bin directory holding the fakes, and a repo directory to run in.

    Each scenario gets its own numbered subdirectory and nothing is deleted afterwards. Windows
    holds the previous bash subprocess's working-directory handle open past the process's exit, so
    a shared sandbox the next scenario tries to remove fails with WinError 32 - a failure about the
    harness rather than about the gate. These directories live under the OS temp directory and are
    left to the OS.
    """
    SANDBOX.mkdir(parents=True, exist_ok=True)
    scenario_dir = Path(tempfile.mkdtemp(dir=SANDBOX, prefix="scenario-"))
    bin_dir = scenario_dir / "bin"
    repo = scenario_dir / "repo"
    bin_dir.mkdir()
    repo.mkdir()

    _write_fake_scanner(bin_dir, finding_module)
    if with_go:
        _write_fake_go(bin_dir, modules)
        for module in modules:
            (repo / module).mkdir(parents=True, exist_ok=True)
            (repo / module / "go.mod").write_text("module fixture\n", encoding="utf-8")
    _seed(repo, MODULES)
    return bin_dir, repo


def _seed(repo: Path, modules: tuple[str, ...]) -> None:
    """Write the module list the scan step iterates, and reset the shim's call log."""
    (repo / "modules.txt").write_text(
        "".join(f"{m}\n" for m in modules), encoding="utf-8", newline="\n"
    )
    log = repo / "scan.log"
    if log.exists():
        log.unlink()


def _run_bash(script: str, cwd: Path, extra_path: Path | None) -> subprocess.CompletedProcess[bytes]:
    """Run a `run:` block verbatim under bash, exactly as a runner would.

    The block is piped to `bash` on stdin as bytes rather than written to a file and named on the
    command line, for the reason check_workflow_bash.py documents: on a Windows host the bash on
    PATH is the WSL bash, which cannot read a `C:\\...` script path and eats the backslashes as
    escapes. Binary stdin removes both problems at once.
    """
    env = dict(os.environ)
    if extra_path is not None:
        env["PATH"] = str(extra_path) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", "-s"],
        input=script.encode("utf-8"),
        capture_output=True,
        cwd=cwd,
        env=env,
    )


def _scan_log(repo: Path) -> list[str]:
    """One line per fake-scanner invocation, as recorded by the shim itself.

    Read from the shim's own log rather than from anything this script remembers, so "the shim
    actually ran N times" is established by the shim rather than assumed by the harness.
    """
    log = repo / "scan.log"
    if not log.is_file():
        return []
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _out(completed: subprocess.CompletedProcess[bytes]) -> str:
    return completed.stdout.decode("utf-8", "replace") + completed.stderr.decode("utf-8", "replace")


# --------------------------------------------------------------------------------------------
# Scenarios against the scan step.
# --------------------------------------------------------------------------------------------


def scenario_clean(scan: str) -> Outcome:
    """Every module clean must exit 0, and each must have actually been scanned."""
    bin_dir, repo = _build_sandbox(with_go=False)
    result = _run_bash(scan, repo, bin_dir)
    calls = _scan_log(repo)

    if len(calls) != len(MODULES):
        return Outcome(
            "clean scan scans every module",
            False,
            f"expected {len(MODULES)} invocations, the shim recorded {len(calls)}: {calls}",
        )
    for module in MODULES:
        if not any(f"-C {module} " in call or call.endswith(f"-C {module}") for call in calls):
            return Outcome(
                "clean scan scans every module",
                False,
                f"no invocation carried -C {module}; calls were {calls}",
            )
    if result.returncode != 0:
        return Outcome(
            "clean scan scans every module",
            False,
            f"all modules were clean but the step exited {result.returncode}:\n{_out(result)[-1500:]}",
        )
    return Outcome("clean scan scans every module", True, f"{len(calls)} invocations, exit 0")


def scenario_finding_blocks(scan: str) -> Outcome:
    """A finding in one module must fail the step and must name that module."""
    affected = "components/oms"
    bin_dir, repo = _build_sandbox(with_go=False, finding_module=affected)
    result = _run_bash(scan, repo, bin_dir)
    calls = _scan_log(repo)
    text = _out(result)

    if len(calls) != len(MODULES):
        return Outcome(
            "a finding fails the step",
            False,
            f"expected {len(MODULES)} invocations, the shim recorded {len(calls)}: {calls}. If the "
            "shim did not run, this scenario is measuring the harness, not the gate.",
        )
    if result.returncode == 0:
        return Outcome(
            "a finding fails the step",
            False,
            f"the scanner reported a reachable vulnerability in {affected} and the step still "
            f"exited 0",
        )
    if affected not in text:
        return Outcome(
            "a finding fails the step",
            False,
            f"the step failed but never named the affected module:\n{text[-1500:]}",
        )
    return Outcome("a finding fails the step", True, f"exit {result.returncode}, affected module named")


def scenario_no_fail_fast(scan: str) -> Outcome:
    """A finding in the FIRST module must not stop the scan.

    This is the property that makes the step useful rather than merely correct. govulncheck exits 3
    on a finding, so a step written with `set -e` fails at the first bad module and an operator
    fixes them one CI run at a time. The step deliberately drops `-e` and aggregates; this asserts
    the aggregation reaches every module even when the first one has already failed.
    """
    bin_dir, repo = _build_sandbox(with_go=False, finding_module=MODULES[0])
    result = _run_bash(scan, repo, bin_dir)
    calls = _scan_log(repo)

    if len(calls) != len(MODULES):
        return Outcome(
            "a finding does not stop the scan",
            False,
            f"{MODULES[0]} failed but only {len(calls)} of {len(MODULES)} modules were scanned: {calls}",
        )
    if result.returncode == 0:
        return Outcome(
            "a finding does not stop the scan",
            False,
            "every module was scanned but the aggregated failure was lost and the step exited 0",
        )
    return Outcome(
        "a finding does not stop the scan",
        True,
        f"all {len(calls)} modules scanned, aggregated failure preserved",
    )


def scenario_tool_error_fails(scan: str) -> Outcome:
    """A scanner that cannot run must fail the step, not be read as a clean result.

    This is the original defect in its own shape. The broken configuration did not report a clean
    result; it exited 1 with "no go.mod file", and the failure stayed invisible anyway because the
    job was red for reasons nobody read. A step that tolerates a scanner failure is strictly worse
    than one that does not, because it converts a broken gate into a green one.
    """
    bin_dir, repo = _build_sandbox(with_go=False)
    _write_exec(
        bin_dir / "govulncheck",
        b"#!/usr/bin/env bash\n"
        b'echo "$*" >> scan.log\n'
        b'echo "govulncheck: no go.mod file" >&2\n'
        b"exit " + str(TOOL_ERROR_EXIT).encode("ascii") + b"\n",
    )
    result = _run_bash(scan, repo, bin_dir)
    calls = _scan_log(repo)

    if len(calls) != len(MODULES):
        return Outcome(
            "a scanner failure fails the step",
            False,
            f"expected {len(MODULES)} invocations, the shim recorded {len(calls)}",
        )
    if result.returncode == 0:
        return Outcome(
            "a scanner failure fails the step",
            False,
            "the scanner failed to run on every module and the step still exited 0",
        )
    return Outcome(
        "a scanner failure fails the step",
        True,
        f"exit {result.returncode} on a scanner that could not run",
    )


def scenario_empty_list_is_unguarded_by_the_scan_step(scan: str) -> Outcome:
    """Deliberately NOT a pass/fail property: it records what the scan step does with no modules.

    The scan step iterates modules.txt and carries no guard of its own, so an empty list exits 0
    having scanned nothing. That is why the RESOLVE step carries the empty-list refusal, and why
    this scenario is reported rather than asserted: if that refusal is ever deleted, this is the
    shape the combined gate degrades into, and it is worth seeing printed on every run.
    """
    bin_dir, repo = _build_sandbox(with_go=False)
    _seed(repo, ())
    result = _run_bash(scan, repo, bin_dir)
    calls = _scan_log(repo)
    return Outcome(
        "scan step over an empty module list (reported, not asserted)",
        True,
        f"exit {result.returncode}, {len(calls)} invocations - the resolve step's refusal is what "
        "keeps this from being a pass over nothing",
    )


# --------------------------------------------------------------------------------------------
# Scenarios against the resolve step. These need jq, because the block projects the module list
# with it. A missing jq is a runner configuration question, not a defect, so they are skipped and
# the skip is printed rather than hidden.
# --------------------------------------------------------------------------------------------


def scenario_resolve_lists_every_module(resolve: str) -> Outcome:
    bin_dir, repo = _build_sandbox(with_go=True, modules=MODULES)
    result = _run_bash(resolve, repo, bin_dir)
    listed_file = repo / "modules.txt"
    listed = (
        [line for line in listed_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if listed_file.is_file()
        else []
    )
    if result.returncode != 0:
        return Outcome(
            "resolve step lists every module",
            False,
            f"exit {result.returncode}:\n{_out(result)[-1500:]}",
        )
    if listed != list(MODULES):
        return Outcome("resolve step lists every module", False, f"modules.txt was {listed}")
    return Outcome("resolve step lists every module", True, f"{len(listed)} modules resolved")


def scenario_resolve_refuses_empty(resolve: str) -> Outcome:
    bin_dir, repo = _build_sandbox(with_go=True, modules=())
    result = _run_bash(resolve, repo, bin_dir)
    text = _out(result)
    if result.returncode == 0:
        return Outcome(
            "resolve step refuses an empty workspace",
            False,
            "go.work resolved to zero modules and the step exited 0, so the scan would pass over nothing",
        )
    if "empty scan" not in text:
        return Outcome(
            "resolve step refuses an empty workspace",
            False,
            f"the step failed but did not say the scan was empty:\n{text[-1500:]}",
        )
    return Outcome("resolve step refuses an empty workspace", True, f"exit {result.returncode}")


def scenario_resolve_refuses_missing_go_mod(resolve: str) -> Outcome:
    modules = ("contracts/go", "services/typo")
    bin_dir, repo = _build_sandbox(with_go=True, modules=modules)
    # `services/typo` is listed by the fake workspace but has no go.mod on disk.
    (repo / "services" / "typo").rmdir()
    result = _run_bash(resolve, repo, bin_dir)
    text = _out(result)
    if result.returncode == 0:
        return Outcome(
            "resolve step refuses a module with no go.mod",
            False,
            "go.work listed a module with no go.mod and the step exited 0, so govulncheck would "
            "fail later with a message that names no module",
        )
    if "services/typo" not in text:
        return Outcome(
            "resolve step refuses a module with no go.mod",
            False,
            f"the step failed but did not name the missing module:\n{text[-1500:]}",
        )
    return Outcome("resolve step refuses a module with no go.mod", True, f"exit {result.returncode}")


# --------------------------------------------------------------------------------------------
# The real tool's workspace constraint, on the real repository.
# --------------------------------------------------------------------------------------------


def scenario_real_scanner(repo_tool: str) -> Outcome:
    """The premise the whole gate rests on, checked against the real scanner and the real tree.

    If govulncheck ever learned to resolve a workspace, the per-module loop would become
    unnecessary and this assertion would fail loudly rather than leaving a redundant structure in
    place nobody can explain. It is also the only check here that touches the repository's own
    modules, and it asserts the opposite of what a reader might assume: at the root the scanner
    REFUSES to run.
    """
    if (ROOT / "go.mod").exists():
        return Outcome(
            "real govulncheck refuses the repository root",
            False,
            "a root go.mod now exists, so this proof's premise is stale; revisit whether the "
            "per-module scan is still the right structure",
        )

    at_root = subprocess.run(
        [repo_tool, "-C", ".", "-format", "text", "./..."],
        capture_output=True,
        cwd=ROOT,
    )
    root_text = at_root.stdout.decode("utf-8", "replace") + at_root.stderr.decode("utf-8", "replace")
    if at_root.returncode == 0 or "no go.mod file" not in root_text:
        return Outcome(
            "real govulncheck refuses the repository root",
            False,
            "expected the root invocation to fail with 'no go.mod file'; it exited "
            f"{at_root.returncode}:\n{root_text[-1500:]}",
        )

    inside = subprocess.run(
        [repo_tool, "-C", "services/control-plane", "-format", "text", "./..."],
        capture_output=True,
        cwd=ROOT,
    )
    if inside.returncode != 0:
        return Outcome(
            "real govulncheck refuses the repository root",
            False,
            "the root invocation is refused as expected, but the per-module invocation failed, so "
            "the scan this gate replaced could not run either:\n"
            + (inside.stdout.decode("utf-8", "replace") + inside.stderr.decode("utf-8", "replace"))[-1500:],
        )
    return Outcome(
        "real govulncheck refuses the repository root",
        True,
        "root invocation refused with 'no go.mod file'; per-module invocation exited 0",
    )


def main() -> int:
    if shutil.which("bash") is None:
        print("prove_vuln_scan_gate: SKIP: no bash on PATH; the scan step was not executed")
        return 2

    if not WORKFLOW.is_file():
        print(f"prove_vuln_scan_gate: SKIP: {WORKFLOW} is not present")
        return 2

    try:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"prove_vuln_scan_gate: {WORKFLOW} does not parse: {exc}")
        return 2

    job = ((workflow.get("jobs") or {}).get("dependency-scan")) or {}
    try:
        scan = _step_script(job, "go vulnerability scan")
        resolve = _step_script(job, "resolve Go modules for scanning")
    except SystemExit as exc:
        print(f"prove_vuln_scan_gate: {exc}")
        return 2

    # Resolved before any sandbox PATH is built, so the real tool is never shadowed by a fake.
    repo_tool = shutil.which("govulncheck")
    has_jq = shutil.which("jq") is not None

    outcomes: list[Outcome] = [
        scenario_clean(scan),
        scenario_finding_blocks(scan),
        scenario_no_fail_fast(scan),
        scenario_tool_error_fails(scan),
        scenario_empty_list_is_unguarded_by_the_scan_step(scan),
    ]

    if has_jq:
        outcomes += [
            scenario_resolve_lists_every_module(resolve),
            scenario_resolve_refuses_empty(resolve),
            scenario_resolve_refuses_missing_go_mod(resolve),
        ]
    else:
        print("  [SKIP] resolve-step scenarios: no jq on PATH, so the block's own filter was not executed")

    if repo_tool:
        outcomes.append(scenario_real_scanner(repo_tool))
    else:
        print("  [SKIP] real-scanner scenario: govulncheck is not installed on this host")

    failures = 0
    print()
    for outcome in outcomes:
        if outcome.passed:
            print(f"  [ok]   {outcome.name}: {outcome.detail}")
        else:
            failures += 1
            print(f"  [FAIL] {outcome.name}: {outcome.detail}")

    print()
    if failures:
        print(
            f"::error::vulnerability scan gate proof FAILED ({failures} of {len(outcomes)} properties)"
        )
        return 1
    print(f"vulnerability scan gate proof: PASS ({len(outcomes)} properties)")
    return 0


if __name__ == "__main__":
    sys.exit(main())