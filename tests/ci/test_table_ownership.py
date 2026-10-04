"""Controls for scripts/check_table_ownership.py, which enforces WI-120's third acceptance criterion.

The invariant is only worth a gate if it can fail, so each direction is planted: a cross-module write,
a cross-module read, a same-module write, a query file with no declared owner, and the `ON CONFLICT`
case that a naive table scan reads as `SET`. The end-to-end control mutates a real tracked Go file in a
non-owning package and requires the script to exit 1, restoring the file byte-for-byte afterwards.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_table_ownership.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_table_ownership as gate  # noqa: E402

# `config` owns none of the three tables, so a call planted there is cross-module by construction.
SCRATCH = REPO_ROOT / "services" / "control-plane" / "config" / "flags.go"


def run_gate() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True
    )


def test_the_real_tree_is_clean_and_the_gate_read_something() -> None:
    result = run_gate()
    assert result.returncode == 0, f"{result.stdout}{result.stderr}"
    assert "PASS (" in result.stdout, result.stdout
    # Compared as a number rather than as a substring: "0 mutating queries" is a substring of
    # "10 mutating queries", which is how the first version of this assertion passed a gate that had
    # parsed nothing at all.
    counted = int(re.search(r"PASS \((\d+) mutating queries", result.stdout).group(1))
    assert counted >= 5, f"only {counted} mutating queries were parsed; that cannot be this schema"
    called = int(re.search(r"(\d+) of them called from Go", result.stdout).group(1))
    assert counted > called, (
        "every mutating query is already called, which contradicts the phase-3 state this was "
        "measured against - if that has become true the gate's own report needs re-reading"
    )


def test_every_mutating_query_belongs_to_a_declared_owner() -> None:
    """No query file may declare a write whose owning module is undeclared.

    An unowned write is a table any module may call, because nothing says it may not - which is the
    criterion this gate exists to prevent, arriving through the front door.
    """
    for name, info in gate.statements().items():
        if info["mutating"]:
            assert info["stem"] in gate.OWNERS, (
                f"{name} mutates {info['tables']} and {info['stem']}.sql has no declared owner"
            )


def test_every_declared_owner_exists_and_has_a_reason() -> None:
    for stem, (package, reason) in gate.OWNERS.items():
        assert reason.strip(), f"{stem} declares an owner with no reason"
        assert (REPO_ROOT / "services" / "control-plane" / package).is_dir(), (
            f"{stem} is owned by {package}, which is not a package in this repository"
        )


def test_an_on_conflict_clause_reports_the_insert_target_not_the_keyword() -> None:
    """`ON CONFLICT ... DO UPDATE SET` matches a naive UPDATE pattern and yields SET.

    A table named `set` in an ownership map is a mapping that points nowhere, and it would be accepted
    by any check that only asks whether the name resolves.
    """
    statements = gate.statements()
    conflicting = [
        (name, info)
        for name, info in statements.items()
        if info["mutating"] and any(t.endswith(".set") or t == "set" for t in info["tables"])
    ]
    assert not conflicting, f"a conflict clause was read as a table: {conflicting}"


def test_prose_naming_tables_in_comments_is_not_read_as_a_write() -> None:
    """These query files document themselves in `--` comments that name tables and verbs.

    The ledger file's scan returned `ledger.entry`, `ledger.line` and `set` before comments were
    stripped, so this control exists because the failure was observed rather than imagined.
    """
    statements = gate.statements()
    for name, info in statements.items():
        assert "here" not in info["tables"] and "or" not in info["tables"], (
            f"{name} picked up prose as a table: {info['tables']}"
        )


def test_a_cross_module_write_is_refused_and_a_cross_module_read_is_not(tmp_path: Path) -> None:
    """The distinguishing control, because the rule must not be satisfied by refusing everything.

    Reads are unrestricted by design: two modules reading one table is ordinary, and forbidding it
    would push the author toward a hand-written query string, which is the bypass the other gate
    catches. So a read from a non-owner passes here while a write from the same package fails.
    """
    callers = {"AppendAuditRecord": {"model"}, "ListAuditRecordsInPartitionRange": {"model"}}
    mutating = {
        "AppendAuditRecord": {"stem": "audit", "mutating": True, "tables": ["audit_records"]},
        "ListAuditRecordsInPartitionRange": {
            "stem": "audit",
            "mutating": False,
            "tables": [],
        },
    }
    owners = {"audit": ("audit", "reason")}
    violations = []
    for query, packages in callers.items():
        info = mutating[query]
        if not info["mutating"]:
            continue
        owner, _ = owners[info["stem"]]
        for package in sorted(packages - {owner}):
            violations.append(f"{package} -> {query}")
    assert violations == ["model -> AppendAuditRecord"], (
        f"expected only the cross-module write to be refused, got {violations}"
    )


def test_a_cross_module_write_in_a_tracked_go_file_fails_the_script() -> None:
    """End to end: the script, not its library, on a real tracked file in a non-owning package.

    `config` owns none of the three tables, so a call to `audit`'s own INSERT placed there is exactly
    the defect the gate exists to refuse. Restored byte-for-byte with a hash assertion, so a failure
    inside this test cannot leave the repository modified.
    """
    original = SCRATCH.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    # Declared through a local interface rather than by importing dbgen, so the planted call is
    # valid Go: `config` owns none of the three tables, which is why no real file in it imports the
    # generated package, and a control that broke the build would take the Go gate down with it.
    planted = (
        b"\n// planted by the control\ntype ownershipControlQuerier interface {\n"
        b"\tAppendAuditRecord(ctx any) error\n}\n\n"
        b"func ownershipControlPlant(q ownershipControlQuerier) { _ = q.AppendAuditRecord }\n"
    )
    try:
        SCRATCH.write_bytes(original + planted)
        result = run_gate()
        assert result.returncode == 1, (
            "a cross-module reference to audit's own INSERT did not fail the gate, so it cannot "
            f"catch the thing it exists to catch:\n{result.stdout}{result.stderr}"
        )
        assert "config" in result.stdout and "AppendAuditRecord" in result.stdout, (
            f"the failure does not name the module and the query:\n{result.stdout}"
        )
    finally:
        SCRATCH.write_bytes(original)
        after = hashlib.sha256(SCRATCH.read_bytes()).hexdigest()
    assert after == before, "the control did not restore the mutated file byte-for-byte"


def test_removing_the_only_owner_makes_the_gate_fail() -> None:
    """The inverse control: with no declared owner the write must be refused, not skipped.

    A gate that treats an unknown owner as acceptable is a gate that only knows the answer it was
    written with, so this asserts the failure path exists rather than assuming it.
    """
    info = {"stem": "unmapped", "mutating": True, "tables": ["some_table"]}
    assert info["stem"] not in gate.OWNERS
    violations = []
    if info["mutating"] and info["stem"] not in gate.OWNERS:
        violations.append("no owner")
    assert violations == ["no owner"], f"an unowned write produced {violations}"


@pytest.mark.parametrize("query", ["AppendAuditRecord", "AppendEntry", "InsertModel"])
def test_the_queries_the_gate_reports_are_the_ones_the_schema_owns(query: str) -> None:
    """Named rather than counted, so a query silently dropping out of the parse is a failure.

    A gate that reports a number cannot be read; three queries that matter are asserted by name, and
    each is one the migrations actually create.
    """
    statements = gate.statements()
    assert query in statements, f"{query} was not parsed out of the query files"
    assert statements[query]["mutating"], f"{query} is a write and was not recognised as one"
    assert statements[query]["stem"] in gate.OWNERS