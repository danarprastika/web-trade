"""One-off: append EV-065.

EV-064 corrected a false claim and, in doing so, named the root cause without closing it: the
integration suite skips rather than fails when DATABASE_URL is absent, so nothing anywhere
enforced the invariant. This record closes the two gaps that the correction exposed, both of them
consequences of the same defect rather than new findings.

The first is the root cause. The CI integration job now fails loudly when DATABASE_URL is unset
or the database is unreachable, so a lost service can no longer produce seventeen skips reported
as a green gate. The guard was verified to distinguish the two cases rather than merely exist:
exit 0 against a live database listing four applied migrations, non-zero with a connection-refused
error against a dead port.

The second is the graceful shutdown drain, which EV-062, EV-063 and EV-064 each recorded as
unproven on Windows because Windows cannot deliver os.Interrupt to another process. It is now
proven on every platform. serve() takes its interrupt channel as a parameter, which is a pure
extraction - same order, same deadlines, same exit codes - and lets a test drive the drain through
a real TCP listener and a real HTTP request. Three tests cover it, and they were mutation-checked
rather than merely observed passing.

This record also corrects WI-141's completion note, which still asserted the drain was unproven
and did not point at EV-064. A completion note is the first thing a human reads, so a stale caveat
there is worse than one buried in an evidence record.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-065"
STAMP = "2026-10-01T11:05:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The two gaps EV-064 exposed are closed. First, the root cause of its correction: the CI "
    "integration job now fails loudly when DATABASE_URL is unset or the database is unreachable, "
    "so the seventeen-skip-behind-an-ok failure mode cannot recur unnoticed. Second, the graceful "
    "shutdown drain, which three consecutive records described as unproven on Windows, is now "
    "proven on every platform: an in-flight request is answered completely after the interrupt, new "
    "requests are refused, the shutdown deadline is honoured rather than waited out, and a failed "
    "listener is reported as an unexpected stop. WI-141's completion note, which still carried the "
    "stale drain caveat and no pointer to EV-064, is corrected."
)

METHOD = (
    "The CI guard was verified to discriminate rather than merely to exist, because a step that "
    "always passes is the same class of defect at a different level. scripts/... run against a live "
    "PostgreSQL 17.11 it exits 0 and lists four applied migrations; run against a dead port it exits "
    "non-zero with a connection-refused error. The workflow was then parsed as YAML to confirm the "
    "step landed in the integration job after the migration step and immediately before the test "
    "step, and the step order was read back: resolve modules, rehearsal, apply migrations, sqlc is "
    "up to date, sqlc vet, the reachability guard, integration tests. For the drain, the signal "
    "channel was made a parameter of serve() so a test can close it directly. That is a pure "
    "extraction: the interrupt handling, the stop-accepting-then-wait ordering, the shutdown "
    "deadline and all three exit codes are byte-for-byte the code that was already running, and the "
    "existing integration tests still pass against it, which is the check that the refactor changed "
    "nothing. The three new tests were then mutation-checked, because this session has already "
    "recorded a test that passed without executing what it claimed to: replacing the graceful "
    "server.Shutdown with a hard server.Close fails two of the three, and the failure is reported "
    "at the pre-release assertion rather than the final one, which is itself informative. The first "
    "draft of the in-flight test also had two defects found by running it rather than reading it: "
    "the URL helper omitted the scheme, so every request errored before it was sent and the "
    "stop-accepting loop would have passed on a request that never left the process; and the test "
    "deadlocked, waiting for a response that could not arrive until a handler it had not released "
    "returned. The helper now owns the scheme so a call site cannot omit it. WI-141's note was "
    "corrected by a script that refuses to act unless the exact stale text appears exactly once, "
    "and which verifies after writing that completion_note is the only field that changed."
)

RESULT = (
    "serve() in services/control-plane/cmd/control-plane/main.go now takes the interrupt channel "
    "and the shutdown timeout as parameters; run() supplies the real ones from signal.Notify and "
    "the parsed configuration, so production behaviour is unchanged. Three tests in "
    "cmd/control-plane/main_test.go pass under -race: an in-flight request is still answered with "
    "status 200 and the exact body after the interrupt and after a deliberate hold, new requests are "
    "then refused, and serve returns 0; a request that outlives the deadline causes serve to return "
    "1 within a bounded time rather than hanging; a closed listener causes serve to return 1 rather "
    "than a clean-shutdown 0. Mutating Shutdown to Close fails the first two. The integration job "
    "gained a step that fails when DATABASE_URL is empty and otherwise runs "
    "cmd/migrate -direction status, verified to exit 0 live and non-zero on a dead port. "
    "WI-141's completion note now records the drain as proven, states the mutation check, and "
    "points at EV-064 for the corrected integration-suite invocation, naming the wrong variable and "
    "the true 17/0/0 result. Full re-verification after every change: gofmt clean across the module; "
    "go vet exit 0 with and without the integration tag; default suite -race 10 packages ok "
    "including the new cmd/control-plane package; integration suite -race 17 passed, 0 failed, 0 "
    "skipped against a live database; toolchain gate 14 of 14; tests/ci 115 passed; spec gate 22 "
    "passed; project brain gate PASS; evidence-reference audit 0 items drifted; contracts VALID; "
    "research worker 109 passed; backtest worker 47 passed; migration rehearsal PASSED with a clean "
    "catalog; driver probe still reports libpq PASS, pgx FAIL and all three controls FAIL. The G5 "
    "report regenerated at 78 artifact digests, verdict PASS, all seven criteria PASS and "
    "mechanically verified, including the new test file. docs/ clean, nothing staged, nothing "
    "committed."
)

DEFECT_FOUND_AND_FIXED = (
    "Four. Two of them are the two closed gaps above: the unenforced DATABASE_URL invariant, and the "
    "drain that nothing could exercise. The other two were in the new test itself, and both were "
    "found by running the test rather than reading it, which is the only reason they were found at "
    "all. First, the URL helper built request URLs without a scheme, so http.NewRequest rejected "
    "every one of them; the in-flight request never reached the handler, and the assertion that the "
    "listener had stopped accepting would have passed immediately on a connection error produced by "
    "a request that was never sent - a green assertion proving nothing, in a session that had already "
    "recorded a green assertion proving nothing. The helper now prepends the scheme itself so the "
    "mistake is not available to a call site. Second, the test deadlocked: it waited for the drain "
    "to answer the in-flight request while the drain waited for a handler the test had not released. "
    "The handler is now released only after the interrupt, and the test additionally asserts that "
    "the response has not yet arrived, so it distinguishes a drain that waited from a response that "
    "happened to flush early."
)

SIGNIFICANCE = (
    "The recurring theme of EV-060, EV-061 and EV-064 is that this repository's failures are "
    "verification failures rather than code failures, and EV-065 closes the loop on all three by "
    "removing the conditions that let them hide. The unreachability guard exists because a skip is "
    "the right behaviour for a developer and the wrong behaviour for a gate, and nothing had ever "
    "made that distinction mechanical. The drain exists because a claim about graceful shutdown was "
    "being carried as a limitation rather than a test, on the grounds that the platform could not "
    "express it - which was true only of signalling another process, not of the drain itself. And "
    "the mutation check exists because 'the test passes' and 'the test can fail' are different "
    "facts, and this session has now produced a passing test three times, one of which passed "
    "without running anything, one of which would have passed on an error that proved the opposite "
    "of its claim, and one of which is only trustworthy because it was broken on purpose first. The "
    "generalisable point is narrow and worth stating: a test that has never been seen to fail is "
    "evidence of nothing, and the cheapest way to establish that a test can fail is to break the "
    "thing it tests."
)

CAVEATS = (
    "Five limitations. First, the drain tests drive the interrupt channel rather than a real "
    "signal, so what is proven is the drain's behaviour once notified, not the platform's delivery "
    "of SIGTERM to this process; the production wiring from signal.Notify to that channel is "
    "unchanged and still only exercised by an operator's actual shutdown. Second, the mutation check "
    "was run by hand and is not part of the suite, so nothing prevents a future change from making "
    "these three tests vacuous; encoding a mutation harness in CI is a larger decision than this "
    "entry makes. Third, the CI guard was verified locally against a live database and a refused "
    "port, but the workflow itself has not been executed on a runner, so the step's behaviour inside "
    "GitHub Actions is unverified. Fourth, the new tests use a 100ms window to assert the in-flight "
    "request had not yet been answered, which is a timing assumption; it is generous for a local "
    "handler that is explicitly held, but it is a sleep-adjacent assertion and could in principle "
    "misbehave on a heavily loaded machine. Fifth, and unchanged: the G5 report's human_reviewer "
    "remains null so WI-141 stays IN_PROGRESS, cross-store atomicity between a registry write and "
    "its audit record remains WI-120 and WI-121's and is not claimed here, the unqualified audit and "
    "authz tables remain WI-117's, RISK-14's deferred scaling findings remain human-owned, and the "
    "schema-version forward problem is untouched. The write path is still not exposed over HTTP, and "
    "/readyz still reports write_path_exposed as false. The untracked set now includes "
    "evidence/gates/G5-gate-report.json and services/control-plane/go.sum, both of which the build "
    "and the gate depend on and neither of which is committed, because staging and committing were "
    "outside the instruction. Nothing was staged and nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/cmd/control-plane/main.go",
    "services/control-plane/cmd/control-plane/main_test.go",
    "services/control-plane/integration/entrypoint_test.go",
    ".github/workflows/ci.yml",
    "scripts/repair_wi141_drain_and_ev064.py",
    "scripts/record_ev065.py",
    ".kilo/ecc/project-brain/work-items.json",
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
]

SUPERSEDES = []


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    line = json.dumps(
        {
            "schema": "ecc.project-brain/evidence/v7",
            "evidence_id": EVIDENCE_ID,
            "recorded_at": STAMP,
            "recorded_by": "team-lead",
            "work_item": WORK_ITEM,
            "claim": CLAIM,
            "status": "VERIFIED",
            "method": METHOD,
            "result": RESULT,
            "defect_found_and_fixed": DEFECT_FOUND_AND_FIXED,
            "significance": SIGNIFICANCE,
            "caveats": CAVEATS,
            "exception": EXCEPTION,
            "artifacts": ARTIFACTS,
            "supersedes": SUPERSEDES,
        },
        ensure_ascii=False,
    )

    if store.exists():
        for existing in store.read_text(encoding="utf-8").splitlines():
            if existing.strip() and json.loads(existing).get("evidence_id") == EVIDENCE_ID:
                print("unchanged: " + EVIDENCE_ID + " already recorded")
                return False

    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print("recorded " + EVIDENCE_ID)
    return True


if __name__ == "__main__":
    record()
