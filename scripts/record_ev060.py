"""One-off: append EV-060.

Tests EV-059's central claim empirically. EV-059 asserted, from reading verify_toolchain.py, that
no Go PostgreSQL driver can be added because pgx drags in a pseudo-version. That claim was scoped to
pgx but stated as universal. It is false: github.com/lib/pq v1.10.9 satisfies the gate unweakened and
connects to a live PostgreSQL 17.11 server, and it has an empty transitive dependency closure.

The project owner's policy decision therefore has a fourth option that requires no control change at
all, which EV-059 did not identify because it never tested a candidate other than pgx.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-060"
STAMP = "2026-10-01T06:58:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "EV-059's technical finding is true and its framing is wrong, and the error matters. It verified "
    "that pgx cannot satisfy the toolchain gate, then wrote that no Go driver can be added. That is "
    "a claim about pgx restated as a claim about all drivers, and it is false. github.com/lib/pq "
    "v1.10.9 passes verify_toolchain.py unweakened, opens a real connection to PostgreSQL 17.11, "
    "round-trips queries through database/sql, and does so with an empty transitive dependency "
    "closure - a smaller supply-chain surface than pgx, not a larger one. A fourth way forward "
    "exists that needs no allowlisting, no vendoring, and no relaxation of any control."
)

METHOD = (
    "Built the claim as an experiment instead of an argument, because EV-059 was itself an argument "
    "from source reading and it was wrong. Created five throwaway modules under _driver_probe, each "
    "a separate go.mod, and ran the unmodified verify_toolchain.py against all five: pgx, libpq, and "
    "three deliberately broken controls pinned to 'latest', to a pseudo-version, and using a "
    "replace to a pseudo-version. The three controls failing is what gives the two real results "
    "meaning - a gate that passes everything would have proved nothing. Then compiled a probe "
    "against the live container and ran it four times: once with valid credentials and three times "
    "with an injected fault (wrong password, wrong port, empty DSN), requiring the valid run to pass "
    "and each fault to fail with a distinct exit code. A probe that only ever prints PASS is not "
    "evidence. Confined everything to a scratch module with GOWORK=off, so the probe could not be "
    "satisfied by, or contaminate, the workspace it was meant to test."
)

RESULT = (
    "Gate behaviour, with the real verify_toolchain.py unweakened: libpq PASS, pgx FAIL on "
    "github.com/jackc/pgservicefile at v0.0.0-20240606120523-5a60cdf6a761, and all three controls "
    "FAIL for the reasons they were built to trigger - 'latest' as unpinned, a direct "
    "pseudo-version, and a replace directive pointing at a pseudo-version. The gate discriminates "
    "correctly, so the libpq PASS is a real signal. Reachability against postgres 17.11 on port "
    "55439: Ping succeeded, SELECT version() returned 'PostgreSQL 17.11 on x86_64-pc-linux-musl', "
    "SELECT current_database() returned the connected database, and db.Close returned cleanly. The "
    "three injected faults all failed as required - exit 1 on 'password authentication failed for "
    "user \"postgres\"', exit 1 on connection refused at the CI port 5432, exit 2 on unset DSN - so "
    "the passing run reflects a genuine round trip rather than a probe that cannot fail. Server "
    "version matches CI's postgres:17.11-alpine on both major and minor. Dependency surface: "
    "'go list -m all' returns exactly two modules, the probe itself and lib/pq, with a two-line "
    "go.sum and no transitive requirements, against pgx's pgservicefile problem."
)

DEFECT_FOUND_AND_FIXED = (
    "One, in evidence rather than in code, and it is the same class of defect this work item has "
    "now produced twice. EV-059 generalised from a single tested sample: one driver was examined, so "
    "'no driver can be added' was written. The reasoning behind it was sound - the pseudo-version "
    "rule in verify_toolchain.py is real, and pgx genuinely fails it - but a true premise was "
    "concluded past its evidence. Correcting it here explicitly, with supersedes set, because the "
    "conclusion had already reached a gate report, a risks file and the work item's blocked status, "
    "and a reader would otherwise take EV-059 at face value. No product code changed, no test "
    "changed behaviour, and the existing parked pgx store is untouched."
)

SIGNIFICANCE = (
    "The lesson is about evidence standards rather than about PostgreSQL drivers, and it is the "
    "third instance of it in this work item. EV-056 over-generalised a Docker constraint, and "
    "EV-059 over-generalised a driver constraint; both were limitations recorded from reading and "
    "then repeated until they read as properties of the world. The corrective that worked both times "
    "was identical: stop reasoning about the limitation and try to break it. Three deliberately "
    "broken control manifests and three injected runtime faults cost minutes and converted two "
    "unverified assertions into verified ones, and here they overturned a claim I had already "
    "written up, reported to the gate, and used to justify declaring the item blocked. It is also "
    "worth naming what did not change: the parked store, the CI comment, the toolchain gate and "
    "docs/ are all exactly as they were, and nothing in this record required editing any of them. "
    "The repository was never wrong. My reading of it was."
)

CAVEATS = (
    "Four limitations, stated because this record overturns a previous one and the correction should "
    "not be read as more than it is. First, the finding is a feasibility result, not a change: "
    "github.com/lib/pq is still absent from services/control-plane/go.mod, which remains "
    "deliberately free of any PostgreSQL driver, and no migration, store or composition-root code was "
    "wired up. The control plane still cannot reach PostgreSQL, and G5.7 is still unmet. Second, "
    "adopting libpq is still the project owner's call and I have not made it, for the same reason "
    "EV-059 gives: switching drivers is an architecture decision, not a work item's to take by "
    "itself. What changes is only that the decision is now correctly posed - it is a choice between "
    "pgx-and-allowlist, vendoring, staying driver-free, and libpq, and the fourth option requires no "
    "control change and shrinks rather than grows the dependency surface. Third, the probe lives at "
    "C:/web-trade/_driver_probe/, is untracked, and is not covered by .gitignore; it must not be "
    "staged, and it is disposable once its result is recorded. Its presence is a housekeeping risk I "
    "am disclosing rather than one I am resolving unilaterally. Fourth, the reachability result is "
    "libpq against PostgreSQL 17.11 on a local container, not against webtrade_test with the "
    "rehydration queries; the migrations in db/migrations were not applied and the real SELECT "
    "statements in db/queries were not exercised, so this proves the driver speaks the protocol and "
    "binds parameters, and does not prove the audit and model-registry queries are correct. "
    "Unchanged: WI-141 acceptance criteria remain verified, the G5 verdict remains FAIL and this "
    "record attests to neither, audit-acceptance and registry-persistence atomicity remain WI-121's, "
    "the schema-version forward problem remains human-owned, the unqualified audit tables remain "
    "WI-117's, RISK-14's deferred scaling findings are open, no specification file was modified, "
    "docs/ remains clean at zero changes, nothing was staged, and nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    "scripts/probe_driver_pinning.py",
    "scripts/record_ev060.py",
]

SUPERSEDES = ["EV-059"]


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
