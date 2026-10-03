"""Tests for the mutation gates' crash-recovery mechanism.

The mechanism under test is `scripts/mutation_gate_recovery.py`: take a copy of every tracked
file a mutation gate is about to change, and repair from that copy if a previous run was killed.

It exists because a `finally` block does not run when a process is killed, and the failure it
prevents has already happened twice in this repository, silently both times:

  * `scripts/mutation_check_model.py` was killed mid-mutation and left
    `services/control-plane/model/identity.go` holding M29 with the workload registry's mutex
    release removed (WI-173).
  * `scripts/mutation_check_local_env.py` was killed mid-mutation and left
    `infra/compose.yaml` at `postgres:alpine` instead of `postgres:17-alpine` (WI-174).

In both cases the next test run failed on a defect nobody had introduced and nobody had made, and
the real cause - a gate that did not clean up after itself - was invisible. A cleanup mechanism
that has only ever been observed working on the happy path is not a mechanism, it is a hope, so
these tests drive the failure paths directly.

Run:
    python -m pytest tests/ci/test_mutation_gate_recovery.py -q
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from mutation_gate_recovery import GateBackup, report_repaired  # noqa: E402

# Every gate that mutates a tracked file must go through this mechanism. A gate that grows its
# own private copy of the logic reintroduces the bug this module was extracted to fix, so the
# list is asserted rather than assumed.
MUTATING_GATES = [
    "scripts/mutation_check_model.py",
    "scripts/mutation_check_local_env.py",
    "scripts/mutation_check_destructive_migrate.py",
]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A fake repository. Every test builds its own, so none can touch the real tree."""
    return tmp_path


def _backup(root: Path, name: str | None = None) -> GateBackup:
    """A backup rooted at `root`, with a directory unique to this call.

    `GateBackup` deliberately stores its copies outside the repository, in a directory keyed by
    gate name, because that is what lets a killed run's work outlive the process. That same
    choice makes the directory shared state: two tests using the same gate name see each other's
    markers. Sharing is what a real gate does, so the tests model it deliberately - and one test
    asserts that two gates cannot repair each other's files - but everything else uses a unique
    name so that a leftover marker from a previous session cannot decide a test's outcome. That
    failure mode is not hypothetical: it produced a cross-run failure here.
    """
    return GateBackup(name or f"gate_{uuid.uuid4().hex}", root)


def test_no_marker_means_nothing_to_repair(root: Path) -> None:
    """The ordinary case: a clean tree produces no repair and no error."""
    target = root / "identity.go"
    target.write_bytes(b"pristine")
    assert _backup(root).recover() == []


def test_recover_restores_a_file_left_mutated(root: Path) -> None:
    """The whole point: a file a killed run left mutated comes back byte-for-byte."""
    target = root / "identity.go"
    original = b"pristine\n"
    backup = _backup(root)
    backup.take({target: original})

    # Exactly the observed failure: the mutation landed and the restore never ran.
    target.write_bytes(b"pristine\nfunc broken() { /* M29 */ }\n")

    assert backup.recover() == ["identity.go"]
    assert target.read_bytes() == original


def test_recover_reports_only_what_it_actually_changed(root: Path) -> None:
    """A marker over an already-correct file must not claim a repair it did not perform.

    Otherwise a stale marker makes the gate announce damage on every subsequent run, and a
    warning that always fires is a warning nobody reads.
    """
    target = root / "identity.go"
    original = b"pristine\n"
    backup = _backup(root)
    # The target must exist, as it does in a real run: the gate reads the pristine
    # bytes from files that are already there. A missing target is a deletion, and
    # `recover` rightly treats that as damage to repair - which is what makes this
    # test's setup the thing to get right.
    target.write_bytes(original)
    backup.take({target: original})

    assert backup.recover() == []
    assert target.read_bytes() == original


def test_recover_recreates_a_parent_directory_that_is_gone(root: Path) -> None:
    """Restoring a file means recreating its path, not just its bytes.

    A stale marker can outlive the directory tree it describes - the backup directory is global
    and keyed by gate name, so a marker from an earlier session survives while whatever the
    gate mutated may since have been moved or deleted wholesale. Without recreating the parent,
    that ends in a bare FileNotFoundError from pathlib, which is the one thing this function
    must never produce: a crash that does not say which file is still mutated.
    """
    target = root / "services" / "model" / "identity.go"
    target.parent.mkdir(parents=True)
    original = b"pristine\n"
    backup = _backup(root)
    backup.take({target: original})

    target.parent.rmdir()
    target.parent.parent.rmdir()
    assert not target.parent.exists()

    assert backup.recover() == [str(Path("services") / "model" / "identity.go")]
    assert target.read_bytes() == original


def test_recover_refuses_cleanly_when_the_file_cannot_be_written(root: Path) -> None:
    """A repair that cannot happen must be named, not raised as an opaque OS error.

    Occupied by a file rather than a directory, the write raises something no message from this
    module explains. The refusal has to name the file, because the caller's only remaining
    option is to restore it by hand and it cannot know which one from a traceback.
    """
    target = root / "services" / "identity.go"
    target.parent.mkdir(parents=True)
    original = b"pristine\n"
    backup = _backup(root)
    backup.take({target: original})

    # The parent path is now occupied by a regular file.
    target.parent.rmdir()
    target.parent.write_bytes(b"in the way")

    with pytest.raises(SystemExit) as excinfo:
        backup.recover()
    message = str(excinfo.value)
    assert "cannot restore" in message
    assert str(Path("services") / "identity.go") in message
    assert "repaired by hand" in message


def test_unreadable_marker_refuses_rather_than_guessing(root: Path) -> None:
    """A marker that cannot be read means a file may be mutated and we cannot tell which.

    Stopping is the only safe reading. Continuing would mean mutating a tree whose current
    contents are unknown, and the mutations would be measured against a baseline that might
    already contain a defect.
    """
    backup = _backup(root)
    backup.dir.mkdir(parents=True, exist_ok=True)
    backup.marker.write_text("{not json", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        backup.recover()
    assert "cannot be read" in str(excinfo.value)


def test_wrongly_shaped_marker_refuses_rather_than_crashing(root: Path) -> None:
    """Valid JSON in the wrong shape is the same situation, and must be as legible.

    This is reachable without malice - hand-writing a marker while testing the repair path is
    enough - and the first version of this module raised a bare KeyError on it. A traceback
    hides the reason behind a stack trace, in a tool whose entire job is to explain why it
    stopped.
    """
    backup = _backup(root)
    backup.dir.mkdir(parents=True, exist_ok=True)
    backup.marker.write_text(json.dumps({"identity.go": "somewhere"}), encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        backup.recover()
    assert "not a manifest written by this gate" in str(excinfo.value)


def test_missing_backup_file_refuses_and_names_the_file(root: Path) -> None:
    """If the backup is gone the tree cannot be trusted, and the message must say which file.

    Restoring what we can and continuing would be worse: a partially repaired tree looks the
    same as a fully repaired one to every later check.
    """
    target = root / "identity.go"
    backup = _backup(root)
    backup.take({target: b"pristine\n"})
    target.write_bytes(b"mutated")

    # The backup the manifest points at disappears, as it would if a cleaner emptied tmpdir.
    for saved in backup.dir.iterdir():
        if saved.name != backup.marker.name:
            saved.unlink()

    with pytest.raises(SystemExit) as excinfo:
        backup.recover()
    assert "identity.go" in str(excinfo.value)
    assert "restored by hand" in str(excinfo.value)


def test_recover_is_idempotent_and_clears_the_marker(root: Path) -> None:
    """Repairing twice is not repairing once, so the second run must report nothing to do."""
    target = root / "identity.go"
    original = b"pristine\n"
    backup = _backup(root)
    backup.take({target: original})
    target.write_bytes(b"mutated")

    assert backup.recover() == ["identity.go"]
    assert not backup.marker.exists()
    assert backup.recover() == []
    assert target.read_bytes() == original


def test_restore_verifies_rather_than_assuming(root: Path) -> None:
    """`restore` is the function that must never fail quietly, so it confirms the write.

    Returning success for a write that did not land is the exact failure this whole mechanism
    exists to stop, and it would stop the mechanism from stopping it.
    """
    target = root / "identity.go"
    target.write_bytes(b"mutated")
    backup = _backup(root)

    assert backup.restore({target: b"pristine\n"}) == []
    assert target.read_bytes() == b"pristine\n"


def test_take_keys_backups_by_repository_relative_path(root: Path) -> None:
    """The manifest must name files by path relative to the repository, not absolutely.

    An absolute path recorded on one machine is meaningless on another, and `recover` would
    either repair the wrong file or fail on a path that no longer exists. The relative form is
    also what makes the marker reviewable.
    """
    nested = root / "services" / "model"
    nested.mkdir(parents=True)
    target = nested / "identity.go"
    backup = _backup(root)
    backup.take({target: b"pristine\n"})

    manifest = json.loads(backup.marker.read_text(encoding="utf-8"))
    assert list(manifest["files"]) == [str(Path("services") / "model" / "identity.go")]


def test_gates_do_not_share_one_backup_directory(root: Path) -> None:
    """Two gates must not be able to repair each other's files.

    `take` stores each backup under `target.name`. Two gates touching files with the same
    basename - `migrate/main.go` and some other `main.go` - would otherwise overwrite each
    other's backup and then "repair" a file with the wrong content. The per-gate directory is
    what makes that impossible.
    """
    first = GateBackup("gate_one", root)
    second = GateBackup("gate_two", root)
    first.take({root / "main.go": b"first\n"})
    second.take({root / "main.go": b"second\n"})

    first.recover()
    second.recover()
    assert first.dir != second.dir


def test_every_mutating_gate_uses_the_shared_mechanism() -> None:
    """No gate may carry its own private copy of the recovery logic.

    This is the property that keeps the three gates correct as they change. A gate that
    inlines its own backup code will drift from the other two, and the copy that drifts is
    the one nobody reviews.
    """
    offenders: list[str] = []
    for relative in MUTATING_GATES:
        source = (REPO_ROOT / relative).read_text(encoding="utf-8-sig")
        if "mutation_gate_recovery" not in source:
            offenders.append(relative)
    assert not offenders, (
        f"these gates mutate tracked files but do not use the shared recovery mechanism: "
        f"{offenders}"
    )


def test_report_repaired_is_silent_when_there_is_nothing_to_say(capsys: pytest.CaptureFixture) -> None:
    """The repair notice must be loud when it fires and silent otherwise.

    A notice printed on every run is how a real one becomes invisible.
    """
    report_repaired(_backup(Path("/nonexistent")), [])
    assert capsys.readouterr().out == ""


def test_report_repaired_uses_ci_error_annotations(capsys: pytest.CaptureFixture) -> None:
    """GitHub Actions surfaces `::error::` lines in the run summary; plain text is buried.

    The person who needs to see this is one who was not watching the gate, and this is the only
    channel that reaches them.
    """
    report_repaired(_backup(Path("/nonexistent")), ["identity.go"])
    out = capsys.readouterr().out
    assert "::error::" in out
    assert "identity.go" in out
