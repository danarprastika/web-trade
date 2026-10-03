"""Crash recovery for mutation gates: backup the files you are about to mutate, and repair from
that backup if a previous run was killed before it could restore itself.

This exists because a `finally` block does not run when a process is killed, and the failure mode
these gates have is precisely the one where nothing else runs. Both occurrences in this
repository's history were silent: a killed run left `model/identity.go` with the workload
registry's mutex release removed, and a killed run left `infra/compose.yaml` pinned to an
unversioned `postgres:alpine`. In both cases the next test run failed on a defect nobody had
introduced and nobody had made, and the actual cause - a gate that did not clean up - was
invisible. See WI-173 and WI-174.

One implementation for all three gates rather than a copy in each, for the reason
`check_workflow_bash.py` was consolidated: a rule that is copied drifts, and a rule that drifts is
worse than no rule because it is still trusted. The directories are keyed by gate name so two
gates cannot repair each other's files.

Usage:

    BACKUP = GateBackup("mutation_check_model")
    repaired = BACKUP.recover()            # call first, before reading originals
    originals = {p: p.read_bytes() for p in TARGETS}
    BACKUP.take(originals)
    try:
        ...
    finally:
        BACKUP.restore_or_die(originals)
        BACKUP.discard()
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path


class GateBackup:
    """Backup and repair for the tracked files one gate run may mutate."""

    def __init__(self, gate_name: str, root: Path) -> None:
        self.root = root
        self.dir = Path(tempfile.gettempdir()) / "kilo" / gate_name
        self.marker = self.dir / "IN_PROGRESS.json"

    def recover(self) -> list[str]:
        """Restore anything a killed predecessor left mutated.

        Returns the paths it had to repair, so the caller can report that the originals it is
        about to read are the reviewed ones rather than whatever the last run left behind. A
        marker that exists but cannot be acted on is fatal rather than ignored: the safe
        interpretation of "I know a file may be mutated and I cannot prove which" is to stop.
        """
        if not self.marker.exists():
            return []
        try:
            manifest = json.loads(self.marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(
                f"::error::{self.marker} exists but cannot be read ({exc}); refusing to continue "
                f"because a previous run may have left a tracked file mutated and this one cannot "
                f"tell which"
            )
        # Valid JSON in the wrong shape is the same situation as unreadable JSON: a marker exists,
        # so a file may be mutated, and there is no trustworthy way to learn which. This case is
        # easy to reach - hand-writing a marker while testing the repair path is enough - so it
        # gets the same clean refusal rather than a KeyError traceback that buries the reason.
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
            raise SystemExit(
                f"::error::{self.marker} is not a manifest written by this gate (expected a "
                f"{{'files': {{...}}}} object); refusing to continue because a previous run may have "
                f"left a tracked file mutated and this one cannot tell which"
            )

        repaired: list[str] = []
        for relative, backup in manifest["files"].items():
            target = self.root / relative
            saved = Path(backup)
            if not saved.exists():
                raise SystemExit(
                    f"::error::{self.marker} references {backup}, which no longer exists; "
                    f"{relative} may still be mutated and must be restored by hand"
                )
            data = saved.read_bytes()
            if not target.exists() or target.read_bytes() != data:
                try:
                    # The parent directory may itself be gone - a stale marker can name a file
                    # whose whole subtree was removed - so restoring the file means recreating
                    # the path. Without this the repair dies with a bare FileNotFoundError from
                    # pathlib, which is the one outcome this function must never produce: a
                    # traceback that does not say which file is still mutated.
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                except OSError as exc:
                    raise SystemExit(
                        f"::error::cannot restore {relative} from {backup} ({exc}); the working "
                        f"tree is left mutated and must be repaired by hand"
                    )
                repaired.append(relative)

        shutil.rmtree(self.dir, ignore_errors=True)
        return repaired

    def take(self, files: dict[Path, bytes]) -> None:
        """Record pristine bytes before anything is mutated. Pristine means unmutated by us."""
        self.dir.mkdir(parents=True, exist_ok=True)
        entries: dict[str, str] = {}
        for target, data in files.items():
            saved = self.dir / target.name
            saved.write_bytes(data)
            entries[str(target.relative_to(self.root))] = str(saved)
        self.marker.write_text(json.dumps({"files": entries}, indent=2), encoding="utf-8")

    def restore(self, files: dict[Path, bytes]) -> list[Path]:
        """Write the pristine bytes back and verify the result rather than assuming it.

        Returns the paths that could not be restored. A silent partial restore is the state this
        whole mechanism exists to prevent, so a failure here is returned loudly.
        """
        broken: list[Path] = []
        for target, data in files.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if target.read_bytes() != data:
                broken.append(target)
        return broken

    def discard(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def report_repaired(backup: GateBackup, repaired: list[str]) -> None:
    """Announce a repair loudly enough that it is found in CI logs by someone who was not looking."""
    if not repaired:
        return
    print(
        "::error::a previous run of this gate was killed before it could restore, and it had left "
        "a tracked file mutated. Repaired from the backup taken before it started:"
    )
    for name in repaired:
        print(f"    restored {name}")
    print()
