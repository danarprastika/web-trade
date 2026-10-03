"""Tests for scripts/verify_toolchain.py.

A CI gate is only worth its runtime if it fails when it should. Every failure mode the
gate claims to detect is exercised here against a synthetic repository, so a future
refactor cannot quietly weaken the gate while leaving the happy path green.

Run:
    python -m pytest tests/ci -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_gate():
    """Import verify_toolchain.py as a module.

    The script lives outside the package tree and the repository root is not guaranteed
    to be on sys.path under every runner, so it is loaded by explicit path rather than
    by name.
    """
    spec = importlib.util.spec_from_file_location(
        "verify_toolchain", REPO_ROOT / "scripts" / "verify_toolchain.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        pytest.skip("verify_toolchain.py could not be located")
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_toolchain"] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()

VERSIONS = """\
GO_VERSION=1.26.2
NODE_VERSION=24.18.0
PYTHON_VERSION=3.14.6
POSTGRES_IMAGE=postgres:17.11-alpine
"""

GO_MOD = "module {pkg}\n\ngo 1.26.2\n"

PYPROJECT_ARRAY = """\
[project]
name = "webtrade-research"
version = "0.1.0"
requires-python = "==3.14.*"
dependencies = [
    "numpy==2.5.1",
    "pydantic==2.12.4",
]
"""

PACKAGE_JSON = {
    "name": "@webtrade/web",
    "version": "0.1.0",
    "private": True,
    "engines": {"node": "24.18.0"},
    "dependencies": {"next": "16.3.6", "react": "19.2.8"},
    "devDependencies": {"typescript": "5.9.3"},
}

LOCKFILE = {"name": "@webtrade/web", "lockfileVersion": 3, "packages": {}}

# A minimal workflow carrying the env block and the service image the gate compares against. It is
# deliberately the smallest document that still contains the things under test: the gate parses the
# pins out of the text, so anything else here would be fixture the tests never exercise. The
# indentation and the bare (unquoted) image value both mirror the real workflow.
WORKFLOW = """\
name: fixture
on: [push]

env:
  GO_VERSION: '1.26.2'
  NODE_VERSION: '24.18.0'
  PYTHON_VERSION: '3.14'

jobs:
  integration:
    runs-on: ubuntu-24.04
    services:
      postgres:
        image: postgres:17.11-alpine
        env:
          POSTGRES_USER: webtrade
        ports:
          - 5432:5432
    steps:
      - run: echo hi
"""


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_repo(root: Path, **overrides) -> Path:
    """Materialise a minimal but valid repository that the gate should accept.

    Each override replaces one file's content, which is how a single test isolates a
    single failure mode without disturbing the rest of the layout.
    """
    files = {
        "toolchain/versions.env": overrides.get("versions", VERSIONS),
        ".github/workflows/ci.yml": overrides.get("workflow", WORKFLOW),
        "apps/web/package.json": overrides.get(
            "package_json", json.dumps(PACKAGE_JSON, indent=2)
        ),
        "apps/web/package-lock.json": overrides.get(
            "lockfile", json.dumps(LOCKFILE, indent=2)
        ),
        # Both Python workspaces are required by the gate, so the fixture provides both.
        "workers/research/pyproject.toml": overrides.get(
            "pyproject", PYPROJECT_ARRAY
        ),
        "workers/backtest/pyproject.toml": overrides.get(
            "pyproject_backtest", PYPROJECT_ARRAY
        ),
    }
    for module_dir in (
        "contracts/go",
        "services/control-plane",
        "components/risk-engine",
        "components/oms",
        "components/reconciliation",
        "adapters/venues",
    ):
        files[f"{module_dir}/go.mod"] = overrides.get(
            f"gomod:{module_dir}", GO_MOD.format(pkg=module_dir.replace("/", "-"))
        )

    for rel, content in files.items():
        write(root / rel, content)
    return root


# --- Happy path -------------------------------------------------------------


def test_valid_repository_passes(tmp_path: Path) -> None:
    build_repo(tmp_path)
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


# --- Toolchain drift -------------------------------------------------------


def test_go_version_drift_fails(tmp_path: Path) -> None:
    build_repo(tmp_path, **{"gomod:components/oms": "module oms\n\ngo 1.25.0\n"})
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_node_version_drift_fails(tmp_path: Path) -> None:
    manifest = {**PACKAGE_JSON, "engines": {"node": "20.0.0"}}
    build_repo(tmp_path, package_json=json.dumps(manifest, indent=2))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_missing_node_engines_fails(tmp_path: Path) -> None:
    """Without engines there is nothing to compare, so drift would be undetectable."""
    manifest = {k: v for k, v in PACKAGE_JSON.items() if k != "engines"}
    build_repo(tmp_path, package_json=json.dumps(manifest, indent=2))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_python_series_drift_fails(tmp_path: Path) -> None:
    build_repo(tmp_path, pyproject=PYPROJECT_ARRAY.replace("==3.14.*", "==3.12.*"))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_missing_versions_file_fails(tmp_path: Path) -> None:
    build_repo(tmp_path)
    (tmp_path / "toolchain" / "versions.env").unlink()
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


# --- Workflow pins mirror versions.env --------------------------------------
#
# The workflow repeats toolchain/versions.env because a workflow expression cannot read a file
# from disk. A duplicated value with nothing comparing the two copies drifts silently, and the drift
# is invisible from the manifests: env.GO_VERSION is what actions/setup-go installs, so a workflow
# left behind at an older pin builds every job on a different toolchain than the modules declare
# while every go.mod still matches versions.env and this gate reports success.
#
# The repetition comes in two shapes and both are checked, because only one of them can be read
# from `env`.


@pytest.mark.parametrize(
    ("key", "current", "behind"),
    [
        ("GO_VERSION", "1.26.2", "1.26.1"),
        ("NODE_VERSION", "24.18.0", "24.17.0"),
        ("PYTHON_VERSION", "3.14", "3.13"),
    ],
)
def test_workflow_env_behind_versions_env_fails(tmp_path: Path, key: str, current: str, behind: str) -> None:
    """Roll each env pin back one step and the gate must name it.

    The line is replaced wholesale rather than by rewriting the value in place, so the fixture keeps
    the quoting style the real workflow uses. The real workflow quotes all three of these; the
    unquoted branch of the parser is exercised by the service-image test below, whose value is bare.
    """
    line = next(l for l in WORKFLOW.splitlines() if l.startswith(f"  {key}:"))
    assert current in line, f"fixture drift: {line!r} does not carry {current!r}"
    build_repo(tmp_path, workflow=WORKFLOW.replace(line, f"  {key}: {behind}"))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


@pytest.mark.parametrize("key", ["GO_VERSION", "NODE_VERSION", "PYTHON_VERSION"])
def test_workflow_env_key_absent_fails(tmp_path: Path, key: str) -> None:
    """A pin with no line to compare against must fail, not be skipped as 'nothing to compare'.

    The workflow line is deleted rather than blanked: a key present with an empty value is a
    different document, and the point here is that the gate must not treat an absent comparison as
    a satisfied one.
    """
    stripped = "\n".join(
        line for line in WORKFLOW.splitlines() if not line.startswith(f"  {key}:")
    )
    assert f"  {key}:" in WORKFLOW, f"fixture drift: {key} is not in the fixture"
    assert f"  {key}:" not in stripped
    build_repo(tmp_path, workflow=stripped)
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_workflow_env_agrees_is_not_a_failure(tmp_path: Path) -> None:
    """The control for the tests above: matching pins must not be reported as drift."""
    build_repo(tmp_path)
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


def test_missing_workflow_fails_rather_than_skipping(tmp_path: Path) -> None:
    """A gate that cannot find its input must fail, not report success having read nothing.

    This is the EV-064 shape. If an absent workflow were treated as 'nothing to compare', the check
    would pass on exactly the repositories where it can prove nothing, and a later rename would
    silently disable it.
    """
    build_repo(tmp_path)
    (tmp_path / ".github" / "workflows" / "ci.yml").unlink()
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_unparseable_workflow_env_block_fails(tmp_path: Path) -> None:
    """A workflow with no single top-level `env:` block must fail, not silently compare nothing."""
    build_repo(tmp_path, workflow=WORKFLOW.replace("env:\n", "x-env:\n"))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_two_top_level_env_blocks_fail(tmp_path: Path) -> None:
    """Two `env:` blocks make the pin ambiguous, and an ambiguous pin is not a pin."""
    build_repo(tmp_path, workflow=WORKFLOW + "\nenv:\n  GO_VERSION: '1.26.2'\n")
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_workflow_python_patch_difference_is_not_drift(tmp_path: Path) -> None:
    """versions.env pins a full patch; the workflow pins the series. They are meant to differ.

    An exact comparison here would report a difference that is not drift, and a gate that reports
    differences that are not drift is a gate whose real output nobody reads. So PYTHON_VERSION is
    compared by major.minor - which is a constraint, not an exemption, because env.PYTHON_VERSION is
    what actions/setup-python installs and verify_python_drift never looks at this file at all.
    """
    build_repo(
        tmp_path,
        workflow=WORKFLOW.replace("PYTHON_VERSION: '3.14'", "PYTHON_VERSION: '3.14.0'"),
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


# --- The Postgres image the integration job actually runs ---------------------
#
# It cannot be an env reference. GitHub's context-availability table allows github, needs, strategy,
# matrix, vars and inputs at `jobs.<job_id>.services` and not env, so `${{ env.POSTGRES_IMAGE }}`
# under services.postgres would not resolve. An earlier version of this check therefore compared the
# then-unused env.POSTGRES_IMAGE against the pin and left the literal CI runs completely unchecked -
# a green gate that had never looked at the value it named. These tests cover the literal instead,
# and the expression case is covered too because "GitHub would not resolve it" is not something an
# operator can infer from a bare inequality.


def test_service_image_behind_the_pin_fails(tmp_path: Path) -> None:
    build_repo(
        tmp_path,
        workflow=WORKFLOW.replace("image: postgres:17.11-alpine", "image: postgres:16-alpine"),
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_service_image_removed_fails_rather_than_skipping(tmp_path: Path) -> None:
    """A service with no `image:` at all must fail, not pass on an absent comparison."""
    build_repo(
        tmp_path,
        workflow=WORKFLOW.replace("        image: postgres:17.11-alpine\n", ""),
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_service_image_as_an_env_expression_fails(tmp_path: Path) -> None:
    """An expression where GitHub cannot resolve it must be named as such, not as an inequality.

    This is the mistake the earlier design of this check was about to introduce in reverse: writing
    `${{ env.POSTGRES_IMAGE }}` there looks like the clean fix and produces a workflow GitHub
    rejects. The message has to say that, because "expected postgres:17.11-alpine, got ${{...}}"
    tells an operator only that the gate is unhappy, not that the workflow will not run.
    """
    build_repo(
        tmp_path,
        workflow=WORKFLOW.replace(
            "image: postgres:17.11-alpine", "image: ${{ env.POSTGRES_IMAGE }}"
        ),
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_every_service_image_declaration_is_checked(tmp_path: Path) -> None:
    """Two jobs can both declare postgres; comparing only the first would let the second drift.

    The fixture gains a second, drifting declaration. If the gate compared just the first match it
    would pass, and the second job would keep running an unpinned major version.
    """
    drift = WORKFLOW + (
        "\n  another:\n"
        "    runs-on: ubuntu-24.04\n"
        "    services:\n"
        "      postgres:\n"
        "        image: postgres:16-alpine\n"
    )
    build_repo(tmp_path, workflow=drift)
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_a_nested_image_key_is_not_mistaken_for_the_service_image(tmp_path: Path) -> None:
    """Only a direct child of the service block is that service's image.

    The fixture nests a deeper `image:` under the service's own `env:` block, which belongs to the
    container and is not the service image. Reading it as one would make the gate fail on a document
    that is correct, which is the other way a drift gate stops being trusted.
    """
    nested = WORKFLOW.replace(
        "        env:\n          POSTGRES_USER:",
        "        env:\n          SERVICE_IMAGE_NOT_RELEVANT: 'postgres:16-alpine'\n"
        "        env:\n          POSTGRES_USER:",
    )
    assert nested != WORKFLOW, "fixture drift: the nested-image anchor was not found"
    build_repo(tmp_path, workflow=nested)
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


# --- Floating dependency versions -------------------------------------------


@pytest.mark.parametrize(
    "spec",
    ["^16.0.0", "~16.3.6", ">=16.0.0", "16.x", "*", "latest", "next", "file:../local"],
)
def test_node_floating_specifier_fails(tmp_path: Path, spec: str) -> None:
    manifest = {**PACKAGE_JSON, "dependencies": {**PACKAGE_JSON["dependencies"], "next": spec}}
    build_repo(tmp_path, package_json=json.dumps(manifest, indent=2))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_node_two_component_version_fails(tmp_path: Path) -> None:
    """A partial pin such as "16.3" is still floating across patch releases."""
    manifest = {**PACKAGE_JSON, "dependencies": {**PACKAGE_JSON["dependencies"], "next": "16.3"}}
    build_repo(tmp_path, package_json=json.dumps(manifest, indent=2))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


@pytest.mark.parametrize("spec", ['">=2.5"', '"~=2.5.1"', '"numpy"', '"2.5.1"'])
def test_python_non_exact_pin_fails(tmp_path: Path, spec: str) -> None:
    # Replace only the version portion, keeping the requirement name intact. Substituting
    # the whole TOML string would leave a nameless entry, which trips a different check
    # and would pass even if the version-pinning logic were broken.
    build_repo(tmp_path, pyproject=PYPROJECT_ARRAY.replace("numpy==2.5.1", "numpy" + spec))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_python_bare_name_without_specifier_fails(tmp_path: Path) -> None:
    """A requirement with no version at all is the crudest form of drift."""
    build_repo(tmp_path, pyproject=PYPROJECT_ARRAY.replace("numpy==2.5.1", "numpy"))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_python_environment_marker_fails(tmp_path: Path) -> None:
    """A marker makes the resolved set platform-dependent."""
    build_repo(
        tmp_path,
        pyproject=PYPROJECT_ARRAY.replace(
            "numpy==2.5.1", "numpy==2.5.1; sys_platform == 'win32'"
        ),
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_go_latest_reference_fails(tmp_path: Path) -> None:
    build_repo(tmp_path, **{"gomod:components/oms": "module oms\n\ngo 1.26.2\n\nrequire example.com/dep latest\n"})
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_go_latest_in_block_form_fails(tmp_path: Path) -> None:
    build_repo(
        tmp_path,
        **{"gomod:components/oms": "module oms\n\ngo 1.26.2\n\nrequire (\n\texample.com/dep latest\n)\n"},
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_go_pseudo_version_fails(tmp_path: Path) -> None:
    build_repo(
        tmp_path,
        **{"gomod:components/oms": "module oms\n\ngo 1.26.2\n\nrequire example.com/dep v0.0.0-20240101120000-abcdef123456\n"},
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_go_tagged_version_passes(tmp_path: Path) -> None:
    build_repo(
        tmp_path,
        **{"gomod:components/oms": "module oms\n\ngo 1.26.2\n\nrequire (\n\texample.com/dep v1.4.2 // indirect\n)\n"},
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


# --- Go replace directives ------------------------------------------------


def test_go_local_directory_replace_passes(tmp_path: Path) -> None:
    """A filesystem replace carries no version, so there is nothing to pin."""
    build_repo(
        tmp_path,
        **{"gomod:components/oms": "module oms\n\ngo 1.26.2\n\nreplace example.com/dep => ../dep\n"},
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


def test_go_local_replace_does_not_swallow_following_line(tmp_path: Path) -> None:
    """Regression: the old pattern used `\\s+` between groups, which matches a
    newline. A directory replace followed by any text therefore had that text read
    as its version, failing a perfectly valid go.mod."""
    build_repo(
        tmp_path,
        **{
            "gomod:components/oms": (
                "module oms\n"
                "\n"
                "go 1.26.2\n"
                "\n"
                "replace example.com/dep => ../dep\n"
                "\n"
                "// a comment follows the replace\n"
                "replace example.com/other => ../other\n"
            )
        },
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


def test_go_latest_in_replace_fails(tmp_path: Path) -> None:
    """A versioned replace must still be pinned: this proves the local-replace
    exemption above did not disable the check."""
    build_repo(
        tmp_path,
        **{"gomod:components/oms": "module oms\n\ngo 1.26.2\n\nreplace example.com/dep => example.com/fork latest\n"},
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_go_pseudo_version_in_replace_fails(tmp_path: Path) -> None:
    build_repo(
        tmp_path,
        **{
            "gomod:components/oms": "module oms\n\ngo 1.26.2\n\nreplace example.com/dep => example.com/fork v0.0.0-20240101120000-abcdef123456\n"
        },
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_go_tagged_version_in_replace_passes(tmp_path: Path) -> None:
    build_repo(
        tmp_path,
        **{"gomod:components/oms": "module oms\n\ngo 1.26.2\n\nreplace example.com/dep => example.com/fork v1.4.2\n"},
    )
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 0


# --- Lockfiles --------------------------------------------------------------


def test_missing_lockfile_fails(tmp_path: Path) -> None:
    build_repo(tmp_path)
    (tmp_path / "apps" / "web" / "package-lock.json").unlink()
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


def test_lockfile_version_1_fails(tmp_path: Path) -> None:
    build_repo(tmp_path, lockfile=json.dumps({"lockfileVersion": 1}, indent=2))
    assert gate.main(["--repo-root", str(tmp_path), "--quiet"]) == 1


# --- Failure aggregation ----------------------------------------------------


def test_all_failures_are_reported_not_just_the_first(tmp_path: Path) -> None:
    """A contributor must see every problem in one run, not one fix per CI run."""
    build_repo(
        tmp_path,
        **{"gomod:components/oms": "module oms\n\ngo 1.24.0\n"},
        pyproject=PYPROJECT_ARRAY.replace("numpy==2.5.1", "numpy>=2.5"),
    )
    report = gate.Report()
    pinned = gate.read_pinned_versions(tmp_path, report)
    gate.verify_go_drift(tmp_path, pinned, report)
    gate.verify_python_pins(
        __import__("tomllib").loads((tmp_path / "workers/research/pyproject.toml").read_text()),
        "workers/research/pyproject.toml",
        report,
    )
    assert len(report.failures) == 2
    assert "go directive" in " ".join(report.failures)
    assert "numpy" in " ".join(report.failures)


def test_real_repository_passes() -> None:
    """The gate must be green against the repository it actually guards."""
    assert gate.main(["--repo-root", str(REPO_ROOT), "--quiet"]) == 0
