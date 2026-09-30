"""Shared PostgreSQL 17 verification harness.

The database assertions are the only proof that the constraints in db/migrations/ are real
rather than decorative, so the thing that runs them has to be trustworthy and has to be the
same thing every time. This module owns that: starting a container, waiting for it to be
actually ready, running SQL, and cleaning up.

It is a module rather than a copy inside each script because the first version of the
migration work duplicated the parsing convention instead, and the two halves disagreed about
where a migration file ends. One owner for the container lifecycle and one owner for the
migration split keeps a second script from being a second, subtly different harness.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path

# The image every check runs against. docs/24 targets PostgreSQL 17 specifically, so a
# different major version is refused rather than warned about: the assertions exercise
# behaviour that differs between majors, and a green run against the wrong one is worse than
# no run.
DEFAULT_IMAGE = "postgres:17-alpine"

# The password for the throwaway container. Verification data only, never a real credential,
# and the container is destroyed at the end of the run.
VERIFY_PASSWORD = "verifyonly"

# Readiness probe budget. A cold postgres:17-alpine on a loaded machine takes several
# seconds; failing earlier would make the check flaky, and waiting forever would hang CI.
READY_ATTEMPTS = 30
READY_DELAY_SECONDS = 1.0

# The marker that separates a migration's up body from its down body.
#
# This constant and the split below are the single owner of that convention, and they have to
# stay in step with services/control-plane/migrate, which parses the same files in Go. When
# the verification harness applied whole files, the 0001 down body dropped the ledger schema
# immediately after the up body created it, and the suite failed with "the verification script
# produced no summary" -- an error that points at the assertions rather than at the migration.
# Two parsers disagreeing about where a file ends is not something to leave to convention.
DOWN_MARKER = "-- migrate:down"


def migration_bodies(text: str) -> tuple[str, str]:
    """Split a migration file into (up, down).

    A file with no marker has an empty down body, which means the migration cannot be
    reverted rather than that its down half happens to be blank.
    """
    up, marker, down = text.partition(DOWN_MARKER)
    return up, (down if marker else "")


class PsqlError(RuntimeError):
    """A statement that had to succeed did not.

    Carries stderr rather than a formatted message so callers can print the server's own
    diagnostics, which is the part that actually identifies the failing statement.
    """

    def __init__(self, action: str, result: subprocess.CompletedProcess) -> None:
        self.action = action
        self.result = result
        detail = (result.stderr or result.stdout or "").strip()
        super().__init__(f"{action} failed: {detail[:2000]}")


def run(cmd: list[str], *, stdin_text: str | None = None,
        timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a command, optionally feeding text to stdin.

    stdout and stderr are captured separately rather than merged. Merged, the error lines and
    the assertion results arrive in whatever order the pipes flush, which is how an earlier
    version of this harness produced an unreadable failure.
    """
    return subprocess.run(
        cmd, input=stdin_text, capture_output=True, text=True, timeout=timeout, check=False,
    )


def docker_available() -> tuple[bool, str]:
    """Report whether a usable Docker daemon is reachable."""
    probe = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60)
    if probe.returncode == 0:
        return True, probe.stdout.strip()
    output = (probe.stderr or probe.stdout).strip()
    return False, (output.splitlines()[0] if output else "docker info failed")


class Postgres:
    """A throwaway PostgreSQL 17 container that is always cleaned up.

    Used as a context manager so the container cannot outlive the check that created it. A
    leaked container holding a published port is the kind of thing that survives on a
    developer machine for months.
    """

    def __init__(self, *, image: str = DEFAULT_IMAGE, label: str = "webtrade-pgverify") -> None:
        self.image = image
        self.name = f"{label}-{uuid.uuid4().hex[:8]}"
        self.version = "unknown version"
        self._started = False

    def __enter__(self) -> "Postgres":
        # No port is published. Every statement this project runs against the verification
        # container goes through `docker exec`, so a published 5432 would expose a
        # password-bearing database to the host network without being used for anything.
        started = run(["docker", "run", "--rm", "--name", self.name,
                       "-e", f"POSTGRES_PASSWORD={VERIFY_PASSWORD}",
                       "-e", "POSTGRES_DB=webtrade",
                       "-d", self.image], timeout=180)
        if started.returncode != 0:
            raise PsqlError("starting the PostgreSQL container", started)
        self._started = True

        for _ in range(READY_ATTEMPTS):
            probe = run(["docker", "exec", self.name, "pg_isready", "-U", "postgres"],
                        timeout=30)
            # pg_isready alone is not readiness. During startup recovery the postmaster
            # accepts a connection on the socket and pg_isready reports success, then refuses
            # every actual statement with FATAL: the database system is starting up. A gate
            # that reports that as a migration failure is worse than no gate, because the
            # failure is not in the thing being tested.
            #
            # So a trivial statement has to succeed as well. This is the check that makes the
            # difference between "the port is open" and "the database answers".
            if probe.returncode == 0 and self.psql("select 1", tuples_only=True).returncode == 0:
                self.version = self._read_version()
                return self
            time.sleep(READY_DELAY_SECONDS)
        raise PsqlError("waiting for PostgreSQL to become ready",
                        subprocess.CompletedProcess([], 1, "", "never became ready"))

    def __exit__(self, *_exc) -> None:
        if self._started:
            run(["docker", "rm", "-f", self.name], timeout=60)
            self._started = False

    def _read_version(self) -> str:
        result = self.psql("select version()")
        if result.returncode != 0:
            # Reported rather than swallowed. Returning "unknown version" here would print a
            # reassuring banner above a run that is about to fail for an unrelated reason.
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise PsqlError("querying the PostgreSQL version",
                            subprocess.CompletedProcess([], result.returncode, "",
                                                       detail[0] if detail else "unknown error"))
        # psql renders a single value in a bordered table, so the version is the line that
        # mentions PostgreSQL rather than a field that can be indexed.
        for line in result.stdout.splitlines():
            if "PostgreSQL" in line:
                return line.strip()
        return "unknown version"

    def psql(self, sql: str = "", *, file: Path | None = None,
             on_error_stop: bool = False,
             tuples_only: bool = False) -> subprocess.CompletedProcess:
        """Run SQL and return the raw result without raising.

        Callers that run assertions need the return code and the output, so this does not
        raise on a failed statement. `apply` is the raising counterpart, for the case where
        a statement had to succeed for the run to mean anything.

        `tuples_only` adds -t -A, which suppresses the column header, the separator, and the
        row count. Anything that tests a value rather than parsing a report needs it: bare
        `select 1` otherwise prints a header line first, so a check for output starting with
        "1" fails against a row that is present.
        """
        cmd = ["docker", "exec", "-i", self.name, "psql", "-U", "postgres", "-d", "webtrade",
               "-v", f"ON_ERROR_STOP={'1' if on_error_stop else '0'}"]
        if tuples_only:
            cmd += ["-t", "-A"]
        return run(cmd, stdin_text=file.read_text(encoding="utf-8") if file else sql)

    def apply(self, sql: str, *, action: str) -> None:
        """Run SQL that must succeed, raising PsqlError with the server's own message."""
        result = self.psql(sql, on_error_stop=True)
        if result.returncode != 0:
            raise PsqlError(action, result)
