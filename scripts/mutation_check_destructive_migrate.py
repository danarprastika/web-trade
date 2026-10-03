"""Mutation gate: prove the destructive-migration guard can fail.

WI-171 was raised because a guard existed in this repository and not in the product.
services/control-plane/integration/harness_test.go refused to reset a database that was not
verifiably disposable, and cmd/migrate -direction down - which reverts the whole applied set, and
whose 0002_audit.sql down body is `DROP TABLE IF EXISTS audit_records CASCADE` - was protected by
nothing at all. `go run ./services/control-plane/cmd/migrate` never executes a line of a _test.go
file, so the harness guard could not have helped.

The rule moved to services/control-plane/migrate/destructive.go and the command now consults it
before opening a connection. That is a safety control over the tamper-evident audit schema, and a
safety control that cannot be observed failing is not known to work. The tests in
cmd/migrate/destructive_guard_test.go and migrate/destructive_test.go each assert one property, and
this gate breaks each property in turn and requires the matching test to notice.

Why a table rather than one mutation
-------------------------------------
The guard is nine separate promises in two files, so one mutation would measure a fraction of them
and still print PASS - the EV-064 shape of a check reporting success without having exercised
anything. Each entry below names the promise, the way of breaking it, and the tests that must
notice. All of them must be noticed.

Two things this gate holds the tests to, both of which a non-zero exit code alone cannot express:

  1. A `--- FAIL` line, not an exit code. A package that does not compile also exits non-zero with
     no test having run, and crediting that as a detection would certify coverage that was never
     measured. The classification is imported from mutation_check_anchor.py so the repository holds
     one definition of the distinction rather than three that could drift apart.

  2. The mutation must compile. This matters more here than in the other gates, because the
     command guard is a block inside a function: a mutation that orphans a brace makes every test
     in the package exit non-zero at once, which would print several confident DETECTED lines
     having established nothing. Each mutation is therefore required to build before any test runs
     under it, and one that does not is reported UNCERTIFIED and fails the gate.

The baseline runs before anything is mutated, each mutation is verified to have landed, and every
file is restored byte-for-byte in a finally block with the restore compared rather than assumed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mutation_check_anchor as anchor_gate  # noqa: E402
from mutation_gate_recovery import GateBackup, report_repaired  # noqa: E402

MODULE = ROOT / "services" / "control-plane"

# Two files are mutated, so each entry names which. The first is the shared rule, the second the
# command that consumes it - and a gate that could only reach one of them would be blind to exactly
# the defect WI-171 describes: a perfect rule in the library and a command that stopped asking.
GUARD = MODULE / "migrate" / "destructive.go"
COMMAND = MODULE / "cmd" / "migrate" / "main.go"

MIGRATE_PKG = "./migrate/"
COMMAND_PKG = "./cmd/migrate/"


@dataclass(frozen=True)
class Mutation:
    """One promise, the way of breaking it, and the tests that must notice."""

    name: str
    target: Path
    find: str
    replace: str
    package: str
    tests: tuple[str, ...]


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        # The whole condition, not `if false && <condition>`. The first version of this mutation
        # appended `&& false`, which left `parsed == migrate.Down` in the file - so the source
        # check that looks for exactly that string still passed against a command that never
        # consulted the guard at all. A mutation has to remove the property, not merely disable it
        # in a way a string search cannot see.
        name="the command stops consulting the guard",
        target=COMMAND,
        find="\tif parsed == migrate.Down {",
        replace="\tif false {",
        package=COMMAND_PKG,
        tests=(
            "TestAnUnboundedRevertAgainstAProductionDatabaseIsRefused",
            "TestTheOptInAloneDoesNotAuthoriseAnUnboundedRevert",
            "TestTheCommandActuallyConsultsTheDestructiveGuard",
        ),
    ),
    Mutation(
        # A refusal that exits 0 is a refusal an operator's tooling reads as success. The schema is
        # untouched - the guard still stopped the run - so this is about the report being true
        # rather than about the guard failing open.
        name="a refusal reports success",
        target=COMMAND,
        find="\t\t\treturn 2\n\t\t}\n\t\tif verdict.Overridden {",
        replace="\t\t\treturn 0\n\t\t}\n\t\tif verdict.Overridden {",
        package=COMMAND_PKG,
        tests=(
            "TestAnUnboundedRevertAgainstAProductionDatabaseIsRefused",
            "TestTheOptInAloneDoesNotAuthoriseAnUnboundedRevert",
        ),
    ),
    Mutation(
        # The other direction of over-application: guarding `up` and `status` as well. A guard that
        # refuses to create or inspect a database is unusable for its normal job, and the only
        # evidence that catches that is the test asserting those two directions reach the
        # connection.
        name="the guard is applied to the non-destructive directions as well",
        target=COMMAND,
        find="\tif parsed == migrate.Down {",
        replace="\tif true {",
        package=COMMAND_PKG,
        tests=("TestTheGuardDoesNotApplyToUpOrStatus",),
    ),
    Mutation(
        # Reinstating the bounded-revert exemption is the exact defect an independent review
        # found in this change set, so it is certified rather than merely commented on: the
        # gate must go red if anyone narrows the guard to the unbounded form again.
        name="the bounded-revert exemption is reinstated",
        target=COMMAND,
        find="\tif parsed == migrate.Down {",
        replace="\tif parsed == migrate.Down && *to == 0 && !givenTo {",
        package=COMMAND_PKG,
        # Only TestABoundedRevertIsGuardedToo. An earlier version of this entry also listed
        # TestAnUnboundedRevertAgainstAProductionDatabaseIsRefused and the gate rejected it:
        # reinstating the exemption leaves the *unbounded* path guarded, so that test still
        # passes and listing it claimed a detection that does not exist. A test that does not
        # fail under the mutation it is supposed to cover is not evidence of coverage.
        tests=("TestABoundedRevertIsGuardedToo",),
    ),
    Mutation(
        name="the shipped policy becomes permissive, so the opt-in is sufficient alone",
        target=GUARD,
        find="\t\tOptInOverrides: false,",
        replace="\t\tOptInOverrides: true,",
        package=MIGRATE_PKG,
        tests=(
            "TestTheCommandPolicyDoesNotLetTheOptInStandAlone",
            "TestTheStrictPolicyRequiresBothTheTargetAndTheOptIn",
        ),
    ),
    Mutation(
        name="the opt-in accepts any value that is set",
        target=GUARD,
        find="\toptedIn := optIn == policy.OptInValue",
        # Keep the variable name and change only the comparison. Redeclaring `optIn` here fails to
        # compile, because that is already the string parameter - which the gate reports as
        # UNCERTIFIED rather than crediting, so the malformed version cost nothing but a run.
        replace='\toptedIn := optIn != ""',
        package=MIGRATE_PKG,
        tests=("TestTheOptInIsComparedExactly",),
    ),
    Mutation(
        name="a DSN naming no database is allowed with the opt-in",
        target=GUARD,
        find="\tif target.Database == \"\" {",
        replace="\tif false {",
        package=MIGRATE_PKG,
        tests=("TestAnUnnamedDatabaseIsRefusedEvenWithTheOptIn",),
    ),
    Mutation(
        name="a query string that redirects the connection is accepted",
        target=GUARD,
        find="\tif len(overrides) > 0 {",
        replace="\tif false && len(overrides) > 0 {",
        package=MIGRATE_PKG,
        tests=("TestAQueryStringCannotRedirectTheGuardToAnotherDatabase",),
    ),
    Mutation(
        # The password never enters DSNTarget today: parsing keeps only u.User.Username(), so the
        # secret is dropped before anything can render it. This mutation reintroduces the whole
        # userinfo - "webtrade:hunter2" - which String then prints verbatim into the refusal.
        # Written against the parse site rather than against String because the leak is the
        # combination: a String that rendered a password would have nothing to render, so breaking
        # only String proves nothing.
        name="the parsed target carries the password into the refusal",
        target=GUARD,
        find="\t\ttarget.User = u.User.Username()",
        replace="\t\ttarget.User = u.User.String()",
        package=MIGRATE_PKG,
        tests=("TestTheRefusalNamesTheDatabaseAndNotThePassword",),
    ),
)

# Files are keyed so the original bytes are read once and restored once per mutation.
TARGETS = sorted({m.target for m in MUTATIONS}, key=str)


def go(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["go", *args],
        cwd=MODULE,
        capture_output=True,
        text=True,
        env={**os.environ, "CGO_ENABLED": os.environ.get("CGO_ENABLED", "0")},
    )


# Crash recovery
# --------------
# A mutation gate writes to production source files, and a `finally` block only runs if the process
# gets to it. A gate that is killed - a CI timeout, a cancelled job, a laptop lid - never reaches
# its finally, and leaves a mutated production file behind with nothing marking it as mutated. This
# gate was written after that happened here: a killed run left CommandOptInPolicy() with
# OptInOverrides flipped to true, so the shipped command would have permitted a destructive
# migration on the opt-in alone, and the only symptom was a later pre-flight check reporting a
# target it could no longer find.
#
# The backup is taken before anything is mutated and lives outside the repository, so a killed run
# is repaired by the next run rather than by a person noticing. This is not belt-and-braces: it is
# the only mechanism, because the failure mode it repairs is precisely the one where nothing else
# runs.
BACKUP_DIR = Path(tempfile.gettempdir()) / "kilo" / "mutation_check_destructive_migrate"
MARKER = BACKUP_DIR / "IN_PROGRESS.json"

# The mechanism itself lives in scripts/mutation_gate_recovery.py, shared with the other two
# gates that mutate tracked files. It was inlined here first and then extracted, because a rule
# copied into a second gate is a rule that drifts, and this repository has already had to
# consolidate `check_workflow_bash.py` for exactly that reason.
BACKUP = GateBackup("mutation_check_destructive_migrate", ROOT)


def recover_interrupted_run() -> list[str]:
    """Restore anything a previous killed run left mutated. Returns what it had to fix."""
    return BACKUP.recover()


def take_backup(files: dict[Path, bytes]) -> None:
    """Record the pristine bytes of every file this run may mutate, before it mutates any."""
    BACKUP.take(files)


def discard_backup() -> None:
    BACKUP.discard()


def build(package: str) -> subprocess.CompletedProcess[str]:
    return go("build", package)


def run_test(package: str, name: str) -> subprocess.CompletedProcess[str]:
    return go("test", "-count=1", "-run", f"^{name}$", package)


def main() -> int:
    # Repairs a killed predecessor before anything else, so the originals captured below are the
    # reviewed ones rather than whatever the last run left behind.
    repaired = recover_interrupted_run()
    if repaired:
        print("::error::a previous run of this gate was killed before it could restore, and it had "
              "left production source mutated. Repaired from the backup taken before it started:")
        for name in repaired:
            print(f"    restored {name}")
        print()

    for target in TARGETS:
        if not target.exists():
            print(f"::error::{target} not found; the mutations have no target and would prove nothing")
            return 1

    originals = {t: t.read_bytes() for t in TARGETS}
    take_backup(originals)
    texts = {t: originals[t].decode("utf-8") for t in TARGETS}

    # Every mutation must be applicable and unambiguous before anything is interpreted. A mutation
    # that silently did not apply would run the tests against an unmutated file, see them pass, and
    # report a property as untested that is in fact untested - the two are indistinguishable from
    # the output, which is the reason this is checked rather than assumed.
    for mutation in MUTATIONS:
        occurrences = texts[mutation.target].count(mutation.find)
        if occurrences != 1:
            print(f"::error::the target text for '{mutation.name}' appears {occurrences} time(s) in "
                  f"{mutation.target.name}, expected exactly 1. The mutation cannot be applied, so "
                  f"this gate would prove nothing about that property; it is failing rather than "
                  f"passing vacuously.")
            return 1

    # Baseline: the packages must build and the tests must be green before anything is written.
    # Without it, "the test failed" has two causes that look identical from the exit code.
    for package in (MIGRATE_PKG, COMMAND_PKG):
        pristine = build(package)
        if pristine.returncode != 0:
            print(pristine.stdout[-800:], pristine.stderr[-800:])
            print(f"::error::{package} does not build on the unmutated tree, so a failure under "
                  f"mutation could not be attributed to the mutation; refusing to interpret any "
                  f"result")
            return 1
    print("baseline: PASS (migrate and cmd/migrate build)")

    # Which package each test lives in, taken from the mutations rather than a cross product.
    # Running all of them against both packages compiles each package twice as often and, worse,
    # a test that does not exist in a package makes `-run` match nothing and exit 0 - which is
    # indistinguishable from the test passing. Deriving the pairs from the mutations means every
    # baseline run is a real test of a test that exists.
    home = {name: m.package for m in MUTATIONS for name in m.tests}

    by_package: dict[str, list[str]] = {}
    for name, package in home.items():
        by_package.setdefault(package, []).append(name)

    print(f"baseline: running the {len(home)} guard tests against the unmutated tree")
    for package, names in by_package.items():
        pattern = "^(" + "|".join(sorted(names)) + ")$"
        green = go("test", "-count=1", "-run", pattern, package)
        if green.returncode != 0:
            print(green.stdout[-800:], green.stderr[-800:])
            print(f"::error::baseline FAIL: {package} guard tests are not green on the unmutated "
                  f"tree, so a failure under mutation would prove nothing; refusing to interpret "
                  f"the result")
            return 1
    print(f"baseline: PASS (all {len(home)} guard tests green on the unmutated tree)\n")

    outcome = 0
    detail: list[str] = []

    for index, mutation in enumerate(MUTATIONS, start=1):
        print(f"=== {index}/{len(MUTATIONS)} {mutation.name}")
        print(f"    {mutation.target.relative_to(ROOT)}  ->  {', '.join(mutation.tests)}")
        try:
            # Bytes, not text. Path.write_text opens in text mode with universal newline
            # translation, which on Windows rewrites every \n to \r\n and makes the mutation land
            # against a different byte sequence than the one that was searched.
            mutation.target.write_bytes(
                texts[mutation.target].replace(mutation.find, mutation.replace).encode("utf-8"))

            mutated = mutation.target.read_bytes().decode("utf-8")
            if mutated == texts[mutation.target] or mutation.replace not in mutated:
                print("  ::error::the mutation did not land in the file; refusing to interpret the "
                      "result")
                detail.append(f"{mutation.name}: the mutation did not land")
                outcome = 1
                continue

            # The soundness check: a mutation that does not compile makes every test in the package
            # exit non-zero without any of them running, which would be reported as detection for
            # all of them at once.
            compiled = build(mutation.package)
            if compiled.returncode != 0:
                print("  [UNCERTIFIED] the mutation does not compile, so no test ran and nothing "
                      "was established:")
                print("   ", (compiled.stderr or compiled.stdout).strip().replace("\n", "\n    "))
                detail.append(f"{mutation.name}: the mutation does not compile, so the package was "
                              f"never tested")
                outcome = 1
                continue

            undetected: list[str] = []
            uncertified: list[str] = []
            for name in mutation.tests:
                verdict, evidence = anchor_gate.classify(run_test(mutation.package, name))
                if verdict == anchor_gate.DETECTED:
                    print(f"  [detected] {name}")
                elif verdict == anchor_gate.PASSED:
                    print(f"  [NOT DETECTED] {name} passed against a broken guard")
                    undetected.append(name)
                elif verdict == anchor_gate.BUILD_FAILURE:
                    reason = f"the package did not build ({evidence}), so no test ran"
                    print(f"  [BUILD FAILURE] {name}: {reason}; this is not a detection")
                    uncertified.append(f"{name}: {reason}")
                else:
                    reason = ("go test exited non-zero without a --- FAIL line, so it is not "
                              "established that any test ran")
                    print(f"  [INDETERMINATE] {name}: {reason}")
                    uncertified.append(f"{name}: {reason}")

            if undetected:
                detail.append(f"'{mutation.name}': " + ", ".join(undetected) +
                              " passed against the broken guard, so they do not test that property")
                outcome = 1
            if uncertified:
                detail.append(f"'{mutation.name}': " + "; ".join(uncertified) +
                              " - these runs proved nothing and cannot be credited")
                outcome = 1
        finally:
            mutation.target.write_bytes(originals[mutation.target])
            if mutation.target.read_bytes() != originals[mutation.target]:
                print(f"  ::error::failed to restore {mutation.target.name} byte-for-byte; the "
                      f"working tree is unsafe and must be restored by hand")
                detail.append(f"{mutation.target.name} could not be restored")
                outcome = 1
        print()

    # The restore only means something if what it restored is usable, so both packages are built
    # again here rather than trusted from the per-mutation pre-flight builds.
    for package in (MIGRATE_PKG, COMMAND_PKG):
        final = build(package)
        if final.returncode != 0:
            print(f"::error::{package} does not build after restoration")
            detail.append(f"{package} does not build after restoration")
            outcome = 1
    if outcome == 0:
        print(f"  both packages restored and building again: True")
        print(f"destructive-migration mutation gate: PASS (all {len(MUTATIONS)} properties are "
              f"enforced, each noticed by a failing assertion rather than a broken build)")
        return 0

    print()
    for line in detail:
        print(line)
    print("::error::destructive-migration mutation gate: FAIL - see the findings above")
    return outcome


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    except SystemExit as exit_code:
        code = exit_code.code if isinstance(exit_code.code, int) else 1
    except BaseException:
        # The backup is deliberately left in place. Whatever went wrong, the tree may be mutated,
        # and this is the only thing that can put it back on the next run.
        raise
    else:
        # main() returned, so every file it mutated has been restored and verified.
        discard_backup()
    sys.exit(code)
