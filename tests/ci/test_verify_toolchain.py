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
