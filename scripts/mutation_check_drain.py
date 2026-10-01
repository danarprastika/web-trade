"""Mutation gate: prove the drain tests can fail.

This exists because of a specific, twice-repeated failure mode in this repository: a check that
reports success without having exercised anything. EV-064 recorded an integration suite that
skipped seventeen tests and still printed "ok". EV-065 recorded a drain test whose URL helper
omitted the scheme, so it would have passed on a request that was never sent. In both cases the
test was green and meaningless, and in both cases the fix was to run one more check rather than
to read harder.

The three tests in cmd/control-plane/main_test.go are load-bearing for G5.7's shutdown claim, and
nothing in the pipeline currently establishes that they can fail. A future refactor that changes
serve() could make all three vacuous - assert against a local variable, or wait on a channel
nobody closes - and the suite would stay green. This gate closes that by deliberately breaking
serve() and requiring the tests to notice.

The mutation replaces the graceful server.Shutdown with a hard server.Close, which is the exact
defect the drain exists to prevent: connections dropped rather than drained. The replacement also
consumes shutdownCtx with `_ =`, because leaving it unused would fail the build rather than the
assertion, and a gate that passes for the wrong reason teaches nothing.

Two properties matter for this gate to mean anything, and both are enforced below rather than
assumed:

  1. The mutation must actually apply. If the target text is absent or appears more than once,
     the file is unchanged, the tests pass, and the gate would "succeed" while proving nothing -
     the same trap as the tests it protects. The mutation is therefore verified to have landed
     before the tests are run, and the gate fails loudly if it did not.

  2. The original file must be restored, whatever happens. The mutation is applied to the working
     tree, so an interrupted run would leave a broken serve() behind. Restoration is in a
     finally block and the restored bytes are compared against the bytes read before the
     mutation, so a partial restore is itself an error.

The gate passes when the mutated build makes the tests fail. A pass of the mutated tests is the
failure this is looking for: it means the tests no longer detect a broken drain.

Run directly, or as the `drain tests can fail` step in the go job.

Idempotent in the sense that matters: it restores the file, so repeated runs are identical.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "services" / "control-plane"
TARGET = MODULE / "cmd" / "control-plane" / "main.go"

GRACEFUL = "if err := server.Shutdown(shutdownCtx); err != nil {"

# `_ = shutdownCtx` keeps the variable used so the mutation compiles. A build failure would make
# `go test` exit non-zero for a reason that has nothing to do with the assertion under test, and
# this gate has to be able to tell "the test detected a broken drain" apart from "the package does
# not build".
MUTATED = "_ = shutdownCtx\n\tif err := server.Close(); err != nil {"

# The tests that must notice. Listed explicitly rather than matching the whole package, because
# the other tests in the package do not exercise the drain and would dilute the signal.
DRAIN_TESTS = (
    "TestTheDrainLetsAnInFlightRequestFinishBeforeItStopsAccepting",
    "TestTheDrainGivesUpOnARequestThatOutlivesTheShutdownDeadline",
)


def go(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", *args],
        cwd=MODULE,
        capture_output=True,
        text=True,
        env={**os.environ, "CGO_ENABLED": os.environ.get("CGO_ENABLED", "0")},
    )


def main() -> int:
    if not TARGET.exists():
        print(f"::error::{TARGET} not found; the mutation has no target and would prove nothing")
        return 1

    original = TARGET.read_bytes()
    text = original.decode("utf-8")

    occurrences = text.count(GRACEFUL)
    if occurrences != 1:
        # Refusing here is the whole point. Silently proceeding would run the unmutated tests,
        # see them pass, and report that they can detect a broken drain when nothing was broken.
        print(f"::error::expected exactly one {GRACEFUL.strip()!r} in {TARGET.name}, found "
              f"{occurrences}. The mutation cannot be applied, so this gate would prove nothing; "
              "it is failing rather than passing vacuously.")
        return 1

    outcome = 0
    detail = ""
    try:
        TARGET.write_text(text.replace(GRACEFUL, MUTATED), encoding="utf-8")

        mutated = TARGET.read_text(encoding="utf-8")
        if MUTATED not in mutated or GRACEFUL in mutated:
            detail = ("::error::the mutation did not land in the file; refusing to interpret "
                      "the test result")
            outcome = 1
        else:
            failures: list[str] = []
            for name in DRAIN_TESTS:
                result = go("test", "-count=1", "-run", f"^{name}$", "./cmd/control-plane/")
                if result.returncode == 0:
                    failures.append(name)
                    print(f"  [NOT DETECTED] {name} passed against a hard close")
                else:
                    print(f"  [detected]     {name} failed against a hard close")

            if failures:
                detail = ("::error::these drain tests pass against a hard server.Close, so they "
                          "do not actually test the drain: " + ", ".join(failures))
                outcome = 1
            else:
                print("drain mutation gate: PASS (both drain tests detect a hard close)")

    finally:
        # Restore unconditionally, then verify the restore by comparing bytes. A silent partial
        # restore would leave production code subtly different from what was reviewed.
        #
        # The restore result is recorded rather than returned from inside the finally block: a
        # return there would discard both the return value and any exception already in flight,
        # so a restore failure could mask, or be masked by, the mutation result. Deciding the
        # exit code after the try/finally completes keeps the two outcomes independent.
        TARGET.write_bytes(original)
        if TARGET.read_bytes() != original:
            restore_failure = ("::error::failed to restore " + str(TARGET) + " byte-for-byte; the "
                               "working tree is unsafe and must be restored by hand")
            print(restore_failure)
            detail = restore_failure
            outcome = 1
        else:
            print(f"  restored {TARGET.name} ({len(original)} bytes)")

    if detail:
        print(detail)
    return outcome


if __name__ == "__main__":
    sys.exit(main())
