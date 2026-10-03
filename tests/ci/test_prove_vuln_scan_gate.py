"""Behavioural tests for scripts/prove_vuln_scan_gate.py's real-scanner scenario.

The rest of that proof is executed by the proof itself, in CI, against the committed `run:` block
with a fake scanner on PATH - see the `prove the vulnerability scan can fail` step. What is NOT
covered there is `scenario_real_scanner`, the one scenario that shells out to the real scanner
against the real repository tree, because it needs a network and an installed govulncheck and so
cannot be asserted in an ordinary test run.

That leaves exactly the code path most able to quietly mislead. `scenario_real_scanner` can
observe the real scanner exiting 3, which means it found a reachable vulnerability. A finding is
not a defect in the harness - the property under test is that the scanner RUNS, and the scan step
is what blocks on a finding - so the property legitimately passes. The hazard is entirely in how
that is reported. The first version of this branch printed `[ok] ... reported a reachable
vulnerability` and discarded the scanner's output, which puts a green marker on a line whose text
says a security finding was found.

That is the confusion this repository has now recorded three times: EV-064 and EV-065 are checks
that reported success without exercising anything, and WI-175 was a package that reported 'ok'
having skipped every test covering the shipped behaviour. A fourth instance, in the proof built
specifically to catch this class, would be worth more than the defect it replaced.

So these tests pin two things: that a reachable vulnerability reaches the reader with the
scanner's own text intact, and that it is raised under a marker that is not `[ok]`.

Run:
    python -m pytest tests/ci/test_prove_vuln_scan_gate.py -q
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROOF = REPO_ROOT / "scripts" / "prove_vuln_scan_gate.py"

SCENARIO = "real govulncheck refuses the repository root"

# govulncheck's documented exit codes, restated here so a change to the proof's constants cannot
# quietly redefine what these stubs mean.
EXIT_NO_VULNERABILITIES = 0
EXIT_VULNERABILITY_FOUND = 3
EXIT_NO_GO_MOD = 1


def load_proof():
    spec = importlib.util.spec_from_file_location("prove_vuln_scan_gate", PROOF)
    assert spec and spec.loader, f"cannot load {PROOF}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Completed:
    """The slice of subprocess.CompletedProcess that the scenario reads."""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture()
def proof(monkeypatch: pytest.MonkeyPatch):
    """The proof module with a clean warning list and a stubbed root go.mod lookup."""
    module = load_proof()
    module.WARNINGS.clear()
    monkeypatch.setattr(Path, "exists", lambda self: False, raising=False)
    return module


def stub_scanner(monkeypatch: pytest.MonkeyPatch, *, root_rc: int, root_err: bytes, inside_rc: int,
                 inside_out: bytes = b"") -> None:
    """Answer the two govulncheck invocations with fixed results, and record the calls.

    The scenario runs exactly two commands, distinguished by the argument after -C: '.' is the
    checkout root and 'services/control-plane' is a module. Stubbing on that is what makes these
    tests hermetic - no network, no scanner, no repository scan.
    """

    def fake_run(cmd, **_kwargs):
        assert cmd[0].endswith("govulncheck"), f"unexpected command: {cmd}"
        target = cmd[cmd.index("-C") + 1]
        if target == ".":
            return _Completed(root_rc, b"", root_err)
        return _Completed(inside_rc, inside_out, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_a_reachable_vulnerability_is_raised_with_the_scanner_text(proof, monkeypatch) -> None:
    """A finding must survive into the reader's output verbatim.

    If the scanner's own text is dropped, the proof has learned that something is wrong and then
    discarded what it learned - and the operator is left with a green line and no finding.
    """
    stub_scanner(
        monkeypatch,
        root_rc=EXIT_NO_GO_MOD,
        root_err=b"govulncheck: no go.mod file",
        inside_rc=EXIT_VULNERABILITY_FOUND,
        inside_out=b"Vulnerability #1: GO-2026-0000 example/osv.io/GHSA-xxxx stdlib\n",
    )

    outcome = proof.scenario_real_scanner("govulncheck")

    assert outcome.name == SCENARIO
    assert outcome.passed, (
        "the property asserts the scanner RUNS, so a reachable vulnerability is not a harness "
        f"failure and the outcome should still pass; got: {outcome.detail}"
    )
    assert len(proof.WARNINGS) == 1, (
        "a reachable vulnerability must be raised exactly once and visibly, not absorbed into the "
        f"passing outcome; WARNINGS was {proof.WARNINGS!r}"
    )
    warning = proof.WARNINGS[0]
    assert "GO-2026-0000" in warning, (
        "the scanner's own finding text must be quoted in the warning; an operator cannot act on a "
        f"paraphrase, and the raw text is the only part that names the affected symbol:\n{warning}"
    )


def test_a_reachable_vulnerability_is_not_reported_as_a_green_line(proof) -> None:
    """The warning must be printed under a marker that cannot be mistaken for a pass.

    Asserted against the source rather than by running main(), because main() shells out to bash and
    to a real scanner. The check is deliberately narrow and exact: it locates the loop that prints
    WARNINGS and requires a [WARN] marker on it. Changing that marker to [ok] - which is the mistake
    this test exists to catch - fails here rather than in a reader's CI log.
    """
    source = PROOF.read_text(encoding="utf-8")
    loop = re.search(r"for warning in WARNINGS:\s*\n\s*print\(\s*f?[\"']\s*(\[[A-Za-z]+\])", source)
    assert loop, (
        "the warning list must actually be printed under a bracketed marker; a warning collected "
        "and never shown is the same defect as a warning never raised"
    )
    assert loop.group(1) == "[WARN]", (
        "warnings must print under [WARN] so they are visually distinct from both passes and "
        "failures. Changing this to [ok] is the exact mistake these tests exist to catch: a green "
        f"line whose text says a reachable vulnerability was found. Found {loop.group(1)}"
    )


def test_a_clean_module_scan_raises_no_warning(proof, monkeypatch) -> None:
    """The control: the warning must be specific to a finding, not to any successful run.

    Without this, a warning that fires on every invocation would satisfy the tests above while
    telling the reader nothing - the failure mode of a check that is always on.
    """
    stub_scanner(
        monkeypatch,
        root_rc=EXIT_NO_GO_MOD,
        root_err=b"govulncheck: no go.mod file",
        inside_rc=EXIT_NO_VULNERABILITIES,
        inside_out=b"No vulnerabilities found.\n",
    )

    outcome = proof.scenario_real_scanner("govulncheck")

    assert outcome.passed, outcome.detail
    assert proof.WARNINGS == [], (
        f"a clean scan must be silent; warnings on every run are noise that trains readers to "
        f"ignore the one that matters: {proof.WARNINGS!r}"
    )
    assert "exited 0" in outcome.detail, (
        "a clean run must say so, so that a reader can tell it apart from a run that found "
        f"something: {outcome.detail}"
    )


def test_a_scanner_that_cannot_run_fails_the_scenario(proof, monkeypatch) -> None:
    """Exit 1 is the broken configuration, not a finding, and must not be softened into a pass.

    This is the exit code the original defect produced on every run. Conflating it with a finding is
    how a permanently red scan job can sit unread for a release cycle, so it stays a failure.
    """
    stub_scanner(
        monkeypatch,
        root_rc=EXIT_NO_GO_MOD,
        root_err=b"govulncheck: no go.mod file",
        inside_rc=EXIT_NO_GO_MOD,
        inside_out=b"govulncheck: loading packages: go: cannot load\n",
    )

    outcome = proof.scenario_real_scanner("govulncheck")

    assert not outcome.passed, (
        "a scanner that cannot run must fail this scenario; the scan step replaced would not have "
        f"worked either: {outcome.detail}"
    )
    assert proof.WARNINGS == [], (
        "a broken scanner is a failure of the scenario, not a warning to report alongside a pass"
    )


def test_a_root_go_mod_would_fail_the_premise(proof, monkeypatch) -> None:
    """If a root go.mod ever appears, the premise of the per-module loop is stale.

    The scenario has to say so rather than quietly re-assert itself: a structure kept for a reason
    that no longer holds is the kind of thing nobody can explain six months later.
    """
    real_exists = Path.exists

    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(proof, "ROOT", REPO_ROOT)

    def guarded(self) -> bool:
        return True if self == proof.ROOT / "go.mod" else real_exists(self)

    monkeypatch.setattr(Path, "exists", guarded)

    outcome = proof.scenario_real_scanner("govulncheck")

    assert not outcome.passed, (
        "with a root go.mod present the per-module structure is redundant and the scenario must "
        f"say so: {outcome.detail}"
    )
    assert "go.mod" in outcome.detail
