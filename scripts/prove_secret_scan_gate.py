#!/usr/bin/env python3
"""Prove the CI secret scan can actually fail.

This is a claim about the STEP, not about the repository's secrets. It never scans this
repository and it never reports what a real finding was. It runs the committed scan command,
unmodified, against scratch repositories whose contents this script fully controls, and asserts
four things that can only all be true at once if the gate is real:

    1. a synthetic GitHub token makes it exit non-zero - the command is looking at all
    2. a credential-shaped value in the one field the allowlist excuses still makes it exit
       non-zero - the exception has not been widened to cover credentials
    3. the same repository without either value exits 0 - the gate discriminates
    4. the repository's own fixture-shaped values exit 0, which is what the allowlist is for

Properties 1 and 3 are what a reader cannot check by reading the config. Property 2 is the one
that constrains the allowlist: it is the failure mode that a value-shaped exception invites, and
it is invisible from the run list, because the widened exception leaves the real repository's scan
green. Property 4 is what catches the opposite failure: if `--config` were dropped from the step, or
the config file were renamed, the fixtures would start failing again and this script would report a
broken step rather than a clean scan.

The scan command is read from the committed workflow and only its volume source is rewritten, so
the flags under test are the ones CI actually runs. Anything this script cannot parse is a hard
failure rather than a fallback to a command of its own: a proof that quietly scans with different
flags proves nothing about the step.

Exit codes:
    0  every executed property held
    1  at least one property was violated
    2  the proof could not run (no docker, workflow unreadable, step unparseable)

Usage:
    python scripts/prove_secret_scan_gate.py
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

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CONFIG = ROOT / ".gitleaks.toml"

SANDBOX = Path(tempfile.gettempdir()) / "kilo" / "prove_secret_scan_gate"

# Two synthetic planted values, each shaped to a different rule, because they fail for different
# reasons and only one of them tests the allowlist.
#
# A GitHub personal access token: `ghp_` followed by 36 characters, which the default `github-pat`
# rule matches on shape alone. It belongs to nobody. It proves the committed command fails on a
# canonical secret shape at all.
#
# A credential-shaped value under `idempotency_key`, which is the field the repository's allowlist
# excuses. The default `generic-api-key` rule reports it - the keyword is in its list and the value
# has entropy - and it carries no hyphen, so the repository's exception, which requires a
# human-readable hyphenated fixture shape, does not apply. This is the value that tests the
# exception: widen the exception from a value shape to the field itself and this stops being
# reported, which is the failure the exception could cause and the only one a reader cannot check
# by reading the config.
PLANTED_TOKEN_LINE = '"idempotency_key": "ghp_0123456789abcdefghijABCDEFGHIJ012345",'
PLANTED_CREDENTIAL_LINE = '"idempotency_key": "x7Kd93mzQpL2vRt8YwZa5NcHb1JfUe6G",'

# The two shapes the repository's allowlist exists for, reproduced verbatim from the files that
# triggered it. If these ever start being reported again the allowlist has stopped applying, which
# is a broken step rather than a new finding.
FIXTURE_LINES = (
    '"idempotency_key": "order-place-trader-01-20260928-001",',
    "WHERE idempotency_key = 'idempotency-key-0001'",
    "audit evidence is queryable and integrity-checked, access is least-privilege, "
    "jurisdiction/venue eligibility is current",
)

COMMIT_ENV = {
    "GIT_AUTHOR_NAME": "prove_secret_scan_gate",
    "GIT_AUTHOR_EMAIL": "prove@example.invalid",
    "GIT_COMMITTER_NAME": "prove_secret_scan_gate",
    "GIT_COMMITTER_EMAIL": "prove@example.invalid",
}


@dataclass
class Outcome:
    """One executed scenario: what the scan did, and whether that was correct."""

    name: str
    passed: bool
    detail: str


def _step_script(job: dict, name: str) -> str:
    """The `run:` text of a named step, or raise if it is missing or is not a script."""
    for step in (job.get("steps") or []):
        if isinstance(step, dict) and step.get("name") == name:
            script = step.get("run")
            if isinstance(script, str) and script.strip():
                return script
    raise SystemExit(f"prove_secret_scan_gate: step {name!r} not found or has no run: block")


def _scan_argv(scan: str) -> list[str]:
    """The committed `docker run ...` invocation, as an argument list.

    Read out of the step rather than restated here, because restating it would let the proof
    certify a command CI does not run. Only the volume source is substituted afterwards; every
    flag, the image tag, and the subcommand come from the workflow.
    """
    joined = " ".join(line.rstrip().removesuffix("\\").strip() for line in scan.splitlines())
    try:
        tokens = shlex.split(joined)
    except ValueError as exc:
        raise SystemExit(f"prove_secret_scan_gate: the scan step does not tokenise: {exc}") from exc

    if not tokens or Path(tokens[0]).name.lower() not in {"docker", "docker.exe", "podman"}:
        raise SystemExit(
            f"prove_secret_scan_gate: the scan step does not start with a container runtime; it "
            f"starts with {tokens[0] if tokens else '<nothing>'!r}"
        )
    if len(tokens) < 2 or tokens[1] != "run":
        raise SystemExit(
            "prove_secret_scan_gate: the scan step is not a `docker run ...` invocation, so the "
            "command this proof would execute is not the one CI runs"
        )

    # The whole invocation, runtime included: the runtime is the program being executed, not an
    # argument to it, and dropping it would turn every scan below into "no such file".
    argv = list(tokens)
    volume = next((i for i, tok in enumerate(argv) if tok.endswith(":/repo")), None)
    if volume is None:
        raise SystemExit(
            "prove_secret_scan_gate: the scan step mounts nothing at /repo, so this proof cannot "
            "substitute a scratch repository for the one the step scans"
        )
    if "--exit-code" not in argv:
        raise SystemExit(
            "prove_secret_scan_gate: the scan step does not pass --exit-code, so gitleaks reports "
            "findings on stdout and exits 0; the gate could not fail on a finding"
        )
    if not any(tok.endswith("/.gitleaks.toml") for tok in argv):
        raise SystemExit(
            "prove_secret_scan_gate: the scan step does not pass the repository's .gitleaks.toml, "
            "so it runs a different scan than this repository declares"
        )
    return argv


def _scratch_dir(label: str) -> Path:
    """A fresh directory under the OS temp tree, created on demand.

    Never removed afterwards. Windows holds a previous container's or git process's handles on
    these paths past exit, so a shared sandbox the next scenario tries to delete fails with
    WinError 32 - a failure about the harness rather than about the gate. They live under the OS
    temp directory and are left to the OS, exactly as prove_vuln_scan_gate.py does.
    """
    SANDBOX.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=SANDBOX, prefix=f"{label}-"))


def _make_repo(label: str, lines: tuple[str, ...]) -> Path:
    """A scratch git repository with the scan's own config and one file carrying `lines`.

    A commit is required because the step scans history, not the working tree: a repository with no
    commit is not what CI scans, and a proof of the wrong thing is worse than no proof.
    """
    repo = _scratch_dir(label)
    shutil.copy2(CONFIG, repo / CONFIG.name)
    body = "\n".join(lines) + "\n"
    (repo / "fixture.txt").write_text(body, encoding="utf-8", newline="\n")

    env = {**os.environ, **COMMIT_ENV}
    for args in (
        ["git", "init", "--quiet", "--initial-branch=main"],
        ["git", "add", "--all"],
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "scratch"],
    ):
        done = subprocess.run(args, cwd=repo, env=env, capture_output=True)
        if done.returncode != 0:
            raise SystemExit(
                f"prove_secret_scan_gate: could not build the scratch repository "
                f"({' '.join(args)}): {done.stderr.decode('utf-8', 'replace')}"
            )
    return repo


def _run_scan(argv: list[str], repo: Path) -> subprocess.CompletedProcess[bytes]:
    """Run the committed scan command against `repo`, with only the volume source rewritten."""
    substituted = [f"{repo}:/repo" if tok.endswith(":/repo") else tok for tok in argv]
    return subprocess.run(substituted, cwd=repo, capture_output=True)


def _out(completed: subprocess.CompletedProcess[bytes]) -> str:
    return completed.stdout.decode("utf-8", "replace") + completed.stderr.decode("utf-8", "replace")


# --------------------------------------------------------------------------------------------
# Scenarios. Each builds its own repository, so none of them can pass on another's state.
# --------------------------------------------------------------------------------------------


def scenario_planted_token_fails(argv: list[str]) -> Outcome:
    """The committed command must fail on a canonical secret shape."""
    repo = _make_repo("token", (PLANTED_TOKEN_LINE,))
    result = _run_scan(argv, repo)
    if result.returncode == 0:
        return Outcome(
            "a planted token fails the scan",
            False,
            "a synthetic GitHub token was committed to a scratch repository and the committed scan "
            "still exited 0, so the scan is not looking and the real scan above cannot be trusted "
            "either",
        )
    if "leaks found" not in _out(result):
        return Outcome(
            "a planted token fails the scan",
            False,
            f"the scan exited {result.returncode} without reporting any leak, so it failed for "
            f"some other reason and the planted value may not be recognised:\n{_out(result)[-1500:]}",
        )
    return Outcome("a planted token fails the scan", True, f"exit {result.returncode}, leak reported")


def scenario_planted_credential_under_the_allowed_field_fails(argv: list[str]) -> Outcome:
    """A credential-shaped value in the exempted field must still be reported.

    This is the property that actually constrains the allowlist. The value is planted under
    `idempotency_key`, the one field `.gitleaks.toml` excuses, and it is shaped like a credential:
    32 mixed-case alphanumerics with no hyphen, which is exactly what the exception's value
    pattern excludes. If someone widens the exception to cover any value in that field - the
    obvious, convenient way to stop the fixtures from being reported - this value stops being
    reported with it, and this scenario fails while the scan over the real repository stays green.
    """
    repo = _make_repo("credential", (PLANTED_CREDENTIAL_LINE,))
    result = _run_scan(argv, repo)
    if result.returncode == 0:
        return Outcome(
            "a credential in the exempted field still fails the scan",
            False,
            "a credential-shaped value under idempotency_key was committed and the committed scan "
            "exited 0. The repository's allowlist exception now covers this value, which means it "
            "covers credentials in that field, and a real secret committed there would not be "
            "reported",
        )
    if "leaks found" not in _out(result):
        return Outcome(
            "a credential in the exempted field still fails the scan",
            False,
            f"the scan exited {result.returncode} without reporting any leak:\n{_out(result)[-1500:]}",
        )
    return Outcome(
        "a credential in the exempted field still fails the scan",
        True,
        f"exit {result.returncode}, leak reported",
    )


def scenario_clean_repository_passes(argv: list[str]) -> Outcome:
    """A repository with nothing in it must pass, so the gate discriminates rather than always fails."""
    repo = _make_repo("clean", ("an ordinary line of prose", 'name = "example"'))
    result = _run_scan(argv, repo)
    if result.returncode != 0:
        return Outcome(
            "a clean repository passes the scan",
            False,
            f"nothing secret was committed and the scan exited {result.returncode}:\n{_out(result)[-1500:]}",
        )
    return Outcome("a clean repository passes the scan", True, "exit 0")


def scenario_repository_fixtures_pass(argv: list[str]) -> Outcome:
    """The repository's own fixture shapes must stay allowed, which is what proves the config is used.

    This is the scenario that fails when `--config` is dropped from the step or the config file is
    renamed, because those fixtures are exactly what the allowlist excuses. A red scan on the real
    repository would look like a security problem; this names it as wiring.
    """
    repo = _make_repo("fixtures", FIXTURE_LINES)
    result = _run_scan(argv, repo)
    if result.returncode != 0:
        return Outcome(
            "the repository's own fixtures stay allowed",
            False,
            "values this repository's .gitleaks.toml is written to excuse were reported by the "
            "committed command, so the configuration is not reaching the scanner. That is a broken "
            f"step, not a new finding:\n{_out(result)[-1500:]}",
        )
    return Outcome("the repository's own fixtures stay allowed", True, "exit 0")


def main() -> int:
    if shutil.which("docker") is None:
        print("prove_secret_scan_gate: SKIP: no container runtime on PATH; the scan was not executed")
        return 2
    probe = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True
    )
    if probe.returncode != 0:
        print(
            "prove_secret_scan_gate: SKIP: the container runtime is on PATH but not answering "
            f"({probe.stderr.decode('utf-8', 'replace').strip()[:200]}); the scan was not executed"
        )
        return 2

    if not WORKFLOW.is_file():
        print(f"prove_secret_scan_gate: SKIP: {WORKFLOW} is not present")
        return 2
    if not CONFIG.is_file():
        print(
            f"prove_secret_scan_gate: {CONFIG} is not present, so the step's --config names a file "
            "that does not exist and the scan cannot be the one this repository declares"
        )
        return 2

    import yaml

    try:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"prove_secret_scan_gate: {WORKFLOW} does not parse: {exc}")
        return 2

    job = ((workflow.get("jobs") or {}).get("secret-scan")) or {}
    try:
        scan = _step_script(job, "scan repository history for secrets")
        argv = _scan_argv(scan)
    except SystemExit as exc:
        print(f"prove_secret_scan_gate: {exc}")
        return 2

    outcomes = [
        scenario_planted_token_fails(argv),
        scenario_planted_credential_under_the_allowed_field_fails(argv),
        scenario_clean_repository_passes(argv),
        scenario_repository_fixtures_pass(argv),
    ]

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
        print(f"::error::secret scan gate proof FAILED ({failures} of {len(outcomes)} properties)")
        return 1
    print(f"secret scan gate proof: PASS ({len(outcomes)} properties)")
    return 0


if __name__ == "__main__":
    sys.exit(main())