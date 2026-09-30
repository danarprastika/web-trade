"""Structural proof that neither worker can hold financial authority.

docs/02 and docs/25 section 4 put the research and backtest workers outside the authority
boundary: they hold no credentials, submit nothing, and have no write path to any
authoritative financial table. The worker READMEs assert this in prose. Prose is not a control —
it is reviewed once and then never again, while a dependency added in a later commit is
reviewed by nobody. So the claims are asserted here against the source as it stands.

Three things are checked, in increasing order of how likely they are to be breached by accident:

1. **Imports.** Neither package may import a network, database, or process-spawning module. A
   worker that cannot import ``socket`` cannot open a connection, whatever a later patch asks
   it to do. The research trust zone cannot route to control-plane data stores at all
   (docs/01 section 9), so the capability should not exist in the import graph.
2. **Declared dependencies.** This is the check most likely to catch a real breach, because a
   dependency is how a capability usually arrives. ``httpx`` in ``dependencies`` would give the
   worker a network stack without any source file importing it yet, so a source-only scan would
   miss the most likely failure.
3. **Credential-shaped literals.** A hard-coded secret does not need a network module to be a
   problem; it leaks by being copied into a ticket.

The tests deliberately use :mod:`ast` rather than a text search. The module docstrings discuss
credentials, sockets, and database drivers at length, and a regex over the source would either
match that prose or be tuned until it stopped matching — either way it would stop describing the
property it claims to describe.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_ROOT = RESEARCH_ROOT.parent / "backtest"

WORKER_ROOTS = (RESEARCH_ROOT, BACKTEST_ROOT)

# Modules that would grant a capability the authority boundary forbids. Split by intent so a
# failure names the reason rather than just the module.
FORBIDDEN_MODULES: dict[str, str] = {
    # Network egress. A worker that cannot open a socket cannot reach a venue, a registry, or a
    # control-plane service, regardless of what a later change intends.
    "socket": "network egress",
    "ssl": "network egress",
    "http": "network egress",
    "urllib": "network egress",
    "urllib3": "network egress",
    "requests": "network egress",
    "httpx": "network egress",
    "aiohttp": "network egress",
    "ftplib": "network egress",
    "smtplib": "network egress",
    "telnetlib": "network egress",
    "xmlrpc": "network egress",
    # Authoritative data stores. The research trust zone cannot route to control-plane stores
    # (docs/01 section 9), so a database driver here is a routing path that should not exist.
    "psycopg": "authoritative store access",
    "psycopg2": "authoritative store access",
    "asyncpg": "authoritative store access",
    "pg8000": "authoritative store access",
    "sqlite3": "authoritative store access",
    "sqlalchemy": "authoritative store access",
    # Process execution. A worker that can spawn a process can shell out to a tool that reaches
    # anywhere, which would make every capability above a policy question rather than a fact.
    "subprocess": "process execution",
    "multiprocessing": "process execution",
    "ctypes": "process execution",
}

# Distribution names that would provide a forbidden capability transitively. Checked against
# declared dependencies, where a capability is most likely to be introduced.
FORBIDDEN_DISTRIBUTIONS = {
    "requests", "httpx", "aiohttp", "urllib3", "websockets", "paramiko",
    "psycopg", "psycopg2", "psycopg-binary", "asyncpg", "pg8000", "sqlalchemy",
    "pymysql", "mysqlclient", "pymongo",
}

# Credential shapes specific enough to have no false positives against prose. A generic
# "password" search would match every docstring in both packages.
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{12,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
)


def _package_sources(root: Path) -> list[Path]:
    """Every module in a worker's importable package, excluding tests and caches.

    Tests are excluded on purpose: a test may legitimately import a module the package itself
    must not, and the boundary is about the code that would run in a research worker.
    """
    package = next((root / "src").glob("webtrade_*"))
    return sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_roots(path: Path) -> set[str]:
    """Top-level names imported by *path*, from its AST rather than its text."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_the_scanner_actually_finds_the_source_it_is_supposed_to_scan() -> None:
    """Guard the guard.

    Every test below is satisfied vacuously if :func:`_package_sources` returns an empty list —
    an unreadable path, a renamed package, or a moved directory would turn the authority
    boundary from an enforced property into a silent pass. A structural test that cannot report
    its own blindness is not a control, so the scanner is asserted to see both workers and a
    plausible number of modules before its output is trusted.

    The count is a floor rather than an exact number so that adding a module does not break
    this, while losing a whole worker does.
    """
    found = {root.name: _package_sources(root) for root in WORKER_ROOTS}
    for name, sources in found.items():
        assert len(sources) >= 3, f"the scanner saw {len(sources)} files in {name}; it is blind"
    assert set(found) == {"research", "backtest"}, (
        f"the scanner covered {sorted(found)}, not both workers"
    )
    # Each worker must report the modules that exist today, so a partial traversal is caught.
    assert "dataset.py" in {p.name for p in found["research"]}
    assert "harness.py" in {p.name for p in found["backtest"]}


def test_no_worker_imports_a_forbidden_capability() -> None:
    """Neither package may reach a network, a database, or a subprocess.

    Asserted per module rather than as a set, so a failure says which file broke the boundary.
    """
    violations: list[str] = []
    for root in WORKER_ROOTS:
        for path in _package_sources(root):
            for imported in sorted(_imported_roots(path) & set(FORBIDDEN_MODULES)):
                reason = FORBIDDEN_MODULES[imported]
                violations.append(f"{path.name}: imports {imported!r} ({reason})")
    assert not violations, "authority boundary breached by import:\n" + "\n".join(violations)


def test_no_worker_declares_a_dependency_that_grants_a_forbidden_capability() -> None:
    """The most likely breach is a dependency, not an import.

    Adding ``httpx`` to ``dependencies`` gives the worker a full network stack while every
    source file remains clean, so a source-only scan would pass while the capability is
    present. This is the check that makes the import scan above sufficient rather than
    reassuring.
    """
    violations: list[str] = []
    for root in WORKER_ROOTS:
        pyproject = root / "pyproject.toml"
        declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        requirements = {
            item
            for key in ("dependencies",)
            for item in declared.get("project", {}).get(key, [])
        }
        for section in ("dev",):
            requirements.update(
                declared.get("project", {}).get("optional-dependencies", {}).get(section, [])
            )
        for requirement in sorted(requirements):
            name = re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].strip().lower()
            if name in FORBIDDEN_DISTRIBUTIONS:
                violations.append(f"{pyproject.name}: declares {name!r}")
    assert not violations, "authority boundary breached by dependency:\n" + "\n".join(violations)


def test_no_worker_source_contains_a_credential_shaped_literal() -> None:
    """A hard-coded secret needs no network module to leak; it leaks by being copied."""
    violations: list[str] = []
    for root in WORKER_ROOTS:
        for path in _package_sources(root):
            text = path.read_text(encoding="utf-8")
            for pattern in CREDENTIAL_PATTERNS:
                if pattern.search(text):
                    violations.append(f"{path.name}: matches {pattern.pattern}")
    assert not violations, "credential-shaped literal found:\n" + "\n".join(violations)


def test_the_workers_declare_no_scripts_that_could_bypass_the_boundary() -> None:
    """Neither package may ship a console entry point.

    A ``[project.scripts]`` entry makes the worker runnable by anyone who can install it. That
    is not an authority breach by itself, but it is the shape a promote-and-execute tool would
    take, and its absence is free to assert and awkward to reintroduce by accident.
    """
    violations: list[str] = []
    for root in WORKER_ROOTS:
        declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        for name in declared.get("project", {}).get("scripts", {}):
            violations.append(f"{root.name}: declares script {name!r}")
    assert not violations, "worker exposes an executable entry point:\n" + "\n".join(violations)


def test_every_declared_dependency_is_pinned_exactly() -> None:
    """A range or unpinned requirement is a moving capability boundary.

    The boundary checked above is only as stable as the dependency set. A requirement like
    ``httpx>=0.20`` can pull a new distribution in transitively on any future resolve, and the
    check for it would then pass or fail according to install order rather than according to
    the source (docs/02 section 10, docs/00 toolchain lifecycle).
    """
    offenders: list[str] = []
    for root in WORKER_ROOTS:
        declared = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        project = declared.get("project", {})
        requirements = list(project.get("dependencies", []))
        for section in declared.get("project", {}).get("optional-dependencies", {}).values():
            requirements.extend(section)
        for requirement in requirements:
            if not re.search(r"==\s*[0-9]", requirement):
                offenders.append(f"{root.name}: {requirement!r}")
    assert not offenders, "unpinned dependency:\n" + "\n".join(offenders)
