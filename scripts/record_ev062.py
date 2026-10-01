"""One-off: append EV-062.

Closes G5.7. EV-060 established that a gate-satisfying PostgreSQL driver existed and that
adopting it was the project owner's decision; EV-061 verified the SQL against a live server but
stated plainly that the Go control plane still could not reach that database, so every adapter
behind the durable ports remained unexercised. This record covers the work that closed both: the
database/sql migration store, the operator CLI, the process entrypoint, and the live tests that
run the entrypoint as a separate OS process.

Product code and CI changed here. The G5 verdict changed from FAIL to PASS as a consequence, and
that is recorded in this entry rather than inferred from it.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-062"
STAMP = "2026-10-01T09:10:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "A running OS process performs the durable rebuild on startup against a live PostgreSQL "
    "17.11, with the SQL adapters behind every durable port. services/control-plane/cmd/control-"
    "plane reads its configuration from the environment, opens and pings the database, assembles "
    "the real SQL sink, chain reader, model store, model snapshot reader and both identity "
    "adapters, calls bootstrap.Build to rehydrate the audit chain, the journal and the workload "
    "registry, binds a socket only after that rebuild succeeds, and serves /healthz and /readyz "
    "until interrupted. TestARunningProcessRebuildsItsStackFromPostgreSQLOnStartup compiles that "
    "binary, seeds a model, an audit trail and a revocation through the real write paths, runs "
    "the binary as a separate process, and asserts over HTTP that it recovered the model, the "
    "partition, the environment, the revocation, and that it reports its write path as not "
    "exposed. G5.7 moves from FAIL to PASS; the gate moves from FAIL to PASS."
)

METHOD = (
    "Four pieces of work, each verified against the live database rather than argued. First, "
    "migrate/store_sql.go: the reviewed parked migrate.PgStore was ported from pgxpool to "
    "database/sql. The bodies carry their own BEGIN and COMMIT, which would close the store's "
    "outer transaction mid-flight, so stripTxControl removes them and the store owns the single "
    "transaction instead; store_sql_test.go covers that the stripping does not damage real SQL. "
    "Second, cmd/migrate, ported from the parked CLI to database/sql with lib/pq imported for its "
    "side effect. Exercised as a real binary: a dry run with no database, an unknown direction, a "
    "missing DATABASE_URL, status against an applied set, an idempotent re-run of up, then a full "
    "down to a clean catalog and up again. Third, cmd/control-plane, written as the process "
    "entrypoint with startup timeout, listener bound before readiness is announced, graceful "
    "shutdown on SIGINT or SIGTERM, and readiness reflecting the guard's true state. Fourth, the "
    "live test suite, which is where the two failures that mattered were found. The entrypoint "
    "tests compile the binary rather than trusting a prebuilt one, so a broken source tree cannot "
    "pass; the child's environment is filtered rather than appended to, because append-order "
    "precedence for duplicate variables differs between Windows and POSIX and the first version "
    "of these tests silently asserted the wrong thing on Windows."
)

RESULT = (
    "Default unit suite with -race: 10 packages ok across audit, authz, bootstrap, config, "
    "db/contract, ledger, migrate, model and strategy. Integration suite with -race: 16 tests "
    "pass, 0 fail. New coverage in this entrypoint: TestAModelRegisteredByOneStackSurvivesAProcess"
    "Restart and TestARestartedStackRefusesToRegisterTheSameModelTwice (G5.7's in-process half), "
    "TestWorkloadIdentitySurvivesAProcessRestart and TestRevocationSurvivesAsARecordBesideIts"
    "Issuance (identity and revocation rehydration, with the revoked identity required to come "
    "back revoked, absent from the live registry, and carrying its reason and evidence), "
    "TestARunningProcessRebuildsItsStackFromPostgreSQLOnStartup (the separate OS process), "
    "TestTheEntrypointRefusesToStartWithoutItsConfiguration (4 subtests: missing DSN, missing "
    "environment, guard limit 0, guard limit 'lots'), and TestTheEntrypointRefusesToStartOnA"
    "RegistryThatHasDriftedFromItsAuditChain. The CLI's full cycle ran green, and the process "
    "reported: 'started in SIMULATION; rehydrated 1 models and 1 audit records across 1 "
    "partition(s) [owner-14492-1]; 0 active workload identities and 1 revocations'. "
    "Verification elsewhere unchanged and still green: toolchain gate 14 of 14; tests/ci 115 "
    "passed; project brain gate PASS with 21 of its own tests passed; contracts VALID; research "
    "worker 109 passed; backtest worker 47 passed; migration rehearsal PASSED with a clean "
    "catalog after revert and all 36 objects present again."
)

DEFECT_FOUND_AND_FIXED = (
    "Four, and three of them are the same class of error EV-060 and EV-061 both recorded: "
    "believing a check before testing that it can fail. First, restart_test.go exported without "
    "calling Exporter.Accept, so Export's final step released a backlog the guard had never been "
    "told about and the guard refused the count mismatch - a real refusal by working code, "
    "correctly read as a test that had the order wrong. Second, and subtler: the test supplied a "
    "partition that the journal never used, because the journal derives an audit record's "
    "partition from the model's owner and not from any caller-supplied scope. Every run therefore "
    "collided with every previous run, first on "
    "audit_records_partition_sequence_key and then on audit_records_pkey. That presented as two "
    "distinct database errors and was one test bug; the fix is a unique owner per run. Third, a "
    "recursive replacement rewrote the body of entryWithOwner to call itself and the test binary "
    "died with a stack overflow, which is an unambiguous failure and cost only a cycle. Fourth, "
    "and in production code rather than in a test: the entrypoint's readiness endpoint was first "
    "written to report 200 whenever the guard was merely not halted, which would tell a "
    "supervisor to send traffic to a process whose next accepted record latches the guard. It now "
    "reports 503 both when the guard is halted and when the backlog has reached its limit. Also "
    "corrected rather than left: CI's integration job would have failed on a missing relation, "
    "because the rehearsal spins up a disposable container and discards its own schema, so the "
    "job now applies migrations to the long-lived service database through the real CLI; and the "
    "obsolete no-driver comment in that step and in audit/reader_test.go was replaced with what is "
    "now true, and the parked pgx store README was given a supersession banner rather than "
    "rewritten, so the record of the wrong argument survives."
)

SIGNIFICANCE = (
    "The gap this closes is the one that made every previous durability claim weaker than it "
    "looked. The restart tests before this entry compared two values of a variable inside one "
    "process, and the SQL beneath them had never been parsed by a database. Both halves are now "
    "real: the tests run the compiled binary as an independent OS process, and every adapter they "
    "touch is the one the process uses in production. The drift test is the most valuable "
    "addition, because it was not in the plan. Starting the process against a partition it was not "
    "configured for produces a registry that cannot be corroborated against the audit chain, and "
    "the process exits 2 rather than serving. A control plane that started anyway would report the "
    "model as unregistered, and the caller's natural response - register it again - would write a "
    "second SUCCEEDED audit record for a registration that already happened. That is precisely "
    "the failure G5 exists to catch, and it was surfaced accidentally by a broken test that had "
    "supplied the wrong partition; it is now asserted on purpose. The driver decision also "
    "resolves a long-running contradiction rather than merely adding a dependency: docs/00 names "
    "the stack as Go, Chi, pgx, sqlc, so pgx was the documented intent, yet WI-106 parked "
    "complete reviewed code because pgx alone could not satisfy the pinning gate. One candidate's "
    "property had been generalised into a claim about all candidates, so a documented, reviewed "
    "migration store and CLI sat unused for the whole of that work. Nothing in the pinning gate "
    "was weakened to get here."
)

CAVEATS = (
    "Six limitations, stated rather than left for a reader to find. First, and most important, "
    "the process exposes no write path: audit records reach durable storage through a "
    "caller-driven accept-then-export pair, and no background loop can substitute for it because "
    "the chain does not record which of its records have already been exported, so re-exporting "
    "one violates the audit table's unique constraint. /readyz reports write_path_exposed as false "
    "and the entrypoint refuses to serve at its backlog limit rather than implying a drain that is "
    "not happening, but the write path itself is the next piece of work and is not claimed here. "
    "Second, the graceful shutdown path is not proven by these tests. stopEntrypoint uses Kill, "
    "because on Windows os.Process.Signal does not deliver os.Interrupt to another process, so the "
    "SIGTERM drain is exercised only by an operator's actual shutdown and not by this suite. "
    "Third, the audit-acceptance and registry-persistence guarantees remain assigned to WI-120 and "
    "WI-121, so this gate does not claim cross-store atomicity between a registry write and its "
    "audit record; the migration store's own atomicity, that a migration body and its applied-set "
    "record commit together, is covered. Fourth, the CI change is unexecuted: this environment has "
    "no GitHub Actions runner, so the new 'apply migrations to the integration database' step and "
    "the CI invocation of cmd/migrate are verified only by running the same command locally "
    "against the same PostgreSQL 17.11 image. Fifth, the entrypoint's HTTP surface is two "
    "endpoints about the process rather than the domain, so nothing in this entrypoint is an API. "
    "Sixth, the migration store's port kept PgStore's reviewed logic but its isolation level, "
    "connection-pool behaviour and mid-commit error paths are exercised only through the tests "
    "listed above, not adversarially. Unchanged: docs/ remains clean at zero modifications, nothing "
    "was staged, nothing was committed, the schema-version forward problem remains human-owned, "
    "the unqualified audit and authz tables remain WI-117's, and RISK-14's deferred scaling "
    "findings are open. The G5 report's human_reviewer remains null; this record and the gate "
    "report attest to the mechanical verification only, not to a named human sign-off."
)

EXCEPTION = ""

ARTIFACTS = [
    "services/control-plane/migrate/store_sql.go",
    "services/control-plane/migrate/store_sql_test.go",
    "services/control-plane/cmd/migrate/main.go",
    "services/control-plane/cmd/control-plane/main.go",
    "services/control-plane/integration/restart_test.go",
    "services/control-plane/integration/identity_test.go",
    "services/control-plane/integration/entrypoint_test.go",
    "services/control-plane/audit/reader_test.go",
    ".github/workflows/ci.yml",
    ".kilo/ecc/project-brain/evidence/wi-106/parked-pgx-store/README.md",
    "evidence/gates/G5-gate-report.json",
    "evidence/gates/G5-gate-report.md",
    "scripts/generate_g5_gate_report.py",
    "scripts/record_ev062.py",
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