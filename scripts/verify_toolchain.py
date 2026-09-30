#!/usr/bin/env python3
"""Fail the build on toolchain drift or floating dependency versions.

docs/00_README.md requires that the exact selected toolchain versions are recorded and
that "CI must fail on unpinned dependencies or toolchain drift".
docs/02_POLYGLOT_ENGINEERING_STANDARD.md section 7 requires that "CI rejects floating
dependency versions, uncommitted lockfile changes, and toolchain drift".

This script is the single implementation of that rule. It lives in the repository rather
than inline in the workflow so that the exact same check runs locally, in a pre-commit
hook, and in CI, and so that it can be unit tested.

Exit codes:
    0  all checks pass
    1  at least one check failed
    2  the script itself could not run (missing file, unparsable manifest)

Usage:
    python scripts/verify_toolchain.py [--repo-root .] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# An exact version pin: three dotted numeric components, optional pre-release/build
# suffix. Deliberately strict. "1.2", "^1.2.3", ">=1.2", "1.x", "latest" and any VCS or
# URL specifier all fail, because each of them makes the build non-reproducible.
EXACT_VERSION = re.compile(
    r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$"
)

# Floating-specifier prefixes that must never appear in a manifest.
FLOATING_PREFIX = ("^", "~", ">", "<", "*", "=", "!=")

# Go modules, in go.work order. Each is a separate module with its own build definition
# and artifact identity (docs/02 section 8).
GO_MODULES = (
    "contracts/go/go.mod",
    "services/control-plane/go.mod",
    "components/risk-engine/go.mod",
    "components/oms/go.mod",
    "components/reconciliation/go.mod",
    "adapters/venues/go.mod",
)

PYTHON_WORKSPACES = (
    "workers/research/pyproject.toml",
    "workers/backtest/pyproject.toml",
)

LOCKFILES = ("apps/web/package-lock.json",)


@dataclass
class Report:
    """Collects check outcomes so one run reports every problem, not just the first.

    Failing fast on the first problem would make a contributor fix issues one CI run at a
    time, so every check is evaluated and all failures are reported together.
    """

    failures: list[str] = field(default_factory=list)
    checks_run: int = 0

    def check(self, ok: bool, message: str) -> bool:
        self.checks_run += 1
        if not ok:
            self.failures.append(message)
        return ok

    @property
    def passed(self) -> bool:
        return not self.failures


def read_pinned_versions(repo_root: Path, report: Report) -> dict[str, str]:
    """Parse toolchain/versions.env, the single source of truth for pinned versions."""
    path = repo_root / "toolchain" / "versions.env"
    if not path.is_file():
        report.check(False, f"missing {path.relative_to(repo_root)}: no pinned toolchain to compare against")
        return {}

    pinned: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            report.check(False, f"toolchain/versions.env:{lineno}: not a KEY=VALUE assignment: {line!r}")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key in pinned:
            report.check(False, f"toolchain/versions.env:{lineno}: duplicate key {key!r}")
        pinned[key] = value
        report.check(
            value != "",
            f"toolchain/versions.env:{lineno}: {key} is pinned to an empty value",
        )
    return pinned


def verify_go_drift(repo_root: Path, pinned: dict[str, str], report: Report) -> None:
    """Every module's go directive must equal the pinned Go version exactly.

    A module pinned to a different patch level than its siblings would build against a
    different toolchain than the workspace was verified with, which is exactly the
    drift docs/00 prohibits.
    """
    want = pinned.get("GO_VERSION")
    if not want:
        return

    for rel in GO_MODULES:
        path = repo_root / rel
        if not path.is_file():
            report.check(False, f"{rel}: missing Go module")
            continue
        match = re.search(r"^go\s+(\S+)\s*$", path.read_text(encoding="utf-8"), re.MULTILINE)
        if not match:
            report.check(False, f"{rel}: no 'go' directive found")
            continue
        got = match.group(1)
        report.check(
            got == want,
            f"{rel}: go directive is {got!r} but toolchain/versions.env pins GO_VERSION={want!r}",
        )


def verify_node_drift(repo_root: Path, pinned: dict[str, str], report: Report) -> None:
    """apps/web/package.json engines.node must equal the pinned Node version.

    Absent engines is itself a failure: without it, npm will happily build on an
    arbitrary Node and the drift gate would have nothing to compare.
    """
    want = pinned.get("NODE_VERSION")
    if not want:
        return

    path = repo_root / "apps" / "web" / "package.json"
    if not path.is_file():
        report.check(False, "apps/web/package.json: missing")
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        report.check(False, f"apps/web/package.json: unparsable JSON: {exc}")
        return

    got = (manifest.get("engines") or {}).get("node")
    report.check(
        got == want,
        f"apps/web/package.json: engines.node is {got!r} but toolchain/versions.env pins NODE_VERSION={want!r}",
    )


def verify_python_drift(repo_root: Path, pinned: dict[str, str], report: Report) -> None:
    """Each Python workspace must pin the same major.minor as PYTHON_VERSION.

    The workspace manifests pin a minor series (==3.14.*) rather than a patch, because
    patch selection belongs to the resolver. The gate therefore enforces the series and
    leaves patch selection to the lock step, which must then be reviewed.
    """
    want = pinned.get("PYTHON_VERSION")
    if not want:
        return
    want_series = ".".join(want.split(".")[:2])

    for rel in PYTHON_WORKSPACES:
        path = repo_root / rel
        if not path.is_file():
            report.check(False, f"{rel}: missing Python workspace")
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            report.check(False, f"{rel}: unparsable TOML: {exc}")
            continue

        got = (data.get("project") or {}).get("requires-python")
        if got is None:
            report.check(False, f"{rel}: no project.requires-python; the interpreter is unpinned")
            continue
        if want_series not in got:
            report.check(
                False,
                f"{rel}: requires-python is {got!r}, which does not pin the series "
                f"{want_series!r} selected in toolchain/versions.env",
            )


def verify_node_pins(manifest: dict, rel: str, report: Report) -> None:
    """Node dependencies must be exact versions.

    A caret or tilde range is a floating dependency version. docs/02 forbids it in CI
    even though it is idiomatic in the wider npm ecosystem, because the resulting build
    is not reproducible.
    """
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        for name, spec in (manifest.get(section) or {}).items():
            if not isinstance(spec, str):
                report.check(False, f"{rel}: {section}.{name} is not a string: {spec!r}")
                continue
            if spec.startswith(FLOATING_PREFIX) or spec in ("latest", "next", "stable"):
                report.check(
                    False,
                    f"{rel}: {section}.{name}={spec!r} is a floating or range specifier; pin an exact version",
                )
            elif not EXACT_VERSION.match(spec):
                report.check(
                    False,
                    f"{rel}: {section}.{name}={spec!r} is not an exact version; "
                    f"a VCS, URL, or wildcard specifier makes the build non-reproducible",
                )


def _iter_pinned_requirements(section: object) -> list[tuple[str, str]]:
    """Normalise a requirements section to (name, specifier) pairs.

    PEP 621 permits `dependencies` as an array of PEP 508 strings ("numpy==2.5.1"), and
    toolchains in common use also accept a table ({name = "numpy==2.5.1"}). Extras
    (`optional-dependencies`) are a table of such sections, keyed by extra name. Handling
    all three shapes here keeps the caller a simple loop.
    """
    pairs: list[tuple[str, str]] = []

    if isinstance(section, list):
        for entry in section:
            if not isinstance(entry, str):
                pairs.append(("<malformed>", repr(entry)))
                continue
            # Split on the first comparison operator, falling back to a bare name.
            match = re.match(r"^([A-Za-z0-9._\-\[\]]+)\s*(.*)$", entry.strip())
            if not match:
                pairs.append((entry, ""))
            else:
                pairs.append((match.group(1), match.group(2).strip()))
        return pairs

    if isinstance(section, dict):
        for name, spec in section.items():
            pairs.append((name, spec if isinstance(spec, str) else repr(spec)))
        return pairs

    return pairs


def verify_python_pins(data: dict, rel: str, report: Report) -> None:
    """Python dependencies must use == exact pins.

    Lower bounds (">=1.0"), compatible-release clauses ("~=1.0"), bare names and any
    environment marker are all floating, because each lets the resolver pick a different
    version over time. An environment marker is rejected outright rather than skipped:
    a marker makes the resolved set platform-dependent, and these workers must resolve
    identically on a developer machine and in CI.
    """
    project = data.get("project") or {}
    for group in ("dependencies", "optional-dependencies"):
        raw = project.get(group) or []
        if group == "optional-dependencies" and isinstance(raw, dict):
            # Extras: a table of tables. Report under the extra name for a clear message.
            for extra, deps in raw.items():
                _verify_pin_pairs(_iter_pinned_requirements(deps), f"{rel}: {group}[{extra}]", report)
        else:
            _verify_pin_pairs(_iter_pinned_requirements(raw), f"{rel}: {group}", report)


def _verify_pin_pairs(pairs: list[tuple[str, str]], label: str, report: Report) -> None:
    for name, spec in pairs:
        if not spec:
            report.check(False, f"{label}: {name} has no version specifier; it is unpinned")
            continue
        if ";" in spec:
            report.check(
                False,
                f"{label}: {name} uses an environment marker ({spec!r}); "
                f"a marker makes the resolved set platform-dependent",
            )
            continue
        if not spec.startswith("=="):
            report.check(
                False,
                f"{label}: {name}={spec!r} is not an exact '==' pin; "
                f"any other specifier lets the resolver drift",
            )


def verify_go_pins(path: Path, rel: str, report: Report) -> None:
    """Go requirements must resolve to a tagged release, not a moving reference.

    Go normally pins to an exact commit, so the failures that matter here are the ones
    that deliberately escape that behaviour: a `latest` keyword, and a `v0.0.0-...`
    pseudo-version, which by definition does not correspond to a tagged release.

    Both the block form (`require (` ... `)`) and the single-line form (`require mod vX`)
    are parsed. Parsing only the block form would leave every single-line require
    unchecked, which is a silent hole in a supply-chain gate.
    """
    text = path.read_text(encoding="utf-8")
    # Drop whole-line comments and trailing `// indirect` style comments.
    text = "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())

    versions: set[tuple[str, str]] = set()

    for block in re.findall(r"^require\s*\((.*?)^\s*\)", text, re.MULTILINE | re.DOTALL):
        for line in block.splitlines():
            parts = line.split()
            if len(parts) == 2:
                versions.add((parts[0], parts[1]))

    # `(?!\()` prevents the single-line pattern from matching the opener of a block
    # directive, where it would otherwise capture "(" as the module name. Block entries
    # are collected above, and the set discards the resulting double-count.
    for mod, ver in re.findall(r"^require\s+(?!\()(\S+)\s+(\S+)", text, re.MULTILINE):
        versions.add((mod, ver))

    # `replace old => new version` — the replacement side must be pinned too.
    #
    # Matching is per line on purpose. An earlier version used `\s+` between the
    # groups, and `\s` matches newlines: for a directory replace, which carries no
    # version, the pattern happily crossed the line break and swallowed whatever
    # token followed — a comment, a blank line, or nothing at all. When the
    # directory replace happened to be the last line of the file the pattern matched
    # nothing, so local replaces went entirely unchecked.
    for line in text.splitlines():
        m = re.match(r"^replace[ \t]+(\S+)[ \t]+=>[ \t]+(\S+)(?:[ \t]+(\S+))?$", line)
        if not m:
            continue
        old, new, ver = m.group(1), m.group(2), m.group(3)
        # A filesystem replace is a deliberate local wiring directive, not a version
        # reference, so there is no version to pin. Pinning is not even expressible
        # here; the Go toolchain resolves it from the working tree.
        #
        # The discriminator must not be "contains a slash": a versioned replace points
        # at a module path such as `example.com/fork`, which also contains one.
        # Local targets are relative (./, ../), absolute (/), or a Windows drive.
        is_local_path = (
            ver is None
            or new.startswith((".", "/"))
            or re.match(r"^[A-Za-z]:", new)
        )
        if is_local_path:
            continue
        versions.add((f"{old} => {new}", ver))

    for mod, ver in sorted(versions):
        if ver == "latest":
            report.check(False, f"{rel}: dependency {mod} is pinned to 'latest'")
        elif ver.startswith("v0.0.0-"):
            report.check(
                False,
                f"{rel}: dependency {mod} uses pseudo-version {ver!r}, "
                f"which does not correspond to a tagged release",
            )
        elif not re.match(r"^v\d+\.\d+\.\d+", ver):
            report.check(
                False,
                f"{rel}: dependency {mod} is pinned to {ver!r}, which is not a tagged "
                f"release version",
            )


def verify_lockfiles(repo_root: Path, report: Report) -> None:
    """A lockfile must exist for every ecosystem that has a lockfile format.

    This asserts presence and basic integrity. It cannot assert that the lockfile matches
    the manifest: `npm ci` is the authoritative check for that, and it runs as a separate
    CI step which fails hard when the two disagree.
    """
    for rel in LOCKFILES:
        path = repo_root / rel
        if not report.check(path.is_file(), f"{rel}: lockfile missing; the build graph is not reproducible"):
            continue
        try:
            lock = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.check(False, f"{rel}: unparsable lockfile JSON: {exc}")
            continue
        report.check(
            isinstance(lock.get("lockfileVersion"), int) and lock["lockfileVersion"] >= 2,
            f"{rel}: lockfileVersion must be an integer >= 2, got {lock.get('lockfileVersion')!r}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=".", help="repository root (default: current directory)")
    parser.add_argument("--quiet", action="store_true", help="print only the summary and any failures")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report = Report()

    try:
        pinned = read_pinned_versions(repo_root, report)
    except OSError as exc:
        print(f"toolchain gate could not run: {exc}", file=sys.stderr)
        return 2

    if pinned:
        verify_go_drift(repo_root, pinned, report)
        verify_node_drift(repo_root, pinned, report)
        verify_python_drift(repo_root, pinned, report)

    package_json = repo_root / "apps" / "web" / "package.json"
    if package_json.is_file():
        try:
            manifest = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.check(False, f"apps/web/package.json: unparsable JSON: {exc}")
        else:
            verify_node_pins(manifest, "apps/web/package.json", report)

    for rel in GO_MODULES:
        path = repo_root / rel
        if path.is_file():
            verify_go_pins(path, rel, report)

    for rel in PYTHON_WORKSPACES:
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            report.check(False, f"{rel}: unparsable TOML: {exc}")
        else:
            verify_python_pins(data, rel, report)

    verify_lockfiles(repo_root, report)

    if not args.quiet and report.passed:
        print(f"toolchain gate: {report.checks_run} checks passed")

    if report.failures:
        print(f"\ntoolchain gate FAILED ({len(report.failures)} of {report.checks_run} checks):", file=sys.stderr)
        for failure in report.failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"toolchain gate: PASS ({report.checks_run} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
