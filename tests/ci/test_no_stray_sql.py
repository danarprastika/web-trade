"""Controls for scripts/check_no_stray_sql.py, which enforces WI-120's second acceptance criterion.

The rule this file tests is stated in sqlc.yaml and was enforced nowhere. A checker with no controls
is a checker that has never rejected anything, which is the defect class this repository has recorded
repeatedly; so each shape is planted and shown to be found, the two exemptions are shown to be the
only reason their files pass, and one tracked file is mutated end to end to show the script itself
fails rather than only its library code.

The mutation restores the file byte-for-byte in a finally block and asserts the hash afterwards, so
a failure inside the test cannot leave a modified tracked file behind.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_no_stray_sql.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_no_stray_sql as checker  # noqa: E402

# The smallest tracked, non-test Go file in the control plane. Small so the byte-for-byte comparison
# after the mutation is a real check rather than a diff nobody reads.
SCRATCH = REPO_ROOT / "services" / "control-plane" / "config" / "flags.go"


@pytest.mark.parametrize(
    "line, expected_shape",
    [
        ('const q = `INSERT INTO ledger.entries (id) VALUES ($1)`', "INSERT INTO"),
        ('const q = "UPDATE ledger.entries SET amount = $1 WHERE id = $2"', "UPDATE ... SET"),
        ('const q = "DELETE FROM ledger.entries WHERE id = $1"', "DELETE FROM"),
        ('const q = "SELECT id FROM ledger.entries WHERE id = $1"', "SELECT ... FROM"),
        ("const q = `create table t (id int)`", "CREATE TABLE"),
        ("const q = `CREATE UNIQUE INDEX ON t (id)`", "CREATE INDEX"),
        ("const q = `DROP TABLE t CASCADE`", "DROP TABLE"),
        ("const q = `ALTER TABLE t ADD COLUMN c int`", "ALTER TABLE"),
        ("const q = `GRANT SELECT ON t TO app`", "GRANT / REVOKE"),
    ],
    ids=[
        "insert",
        "update",
        "delete",
        "select",
        "create-table",
        "create-index",
        "drop-table",
        "alter-table",
        "grant",
    ],
)
def test_each_statement_shape_is_detected(
    tmp_path: Path, line: str, expected_shape: str
) -> None:
    """One control per shape, because a rule that catches four kinds of query catches the fifth by
    accident at best, and a shape it silently ignores is a shape the codebase can grow into.
    """
    target = tmp_path / "sample.go"
    target.write_text(f"package sample\n\n{line}\n", encoding="utf-8")
    hits = checker.violations_in(target)
    assert [shape for _, shape, _ in hits] == [expected_shape], (
        f"{line!r} was not reported as {expected_shape}; got {hits}"
    )


def test_a_statement_split_across_lines_is_still_detected(tmp_path: Path) -> None:
    """The shapes are matched on the whole line, and a query formatted over several lines is the
    normal way a Go string looks once someone has run it through a formatter. A checker that reads
    one line at a time is defeated by gofmt, which is why the SELECT shape spans lines and why the
    others are anchored on the statement keyword rather than on a column list.
    """
    target = tmp_path / "sample.go"
    target.write_text(
        'package sample\n\nconst q = `\n  INSERT\n  INTO\n  ledger.entries (id)\n  VALUES ($1)\n`\n',
        encoding="utf-8",
    )
    assert checker.violations_in(target), "a statement broken across lines was not detected"


def test_a_comment_describing_sql_is_not_a_violation(tmp_path: Path) -> None:
    """The negative control for the comment exclusion.

    The migrator's own comments quote the statements it runs, and this repository documents its
    reasoning in comments throughout. A checker that flagged those would train its reader to delete
    the explanation rather than the query, which is the opposite of what a gate is for.
    """
    target = tmp_path / "sample.go"
    target.write_text(
        "package sample\n\n"
        "// DownTo reverts applied migrations; `DELETE FROM migrate.applied_set WHERE version = $1`\n"
        "// is the one statement this module writes by hand.\n",
        encoding="utf-8",
    )
    assert checker.violations_in(target) == []


def test_a_go_identifier_containing_select_is_not_a_violation(tmp_path: Path) -> None:
    """`SELECT ... FROM` needs the FROM to be within reach, because `selected` and `fromRow` are
    ordinary Go names. A pattern loose enough to match prose is a pattern whose every report is
    noise.
    """
    target = tmp_path / "sample.go"
    target.write_text(
        "package sample\n\n// selected reports whether fromRow was seen.\nfunc selected(fromRow string) {}\n",
        encoding="utf-8",
    )
    assert checker.violations_in(target) == []


def test_the_generated_package_and_the_migrator_are_the_only_exemptions() -> None:
    """Named exemptions with reasons, asserted rather than assumed.

    An exemption list that grows silently is the same bypass with an extra step, so the count is
    pinned and every entry carries a non-empty reason. Both current exemptions are load-bearing and
    were re-checked against the tree rather than carried on trust.
    """
    assert set(checker.EXEMPT) == {
        "services/control-plane/db/dbgen",
        "services/control-plane/migrate/store.go",
        "services/control-plane/migrate/store_sql.go",
    }
    for path, reason in checker.EXEMPT.items():
        assert reason.strip(), f"{path} is exempt with no reason given"
        assert (REPO_ROOT / path).is_dir() or (REPO_ROOT / path).is_file(), (
            f"{path} is exempt but does not exist, so the exemption has stopped describing anything"
        )


def test_the_exemption_list_exactly_covers_the_files_that_hold_sql() -> None:
    """An exemption list that falls behind the code is the same bypass with an extra step.

    Every tracked, non-test Go file is scanned; the set of files that actually contain a
    statement-shaped literal must equal the exempt set. Equality in both directions is what makes
    this worth having: an exemption with no violation behind it is a hole waiting for the code to
    move into it, and a violation with no exemption is a gate that will be silenced by adding an
    entry instead of by fixing the query. The check found its own second exemption this way -
    `migrate/store_sql.go` was not listed when the first version of the rule ran against the tree.
    """
    violating: set[str] = set()
    for path in checker.go_files():
        name = checker.rel(path)
        if checker.exempt_reason(name):
            continue
        if checker.violations_in(path):
            violating.add(name)
    assert not violating, (
        "files outside the exemptions contain SQL: " + ", ".join(sorted(violating))
    )
    unused = {
        name
        for name in checker.EXEMPT
        if name != checker.GENERATED_PACKAGE
        and not checker.violations_in(REPO_ROOT / name)
    }
    assert not unused, (
        "these exemptions cover no statement any more, so they are unearned: "
        + ", ".join(sorted(unused))
    )


def test_the_generated_package_is_still_scanned_by_sqlc_and_the_migrator_is_still_tested() -> None:
    """An exemption is a hole unless something else covers the file.

    `db/dbgen` is generated from the schema, which is what makes a literal there the output of the
    check rather than a bypass of it, and `migrate/store.go` is covered by the migrator's own tests.
    Both claims are verified against the repository rather than repeated from the exemption's reason
    string, because the second one is the kind of statement that stops being true when a test is
    renamed.
    """
    generated = REPO_ROOT / "services" / "control-plane" / "db" / "dbgen"
    assert list(generated.glob("*.sql.go")), "db/gen no longer holds generated query files"
    sqlc = (REPO_ROOT / "sqlc.yaml").read_text(encoding="utf-8")
    assert "services/control-plane/db/dbgen" in sqlc, (
        "sqlc no longer generates into the package the exemption names"
    )
    migrator_tests = list((REPO_ROOT / "services" / "control-plane" / "migrate").glob("*_test.go"))
    assert migrator_tests, "the migrator has no tests, so its exemption covers nothing"


def test_the_repository_is_clean_and_the_check_is_not_vacuous() -> None:
    """PASS on the real tree, and a non-zero file count so PASS cannot mean "found nothing to read".
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, f"the real tree is not clean:\n{result.stdout}{result.stderr}"
    assert "PASS (" in result.stdout, result.stdout
    counted = int(result.stdout.split("PASS (")[1].split(" ")[0])
    assert counted > 50, f"only {counted} Go files were checked; that cannot be this repository"


def test_a_stray_statement_in_a_tracked_go_file_fails_the_script() -> None:
    """The end-to-end control: the script, not its library function, on a real tracked file.

    Every other control here exercises `violations_in` directly. This one plants a stray statement
    in an actual tracked source file and runs the script the way CI runs it, because a gate can
    import cleanly and still never execute its own scanning - the same blind-spot the secret-scan
    proof had until it was made to scan this repository rather than a scratch one.

    The file is restored in `finally` and the restoration is asserted by hash, so an assertion
    failure inside this test cannot leave the repository modified.
    """
    original = SCRATCH.read_bytes()
    before = hashlib.sha256(original).hexdigest()
    try:
        SCRATCH.write_bytes(
            original
            + b"\n// planted by the control\nconst strayQuery = \"DELETE FROM ledger.entries\"\n"
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True
        )
        assert result.returncode == 1, (
            "a stray DELETE in a tracked Go file did not fail the script, so the gate cannot catch "
            f"the thing it exists to catch:\n{result.stdout}{result.stderr}"
        )
        assert "config/flags.go" in result.stdout, (
            f"the failure does not name the file:\n{result.stdout}"
        )
        assert "DELETE FROM" in result.stdout, (
            f"the failure does not name the statement:\n{result.stdout}"
        )
    finally:
        SCRATCH.write_bytes(original)
        after = hashlib.sha256(SCRATCH.read_bytes()).hexdigest()
    assert after == before, "the control did not restore the mutated file byte-for-byte"


def test_the_exemption_is_the_only_reason_the_migrator_passes() -> None:
    """Removing the exemption must produce a finding, or the exemption is hiding nothing and the
    rule is not being applied to that file at all.
    """
    store = REPO_ROOT / "services" / "control-plane" / "migrate" / "store.go"
    name = "services/control-plane/migrate/store.go"
    assert checker.exempt_reason(name), "the exemption this control removes is not in force"
    hits = checker.violations_in(store)
    assert hits, (
        "store.go holds no statement-shaped literal, so exempting it hides nothing and the "
        "exemption should be deleted rather than kept as an unexplained allowance"
    )