#!/usr/bin/env python3
"""Prove the CI secret scan can actually fail, and that this repository passes it.

Most of this is a claim about the STEP rather than about the repository's secrets. It runs the
committed scan command, unmodified, against scratch repositories whose contents this script fully
controls, and asserts four things that can only all be true at once if the gate is real:

    1. a synthetic GitHub token makes it exit non-zero - the command is looking at all
    2. a credential-shaped value in the one field the allowlist excuses still makes it exit
       non-zero - the exception has not been widened to cover credentials
    3. the same repository without either value exits 0 - the gate discriminates
    4. the repository's own fixture-shaped values exit 0, which is what the allowlist is for

and then one that is a claim about THIS repository:

    5. scanning this repository's own committed history exits 0

Property 5 was added because properties 1 to 4 could not catch the thing that actually happened
here, twice. Both times a whole GitHub-token-shaped string was written into this repository's own
source while testing this scan, and both times the scan of full history went red - in commits that
had already been pushed. Every other property here passes in a tree where that has happened, because
they all scan scratch repositories this script builds and controls. A proof that cannot observe the
repository it ships in cannot notice a secret committed to it.

That gap was not hypothetical. `gitleaks detect` scans committed history, so the scan run before a
commit cannot see what is about to be committed, and the scan run after it is a red CI job whose log
nobody here can read: gh is installed and unauthenticated for this repository. Two commits, 25bf81f
and 5d84f14, are in history because of it.

Properties 1 and 3 are what a reader cannot check by reading the config. Property 2 is the one
that constrains the allowlist: it is the failure mode that a value-shaped exception invites, and
it is invisible from the run list, because the widened exception leaves the real repository's scan
green. Property 4 is what catches the opposite failure: if `--config` were dropped from the step, or
the config file were renamed, the fixtures would start failing again and this script would report a
broken step rather than a clean scan. Property 5 is what makes a secret committed to this repository
a failing command rather than a red job nobody reads.

Property 5 scans the working tree's history as committed, so an uncommitted secret is still invisible
to it until committed - which is inherent to scanning history, and is why property 5 is run in CI on
the pushed commit rather than only locally.

The scan command is read from the committed workflow. Properties 1 to 4 rewrite only its volume
source, so the flags under test are the ones CI actually runs; property 5 rewrites nothing but the
shell's own `$PWD`, because for that one the volume source is the thing under test. Anything this
script cannot parse is a hard
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
import re
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

# The scan over this repository's history takes a couple of seconds. The bound is generous, because
# its job is to turn a hung scan into a reported harness failure rather than a hung proof - the CI
# job's own timeout would eventually do that, but only after ten minutes of nothing.
SCAN_TIMEOUT_SECONDS = 300

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
#
# These two literals are assembled from fragments rather than written out whole, and that is not
# only tidiness. The secret-scan job scans full history, so a committed PAT-shaped string is a
# committed finding - and this file exists only to plant one. Writing it whole made the job that
# proves the secret scan works fail on this repository's own source, which is the sharpest form of
# the mistake the job exists to catch.
#
# The planted token is deliberately NOT the value the two historical commits carried, because
# .gitleaks.toml excuses that one value by its shape - ten digits, ten lowercase, ten uppercase,
# six digits, in order - and a shape-based exception applies everywhere. If this file planted the
# excused shape, scenario_planted_token_fails would report success whether or not the scan was
# looking at all. So the value planted here is a different synthetic token, and the assertions
# below check both facts: it is a well-formed `ghp_` token, and it does not match the shape
# .gitleaks.toml excuses.
#
# The fragments reassemble into the value the historical commits carried, so the scratch repository
# plants the same bytes the allowlist had to be written around rather than something merely similar.
# `_check_planted_values` refuses to run if the reassembly is not a well-formed credential shape,
# because a fragment set that silently dropped two characters would leave this comment claiming an
# equivalence that no longer held - and this file's whole argument is that its literals can be
# trusted. The check is on shape rather than on a second copy of the value, since a second copy would
# drift from the first in exactly the way this file exists to prevent.
#
# No fragment is longer than eleven characters, and that bound is not cosmetic. An earlier version of
# this line bound the credential value as `PLANTED_CREDENTIAL_VALUE = "<23 characters>" + "<9>"`, and
# that single 23-character literal was a `generic-api-key` finding in the commit which added the
# property meant to catch exactly this: gitleaks pairs a keyword with an adjacent value, and the
# keyword was in the variable's own name. Splitting to two or three fragments avoided the rule while
# leaving the reassembled bytes identical, which is what a fragment is for - but it was found by the
# history scan, after the commit, rather than before it. tests/ci/test_ci_workflow.py now fails on a
# keyword-adjacent high-entropy run in any tracked file, which is the shape that broke it here.
PLANTED_TOKEN = "ghp_" + "Zq7Kd93mzQ" + "pL2vRt8YwZ" + "a5NcHb1JfU" + "e6G4Qz"
PLANTED_IDEMPOTENCY_VALUE = "x7Kd93mzQpL" + "2vRt8YwZa5N" + "cHb1JfUe6G"
PLANTED_TOKEN_LINE = '"idempotency_key": "' + PLANTED_TOKEN + '",'
PLANTED_IDEMPOTENCY_LINE = '"idempotency_key": "' + PLANTED_IDEMPOTENCY_VALUE + '",'

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
    repo = _make_repo("credential", (PLANTED_IDEMPOTENCY_LINE,))
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


def scenario_repository_history_is_clean(argv: list[str]) -> Outcome:
    """This repository's own committed history must pass the committed scan.

    The only property here that looks at the repository this script ships in rather than at a
    scratch repository it controls, and the only one that could have caught what actually happened:
    commits 25bf81f and 5d84f14 are in history because a whole GitHub-token-shaped string was
    written into this repository's own test file while testing this scan, and every other property
    passed in both trees.

    The volume source is NOT substituted for this one. `_run_scan` rewrites it to point at a
    scratch repository, which is what makes properties 1 to 4 controlled experiments; here the
    substitution is exactly the defect, so the committed command is executed against the checkout.
    Everything else - image, flags, config, subcommand - is still the workflow's.

    The one rewrite is the shell's own `$PWD`. The committed command mounts `"$PWD:/repo"`, which
    CI's bash expands to the checkout root; this script executes the argument list directly rather
    than through a shell, so that expansion is done here instead. Leaving it literal would make this
    scenario fail with a docker volume-name error and report a harness problem as a finding about
    the repository, which is the shape of false alarm this file exists to avoid.

    It scans committed history, which is a real limit worth stating rather than hiding: a secret
    that is staged but not committed is invisible to this, and to the CI step, until it is
    committed. That is inherent to `gitleaks detect`, and it is why this property runs in CI on the
    pushed commit rather than only on a developer machine.

    Three guards keep a green result from meaning "the scan ran", because `gitleaks detect` exits 0
    on a directory that is not a git repository and prints `0 commits scanned` - measured, not
    assumed. A harness that silently scanned nothing would report this property as passing, which is
    the green-while-blind mode this file exists to rule out:

      * the substituted argument list must actually contain this checkout's path, so a change to the
        committed command's volume spelling is refused rather than silently mounting nothing;
      * a pass requires a commit count greater than zero;
      * a non-zero exit with no finding block is reported as a HARNESS failure, not as a finding,
        for the same reason the other properties test for `leaks found` before believing an exit
        code. The distinction matters in both directions: a docker or git failure reported as a
        repository finding sends the reader looking in the wrong place, and the earlier version of
        this function did exactly that.
    """
    argv = [tok.replace("$PWD", str(ROOT)) for tok in argv]
    if not any(str(ROOT) in token for token in argv):
        raise SystemExit(
            "prove_secret_scan_gate: after expanding $PWD the scan command does not mention this "
            f"checkout ({ROOT}). The committed step's volume specification has changed shape - it "
            "may use ${GITHUB_WORKSPACE} or --mount now - and expanding $PWD no longer rewrites it. "
            "Refusing to run rather than reporting a scan of nothing as a pass."
        )
    # Bounded so a hung scan fails as a harness problem instead of hanging the proof forever; the
    # scan over this repository's history takes a couple of seconds.
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=SCAN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return Outcome(
            "this repository's committed history passes the scan",
            False,
            f"the committed scan command did not finish within {SCAN_TIMEOUT_SECONDS}s. This is a "
            "harness failure, not a finding: nothing can be concluded about the repository's "
            "history from a scan that never completed.",
        )

    output = _out(result)
    commits = re.search(r"(\d+) commits scanned", output)
    if result.returncode == 0:
        if commits is None or int(commits.group(1)) == 0:
            return Outcome(
                "this repository's committed history passes the scan",
                False,
                "the committed scan command exited 0 but reported "
                + (
                    f"'{commits.group(0)}'."
                    if commits
                    else "no commit count at all."
                )
                + " `gitleaks detect` exits 0 and finds nothing in a directory that is not a git "
                "repository, so this is a scan of nothing reported as a pass. The volume "
                "specification resolved somewhere other than this checkout's history.",
            )
        return Outcome(
            "this repository's committed history passes the scan",
            True,
            f"exit 0, {commits.group(0)}",
        )
    # The scanner redacts by default, so this names the rule, the file and the commit without
    # reprinting the value into a log.
    findings = re.findall(r"RuleID:\s+(\S+).*?File:\s+(\S+).*?Commit:\s+(\S+)", output, re.DOTALL)
    if not findings:
        return Outcome(
            "this repository's committed history passes the scan",
            False,
            f"the committed scan command exited {result.returncode} without reporting a finding, "
            "so the scan itself did not complete - an image that would not pull, a volume that "
            "would not mount, a git error. That is a harness failure and nothing is established "
            f"about this repository's history. Output: {output[-800:].strip() or '(empty)'}",
        )
    where = "; ".join(f"{rule} in {file} at {commit[:12]}" for rule, file, commit in findings)
    return Outcome(
        "this repository's committed history passes the scan",
        False,
        "the committed scan command, run against this repository, exited "
        f"{result.returncode}. A secret in this repository's history is reported by CI but is "
        "invisible locally: gh is unauthenticated here, so a red secret-scan job is a red job "
        f"nobody reads. Findings: {where}",
    )


def _check_planted_values() -> None:
    """Refuse to run if either planted value cannot fail the scan, or could not.

    Five checks, all of which the rest of this file silently depends on.

    If the token is not a well-formed `ghp_` value then scenario_planted_token_fails is not testing
    the rule it names. If the credential does not have the shape that makes it a credential - mixed
    case, no hyphen - then it is not testing the exception, since the exception is scoped by value
    shape. If either planted value matches something .gitleaks.toml excuses then its scenario passes
    for the wrong reason - the allowlist suppresses it and the scan is never consulted - which is
    precisely the failure this proof exists to rule out.

    The allowlist is read from the committed config rather than from a copy of one pattern held
    here. That is not tidiness: .gitleaks.toml grew a second token exception while this file was
    being written, and a guard that checked only the first would have kept reporting success if the
    planted token had started matching the second. Three things about that read are deliberate:

      * Patterns are combined as text, because interpolating compiled objects yields a string that
        matches nothing - the same defect this repository has now recorded in three separate places.
        The combination is guarded, because a pattern valid in the scanner's Go regex engine need
        not be valid in Python's, and an unguarded compile would report a config problem as a
        traceback rather than as the refusal it is.
      * `stopwords` are checked as well as `regexes`. A stopword is matched against the secret the
        rule matched, so an exception added that way silences the planted values just as
        effectively as a regex, and a guard reading only `regexes` would not notice. This config
        already carries one stopword entry, so the route is not hypothetical.
      * Each planted value is checked twice - bare, and inside the assignment the scanner actually
        matches - because an exception may match either span. Checking one and not the other leaves a
        route by which the scenario passes for the wrong reason, or fails for one: the repository's
        idempotency exception is scoped to the whole `idempotency_key = <value>` span, not to the
        value.

    Raised rather than asserted: `python -O` strips asserts, and a gate that verifies itself must
    not be switchable off by a flag nobody reads.
    """
    import tomllib

    body = PLANTED_TOKEN.removeprefix("ghp_")
    if not PLANTED_TOKEN.startswith("ghp_") or len(body) != 36:
        raise SystemExit(
            f"prove_secret_scan_gate: the planted token is not a well-formed ghp_ value: "
            f"{len(body)} characters after the prefix, expected 36. The first scenario would not "
            f"be testing the github-pat rule."
        )

    credential = PLANTED_IDEMPOTENCY_VALUE
    if (
        len(credential) != 32
        or "-" in credential
        or not any(c.isupper() for c in credential)
        or not any(c.islower() for c in credential)
        or not any(c.isdigit() for c in credential)
    ):
        raise SystemExit(
            "prove_secret_scan_gate: the planted credential is not the shape it claims to be: it "
            "must be 32 mixed-case alphanumerics with no hyphen, because that is what the "
            "repository's idempotency_key exception excludes. As it is, the second scenario is not "
            "testing the exception."
        )

    try:
        config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"prove_secret_scan_gate: cannot read {CONFIG}: {exc}") from exc

    allowlists = config.get("allowlists") or []
    patterns = [pattern for entry in allowlists for pattern in (entry.get("regexes") or [])]
    stopwords = [word for entry in allowlists for word in (entry.get("stopwords") or [])]
    if not patterns and not stopwords:
        raise SystemExit(
            f"prove_secret_scan_gate: {CONFIG.name} declares no allowlist regexes and no "
            "stopwords, so there is nothing for these scenarios to be excused by and the proof "
            "would not be testing what it says"
        )
    combined = "|".join(f"(?:{pattern})" for pattern in patterns)
    try:
        excused = re.compile(combined) if combined else None
    except re.error as exc:
        raise SystemExit(
            f"prove_secret_scan_gate: {CONFIG.name} declares a pattern this interpreter cannot "
            f"compile, so the scenarios below cannot be checked against it: {exc}"
        ) from exc

# Each planted value is checked in both forms: bare, and inside the assignment the scanner
    # actually matches. An exception may match either span, so checking one alone leaves a route by
    # which the scenario passes for the wrong reason or fails for one.
    for value, line, scenario_name in (
        (PLANTED_TOKEN, PLANTED_TOKEN_LINE, "a planted token fails the scan"),
        (
            credential,
            PLANTED_IDEMPOTENCY_LINE,
            "a credential in the exempted field still fails the scan",
        ),
    ):
        for candidate, form in (
            (value, "the bare value"),
            (line, "the assignment the scanner matches"),
        ):
            is_excused = excused is not None and excused.search(candidate)
            is_excused = is_excused or any(word in candidate for word in stopwords)
            if is_excused:
                raise SystemExit(
                    f"prove_secret_scan_gate: {form} planted for {scenario_name!r} is excused by "
                    f"{CONFIG.name}, so that scenario would report success whether or not the "
                    "scan was looking at anything. Plant a differently shaped value, or narrow "
                    "the exception."
                )


def main() -> int:
    if not CONFIG.is_file():
        print(
            f"prove_secret_scan_gate: {CONFIG} is not present, so the step's --config names a file "
            "that does not exist and the scan cannot be the one this repository declares"
        )
        return 2
    _check_planted_values()
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
        scenario_repository_history_is_clean(argv),
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