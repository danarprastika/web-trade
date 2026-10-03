"""Open WI-175: a timing-sensitive advisory-lock test, and the skipped-test gap that let a real
regression pass unremarked.

The second half is the more valuable item and is not a defect in any single file: cmd/migrate's
live tests skip when DATABASE_URL is unset, so the package carrying the safety-critical change had
no live coverage in the local runs that were reporting it green.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"


def main() -> bool:
    doc = json.loads(STORE.read_text(encoding="utf-8"))
    items = doc["items"]
    by_id = {i["id"]: i for i in items}

    if "WI-175" not in by_id:
        items.append(
            {
                "id": "WI-175",
                "phase": 2,
                "title": "cmd/migrate's live tests skip without DATABASE_URL, so its behavioural coverage is invisible by default",
                "status": "PENDING",
                "priority": "high",
                "acceptance_criteria": [
                    "A local or CI run of the cmd/migrate package reports how many tests were "
                    "skipped as well as how many passed, so a green result cannot be a skip "
                    "wearing the costume of a pass",
                    "The package's live tests are exercised somewhere on every verification run - "
                    "either DATABASE_URL is set for that package, or a gate asserts that the live "
                    "tests ran rather than skipped",
                    "A regression confined to the live tests cannot pass the full verification "
                    "sweep, which is the property that was violated when WI-171's guard fix broke "
                    "four of those tests and nothing reported it",
                    "The same pass/skip reporting is applied to the other packages that skip "
                    "without a database, including integration and migrate",
                ],
                "source": "Found by an independent review of the WI-171 fix (EV-074); "
                "services/control-plane/cmd/migrate/main_test.go disposableDSN",
                "reproduction": "disposableDSN calls t.Skip when DATABASE_URL is unset, so the "
                "four tests that drive a real up/down/status against a scratch database - "
                "TestABoundedRevertStopsAtTheTarget, TestAnUnboundedRevertStillRevertsEverything, "
                "TestARevertToAVersionThatIsNotAppliedIsRefused and "
                "TestARevertToAnUnknownVersionIsRefused - do not run under a plain `go test "
                "./cmd/migrate/`. Observed directly: with DATABASE_URL unset the package passes; "
                "with it set, the same tree failed all four, each refused at the destructive guard "
                "because the scratch database was named migrate_cli_<pid>_<hex> and so announced "
                "itself neither disposable nor prefixed. The breakage had been present across two "
                "full verification sweeps and a green mutation gate before a reviewer's question "
                "about whether the new test was genuine prompted anyone to run the package with a "
                "database attached.",
                "notes": "This is the same failure class as EV-064, EV-071 and EV-072, reached from "
                "the opposite direction. Those were gates that reported success without verifying "
                "anything. This is a suite whose success depends on an environment variable that "
                "was never set, reported without a skip count, in the one package where the "
                "safety-critical behaviour lives.\n\n"
                "The fix is deliberately small. The regression itself is fixed and verified - the "
                "scratch database now uses the test_ prefix form and a cliEnv helper passes "
                "MIGRATE_ALLOW_DESTRUCTIVE=1, and the package is green with DATABASE_URL set. What "
                "is missing is the reporting, so that the next such breakage cannot hide behind a "
                "green line.\n\n"
                "Note the interaction with the mutation gate: mutation_check_destructive_migrate.py "
                "runs behavioural properties against cmd/migrate, and several of those properties "
                "are behavioural only because the guard refuses before connecting rather than "
                "because it refuses correctly. A skip would not fail the gate's baseline - a "
                "skipped package exits zero - so the gate could have been certifying properties "
                "that were not being exercised at all.",
                "dependencies": [],
            }
        )

    if "WI-176" not in by_id:
        items.append(
            {
                "id": "WI-176",
                "phase": 2,
                "title": "The advisory-lock serialisation test is timing-sensitive against a shared database",
                "status": "PENDING",
                "priority": "low",
                "acceptance_criteria": [
                    "TestTwoConcurrentRunsSerialiseOnTheAdvisoryLock cannot fail because the "
                    "machine was busy, so a failure means the lock genuinely did not serialise",
                    "The test either synchronises on observed state rather than on elapsed time, "
                    "or is given a tolerance that reflects the property being checked rather than "
                    "the speed of the host",
                ],
                "source": "Observed during the EV-074 verification sweep; "
                "services/control-plane/migrate/live_test.go:241",
                "reproduction": "During a full-module `go test -race -count=1 ./...` with "
                "DATABASE_URL set, this test failed once with 'the second run returned while the "
                "first still held the lock: err=<nil> applied=[0001_hand.sql]'. It then passed "
                "three consecutive times when run alone, and twice more in the identical full-module "
                "run. The assertion depends on wall-clock timing between two concurrent processes "
                "against one shared database.",
                "notes": "Not introduced by this change set and not touched by it - migrate/ has no "
                "modified tracked file. Recorded because a test that fails once in five under load "
                "will fail in CI eventually, and because the honest report is that it failed once, "
                "not that it is stable. The failure mode matters: the message says the second run "
                "completed while the first held the lock, which is the property under test, so it "
                "must be established whether this is a timing tolerance that is too tight or a real "
                "serialisation gap in the lock.",
                "dependencies": [],
            }
        )

    out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    with io.open(STORE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(out)

    print("WI-175 and WI-176 recorded")
    return True


if __name__ == "__main__":
    main()