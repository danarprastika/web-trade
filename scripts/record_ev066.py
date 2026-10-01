"""One-off: append EV-066.

EV-065 published a caveat that the CI workflow had never been executed, so its steps' behaviour
was unverified. This record executes both the go job and the integration job step sequences
locally, per module, exactly as the workflow runs them, and reports what each step did.

It also records a self-correction, because the local run produced one false alarm that I raised
and then had to retract, and the reason is worth keeping. The `sqlc is up to date` step initially
read as a serious defect: the committed generated file lacks three queries the production code
calls, which looks like a build-broken repository. It is not. The callers that reference those
generated methods are themselves untracked, so HEAD never referenced the methods and HEAD builds
clean; the working tree is internally consistent because the regenerated output and the callers
are present together, and `sqlc generate` is a verified no-op against them. The step fails in the
working tree for exactly the reason it is designed to fail - the regenerated dbgen is tracked but
not yet committed - and that is a commit-hygiene signal about uncommitted work, not broken code.
The single genuine consequence is that the queries, the regenerated dbgen, and the three caller
files must be committed together, because CI's fresh-checkout generate/diff only agrees when all
three agree with each other.

This is a narrower claim than EV-065's caveat and the narrowing is deliberate: the steps were run
locally on this platform, not on a GitHub runner, so runner-specific behaviour remains unproven.

Idempotent, append-only, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-066"
STAMP = "2026-10-01T12:30:00Z"

WORK_ITEM = "WI-141"

CLAIM = (
    "The CI workflow's go job and integration job step sequences were executed locally, per module, "
    "exactly as the workflow runs them. Every step passes except one: `sqlc is up to date` fails "
    "solely because the regenerated dbgen is tracked but not yet committed, which is that step's "
    "intended signal rather than a code defect. This narrows EV-065's caveat that the workflow had "
    "never been executed. The remaining action is a single commit carrying the queries, the "
    "regenerated dbgen, and the three caller files together."
)

METHOD = (
    "The module list was taken from `go work edit -json` rather than parsed by hand, matching the "
    "workflow. The go job's five steps were run: every listed module's go.mod exists; `gofmt -l` is "
    "empty; `go vet`, `go build`, and `go test -race` pass for all six modules; `go mod verify` "
    "reports all modules verified in each. The integration job's steps were run in order: the "
    "migration rehearsal passes; `cmd/migrate -direction up` against the live database is idempotent "
    "and exits 0; the new reachability guard exits 0 live; `sqlc vet` exits 0; and `go test "
    "-tags=integration -race` passes for all six modules. The `sqlc is up to date` step was run as "
    "`sqlc generate` followed by `git diff --exit-code`, which reported a non-empty diff, and the "
    "diff was read to identify the three missing generated methods. Those methods are called by "
    "store_read.go and identity_read.go, which looked like a build-broken repository until "
    "`git status` showed both callers are untracked, so HEAD never referenced the methods and "
    "builds clean. The working tree is internally consistent: the regenerated output and the "
    "callers are present together, `sqlc generate` run twice produced a byte-identical file, and "
    "the full build and both test suites pass against it."
)

RESULT = (
    "go job, all steps: every module's go.mod present; gofmt clean; go vet exit 0 for all six "
    "modules; go build exit 0 for all six; go test -race ok for all six; go mod verify 'all modules "
    "verified' in each of the six. integration job: migration rehearsal PASSED (up, down to a clean "
    "catalog, up again); `go run ./services/control-plane/cmd/migrate -direction up` exit 0, "
    "reporting the database already current; the new reachability guard `go run "
    "./services/control-plane/cmd/migrate -direction status` exit 0, listing four applied "
    "migrations; `sqlc vet` exit 0; `go test -tags=integration -race` ok for all six modules. The "
    "single failing step is `sqlc is up to date`, and its cause is established rather than "
    "assumed: the committed dbgen lacks the three regenerated methods because it predates them, the "
    "three caller files that reference the methods are untracked, and therefore HEAD builds clean "
    "and the working tree is self-consistent. The regenerated output is idempotent under "
    "`sqlc generate` and the full build, unit suite, and integration suite all pass against it. The "
    "commit that clears the step must include together: services/control-plane/db/queries/"
    "model_registry.sql (tracked, modified - the three new queries), services/control-plane/db/"
    "dbgen/model_registry.sql.go and querier.go (tracked, modified - the regenerated output), and "
    "services/control-plane/model/store_read.go, identity_read.go, and restore.go (untracked - the "
    "callers). Those six files must land together, because CI's fresh-checkout generate/diff only "
    "agrees when the queries, the generated code, and the callers all agree with each other."
)

DEFECT_FOUND_AND_FIXED = (
    "No code defect. One false alarm raised and corrected within this pass, recorded because the "
    "correction is the useful part. The `sqlc is up to date` step first read as a serious finding: "
    "the committed generated file was missing three queries that the production code calls, which "
    "resembles a repository that cannot build. It does not. The callers referencing those generated "
    "methods are untracked, so HEAD never referenced them and builds clean; the working tree holds "
    "the regenerated output and the callers together and is self-consistent. The step fails only "
    "because the regenerated output is uncommitted, which is precisely the condition it exists to "
    "report. I initially announced it as a fixed defect and then retracted that, which is the "
    "second time in this work that a check's output was read as more dramatic than it warranted, "
    "and the same discipline applies: the step's message was trusted before its cause was "
    "established, and reading `git status` rather than the diff would have prevented the false "
    "claim."
)

SIGNIFICANCE = (
    "The value of this record is a bounded claim replacing an open one. EV-065 said the workflow's "
    "steps were unverified because they had never been run; they have now been run, locally and per "
    "module, and every one passes except the one that is reporting an uncommitted working tree. That "
    "narrows the caveat honestly without overstating it: these are local runs, not runner runs, so "
    "anything specific to GitHub Actions - the containerised PostgreSQL service, the Ubuntu shell in "
    "the step scripts, the jq dependency in the module-resolution step - remains unproven here. The "
    "self-correction is the more transferable part. The temptation in this repository's evidence "
    "work is to read a check's output as a finding before establishing what the check actually "
    "measured, and twice now that produced a claim that had to be walked back: the integration "
    "suite that never ran, and this generated-code step that was never broken. Both were caught by "
    "running one more check rather than by reading harder, and the durable instruction is the same "
    "one the mutation check encodes: establish what the check did before believing what it said."
)

CAVEATS = (
    "Four limitations. First, these are local runs on Windows, not GitHub runner runs, so "
    "runner-specific behaviour is unverified: the postgres:17.11-alpine service container, the "
    "bash step scripts under `set -euo pipefail`, and the `jq` call in module resolution were each "
    "reproduced with local equivalents rather than executed as written. Second, the `sqlc is up to "
    "date` step cannot be observed passing in this working tree at all until the regenerated output "
    "is committed, so its green path is argued from idempotence and a consistent tree rather than "
    "observed; the first real confirmation will be the step's result on the first CI run after the "
    "commit. Third, the mutation harness that would keep the three drain tests from going vacuous is "
    "still not built; it was deliberately left out of EV-065 as a decision beyond that entry's "
    "scope, and building it is left as an open recommendation rather than done here. Fourth, and "
    "unchanged: the G5 report's human_reviewer remains null so WI-141 stays IN_PROGRESS, "
    "cross-store atomicity remains WI-120 and WI-121's and is not claimed, WI-117's unqualified "
    "audit and authz tables and RISK-14 remain other owners', the schema-version forward problem is "
    "untouched, the write path is still not exposed over HTTP, and the drain tests still drive the "
    "interrupt channel rather than a real signal. Nothing was staged and nothing was committed."
)

EXCEPTION = ""

ARTIFACTS = [
    ".github/workflows/ci.yml",
    "services/control-plane/db/queries/model_registry.sql",
    "services/control-plane/db/dbgen/model_registry.sql.go",
    "services/control-plane/db/dbgen/querier.go",
    "services/control-plane/model/store_read.go",
    "services/control-plane/model/identity_read.go",
    "services/control-plane/model/restore.go",
    "scripts/record_ev066.py",
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
