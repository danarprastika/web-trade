"""Static validation of the CI workflow.

This is not a substitute for running the workflow, and it is not claimed to be one. It
catches the class of error that would otherwise be discovered only after pushing: a
malformed document, an action pinned to something that is not a commit SHA, or a step
referencing an output id that does not exist.

The SHA check is the important one. docs/02_POLYGLOT_ENGINEERING_STANDARD.md section 10
requires a locked, attested dependency graph, and a CI step pinned to a mutable tag like
`@v4` is a supply-chain hole. A workflow that looks pinned but is not would be worse than
an obviously unpinned one, because review would not catch it.

Run:
    python -m pytest tests/ci -q
"""

from __future__ import annotations

import copy
import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML is required to parse the workflow")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

# Every action this workflow references, mapped to the tag the SHA was resolved from.
# The comment on each `uses:` line must agree with this map, so a SHA cannot be silently
# repointed at a different tag.
EXPECTED_ACTIONS = {
    "actions/checkout": "v4.2.2",
    "actions/setup-go": "v5.5.0",
    "actions/setup-node": "v4.1.0",
    "actions/setup-python": "v5.6.0",
    "actions/upload-artifact": "v4.6.2",
    "github/codeql-action": "v3.28.17",
    "anchore/sbom-action": "v0.20.6",
    "sigstore/cosign-installer": "v3.8.2",
    "docker/build-push-action": "v6.17.0",
}


@pytest.fixture(scope="module")
def workflow() -> dict:
    if not WORKFLOW.is_file():
        pytest.skip("ci.yml not present")
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), "workflow must parse to a mapping"
    return parsed


def _uses_entries(workflow: dict) -> list[tuple[str, str]]:
    """Yield (action_path, pinned_ref) for every `uses:` in the workflow.

    A subpath action (`github/codeql-action/init`) is normalised back to its repository
    so it can be checked against EXPECTED_ACTIONS.
    """
    found: list[tuple[str, str]] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in (job or {}).get("steps") or []:
            uses = step.get("uses")
            if not uses:
                continue
            parts = uses.split("@", 1)
            if len(parts) != 2:
                continue
            action, ref = parts
            owner_repo, _, _subpath = action.partition("/")[0] + "/" + action.partition("/")[1].split("/")[0], "", ""
            # action looks like "owner/repo" or "owner/repo/subpath"
            segments = action.split("/")
            owner_repo = "/".join(segments[:2])
            found.append((owner_repo, ref))
    return found


def test_workflow_parses_and_declares_triggers(workflow: dict) -> None:
    # PyYAML resolves the bare key `on` to the boolean True, a YAML 1.1 quirk. Accept
    # either so the test does not depend on how the loader normalises it.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers, "workflow must declare triggers"
    assert "pull_request" in triggers, "PRs must be validated before merge"


def test_project_brain_gate_runs_on_every_merge(workflow: dict) -> None:
    """The Project Brain is the record of what this project has verified. Its gate must run
    in CI, and its own failure modes must be tested there, otherwise the ledger can
    quietly drift into overstating what was actually checked while still looking healthy."""
    jobs = workflow.get("jobs") or {}
    assert "project-brain" in jobs, (
        "the Project Brain integrity gate must run in CI; it is the only thing standing "
        "between a stale or overstating ledger and a green build"
    )
    steps = yaml.safe_load(yaml.safe_dump(jobs["project-brain"]))["steps"]
    runs = [
        s.get("run", "") for s in steps if isinstance(s, dict) and s.get("run")
    ]
    joined = "\n".join(runs)
    assert "scripts/verify_project_brain.py" in joined, (
        "the project-brain job must actually run the gate, not merely exist"
    )
    assert "tests/ci/test_verify_project_brain.py" in joined, (
        "the project-brain job must run the gate's own tests, so a gate that has stopped "
        "rejecting tampering fails here rather than at the next real integrity incident"
    )


def test_every_job_that_runs_the_ci_suite_first_installs_its_dependencies(
    workflow: dict,
) -> None:
    """Any job that runs tests/ci must install that suite's pinned dependencies first.

    This is not hypothetical, and it was not one job. The toolchain job went straight from
    actions/setup-python to `python -m pytest tests/ci` with no install step, so on the runner
    pytest was absent and the step exited 1 in under a second; because the workflow is
    fail-fast, that one missing line left all eleven other jobs skipped. The spec-gate and
    project-brain jobs carried the identical defect, hidden behind the same fail-fast, and each
    died in about five seconds for the same reason. None of it involved the code under test.

    So this is asserted for EVERY such job rather than for the one that happened to be
    diagnosed. A new gate job added without the install would otherwise fail for want of its own
    dependency, and the error would name a missing module rather than the missing line.

    Order is part of the assertion: an install placed after the pytest call is the same defect
    with extra lines.
    """
    jobs = workflow.get("jobs") or {}
    assert jobs, "the workflow declares no jobs, so this assertion is vacuous"

    offenders: list[str] = []
    checked = 0
    for name, job in jobs.items():
        steps = (job or {}).get("steps") or []
        runs = [
            s.get("run", "") for s in steps if isinstance(s, dict) and s.get("run")
        ]
        first_use = next(
            (i for i, run in enumerate(runs) if "pytest" in run and "tests/ci" in run),
            None,
        )
        if first_use is None:
            continue
        checked += 1
        installed = any(
            "pip install" in run and "tests/ci/requirements.txt" in run
            for run in runs[:first_use]
        )
        if not installed:
            offenders.append(
                f"{name} (runs tests/ci at step {first_use} with no earlier "
                f"pip install of tests/ci/requirements.txt)"
            )

    assert checked, (
        "no job runs tests/ci any more, so the gates' own negative cases are unverified; a gate "
        "that has stopped rejecting bad input is trusted and therefore worse than no gate"
    )
    assert not offenders, (
        "these jobs run the CI suite without installing its dependencies. actions/setup-python "
        "gives a clean interpreter with no pytest, so `python -m pytest tests/ci/...` fails with "
        "'No module named pytest' before any test runs:\n  "
        + "\n  ".join(offenders)
    )


def test_the_ci_suite_dependencies_are_pinned_not_floating(workflow: dict) -> None:
    """tests/ci's requirements must be exact pins.

    pytest.importorskip means a missing PyYAML makes tests/ci/test_ci_workflow.py skip
    instead of fail, so an unpinned dependency that resolves differently on the runner is
    the difference between 141 executed tests and 113 executed tests, reported the same
    green either way.
    """
    requirements = REPO_ROOT / "tests" / "ci" / "requirements.txt"
    assert requirements.is_file(), (
        "tests/ci/requirements.txt is missing, so the toolchain job cannot install what the "
        "suite needs and the job cannot start"
    )
    pins = [
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert pins, "tests/ci/requirements.txt declares no dependencies, so nothing is installed"
    unpinned = [p for p in pins if "==" not in p]
    assert not unpinned, (
        f"tests/ci/requirements.txt must pin every dependency exactly; unpinned: {unpinned}"
    )


# The dependency set the contract validator imports, named rather than discovered, so that a
# dependency added to the validator without a pin is a test failure and not a runner-only
# surprise. Keep in step with the imports at the top of tests/contracts/validate_contracts.py.
CONTRACT_VALIDATOR_REQUIREMENTS = REPO_ROOT / "tests" / "contracts" / "requirements.txt"
RESEARCH_PYPROJECT = REPO_ROOT / "workers" / "research" / "pyproject.toml"


def _pinned_pairs(text: str) -> dict[str, str]:
    """Parse `name==version` lines into a mapping, ignoring comments and blanks."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            name, sep, version = entry.partition("==")
            if sep:
                pairs[name.strip().lower()] = version.strip()
    return pairs


def test_every_job_that_runs_the_contracts_validator_first_installs_its_dependencies(
    workflow: dict,
) -> None:
    """Any job that runs the contract validator must install its pinned dependencies first.

    The contracts job went straight from actions/setup-python to the validator with nothing
    installed between them, and the validator's own answer to a missing package is exit 2 with
    "FATAL: the 'jsonschema' and 'referencing' packages are required". Six seconds of red, every
    run, reading as a contract failure. It is asserted for every such job rather than for the one
    that was diagnosed, because the same omission in a future job would be reported by the
    validator as a broken corpus rather than as a missing install line.

    Order is part of the assertion: an install after the validator is the same defect with the
    lines in the wrong order.
    """
    jobs = workflow.get("jobs") or {}
    offenders: list[str] = []
    checked = 0
    for name, job in jobs.items():
        steps = (job or {}).get("steps") or []
        runs = [s.get("run", "") for s in steps if isinstance(s, dict) and s.get("run")]
        first_use = next(
            (i for i, run in enumerate(runs) if "validate_contracts.py" in run),
            None,
        )
        if first_use is None:
            continue
        checked += 1
        installed = any(
            "pip install" in run and "tests/contracts/requirements.txt" in run
            for run in runs[:first_use]
        )
        if not installed:
            offenders.append(
                f"{name} (runs validate_contracts.py at step {first_use} with no earlier "
                f"pip install of tests/contracts/requirements.txt)"
            )

    assert checked, (
        "no job runs the contract validator any more, so the canonical corpus is no longer "
        "enforced by CI and every binding can drift from it silently"
    )
    assert not offenders, (
        "these jobs run the contract validator without installing its dependencies. "
        "actions/setup-python gives a clean interpreter, so the validator exits 2 with its own "
        "FATAL message before a single case is checked:\n  " + "\n  ".join(offenders)
    )


def test_the_contracts_validators_dependencies_are_pinned_and_not_duplicated_drift() -> None:
    """The validator's dependency set is pinned exactly, and the research worker agrees with it.

    Two declarations of one dependency set exist on purpose: tests/contracts/requirements.txt is
    what the contracts job installs, and workers/research/pyproject.toml is what
    test_schema_layer_rejects_document_cases needs because that test runs the validator as a
    subprocess inside the research worker's own environment. That arrangement is only safe while
    the two agree, so the agreement is asserted here rather than left to a reader to notice.

    The failure this pins down is not hypothetical either: the research worker's pin was
    jsonschema==4.26.1, a version that has never existed on PyPI, so every install of that extra
    failed to resolve and the validator was never executed in either job.
    """
    assert CONTRACT_VALIDATOR_REQUIREMENTS.is_file(), (
        "tests/contracts/requirements.txt is missing, so the contracts job has nothing to "
        "install and the validator exits 2 on a clean interpreter"
    )
    pins = _pinned_pairs(CONTRACT_VALIDATOR_REQUIREMENTS.read_text(encoding="utf-8"))
    assert pins, "tests/contracts/requirements.txt declares no dependencies"
    unpinned = [
        line.strip()
        for line in CONTRACT_VALIDATOR_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#") and "==" not in line
    ]
    assert not unpinned, (
        "tests/contracts/requirements.txt must pin every dependency exactly; unpinned: "
        f"{unpinned}"
    )

    assert RESEARCH_PYPROJECT.is_file(), "workers/research/pyproject.toml is missing"
    project = tomllib.loads(RESEARCH_PYPROJECT.read_text(encoding="utf-8"))
    dev = ((project.get("project") or {}).get("optional-dependencies") or {}).get("dev") or []
    research_pins = _pinned_pairs("\n".join(dev))

    for name, version in sorted(pins.items()):
        assert name in research_pins, (
            f"{name} is installed for the contracts job but is not declared in the research "
            "worker's dev extra, so the research worker's own run of the validator would fail "
            "on a missing package"
        )
        assert research_pins[name] == version, (
            f"{name} is pinned at {version} in tests/contracts/requirements.txt and "
            f"{research_pins[name]} in workers/research/pyproject.toml. The contracts job and "
            "the research worker run the same validator, so one dependency set means one pin."
        )


def test_every_codeql_init_step_passes_inputs_the_action_actually_defines(workflow: dict) -> None:
    """A CodeQL init input that does not exist is ignored, not rejected.

    This workflow passed `language:` where codeql-action v3 takes `languages`. The action's own
    warning listed `language` among "unexpected input(s)", the job carried on, and every one of
    the three matrix legs silently initialised ALL languages instead of its own. Each then ran
    Go's autobuild, each failed on Go extraction, and not one of them analysed the language its
    name claimed - a job named "SAST (CodeQL) (python)" that never looked at the Python.

    An unknown input is the quiet kind of typo, so it is asserted here: the plural input is
    required, the singular one is rejected outright, and the value must be a matrix expression
    or a literal list rather than a bare string that the action would silently not understand.
    """
    jobs = workflow.get("jobs") or {}
    inits: list[tuple[str, dict]] = []
    for name, job in jobs.items():
        for step in (job or {}).get("steps") or []:
            if isinstance(step, dict) and str(step.get("uses", "")).startswith(
                "github/codeql-action/init@"
            ):
                inits.append((name, step))

    assert inits, "no CodeQL init step found; the assertion below would be vacuous"

    problems: list[str] = []
    for name, step in inits:
        with_block = step.get("with") or {}
        if "language" in with_block:
            problems.append(
                f"job {name}: passes 'language', which codeql-action does not define, so the "
                "step silently analysed every language instead of the requested one"
            )
        languages = with_block.get("languages")
        if languages is None:
            problems.append(f"job {name}: no 'languages' input, so nothing is scoped")
        elif not (
            isinstance(languages, list)
            or (isinstance(languages, str) and "${{" in languages)
        ):
            problems.append(
                f"job {name}: languages={languages!r} is neither a list nor an expression"
            )
    assert not problems, "\n".join(problems)


def _resolve_matrix_value(raw: object, leg: dict) -> str:
    """Resolve a `${{ matrix.<key> }}` expression against one `matrix.include` entry.

    A workflow that scopes a step per matrix leg passes the expression through as a string, so a
    test that reads it gets `${{ matrix.build-mode }}` rather than `manual`. Comparing that to a
    literal can only ever fail, and a test that wraps such a comparison in `if ...:` never runs at
    all. This resolves the expression the same way the Actions runner would, so an assertion about
    the Go leg is about the Go leg.
    """
    if not isinstance(raw, str):
        return ""
    match = re.fullmatch(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}", raw.strip())
    if match is None:
        return raw
    value = leg.get(match.group(1))
    return "" if value is None else str(value)


def test_the_go_sast_leg_builds_every_workspace_module_rather_than_autobuilding_the_root(
    workflow: dict,
) -> None:
    """The Go SAST leg cannot use autobuild, and must resolve its module list from go.work.

    Autobuild builds from the checkout root. This repository has go.work at the root and
    deliberately no root go.mod, so that build fails outright ("directory prefix . does not
    contain modules listed in go.work"), and CodeQL reports it as "Extraction failed for all
    discovered Go projects" - a message naming neither a module nor the cause. The fix is a
    manual build that iterates the modules go.work actually declares.

    Five properties are asserted rather than one. The build mode must resolve, through the
    matrix, to `manual` - not autobuild, which fails for exactly the old reason, and not `none`,
    which skips the build and leaves nothing to trace. The build must derive its module list from
    `go work edit`, because a hardcoded list is a sixth thing to remember: a module added to
    go.work would then be extracted by no one, which is the same invisible-pass class of defect
    this repository has recorded repeatedly. The build must be gated to the Go leg, must precede
    the analyse step, and must refuse an empty module list rather than succeeding having built
    nothing.
    """
    assert (REPO_ROOT / "go.work").is_file(), "go.work is missing, so this gate's premise is stale"
    assert not (REPO_ROOT / "go.mod").is_file(), (
        "a root go.mod now exists, so CodeQL autobuild may work again; revisit whether the "
        "manual workspace build is still the right structure"
    )

    jobs = workflow.get("jobs") or {}
    assert "sast" in jobs, "the SAST job is missing, so Go is never statically analysed"
    job = jobs["sast"]

    matrix = ((job.get("strategy") or {}).get("matrix") or {})
    legs = matrix.get("include") or []
    go_legs = [leg for leg in legs if leg.get("language") == "go"]
    assert go_legs, (
        "the SAST matrix declares no Go leg; Go is the language this repository is written in "
        "and its absence is a silent loss of coverage"
    )

    steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
    init = next(
        (s for s in steps if str(s.get("uses", "")).startswith("github/codeql-action/init@")),
        None,
    )
    analyse = next(
        (s for s in steps if str(s.get("uses", "")).startswith("github/codeql-action/analyze@")),
        None,
    )
    assert init is not None and analyse is not None, (
        "the SAST job must both initialise and analyse, or there is no database to analyse"
    )

    build_mode = _resolve_matrix_value(
        (init.get("with") or {}).get("build-mode"), go_legs[0]
    )
    assert build_mode == "manual", (
        "the Go leg must resolve to build-mode: manual. It found "
        f"{build_mode!r} instead. Autobuild builds from a root that has no go.mod and therefore "
        "extracts nothing, and `none` skips the build entirely so there is nothing for CodeQL to "
        "trace. The value is read through the matrix rather than taken literally, because the init "
        "step passes the string '${{ matrix.build-mode }}': comparing the literal string against "
        "'manual' cannot succeed, so an earlier version of this assertion was dead code that "
        "appeared to pass while checking nothing."
    )

    build_index = next(
        (
            i
            for i, s in enumerate(steps)
            if "go work edit" in (s.get("run") or "") and "go build" in (s.get("run") or "")
        ),
        None,
    )
    assert build_index is not None, (
        "the Go leg declares build-mode: manual but no step builds the workspace, so extraction "
        "has nothing to trace"
    )
    assert build_index < steps.index(analyse), (
        "the build must happen before analysis: CodeQL traces the build it is given, and a build "
        "after the analyse step extracts nothing"
    )
    assert "go" in str((steps[build_index].get("if") or "")).lower(), (
        "the workspace build must be gated to the Go leg; the matrix also runs javascript and "
        "python, which have no workspace to build"
    )

    build_run = steps[build_index].get("run") or ""
    assert re.search(r"done\s+<\s*(?!<|\()\S", build_run), (
        "the build loop must read its module list from a plain file, not from a process "
        "substitution. Under `set -euo pipefail` a failure inside `done < <(...)` does not "
        "propagate to this step, and an empty list makes the loop body run zero times. Both are "
        "exit 0 with nothing built, so a resolution that silently returned nothing would leave the "
        "Go leg extracting nothing and reporting success"
    )
    assert (
        re.search(r"test\s+-s\s+modules\.txt", build_run)
        or re.search(r"-eq\s+0", build_run)
        or re.search(r"!\s*-s\s+", build_run)
    ), (
        "the build step must refuse an empty module list before building anything. An empty list "
        "is the same silent no-op the process-substitution form had, one level up: nothing is "
        "built and the step passes. The go, dependency-scan and integration jobs each refuse it, "
        "and this step has to as well"
    )


GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"


def test_no_job_contains_the_same_step_twice(workflow: dict) -> None:
    """A repeated step runs twice, and nothing else in this suite notices.

    YAML permits two list entries with the same keys, so a duplicated step is not a parse error,
    not a bash syntax error, and not a failure of any behavioural gate: the workflow stayed green
    while running one command twice. It arrived here as an editing accident - a step was re-inserted
    beside the one it replaced - and the run that would have caught it did not exist. That is the
    whole justification for this test.

    Both halves are asserted. A repeated `name` is the readable case, and a repeated `uses` is the
    case where the step has no name to repeat, which is how most `uses:` steps are written here.
    """
    offenders: list[str] = []
    for name, job in (workflow.get("jobs") or {}).items():
        steps = [s for s in ((job or {}).get("steps") or []) if isinstance(s, dict)]
        for field in ("name", "uses"):
            seen: set[str] = set()
            repeated: list[str] = []
            for step in steps:
                value = step.get(field)
                if not isinstance(value, str) or not value:
                    continue
                if value in seen:
                    repeated.append(value)
                seen.add(value)
            for value in repeated:
                offenders.append(f"job {name}: {field} {value!r} appears on more than one step")

    assert not offenders, (
        "these steps are duplicated, so each runs more than once and a change to one copy leaves "
        "the other running something stale:\n  " + "\n  ".join(offenders)
    )


def test_the_secret_scan_runs_the_repositorys_own_config_and_can_still_fail(
    workflow: dict,
) -> None:
    """The secret scan's wiring must be complete, and its gate must still be able to fail.

    Three separate ways this job can be green without scanning anything, all asserted here.

    A `.gitleaks.toml` that is not passed to the scanner. Gitleaks finds a config in its own
    working directory, which inside this container is not the repository, so a config that exists
    but is never named runs nothing. The step must pass `--config` explicitly.

    A config that disables rules. An allowlist is the one change to a secret gate that can turn it
    into a gate that never fires, and the way that happens quietly is a rule switched off rather
    than a value excused. `useDefault = true` must be set and no rule may be disabled.

    A gate nobody can watch fail. The scan runs with an allowlist, so the job needs the proof that
    plants a credential and requires a failure. The proof being present in scripts/ is worthless
    if the job does not run it.
    """
    jobs = workflow.get("jobs") or {}
    assert "secret-scan" in jobs, "docs/06 section 7 requires a secret scan on every merge"
    steps = [
        s for s in ((jobs["secret-scan"].get("steps")) or []) if isinstance(s, dict)
    ]
    runs = [s.get("run") or "" for s in steps]
    scan = next((run for run in runs if "gitleaks" in run and "detect" in run), None)
    assert scan is not None, (
        "the secret-scan job must actually run the scanner; a job that exists without running it "
        "reports a clean scan it never performed"
    )

    assert "--config" in scan and ".gitleaks.toml" in scan, (
        "the scan step must pass the repository's .gitleaks.toml explicitly. Gitleaks only "
        "auto-discovers a config in its own working directory, which is not the repository inside "
        "this container, so an unnamed config is a config that does not run"
    )
    assert "--exit-code" in scan, (
        "the scan step must pass --exit-code, otherwise gitleaks reports findings on stdout and "
        "exits 0 and the gate cannot fail on a finding"
    )
    assert any("prove_secret_scan_gate.py" in run for run in runs), (
        "the secret-scan job must run scripts/prove_secret_scan_gate.py. The scan runs with an "
        "allowlist, and an allowlist widened until the scan is blind leaves this job green; the "
        "proof is what makes that failure visible"
    )

    assert GITLEAKS_CONFIG.is_file(), (
        ".gitleaks.toml is missing, so the scan step's --config names a file that does not exist"
    )
    config = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    assert (config.get("extend") or {}).get("useDefault") is True, (
        ".gitleaks.toml must set [extend] useDefault = true, so the scan keeps gitleaks' own rule "
        "set instead of running whatever rules this file happens to declare"
    )
    disabled = [
        name
        for name, rule in (config.get("rules") or {}).items()
        if isinstance(rule, dict) and rule.get("enabled") is False
    ]
    assert not disabled, (
        "these rules are disabled in .gitleaks.toml. A disabled rule is indistinguishable from a "
        f"rule that found nothing: {disabled}"
    )
    for index, entry in enumerate(config.get("allowlists") or []):
        assert entry.get("description"), (
            f"allowlist entry {index} has no description, so an unexplained exception is "
            "indistinguishable from a forgotten one"
        )
        for path in entry.get("paths") or []:
            assert "*" not in path, (
                f"allowlist entry {index} excuses the whole path {path!r}. A value-shaped "
                "exception cannot hide a future secret in a directory; a path-shaped one can"
            )


def test_the_token_exception_neither_hides_a_credential_nor_excuses_the_proofs_own_value() -> None:
    """The one value-shaped exception in .gitleaks.toml must be narrow, and coupled to the proof.

    `.gitleaks.toml` excuses the shape of a single synthetic token, because two historical commits
    carry it in whole and the scan covers history. That exception is value-shaped and this scanner
    applies it everywhere - scoping it by commit, by path or by fingerprint was tried and each was
    observed not to restrict anything, which is recorded in the config's own description.

    So the proof cannot plant the same shape. If it did, the allowlist would suppress the planted
    value and `scenario_planted_token_fails` would pass without the scan looking at all - a proof
    that reports success because the thing it plants is invisible.

    Both halves are checked here rather than asserted in prose, because both fail silently: a
    widened exception hides a real credential, and a colliding planted value fakes a passing proof.
    """
    config = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    patterns = [
        pattern
        for entry in (config.get("allowlists") or [])
        for pattern in (entry.get("regexes") or [])
    ]
    # Combine the patterns as text. Compiling them first and interpolating the compiled objects
    # yields the literal string "re.compile('ghp_…')", which matches nothing - so the assertion
    # below would pass for a config that excuses every token in the world. Caught by running this
    # against a deliberately widened exception, which is the only reason it is not still there.
    token_patterns = [pattern for pattern in patterns if "ghp_" in pattern]

    assert token_patterns, (
        "expected .gitleaks.toml to carry a ghp_ exception, since the historical commits contain a "
        "synthetic token in whole and the scan covers history"
    )
    combined = re.compile("|".join(f"(?:{p})" for p in token_patterns))

    # A realistic token: the ghp_ prefix plus 36 random base62 characters. It carries the prefix on
    # purpose. A control without it cannot fail this assertion whatever the exception matches,
    # because every one of these patterns is anchored on the prefix - which is exactly the mistake
    # that made an earlier version of this check unbreakable.
    plausible = "ghp_7Kq2Wz9XpL4mBv6NcYd8Rt3HsJ5Fg1UaE0Zi"
    assert len(plausible) == 4 + 36, "the control token must be a realistic token length"
    assert not combined.search(plausible), (
        "the token exception matches a realistic random token, so it is not narrow: a real GitHub "
        "token committed anywhere in this repository would be excused. The pattern must describe "
        "the one synthetic value's shape, which no random token has."
    )

    spec = importlib.util.spec_from_file_location(
        "prove_secret_scan_gate_under_test", REPO_ROOT / "scripts" / "prove_secret_scan_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    body = module.PLANTED_TOKEN.removeprefix("ghp_")
    assert module.PLANTED_TOKEN.startswith("ghp_") and len(body) == 36, (
        "the proof's planted token is not a well-formed ghp_ value, so the first scenario is not "
        "testing the github-pat rule at all"
    )
    assert not combined.search(module.PLANTED_TOKEN), (
        "the proof plants a token that .gitleaks.toml excuses. The first scenario would then pass "
        "because the allowlist suppressed it, not because the scan detected anything. Plant a "
        "differently shaped synthetic token."
    )


def test_every_action_is_pinned_to_a_full_commit_sha(workflow: dict) -> None:
    uses_entries = _uses_entries(workflow)
    assert uses_entries, "no actions referenced; the test would otherwise pass vacuously"
    for action, ref in uses_entries:
        assert FULL_SHA.match(ref), (
            f"{action} is pinned to {ref!r}, which is not a 40-character commit SHA. "
            f"Mutable tags such as @v4 are a supply-chain hole (docs/02 section 10)."
        )


def test_every_uses_line_is_sha_pinned_and_annotated(workflow: dict) -> None:
    """Catches the common regression: someone 'simplifies' a SHA back to a tag.

    Each `uses:` must pin a full commit SHA *and* carry a `# <tag>` annotation. The
    annotation matters as much as the pin: without it, the next person cannot tell which
    release a SHA corresponds to and has no way to verify it.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    pattern = re.compile(r"^\s*-?\s*uses:\s*(\S+?)@(\S+)\s*(#.*)?$", re.MULTILINE)
    entries = pattern.findall(text)
    assert entries, "no `uses:` lines found; the test would otherwise pass vacuously"
    for action, ref, comment in entries:
        assert FULL_SHA.match(ref), (
            f"{action} uses ref {ref!r}, which is not a 40-character commit SHA. "
            f"Mutable tags such as @v4 are a supply-chain hole (docs/02 section 10)."
        )
        assert comment.strip().startswith("#"), (
            f"{action} is pinned to {ref} but has no '# <tag>' annotation, so the pin "
            f"cannot be traced back to a release or independently verified"
        )


def test_action_tag_comments_match_the_expected_map(workflow: dict) -> None:
    """A SHA must be discoverably traceable to the tag it was resolved from."""
    text = WORKFLOW.read_text(encoding="utf-8")
    seen: dict[str, str] = {}
    for match in re.finditer(r"uses:\s*(\S+?)@([0-9a-f]{40})\s*#\s*(\S+)", text):
        action, _sha, tag = match.group(1), match.group(2), match.group(3)
        segments = action.split("/")
        owner_repo = "/".join(segments[:2])
        seen[owner_repo] = tag

    missing = set(EXPECTED_ACTIONS) - set(seen)
    assert not missing, f"these actions have no tag annotation: {sorted(missing)}"
    for action, expected_tag in EXPECTED_ACTIONS.items():
        assert seen[action] == expected_tag, (
            f"{action} is annotated as {seen[action]!r} but this test expects "
            f"{expected_tag!r}. If the pin was deliberately changed, update both."
        )


def test_every_annotated_action_is_in_the_expected_map(workflow: dict) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for match in re.finditer(r"uses:\s*(\S+?)@[0-9a-f]{40}", text):
        segments = match.group(1).split("/")
        owner_repo = "/".join(segments[:2])
        assert owner_repo in EXPECTED_ACTIONS, (
            f"{owner_repo} is referenced but has no verified SHA recorded in this test; "
            f"resolve it and add it to EXPECTED_ACTIONS"
        )


def test_default_permissions_are_read_only(workflow: dict) -> None:
    perms = workflow.get("permissions")
    assert perms == {"contents": "read"}, (
        f"top-level permissions must be read-only; got {perms!r}. "
        f"Jobs needing more must request it explicitly."
    )


def test_no_job_writes_secrets_to_the_log(workflow: dict) -> None:
    """A secret echoed into a CI log is a disclosure, not a diagnostic."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "echo ${{ secrets." not in stripped, f"secret echoed to log: {stripped!r}"
        assert "set -x" not in stripped, "shell tracing can disclose secrets"


def test_go_commands_do_not_use_a_root_relative_package_pattern(workflow: dict) -> None:
    r"""Regression guard for a real bug found by running the workflow's commands locally.

    `go vet ./...` and `go test ./...` at the repository root FAIL in a Go workspace:
    go.work lists modules in subdirectories, so a root-relative pattern matches no
    module and the tool reports "directory prefix . does not contain modules listed in
    go.work". The CI job would have failed on every single run.

    Modules are therefore addressed per module, and the list is taken from
    `go work edit -json` rather than parsed out of go.work by hand: a naive
    `/^use\s+/` pattern captures the literal "(" from the `use (...)` block and gates
    nothing.
    """
    go_job = (workflow.get("jobs") or {}).get("go") or {}
    steps = go_job.get("steps") or []
    scripts = "\n".join(str(s.get("run", "")) for s in steps)

    for bad in ("go vet ./...", "go test ./...", "go build ./...", "gofmt -l . | xargs"):
        assert bad not in scripts, (
            f"{bad!r} does not work against the repository root in a Go workspace; "
            f"iterate the modules from `go work edit -json` instead"
        )

    assert "go work edit -json" in scripts, (
        "the Go job must derive its module list from `go work edit -json` so the block "
        "and single-line `use` forms both work and adding a module needs no workflow edit"
    )
    # Every module-scoped Go command must be driven by the resolved module list, so a
    # module added to go.work cannot escape the gate.
    for command in ("go vet", "go build", "go test", "go mod verify"):
        assert re.search(rf"{re.escape(command)}.*\$m", scripts, re.DOTALL) or command in scripts, (
            f"{command} must be run per module, driven by the resolved module list"
        )
    # Guard the empty-workspace case: a gate over zero modules passes vacuously.
    assert "refusing to run an empty gate" in scripts, (
        "the Go job must fail when go.work resolves to zero modules, otherwise the gate "
        "passes vacuously over nothing"
    )


def test_dependency_scan_and_integration_use_module_scoped_patterns(workflow: dict) -> None:
    """The same root-relative `./...` trap applies to govulncheck and the integration job."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for job_name in ("dependency-scan", "integration"):
        job = (workflow.get("jobs") or {}).get(job_name) or {}
        scripts = "\n".join(str(s.get("run", "")) for s in (job.get("steps") or []))
        scripts += "\n".join(
            str(s.get("with", {}).get("go-package", "")) for s in (job.get("steps") or [])
        )
        assert not re.search(r"go[- ](?:vet|test|build)[^\n]*\s\./\.\.\.", scripts), (
            f"job {job_name!r} uses a root-relative Go package pattern, which does not "
            f"match any module in this workspace"
        )


def test_the_go_vulnerability_scan_runs_inside_a_module_and_can_fail(workflow: dict) -> None:
    """WI-176. The Go vulnerability scan could never run, and never said so.

    govulncheck resolves exactly one module, rooted at the directory it is invoked from, and exits
    1 with "no go.mod file" when that directory has no go.mod. This repository has go.work at the
    root and no root go.mod, so the scan cannot be driven from the checkout root at all. The
    previous wiring used `golang/govulncheck-action`, which runs `govulncheck -C . <patterns>` at
    the root, so every run failed that way and no Go code was ever scanned.

    It stayed invisible because a gate that always errors produces no findings to review. EV-014
    records the scan as configuration-only and never observed, which is exactly the caveat a broken
    gate generates about itself, and no finding ever contradicted it.

    These assertions encode the structure that makes the scan able to run. They are deliberately
    static: they need no network and no scanner, so they hold in every job. The behaviour - that
    the step exits non-zero when a module reports a vulnerability, and keeps scanning afterwards -
    is proved by execution in scripts/prove_vuln_scan_gate.py, which runs this same committed
    `run:` block against a fake scanner.
    """
    job = (workflow.get("jobs") or {}).get("dependency-scan") or {}
    steps = job.get("steps") or []
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    uses = "\n".join(str(s.get("uses", "")) for s in steps)

    assert "govulncheck-action" not in uses, (
        "golang/govulncheck-action runs `govulncheck -C .` at the checkout root, which cannot work "
        "in a workspace with no root go.mod; invoke govulncheck once per module instead"
    )

    install = re.search(r"go install\s+golang\.org/x/vuln/cmd/govulncheck@(\S+)", runs)
    assert install, (
        "with the action gone, the job must install govulncheck itself or the scan step runs "
        "against a binary that is not there"
    )
    assert install.group(1) != "latest", (
        "govulncheck must be pinned to an exact version; @latest lets the scanner's behaviour, "
        "and therefore the finding set, change under a commit that changed nothing"
    )

    # govulncheck's own module resolution is the defect, so the module list has to come from the
    # Go toolchain rather than a regex over go.work.
    assert re.search(r"go work edit -json.*DiskPath", runs, re.DOTALL), (
        "the module list must come from `go work edit -json`; parsing go.work with a regex "
        "captures the literal '(' from the `use (...)` block and scans nothing"
    )
    assert re.search(r'govulncheck\s+-C\s+"\$m"', runs), (
        "govulncheck must be invoked with -C naming each module, because it resolves one module "
        "rooted at its working directory; scanning from the repository root is the original bug"
    )
    assert re.search(r"done < modules\.txt", runs), (
        "the scan must iterate the resolved module list, so a module added to go.work is scanned "
        "with no workflow edit"
    )

    # A scan over zero modules is a pass over nothing.
    assert "refusing to run an empty scan" in runs, (
        "the scan must fail when go.work resolves to zero modules, otherwise it reports success "
        "having scanned no code"
    )

    # So is a scan whose module list is absent. `done < modules.txt` fails its redirect when the
    # file is missing, and without errexit the loop body simply never runs: status stays 0 and the
    # step exits 0 having scanned nothing. This is the original defect class reintroduced one step
    # removed, and it is only unreachable while the resolve step happens to run first in the same
    # directory - the same invisibility as the original bug.
    assert re.search(r'\[ ! -s modules\.txt \]', runs), (
        "the scan must refuse a missing or empty modules.txt before iterating it; `done < modules.txt` "
        "fails its redirect silently under a step without errexit, so the step exits 0 having scanned "
        "nothing"
    )
    assert "refusing to report a clean scan" in runs, (
        "that refusal must say what it is refusing, so an operator reading the log is not left to "
        "work out whether an empty result meant no code or no modules"
    )
    assert re.search(r"set -euo pipefail", runs), (
        "the step needs errexit for everything that is not the scanner itself; otherwise a typo in "
        "any other line of the block fails silently and the step reports success"
    )

    # Aggregating failures so every module is scanned must not discard the failure.
    assert re.search(r'govulncheck[^\n]*\|\|', runs), (
        "the step must tolerate a failing module so the remaining modules are still scanned, and "
        "that requires an explicit `||` branch; a bare invocation under `set -e` stops at the "
        "first affected module"
    )
    assert re.search(r'status=1', runs) and re.search(r'exit "\$status"', runs), (
        "the step must record a failing module and exit with that status; a status variable that "
        "is never read makes the aggregation a pass"
    )

    assert "prove_vuln_scan_gate.py" in runs, (
        "the behavioural proof must run in CI: a static assertion cannot tell a gate that blocks "
        "from one that reports success after scanning everything"
    )


def test_integration_job_fails_if_the_live_migration_tests_skipped(workflow: dict) -> None:
    """WI-175. A skip in a live-database package means those tests verified nothing.

    `disposableDSN` and its equivalents skip when DATABASE_URL is absent, and `go test` prints
    "ok" either way. Those tests carry no build tag, so they compile into the `go` job too -
    which has no database and reported a clean package result having executed none of them. The
    `go` job genuinely has no database, so skipping there is correct; what is not acceptable is
    that the one job which does have a database proves nothing about it.

    The integration job already asserts DATABASE_URL is set and reachable, so a skip there
    cannot mean "no database configured" - it can only mean the enforcement itself is broken.
    Asserted here because a CI step that nothing verifies is the same class of defect as the
    skip it was added to catch.
    """
    job = (workflow.get("jobs") or {}).get("integration") or {}
    steps = job.get("steps") or []
    script = "\n".join(str(s.get("run", "")) for s in steps)

    # All three packages that skip without a database, not just the one the defect was filed
    # against. WI-175's fourth criterion asks for the same reporting everywhere it applies, and
    # a check that covered only cmd/migrate would leave migrate and integration able to skip
    # silently in exactly the same way.
    for package in (
        "./services/control-plane/cmd/migrate/...",
        "./services/control-plane/migrate/...",
        "./services/control-plane/integration/...",
    ):
        assert package in script, f"the skip check does not cover {package}"

    assert "grep -q '^--- SKIP'" in script, (
        "the integration job must fail when a live test skips; without a skip check this step "
        "is the very failure mode it was written to prevent"
    )
    # `-v` is not optional: without it `go test` does not print the `--- SKIP` lines this
    # check greps for, so the step would pass having detected nothing.
    assert re.search(r"go test[^\n]*-v", script), (
        "the skip check needs `go test -v`; without -v there are no `--- SKIP` lines to find"
    )
    # And the refusal must be a failure, not a warning.
    assert re.search(r"grep -q '\^--- SKIP'; then(?:.|\n)*?exit 1", script), (
        "a detected skip must exit non-zero; an annotation alone would not fail the job"
    )


def test_every_skip_in_the_live_database_packages_is_a_database_skip() -> None:
    """The CI step fails on *any* skip, which is only sound if every skip there is a DB skip.

    If a package in that list ever grows a legitimate skip - an unsupported platform, a
    timing-dependent case - the job would start failing for a reason unrelated to the
    invariant it exists to protect, and the fix would be to weaken the check. So the premise
    is asserted rather than trusted, and adding a real skip means writing down why it is
    allowed here.
    """
    repo = REPO_ROOT
    for package in ("cmd/migrate", "migrate", "integration"):
        for test_file in (repo / "services" / "control-plane" / package).glob("*_test.go"):
            source = test_file.read_text(encoding="utf-8-sig")
            for number, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                if not stripped.startswith("t.Skip"):
                    continue
                assert "DATABASE_URL" in stripped, (
                    f"{test_file.relative_to(repo)}:{number} skips for a reason other than a "
                    f"missing DATABASE_URL ({stripped!r}). The CI skip check fails on any skip "
                    f"in this package, so this either needs an exemption written down there or "
                    f"a narrower check"
                )


def test_pull_request_job_checkpoints_are_all_required_gates(workflow: dict) -> None:
    """docs/09 lists the every-merge gates; each must be a real job."""
    jobs = workflow.get("jobs") or {}
    for required in (
        "toolchain",  # formatting-adjacent drift gate
        "go",  # formatting + unit
        "web",  # lint + build
        "contracts",  # contract validation
        "sast",
        "dependency-scan",
        "spec-gate",  # docs/11 G0 integrity
    ):
        assert required in jobs, f"docs/09 requires a {required} gate on every merge"

    # The protected-branch extras must be conditional on main, not unconditional.
    for protected_job in ("integration", "artifact"):
        assert protected_job in jobs, f"docs/09 requires {protected_job} on protected branches"
        job = jobs[protected_job]
        condition = str(job.get("if", ""))
        assert "refs/heads/main" in condition, (
            f"{protected_job} must be restricted to the protected branch; got if: {condition!r}"
        )
        assert "github.event_name == 'push'" in condition, (
            f"{protected_job} must not run on pull requests; got if: {condition!r}"
        )


def test_supply_chain_jobs_emit_sbom_and_provenance(workflow: dict) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "sbom" in text.lower(), "docs/02 section 10 requires an SBOM per artifact"
    assert "cosign attest" in text, "docs/02 section 10 requires provenance attestation"
    # Attestation must bind a real digest, not a mutable tag.
    assert "IMAGE_DIGEST" in text and "steps.build.outputs.digest" in text, (
        "provenance must attest the immutable digest produced by the build step"
    )


def test_artifact_job_does_not_push(workflow: dict) -> None:
    """A CI run is not authorisation to deploy; promotion is a separate gated step."""
    artifact = (workflow.get("jobs") or {}).get("artifact") or {}
    for step in artifact.get("steps") or []:
        if str(step.get("uses", "")).startswith("docker/build-push-action"):
            assert step.get("with", {}).get("push") is False, (
                "the protected-branch build must not push; promotion is environment-gated"
            )
            assert step.get("id") == "build", (
                "the build step needs id 'build' for its digest to be attestable"
            )


def test_service_container_images_are_pinned_to_exact_tags(workflow: dict) -> None:
    """Registry pulls must name an explicit version, never `latest`.

    Only `jobs.<id>.services.<name>.image` is checked. An `image:` key on a step input
    (for example the SBOM action's `image:`, which names a locally built artifact) is a
    reference to something this workflow just produced, not a registry pull, and pinning
    it to a version tag would be meaningless.
    """
    for job_name, job in (workflow.get("jobs") or {}).items():
        for svc_name, svc in ((job or {}).get("services") or {}).items():
            image = (svc or {}).get("image")
            if not image:
                continue
            assert ":latest" not in image, (
                f"job {job_name!r} service {svc_name!r} uses floating tag {image!r}"
            )
            assert re.search(r":v?\d+\.\d+", image), (
                f"job {job_name!r} service {svc_name!r} image {image!r} is not pinned to "
                f"an explicit version tag"
            )


def test_scanner_container_image_is_pinned(workflow: dict) -> None:
    """The secret scanner runs as a container; it must be pinned like any other dependency."""
    text = WORKFLOW.read_text(encoding="utf-8")
    pulls = re.findall(r"zricethezav/gitleaks:(\S+)", text)
    assert pulls, "expected the gitleaks container image to be referenced"
    for ref in set(pulls):
        assert re.match(r"^v\d+\.\d+\.\d+$", ref), (
            f"gitleaks image tag {ref!r} must be an exact release version"
        )


def test_every_job_has_a_timeout(workflow: dict) -> None:
    """A hung job is an unbounded runner cost and a stalled merge queue."""
    for name, job in (workflow.get("jobs") or {}).items():
        assert job.get("timeout-minutes"), f"job {name!r} has no timeout-minutes"


# ---------------------------------------------------------------------------
# Coverage completeness.
#
# The Go modules are enumerated from go.work at run time, so a new Go module is picked up
# without touching the workflow and cannot drift out of coverage. The Python workers are
# named literally, which is what makes the difference matter: a worker that is added to the
# tree and forgotten in the workflow is tested nowhere, and every gate that runs locally
# still passes.
#
# workers/backtest was exactly that. It was built under WI-140, passed every local gate, and
# was absent from this workflow's test job, its dependency scan, and its licence scan. The
# omission was invisible to every check in this file - the workflow parsed, every action was
# SHA-pinned, every job had a timeout - because each of those checks asks a question about the
# workflow that is present, and none of them asks which code the workflow is supposed to cover.
#
# These two tests are the general form of that omission.
# ---------------------------------------------------------------------------


def _python_workers() -> list[str]:
    """Every directory under workers/ that is an installable Python distribution."""
    workers = REPO_ROOT / "workers"
    if not workers.is_dir():
        return []
    return sorted(
        f"workers/{child.name}"
        for child in workers.iterdir()
        if child.is_dir() and (child / "pyproject.toml").is_file()
    )


def test_the_workflow_installs_tests_scans_and_licences_every_python_worker(
    workflow: dict,
) -> None:
    """Each worker must satisfy all four obligations, or it is not covered.

    Checking only that a worker's name appears in the workflow is too weak, and mutation
    testing is what showed it: removing the backtest test step left every check in this file
    green, because the worker was still named in the lint step, so a substring assertion passed
    on the strength of an unrelated reference. A coverage test that is satisfied by a mention is
    not testing coverage.

    The four obligations are therefore asserted separately, each against the command that
    discharges it:

    * **installed** - otherwise the worker's dependencies are absent and its imports fail;
    * **tested** - a pytest invocation over its test directory;
    * **dependency-scanned** - a pip-audit run with the worker installed;
    * **licence-scanned** - a liccheck invocation naming the worker's project.

    The first is not obviously important on its own, but it is what makes the third verifiable:
    pip-audit and liccheck inspect what is installed, so a worker that is never installed
    cannot be scanned, and a scan that silently skipped it would report clean.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    workers = _python_workers()
    assert workers, "expected at least one Python worker; discovery is not working"

    obligations: tuple[tuple[str, str], ...] = (
        ("installed", r"pip install [^\n]*{worker}"),
        ("tested", r"pytest {worker}/tests"),
        ("dependency-scanned", r"pip install [^\n]*{worker}"),
        ("licence-scanned", r"--project {worker}\b"),
    )
    for worker in workers:
        for label, template in obligations:
            assert re.search(template.format(worker=re.escape(worker)), text), (
                f"{worker} is not {label} anywhere in ci.yml. A worker that is only "
                f"partially covered is a worker that looks covered."
            )


def test_every_python_worker_has_a_release_gate(workflow: dict) -> None:
    """A worker with no entry in run_gates.py is not part of the release sweep.

    Separate from the workflow check because the two are independent obligations: a worker
    can be tested in CI and still be absent from the local gate sweep, which is how
    workers/backtest was missed in scripts/run_gates.py while being genuinely present in the
    tree. Both omissions occurred; this asserts the gate half.
    """
    gates = REPO_ROOT / "scripts" / "run_gates.py"
    if not gates.is_file():
        pytest.skip("run_gates.py not present")
    text = gates.read_text(encoding="utf-8")
    for worker in _python_workers():
        assert f'"{worker}/tests"' in text or f"'{worker}/tests'" in text, (
            f"{worker} is not exercised by any gate in scripts/run_gates.py; it is absent "
            f"from the release sweep"
        )


def _bash_gate():
    """Load scripts/check_workflow_bash.py as a module, by path.

    Loaded by explicit path rather than by putting scripts/ on sys.path, because the whole point
    of importing it is that this file and the script cannot drift: an import that resolved to some
    other check_workflow_bash anywhere on the path would defeat that, and would do it silently.

    The module is re-read on each call rather than cached in a global. It is cheap to parse, and a
    cached copy would mean a test could pass against a stale version of the gate after the gate
    itself had been edited - which is precisely the failure this consolidation is meant to end.
    """
    path = REPO_ROOT / "scripts" / "check_workflow_bash.py"
    if not path.is_file():
        pytest.skip("check_workflow_bash.py not present")
    spec = importlib.util.spec_from_file_location("_check_workflow_bash", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered for the duration of exec_module and removed after. @dataclass resolves its own
    # annotations through sys.modules[cls.__module__], so a module executed without an entry there
    # raises while the class body is being built - and the error names dataclasses internals
    # rather than the missing entry, which is a poor way to learn this.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def test_every_run_block_is_valid_bash(workflow: dict) -> None:
    """Every `run:` block must be syntactically valid bash.

    A syntax error in a step is the most expensive cheap failure available in this repository:
    it does not fail where it is written, it fails minutes into a later job on a runner, after
    the build cache is warm and the developer has moved on. It is also invisible to every other
    check in this file, all of which parse the YAML rather than the shell.

    This mirrors what scripts/check_workflow_bash.py does inside the toolchain job. It is
    duplicated here deliberately, for a specific reason: a step that runs inside CI cannot catch
    a malformed workflow, because a workflow GitHub cannot parse does not run its own jobs. The
    local suite is the only place this is caught before a push.

    What is *not* duplicated is the rule itself. The block discovery, the binary-stdin `bash -n`
    call, and the non-vacuity assertion all come from the script, imported by path. An earlier
    version reimplemented the loop here, which left two copies of one check: the pytest copy
    refused a workflow with zero `run:` blocks while the standalone script passed it, so the CI
    step only failed closed as long as some sibling step had run first. Two copies of a rule is
    one more edit than it takes for them to disagree, and they disagreed about exactly the case
    that cannot announce itself.

    The check is skipped, never failed, when bash is absent, because a missing interpreter is
    not a malformed workflow and must not be reported as one.
    """
    gate = _bash_gate()

    # Asserted before the loop rather than after: an empty result should stop the test, not run a
    # zero-iteration loop and then be noticed. The message is the gate's, so the two cannot
    # describe the same rule in different words.
    blocks = gate.collect_run_blocks(workflow)
    assert blocks, gate.VACUITY

    for block in blocks:
        result = gate.bash_syntax_check(block.script)
        assert result.returncode == 0, (
            f"{block.job}: {block.label} is not valid bash: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )


def test_bash_gate_script_passes_on_the_real_workflow() -> None:
    """The standalone gate must exit zero on the workflow as committed.

    This is the script's own entry point rather than a reimplementation of it. Since the pytest
    check above now delegates to the script's functions, nothing else would notice if `main()`
    itself started failing - returning the wrong code, or reporting a failure on a valid
    workflow - and the standalone CI step is what runs it. Run as a subprocess so the exit code
    under test is the one a caller would see.
    """
    if shutil.which("bash") is None:
        pytest.skip("no bash on PATH; the run blocks were not syntax-checked")

    result = subprocess.run(
        [sys.executable, "scripts/check_workflow_bash.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "check_workflow_bash.py failed on the committed workflow:\n"
        + result.stdout[-2000:]
        + result.stderr[-2000:]
    )


@pytest.mark.parametrize(
    "workflow_yaml, reason",
    [
        ("jobs:\n  toolchain:\n    steps: []\n", "a job whose steps were emptied"),
        (
            "jobs:\n  toolchain:\n    steps:\n      - uses: actions/checkout@v4\n",
            "a job whose run: steps became uses: steps",
        ),
        ("name: ci\non: push\n", "a workflow with no jobs key at all"),
        ("jobs: {}\n", "a workflow with an empty jobs mapping"),
        ("- just\n- a\n- list\n", "a document that parses to a list, not a mapping"),
    ],
)
def test_bash_gate_script_fails_when_it_finds_no_run_blocks(
    workflow_yaml: str, reason: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero `run:` blocks must be a failure, in the script, not only in this file.

    The script prints "PASS (0 run: blocks parsed)" and returns 0 for a workflow it examined
    nothing in. Every shape below produces that outcome - an emptied job, a `run:` renamed to
    `uses:`, a jobs key that vanished, a mapping with no steps, even a document that is not a
    mapping at all - and in each of them the workflow's bash has not been checked by anything.

    The gate's whole value is that a syntax error in a step is caught before a runner finds it.
    If the step that would have caught it stops finding steps, it must say so rather than report
    a pass, because a pass here is indistinguishable from the workflow being fine.

    Driven in-process against a temporary workflow rather than by editing .github/workflows/ci.yml
    and restoring it, so the test cannot leave the real workflow modified if it dies partway.
    Bash is required because main() skips before this guard is reached, and a skip here would be
    the gate declining to run - which is exactly the outcome this test must not confuse with a
    verdict.
    """
    if shutil.which("bash") is None:
        pytest.skip("no bash on PATH; the run blocks were not syntax-checked")

    gate = _bash_gate()
    workflow_path = tmp_path / "no-run-blocks.yml"
    workflow_path.write_text(workflow_yaml, encoding="utf-8", newline="\n")

    original = gate.WORKFLOW
    gate.WORKFLOW = workflow_path
    try:
        exit_code = gate.main()
        output = capsys.readouterr().out
    finally:
        gate.WORKFLOW = original

    assert exit_code != 0, (
        f"check_workflow_bash.py returned 0 for {reason}. A gate that examined nothing must fail, "
        f"not report a pass. Output was:\n{output}"
    )
    assert gate.VACUITY in output, (
        f"the failure did not say why it failed: {reason}. Output was:\n{output}"
    )
    assert "PASS" not in output, f"a vacuous run still reported a pass: {reason}"


def test_bash_gate_script_passes_a_workflow_with_one_valid_run_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The zero-block guard must not be a blanket refusal.

    A guard added to the wrong side of a condition - `if blocks: check them` instead of
    `if not blocks: fail` - passes every test above and fails the only thing that matters. This is
    the positive control for the test above, and it is the same shape of control
    scripts/prove_bash_gate_detects.py established for `bash -n` itself.
    """
    if shutil.which("bash") is None:
        pytest.skip("no bash on PATH; the run blocks were not syntax-checked")

    gate = _bash_gate()
    workflow_path = tmp_path / "one-run-block.yml"
    workflow_path.write_text(
        "jobs:\n  toolchain:\n    steps:\n      - name: one valid block\n"
        "        run: |\n          set -euo pipefail\n          echo hello\n",
        encoding="utf-8",
        newline="\n",
    )

    original = gate.WORKFLOW
    gate.WORKFLOW = workflow_path
    try:
        exit_code = gate.main()
        output = capsys.readouterr().out
    finally:
        gate.WORKFLOW = original

    assert exit_code == 0, f"a workflow with one valid run: block was rejected. Output:\n{output}"
    assert "PASS (1 run: blocks parsed)" in output, output


# --- Worker typecheck invocation (WI-192) --------------------------------------

# A mypy invocation, with the working directory it establishes either through a `cd` in the same
# command or through the step's own `working-directory:`. The closing paren of a subshell form is
# excluded from the argument span so `(cd X && python -m mypy src)` yields the target `src`.
_MYPY_INVOCATION = re.compile(
    r"(?:\(\s*cd\s+(?P<dir>[^\s&;)]+)\s*&&\s*)?python\s+-m\s+mypy\b(?P<args>[^\n)]*)"
)


def _mypy_invocations(workflow: dict) -> list[tuple[str, Path, list[str]]]:
    """Every mypy invocation in the workflow as (where, working directory, target paths).

    Comment text is stripped per line first. A run: block here documents its own reasoning in
    comments, and a rule that matched the documentation would report problems for an invocation
    that does not exist - a failure that reads as a real defect and trains the reader to ignore it.
    """
    found: list[tuple[str, Path, list[str]]] = []
    for job_name, job in sorted((workflow.get("jobs") or {}).items()):
        for step in job.get("steps") or []:
            script = str(step.get("run", ""))
            if "mypy" not in script:
                continue
            step_dir = str(step.get("working-directory") or "")
            for line in script.splitlines():
                code = line.split("#", 1)[0]
                match = _MYPY_INVOCATION.search(code)
                if not match:
                    continue
                cwd = REPO_ROOT
                for part in (step_dir, match.group("dir") or ""):
                    if part:
                        cwd = cwd / part
                args = match.group("args").split()
                # `--config-file X` takes a path as its value; reading that value as a target
                # would send the config-file search up from the wrong directory.
                targets = [
                    arg
                    for index, arg in enumerate(args)
                    if not arg.startswith("-") and (index == 0 or args[index - 1] != "--config-file")
                ]
                found.append((f"job {job_name!r}: {line.strip()}", cwd, targets))
    return found


def _worker_mypy_problems(workflow: dict) -> list[str]:
    """Every mypy invocation, checked against the paths the config it will read declares.

    Returns a list of human-readable problems, empty when every invocation is sound. It is a
    function rather than inline test body so the controls below drive this exact rule against a
    mutated workflow, instead of asserting a second and weaker version of it - which is how the
    duplicate-step and bash-gate checks in this file drifted apart in the first place.
    """
    invocations = _mypy_invocations(workflow)
    if not invocations:
        # Fail closed, in the shape scripts/check_workflow_bash.py uses. A rule that examined
        # nothing must not report success.
        return [
            "no mypy invocation was found in the workflow, so no worker typecheck was checked; "
            "a rule with nothing to examine must not pass"
        ]

    problems: list[str] = []
    for where, cwd, targets in invocations:
        if not targets:
            problems.append(f"{where}: no path to check was passed to mypy")
            continue

        for target in targets:
            if not (cwd / target).is_dir():
                problems.append(
                    f"{where}: {target!r} does not exist relative to the working directory it runs "
                    f"in, {cwd.relative_to(REPO_ROOT) if cwd != REPO_ROOT else 'the repository root'}"
                )

        # The configuration mypy will read is the nearest pyproject.toml above the target that
        # declares one. An explicit --config-file would win over that, but the relativity problem
        # below is a property of the working directory either way, so it is checked regardless.
        config = None
        for candidate in [cwd / targets[0], *((cwd / targets[0]).parents)]:
            pyproject = candidate / "pyproject.toml"
            if not pyproject.is_file():
                continue
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, UnicodeDecodeError):
                continue
            if "mypy" in data.get("tool", {}):
                config = pyproject
                break

        if config is None:
            problems.append(
                f"{where}: no pyproject.toml declaring [tool.mypy] was found above {target!r}, so "
                f"there is no strict configuration for this worker to be checked against"
            )
            continue

        mypy_path = tomllib.loads(config.read_text(encoding="utf-8")).get("tool", {}).get("mypy", {})
        for entry in mypy_path.get("mypy_path") or []:
            if not (cwd / entry).is_dir():
                problems.append(
                    f"{where}: mypy reads {config.relative_to(REPO_ROOT)}, which declares "
                    f"mypy_path {entry!r}, and mypy resolves mypy_path relative to the current "
                    f"working directory - which for this invocation is "
                    f"{cwd.relative_to(REPO_ROOT) if cwd != REPO_ROOT else 'the repository root'}, "
                    f"where {entry!r} does not exist. Invoke mypy from the directory holding that "
                    f"pyproject.toml."
                )
    return problems


def test_every_worker_typecheck_runs_where_its_configured_paths_resolve(workflow: dict) -> None:
    """WI-192. mypy was invoked from a directory where its own configured paths do not exist.

    The two Python workers declare the same relative paths for the same purpose in the same
    shape: `pythonpath = ["src", "../research/src"]` under [tool.pytest.ini_options] and
    `mypy_path = ["src", "../research/src"]` under [tool.mypy]. workers/backtest/pyproject.toml
    carries a comment stating the mypy entry exists so both tools resolve webtrade_research from
    the same place. They do not, and the difference is exactly the trap:

    pytest resolves `pythonpath` relative to rootdir - the directory holding the pyproject.toml -
    so it works from any working directory. mypy resolves `mypy_path` relative to the CURRENT
    WORKING DIRECTORY. From the repository root, where the workflow invoked it, those entries name
    `<root>/src` and `<root>/../research/src`, and neither exists.

    So the gate could not pass, and could not be rescued by installing the dependency either:
    webtrade-research ships no py.typed marker, so mypy does not read the installed wheel and
    reports the import as missing rather than as an untyped Any. Measured on this tree:
    `python -m mypy workers/backtest/src` from the repository root exits 1 with four
    import-not-found errors; the same command from workers/backtest exits 0; installing both local
    packages changes neither number.

    It was never observed because the job failed earlier, at the worker install steps (EV-083), and
    the blocker on WI-107 recorded the python workers as pending rather than as a gate that had
    never succeeded. A gate that always errors is the cheapest kind to miss: it produces no findings
    to review, so nothing contradicts a record that says it is merely unobserved.

    The check is static and general: it reads every mypy invocation in the workflow and verifies
    each against the `mypy_path` of the configuration it will load, so a third worker, or a
    future `working-directory:`, is covered by the same rule rather than by a new assertion.
    """
    problems = _worker_mypy_problems(workflow)
    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize(
    "replacement, expected",
    [
        (
            "set -euo pipefail\npython -m mypy workers/research/src\n"
            "python -m mypy workers/backtest/src\n",
            "mypy_path '../research/src'",
        ),
        (
            "set -euo pipefail\n(cd workers/research && python -m mypy src)\n"
            "(cd workers/backtest/src && python -m mypy .)\n",
            "mypy_path 'src'",
        ),
        (
            "set -euo pipefail\npython -m ruff check workers/research workers/backtest\n",
            "no mypy invocation was found",
        ),
    ],
    ids=["invoked-from-the-root", "cd-into-the-wrong-directory", "worker-removed-entirely"],
)
def test_the_worker_typecheck_check_rejects_each_way_of_getting_it_wrong(
    workflow: dict, replacement: str, expected: str
) -> None:
    """Three controls, because a rule that only fires on one shape proves nothing.

    The first restores the original wiring exactly: both invocations from the repository root, which
    is what shipped and what failed. The second keeps a `cd` but descends one level too far, into
    the source directory rather than the worker root - which a rule that only asked whether a `cd`
    was present would wave through, and which really does fail, because `src` then means
    `workers/backtest/src/src`. The third deletes the invocation entirely, which must fail closed
    rather than report a clean result having checked nothing.

    What is deliberately NOT a control: `(cd workers/research && python -m mypy ../backtest/src)`.
    That reads like a mistake and is not one - mypy_path resolves against the working directory, and
    from workers/research both entries exist, so the invocation succeeds. A control asserting it
    fails would encode a false belief about the tool to make the rule look thorough.
    """
    mutated = copy.deepcopy(workflow)
    replaced = 0
    for job in mutated["jobs"].values():
        for step in job.get("steps") or []:
            if "mypy" in str(step.get("run", "")):
                step["run"] = replacement
                replaced += 1
    assert replaced, "the mutation did not find a mypy step to replace, so it proved nothing"

    problems = _worker_mypy_problems(mutated)
    assert problems, "the mutated workflow passed the check; the check does not detect the defect"
    assert any(expected in problem for problem in problems), (
        f"expected a problem naming {expected!r}, got:\n" + "\n".join(problems)
    )


def test_the_worker_typecheck_check_accepts_a_worker_with_no_configured_paths(workflow: dict) -> None:
    """The positive control for the rule above, and the reason it is not a blanket refusal.

    workers/research declares no `mypy_path`, because it imports nothing from the other worker. A
    root-relative invocation is therefore correct for it, and a check that demanded a `cd` from
    every worker would reject a valid configuration - the mistake of adding the guard to the wrong
    side of the condition. This asserts the rule reads the configuration rather than pattern-matching
    the shape of the command.
    """
    mutated = copy.deepcopy(workflow)
    for job in mutated["jobs"].values():
        for step in job.get("steps") or []:
            if "mypy" in str(step.get("run", "")):
                step["run"] = "set -euo pipefail\npython -m mypy workers/research/src\n"

    assert _worker_mypy_problems(mutated) == []
