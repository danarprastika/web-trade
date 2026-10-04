"""Controls for scripts/check_npm_audit.py, driven through its file seam rather than through npm.

The gate's whole subject is an advisory that has no fix, so a control that shells out to npm would
test the registry's current opinion rather than the gate. Worse, the condition that matters - an
unlisted advisory arriving - cannot be produced on demand from a real registry, so a control that
depended on npm could never demonstrate that the gate rejects one.

So the gate accepts `--audit-json` and `--production-json`, and these controls state conditions
against synthetic reports. Each asserts a property of the decision, not a substring of the output.

The report shape is npm's v7+ `vulnerabilities` map. Two details of it are load-bearing and are
reproduced rather than simplified, because a fixture that flattened them would test a gate that does
not exist:

  One advisory produces several entries. `braces` carries the advisory in `via` as an object with a
  `url` and a `severity`; the four packages that depend on it carry a bare string in `via` naming
  their vulnerable dependency. A gate that counted entries instead of advisories would see five
  findings here and one here.

  `severity` is stated twice, on the package and on the advisory, and they are not guaranteed to
  agree. The gate reads the advisory's, because the package severity describes how bad it is to
  depend on that package, while the question being asked is how bad the advisory is.
"""

from __future__ import annotations

import copy
import importlib.util
import pathlib
import subprocess
import sys

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]

BRACES_ADVISORY = "GHSA-vfj7-8cjw-p6xm"


def _gate():
    """Load the gate by path, the way the workflow invokes it.

    Not imported as a module: `scripts/` is not a package, and adding one to make it importable
    would be a change to the layout to serve the tests.
    """
    path = ROOT / "scripts" / "check_npm_audit.py"
    spec = importlib.util.spec_from_file_location("check_npm_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _advisory(name: str = "braces", severity: str = "high", identifier: str = BRACES_ADVISORY) -> dict:
    return {
        "source": 1240992,
        "name": name,
        "dependency": name,
        "title": f"{name} advisory",
        "url": f"https://github.com/advisories/{identifier}",
        "severity": severity,
        "range": "<=3.0.3",
    }


def _report() -> dict:
    """The audit this repository actually produces: one advisory, four carriers."""
    return {
        "auditReportVersion": 3,
        "vulnerabilities": {
            "braces": {
                "name": "braces",
                "severity": "high",
                "isDirect": False,
                "via": [_advisory()],
                "effects": ["micromatch"],
            },
            "micromatch": {
                "name": "micromatch",
                "severity": "high",
                "isDirect": False,
                "via": ["braces"],
                "effects": ["fast-glob"],
            },
            "fast-glob": {
                "name": "fast-glob",
                "severity": "high",
                "isDirect": False,
                "via": ["micromatch"],
                "effects": ["@next/eslint-plugin-next"],
            },
            "@next/eslint-plugin-next": {
                "name": "@next/eslint-plugin-next",
                "severity": "high",
                "isDirect": False,
                "via": ["fast-glob"],
                "effects": ["eslint-config-next"],
            },
            "eslint-config-next": {
                "name": "eslint-config-next",
                "severity": "high",
                "isDirect": True,
                "via": ["@next/eslint-plugin-next"],
                "effects": [],
            },
        },
        "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 5, "critical": 0}},
    }


def _clean() -> dict:
    return {"auditReportVersion": 3, "vulnerabilities": {}, "metadata": {"vulnerabilities": {}}}


def test_the_current_audit_is_exactly_the_enumerated_exception() -> None:
    """The positive case: the one known advisory, excepted, with a clean production tree."""
    gate = _gate()

    assert gate.check(_report(), _clean(), gate.EXCEPTIONS) == []


def test_one_advisory_is_one_finding_not_five() -> None:
    """npm lists four carrier packages for one advisory, and the gate must count one.

    If it counted entries, this tree would report five blocking findings against a single exception
    and the exact-match rule would fail on a clean tree - or, worse, a second exception would be
    added to balance the arithmetic, excusing two advisories to cover one.
    """
    gate = _gate()

    assert len(gate.advisories(_report())) == 1
    assert len(gate.EXCEPTIONS) == 1


def test_a_second_advisory_in_the_same_package_is_not_covered() -> None:
    """The exception names a GHSA identifier, so a different advisory in `braces` still blocks.

    This is the distinction between an exception and a suppression. Written as "braces is accepted"
    or "5 highs are accepted", it would keep passing here - same package, same severity, same
    everything except the one thing that says which vulnerability is being tolerated.
    """
    gate = _gate()
    report = _report()
    report["vulnerabilities"]["braces"]["via"].append(
        _advisory(identifier="GHSA-0000-0000-0000", severity="critical")
    )

    problems = gate.check(report, _clean(), gate.EXCEPTIONS)

    assert problems, "a second, different advisory in an excepted package was not reported"
    assert any("GHSA-0000-0000-0000" in problem for problem in problems), (
        f"the report does not name the advisory that was not covered:\n" + "\n".join(problems)
    )


def test_an_exception_that_matches_nothing_is_itself_a_failure() -> None:
    """A stale exception must fail, so it cannot outlive its justification.

    The realistic path is upstream: braces publishes a fix, the advisory disappears, and the
    exception is left behind still excusing it. Nothing about that state is dangerous on its own,
    which is why it survives review after review - it is only visible if something refuses to pass
    while an unused permission is still granted.
    """
    gate = _gate()

    problems = gate.check(_clean(), _clean(), gate.EXCEPTIONS)

    assert problems, "an exception matching no advisory still passed"
    assert any("matched nothing" in problem for problem in problems), (
        f"the report does not say the exception is stale:\n" + "\n".join(problems)
    )


def test_a_finding_in_the_production_tree_voids_a_dev_only_exception() -> None:
    """The justification is measured, so it stops holding when the thing it claims stops being true.

    Every dev-only exception in the gate rests on production dependencies being clean. If the
    vulnerable package ever moves into the production tree, the reason for accepting it is gone -
    and the gate must notice on that run rather than leaving a comment asserting a property that has
    stopped being true.
    """
    gate = _gate()
    production = _clean()
    production["vulnerabilities"]["braces"] = {
        "name": "braces",
        "severity": "high",
        "isDirect": True,
        "via": [_advisory()],
        "effects": [],
    }

    problems = gate.check(_report(), production, gate.EXCEPTIONS)

    assert problems, "a production-tree finding did not fail the gate"
    assert any("PRODUCTION" in problem for problem in problems), (
        f"the report does not identify the finding as production-tree:\n" + "\n".join(problems)
    )


def test_an_unreadable_report_shape_fails_rather_than_passing_empty() -> None:
    """A report with no `vulnerabilities` key is not an empty finding set, and must not pass as one.

    npm changing its report format would otherwise produce a gate that finds nothing and reports
    that everything is fine - the failure mode this repository records repeatedly, reached here by
    an upstream release rather than by a careless edit.
    """
    gate = _gate()
    shapeless = {"auditReportVersion": 3, "metadata": {"vulnerabilities": {"high": 5}}}

    with pytest.raises(SystemExit) as raised:
        gate.check(shapeless, _clean(), gate.EXCEPTIONS)

    assert "could not read" in str(raised.value) or "understand" in str(raised.value), str(
        raised.value
    )


def test_severity_is_read_from_the_advisory_not_from_the_package() -> None:
    """A moderate package carrying a high advisory still blocks.

    npm states severity on both the package and the advisory and they need not agree: the package
    severity describes depending on it, the advisory severity describes the vulnerability. Reading
    the wrong one lets an exception hide a high advisory behind a moderate package entry.
    """
    gate = _gate()
    report = _report()
    report["vulnerabilities"]["braces"]["severity"] = "moderate"
    report["vulnerabilities"]["braces"]["via"][0]["severity"] = "high"

    assert len(gate.advisories(report)) == 1, "the advisory's own severity was not the one consulted"


def test_the_gate_reports_the_chain_npm_itself_reports() -> None:
    """The failure message must name the whole path, so a reader need not re-derive it.

    The chain is read from `via` and `effects` rather than from a hand-written constant, so it stays
    true when the dependency graph changes - which is the only property that makes it worth printing.
    """
    gate = _gate()
    report = _report()
    report["vulnerabilities"]["braces"]["via"].append(
        _advisory(identifier="GHSA-1111-1111-1111")
    )

    problems = gate.check(report, _clean(), gate.EXCEPTIONS)

    assert problems
    assert any("eslint-config-next" in problem and "braces" in problem for problem in problems), (
        f"the report did not name both ends of the chain:\n" + "\n".join(problems)
    )


def test_the_workflow_runs_the_gate_rather_than_the_bare_audit_command() -> None:
    """The gate is only a control if CI invokes it; a bare `npm audit` would restore the failure.

    Cheap, and it is the whole fix: this step is what turns an unfixable advisory into a bounded,
    justified and re-measured one, and a future edit that helpfully restores
    `npm audit --audit-level=high` would reintroduce a permanently red dependency-scan job with no
    failure in this file to explain why.
    """
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["dependency-scan"]["steps"]
    audit_steps = [str(step.get("run", "")) for step in steps if step.get("name") == "npm audit"]

    assert len(audit_steps) == 1, f"expected exactly one npm audit step, found {len(audit_steps)}"
    run = audit_steps[0]
    assert "check_npm_audit.py" in run, f"the npm audit step does not run the gate:\n{run}"
    assert "--audit-level" not in run, (
        f"the step still runs the bare npm audit, which cannot pass on this tree:\n{run}"
    )


def test_the_gate_runs_standalone_and_reports_the_exception() -> None:
    """The script must work as the workflow invokes it: one argument, real npm, exit 0 here.

    Wired but unrunnable is a gate that has stopped gating, and it is not caught by the seam-based
    controls above because they never execute main(). This one does, so a broken import, an
    unresolvable npm, or a bad default surfaces. It needs the network and node_modules, which is why
    it is one test rather than the fixture the rest of the file uses.
    """
    if not (ROOT / "apps" / "web" / "node_modules").is_dir():
        pytest.skip("apps/web/node_modules is absent; the registry scan cannot run")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_npm_audit.py")],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=ROOT,
    )

    assert result.returncode == 0, f"the gate failed on this tree:\n{result.stdout}\n{result.stderr}"
    assert BRACES_ADVISORY in result.stdout, (
        "the gate passed without printing the advisory it excepted; a silent pass is what this gate "
        f"exists to avoid:\n{result.stdout}"
    )
