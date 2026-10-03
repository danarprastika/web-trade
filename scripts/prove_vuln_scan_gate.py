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
import shlex
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

# Things a scenario observed that must reach the reader but are not failures of the step under
# test. Collected at module scope so a scenario can raise one without threading a return value
# through main(), and printed under a [WARN] marker rather than [ok]: a warning that looks like a
# pass is the confusion this repository has recorded three times.
WARNINGS: list[str] = []


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
    #
    # The printf line was quoted wrongly and the shim never parsed. It emitted
    #   printf '{"Use":[...]}\n"
    # with the single quote opened and never closed and a stray double quote at the end, so bash
    # aborted the shim with "unexpected EOF while looking for matching `''" and every one of the
    # three resolve scenarios failed on the fake rather than on the step. It went unnoticed for
    # the same reason as the rmdir defect above: the scenarios are skipped wherever jq is absent,
    # and on the one host where jq is present the script's own stdout interleaved the parse error
    # with "jq: command not found", which reads as a missing tool. A fixture that has never run is
    # not a fixture, so the payload below is emitted as a single correctly closed quoted string.
    body = (
        b"#!/usr/bin/env bash\n"
        b'if [ "$1" = "work" ] && [ "$2" = "edit" ]; then\n'
        b"  printf '{\"Use\":[" + entries.encode("utf-8") + b"]}\\n'\n"
        b"  exit 0\n"
        b"fi\n"
        b"exit 0\n"
    )
    _write_exec(bin_dir / "go", body)
    # Asserted rather than trusted. This shim is the entire input to three scenarios, and the
    # defect it carried was invisible precisely because nothing checked that it parsed. Fed to
    # bash on stdin, not named on the command line, for the reason _run_bash documents: the bash
    # reachable from a Windows path cannot read a `C:\...` script argument and eats the
    # backslashes.
    parsed = subprocess.run(
        ["bash", "-s", "work", "edit", "-json"],
        input=(bin_dir / "go").read_bytes(),
        capture_output=True,
    )
    if parsed.returncode != 0 or b'"Use"' not in parsed.stdout:
        raise SystemExit(
            "prove_vuln_scan_gate: the fake `go` shim does not answer `work edit -json` "
            f"(exit {parsed.returncode}): {parsed.stderr.decode('utf-8', 'replace')}"
        )


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
# Can the executed step run jq? Measured inside bash, because that is the shell the step runs in.
# --------------------------------------------------------------------------------------------


def _bash_tool_path(tool: str) -> str | None:
    """The path bash itself resolves `tool` to, or None if bash cannot run it.

    Deliberately not `shutil.which`. That answers "can Python start it", which is a different
    question from "can the committed block start it", and on this host the two disagree in a way
    that inverts the verdict. Python finds `jq.exe`, so the resolve scenarios used to run, and then
    the block's own `jq` call died with 127 because the bash on PATH is the WSL bash and it
    resolves extensionless names only. The scenarios then reported a gate defect where the honest
    verdict was "this host cannot execute the step's own filter". The skip is real coverage and it
    has to be decided in the step's environment, not in the harness's.
    """
    probe = subprocess.run(
        ["bash", "-c", f"command -v {shlex.quote(tool)}"], capture_output=True
    )
    if probe.returncode != 0:
        return None
    found = probe.stdout.decode("utf-8", "replace").strip()
    return found or None


def _bash_can_run(command: str) -> bool:
    """Whether bash can execute `command`, asked with its `--version` rather than by inspection.

    A path that exists is not a path that runs. Windows binaries are executable under WSL
    interop, and a jq installed this way reports its version, so the probe is the real question.

    The command is interpolated into the script rather than passed as `"$1"`. The bash reached
    through the Windows path is the WSL launcher, and it does not hand positional parameters to
    `-c` in a way that survives this call - a probe written that way reports every binary as
    unrunnable, which would have silently downgraded all three resolve scenarios to a skip again.
    """
    probe = subprocess.run(
        ["bash", "-c", f"{shlex.quote(command)} --version"], capture_output=True
    )
    return probe.returncode == 0


def _wsl_candidates(windows_path: str) -> list[str]:
    """Every WSL spelling of a Windows path worth trying, most likely first.

    The extension case is not cosmetic. `shutil.which("jq")` builds its candidate from PATHEXT
    and hands back `jq.EXE`, and the Windows filesystem opens that without complaint while the
    WSL interop launch of the same path fails. The lowercase spelling is the one that runs, so
    both are tried rather than the first one being assumed.
    """
    drive, sep, rest = windows_path.partition(":")
    if not sep or len(drive) != 1 or not rest.startswith("\\"):
        return [windows_path]
    root = f"/mnt/{drive.lower()}"
    head, dot, ext = rest.rpartition(".")
    spellings = [rest]
    if dot and head:
        spellings += [f"{head}.exe", f"{head}.EXE"]
    return [root + spelling.replace("\\", "/") for spelling in dict.fromkeys(spellings)]


def _jq_executable() -> str | None:
    """An absolute path the step's own shell can launch jq from, or None if this host has none."""
    for name in ("jq.exe", "jq"):
        host = shutil.which(name)
        if host is None:
            continue
        targets = _wsl_candidates(host) if os.name == "nt" else [host]
        for target in targets:
            if _bash_can_run(target):
                return target
    return None


def _jq_reachable() -> bool:
    """Whether the resolve scenarios can execute at all on this host.

    True when bash resolves `jq` directly (a Linux runner, which is the environment these
    scenarios are for), or when the host has a jq that bash can still launch by absolute path.
    """
    return _bash_tool_path("jq") is not None or _jq_executable() is not None


def _ensure_jq(bin_dir: Path) -> bool:
    """Give the executed block a `jq` it can run. Returns False only if this host has none.

    Nothing is installed when bash already resolves `jq`, so on a runner the block runs against
    the real jq exactly as committed. Otherwise a launcher goes into the sandbox bin dir - which
    the scenario already puts first on PATH - that execs the real binary under the name the block
    calls. That is not a fake: the block's own filter is still evaluated by jq, and the launcher
    adds no logic of its own. It exists because the alternative is three scenarios that never run
    on a developer's machine, which is precisely how the two defects fixed in this file survived.
    """
    if _bash_tool_path("jq") is not None:
        return True
    target = _jq_executable()
    if target is None:
        return False
    # The CR filter is a host adaptation, and it is narrow on purpose. A native jq.exe writes
    # CRLF on stdout, which inside this WSL bash arrives as a trailing \r on every path, so
    # `while read -r m` yields "contracts/go\r" and the step's own `-f "$m/go.mod"` test fails on
    # every module - a failure about this host's line endings reported as a failure about the
    # gate. On the runner these scenarios exist for, jq writes LF and `tr -d '\r'` is a no-op.
    # Nothing else is filtered, the block's own filter still runs, and the bytes the block reads
    # are the bytes it would read on Linux.
    launcher = f'#!/usr/bin/env bash\n"{target}" "$@" | tr -d "\\r"\n'
    _write_exec(bin_dir / "jq", launcher.encode("utf-8"))
    return True


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

    This is the property that makes the step useful rather than merely correct, and it comes from
    the aggregation rather than from the absence of errexit. The `|| rc=$?` branch already
    suppresses errexit for the scanner, so restoring `set -e` would change nothing here - which the
    comment in the workflow says, because an earlier version of it claimed the opposite. What the
    aggregation buys is that a failure is recorded and the loop continues, so an operator sees
    every affected module in one run instead of fixing them one CI run at a time.
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


def scenario_missing_module_list_fails(scan: str) -> Outcome:
    """No modules.txt at all must fail the step.

    This is the hole review found in the step as first written, and it is worth keeping a
    dedicated scenario for rather than folding into the empty-list case. `done < modules.txt` with
    no such file fails its redirect; with errexit not yet present the loop body simply never ran,
    `status` stayed 0, and the step exited 0 having scanned nothing. That is the exact defect class
    this script exists to eliminate, reintroduced one layer up, and it was unreachable only
    because the resolve step happened to run first in the same directory - the same invisibility as
    the original bug with one step removed.
    """
    bin_dir, repo = _build_sandbox(with_go=False)
    (repo / "modules.txt").unlink()
    result = _run_bash(scan, repo, bin_dir)
    calls = _scan_log(repo)
    text = _out(result)

    if result.returncode == 0:
        return Outcome(
            "a missing module list fails the step",
            False,
            f"modules.txt does not exist and the step still exited 0 after {len(calls)} "
            "invocations: a vulnerability gate reported success having scanned nothing",
        )
    if "refusing to report a clean scan" not in text:
        return Outcome(
            "a missing module list fails the step",
            False,
            f"the step failed but did not say it was refusing to scan nothing:\n{text[-1500:]}",
        )
    return Outcome(
        "a missing module list fails the step",
        True,
        f"exit {result.returncode}, {len(calls)} invocations",
    )


def scenario_empty_module_list_fails(scan: str) -> Outcome:
    """An EMPTY module list must fail the step, and this asserts it rather than reporting it.

    This scenario used to be the opposite: it asserted nothing, and its docstring claimed the scan
    step had no empty-list guard of its own. That stopped being true when the `[ ! -s modules.txt ]`
    guard was added, and a stale claim in a comment is not a smaller problem than the one it
    describes - it told a reader that the empty case was uncovered when the coverage was the whole
    point of the line above it.

    It is asserted now, and it is a distinct property from the missing-file case for a specific
    reason: `! -s` refuses an empty file as well as a missing one, but `! -e` would accept a
    zero-byte file. A guard weakened from `-s` to `-e` still catches a missing modules.txt, so the
    scenario above would keep passing, and the empty case - go.work resolving to zero modules, which
    is the same pass-over-nothing - would go back to exiting 0 with nothing asserting it. Only a
    scenario that seeds an empty file can tell those two apart.
    """
    bin_dir, repo = _build_sandbox(with_go=False)
    _seed(repo, ())
    result = _run_bash(scan, repo, bin_dir)
    calls = _scan_log(repo)
    text = _out(result)

    if result.returncode == 0:
        return Outcome(
            "an empty module list fails the step",
            False,
            f"modules.txt is zero bytes and the step still exited 0 after {len(calls)} "
            "invocations: a vulnerability gate reported success having scanned nothing. This is "
            "what the guard degrades to if `[ ! -s ]` becomes `[ ! -e ]`",
        )
    if "refusing to report a clean scan" not in text:
        return Outcome(
            "an empty module list fails the step",
            False,
            f"the step failed but did not say it was refusing to scan nothing:\n{text[-1500:]}",
        )
    return Outcome(
        "an empty module list fails the step",
        True,
        f"exit {result.returncode}, {len(calls)} invocations",
    )


# --------------------------------------------------------------------------------------------
# Scenarios against the resolve step. These need jq, because the block projects the module list
# with it. A missing jq is a runner configuration question, not a defect, so they are skipped and
# the skip is printed rather than hidden.
# --------------------------------------------------------------------------------------------


def scenario_resolve_lists_every_module(resolve: str) -> Outcome:
    bin_dir, repo = _build_sandbox(with_go=True, modules=MODULES)
    if not _ensure_jq(bin_dir):
        return Outcome(
            "resolve step lists every module",
            False,
            "HARNESS failure, not a gate failure: main() decided jq was reachable and this "
            "scenario could not provide it, so nothing about the step was executed",
        )
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
    if not _ensure_jq(bin_dir):
        return Outcome(
            "resolve step refuses an empty workspace",
            False,
            "HARNESS failure, not a gate failure: jq was unreachable inside the step's shell, so "
            "the step's own filter was never executed",
        )
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
    if not _ensure_jq(bin_dir):
        return Outcome(
            "resolve step refuses a module with no go.mod",
            False,
            "HARNESS failure, not a gate failure: jq was unreachable inside the step's shell, so "
            "the step's own filter was never executed",
        )
    # `services/typo` is listed by the fake workspace but does not exist on disk, which is what a
    # typo in go.work looks like and what the resolve step's `-f "$m/go.mod"` test refuses.
    #
    # It is removed recursively rather than with rmdir. The first version of this line called
    # rmdir() on a directory _build_sandbox had just populated with a go.mod, which raised
    # WinError 145 on any platform where rmdir refuses a non-empty directory. That exception
    # escaped main() as a traceback, so this scenario has never actually run: it is skipped
    # wherever jq is absent, and on the Ubuntu runner - the one place jq is present - it raised
    # instead of reporting. The dependency-scan job has been red on this step since the scenario
    # was introduced, and the traceback named no property, so the failure read as a broken script
    # rather than as a broken scenario. Confirmed against the runner's own step list before this
    # was fixed.
    shutil.rmtree(repo / "services" / "typo")
    assert not (repo / "services" / "typo").exists(), (
        "fixture drift: the missing-module directory still exists, so this scenario would be "
        "asserting the sandbox rather than the step"
    )
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
    inside_text = inside.stdout.decode("utf-8", "replace") + inside.stderr.decode("utf-8", "replace")
    if inside.returncode == VULN_EXIT:
        # govulncheck's exit code for a reachable vulnerability. Failing this scenario on it would
        # be the wrong verdict: the property under test is that the scanner RUNS, and a finding is
        # proof that it did, not evidence of a broken harness. The scan step above is what blocks
        # on a finding, and it has already run by the time this scenario executes.
        #
        # What is not acceptable is reporting it as a plain green line. The first version of this
        # branch did exactly that - `[ok] ... reported a reachable vulnerability` with the
        # scanner's own output discarded - which makes a security finding look like a passing
        # checkmark. That is the confusion this repository has now recorded three times (EV-064,
        # EV-065, WI-175): a green marker on a line whose text says something went wrong. So the
        # property still passes, the finding is raised as a WARN with the scanner's text quoted,
        # and nothing about it is dropped.
        WARNINGS.append(
            "govulncheck reports a REACHABLE VULNERABILITY in services/control-plane at this "
            "commit (exit 3). The property below only asserts that the scanner runs, so it still "
            f"passes, but the finding itself is not swallowed:\n{inside_text[-1500:].strip()}"
        )
        return Outcome(
            "real govulncheck refuses the repository root",
            True,
            "root invocation refused with 'no go.mod file'; per-module invocation ran and reported "
            "a reachable vulnerability (exit 3) - see the WARN above, and note the scan step itself "
            "blocks on this",
        )
    if inside.returncode != 0:
        return Outcome(
            "real govulncheck refuses the repository root",
            False,
            "the root invocation is refused as expected, but the per-module invocation failed in a "
            "way that is not a reported finding, so the scan this gate replaced could not run "
            f"either (exit {inside.returncode}):\n{inside_text[-1500:]}",
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
    # Measured inside bash, not on the host PATH, because bash is what executes the step. See
    # _jq_reachable for why getting this wrong inverts the verdict rather than merely coarsening it.
    has_jq = _jq_reachable()

    outcomes: list[Outcome] = [
        scenario_clean(scan),
        scenario_finding_blocks(scan),
        scenario_no_fail_fast(scan),
        scenario_tool_error_fails(scan),
        scenario_missing_module_list_fails(scan),
        scenario_empty_module_list_fails(scan),
    ]

    if has_jq:
        outcomes += [
            scenario_resolve_lists_every_module(resolve),
            scenario_resolve_refuses_empty(resolve),
            scenario_resolve_refuses_missing_go_mod(resolve),
        ]
    else:
        print(
            "  [SKIP] resolve-step scenarios: bash on this host cannot run jq, so the block's own\n"
            "         filter was not executed. This is real coverage that did not happen; on a\n"
            "         runner with jq installed all three run and all three assert."
        )

    if repo_tool:
        outcomes.append(scenario_real_scanner(repo_tool))
    else:
        print("  [SKIP] real-scanner scenario: govulncheck is not installed on this host")

    failures = 0
    print()
    # Warnings are printed under their own marker, never under [ok]. A green line whose text says a
    # reachable vulnerability was found is exactly the confusion this repository has recorded three
    # times - EV-064, EV-065 and WI-175 - and this script is the one built to catch it, so the
    # reporting shape is held to the same standard as the behaviour it reports on.
    for warning in WARNINGS:
        print(f"  [WARN] {warning}")
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
