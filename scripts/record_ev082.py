"""Record EV-082 to EV-089: eight gates that were reporting something they had not measured.

One evidence record per finding, in the same order as WI-181 to WI-188. Each records what was
claimed, how it was established by execution rather than by reading, what the result was, and what
is explicitly NOT claimed - including, for EV-087, the planted value that turned out never to have
been reported by the scanner and would otherwise have made that proof pass for a fourth unexamined
reason.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

STAMP = "2026-10-03T18:20:00Z"

SHARED_ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    ".github/workflows/ci.yml",
    "tests/ci/test_ci_workflow.py",
    "scripts/update_work_items_wi181.py",
    "scripts/record_ev082.py",
]

RECORDS = [
    {
        "evidence_id": "EV-082",
        "work_item": "WI-181",
        "claim": (
            "The vulnerability scan gate proof's resolve-step scenarios now execute and assert. "
            "All three had never run: one raised before reaching the step, one fed the step a `go` "
            "that printed nothing, and one decided whether jq was available by asking a different "
            "shell than the one that runs the step."
        ),
        "method": (
            "The CI step 'prove the vulnerability scan can fail' failed on 47a3137 and CI logs are "
            "not readable without authentication for this repository, so the script was read and "
            "executed locally. Each of the three defects was then reproduced in isolation before "
            "being fixed, and each fix was checked by re-running the proof with jq on PATH, which "
            "is the configuration in which the scenarios execute at all."
        ),
        "result": (
            "scripts/prove_vuln_scan_gate.py reports PASS (10 properties) ON A HOST THAT CAN RUN JQ, up "
            "from PASS (7). The count is host-dependent and the headline alone did not say so, "
            "which an independent review flagged: on a host without jq this proof reports PASS (7) "
            "with the three resolve scenarios explicitly skipped, so quoting 10 alone reads as "
            "though all ten had run here. On this host the observed result is PASS (7) with three "
            "skips, and the skips are reported by the proof rather than hidden. Where jq is "
            "available the three resolve scenarios no longer skip: 'resolve step lists every "
            "module', "
            "'resolve step refuses an empty workspace' and 'resolve step refuses a module with no "
            "go.mod' all execute and pass, and the real-scanner property runs rather than skipping "
            "on the control plane."
        ),
        "defect_found_and_fixed": (
            "1. scenario_resolve_refuses_missing_go_mod called rmdir() on a directory "
            "_build_sandbox had just populated, raising WinError 145; the exception escaped main() "
            "as a traceback naming neither the scenario nor a property. Now shutil.rmtree plus an "
            "assertion that the fixture is what it claims. "
            "2. _write_fake_go emitted a printf whose single quote was never closed, so the shim died "
            "with 'unexpected EOF while looking for matching' on every call; it is now asserted to "
            "answer `work edit -json` at construction time, because it is the entire input to three "
            "scenarios. "
            "3. has_jq used shutil.which, which asks whether Python can start jq, while the step runs "
            "under bash; on this host Python resolves jq.exe and WSL bash cannot run it, so three "
            "scenarios ran and failed with exit 127 instead of reporting the honest skip. "
            "4. _bash_can_run passed its command as \"$1\" to bash -c, and the bash reachable "
            "through the Windows path does not deliver positional parameters that way; every binary "
            "was reported unrunnable, which silently returned all three scenarios to a skip. "
            "5. _wsl_candidates was added because shutil.which('jq') returns a PATHEXT-derived "
            "jq.EXE while the file is jq.exe, and only the lowercase spelling launches under WSL "
            "interop."
        ),
        "significance": (
            "The proof exists to demonstrate that the vulnerability gate can fail. It had three "
            "scenarios that could not run, and its own step in CI had been red on every run since "
            "they were introduced - so the instrument was reporting on the gate while never "
            "touching three of its five properties. The interaction is the finding: each defect "
            "alone was survivable, and together they produced a step that was permanently red, "
            "never green, and never diagnosed, because the traceback named nothing and the "
            "captured output interleaved the fixture's parse error with 'jq: command not found'."
        ),
        "caveats": (
            "The three resolve scenarios execute on a host that can run jq. A host that cannot "
            "reports SKIP and states plainly that the coverage did not happen; it does not report a "
            "gate failure and it does not pass silently.\n\n"
            "Where jq must be supplied from a host binary the step's shell cannot resolve, a launcher "
            "is installed in the sandbox bin dir that execs the real binary and filters CR. The CR "
            "filter exists because a native jq writes CRLF and the step reads its output line by "
            "line; on a runner jq writes LF and the filter is a no-op. Nothing else about the "
            "block's filter is altered."
        ),
        "exception": "No exception. Nothing was skipped or weakened to reach a green proof.",
        "artifacts": SHARED_ARTIFACTS + ["scripts/prove_vuln_scan_gate.py"],
        "supersedes": [],
    },
    {
        "evidence_id": "EV-083",
        "work_item": "WI-182",
        "claim": (
            "Every install of workers/research's dev extra now resolves. It previously named "
            "jsonschema==4.26.1, a version that has never been published, so the pin could never be "
            "satisfied."
        ),
        "method": (
            "The CI step 'install research worker' failed with no further detail, and CI logs are "
            "not readable without authentication for this repository. The pin was checked against "
            "the PyPI JSON API and then reproduced locally with "
            "`python -m pip install --dry-run ./workers/research[dev]`, before and after."
        ),
        "result": (
            "`pip install --dry-run \"./workers/research[dev]\"` exits 0 and reports 'Would install'. "
            "The same command with the old pin fails with 'ERROR: Could not find a version that "
            "satisfies the requirement jsonschema==4.26.1 (from versions: ... 4.25.0, 4.25.1, "
            "4.26.0)'. PyPI reports 4.26.0 as the current release."
        ),
        "defect_found_and_fixed": (
            "workers/research/pyproject.toml pinned jsonschema==4.26.1, which does not exist. "
            "Changed to 4.26.0, the current release and the nearest published version. "
            "referencing==0.37.0 was added as an explicit declaration: "
            "tests/contracts/validate_contracts.py imports it directly, and jsonschema 4.26.0 "
            "requires referencing>=0.28.4, so 0.37.0 is inside its supported range. A direct import "
            "of a package that arrives only transitively is a missing pin, not a convenience."
        ),
        "significance": (
            "One unpublishable version number took out three CI steps across two jobs: the research "
            "worker's install, the backtest worker's install, and the dependency-scan job's python "
            "audit. It survived every local check because the package was already installed in the "
            "developer's environment, so pip never went to the network for it, and because "
            "scripts/verify_toolchain.py asserts that each pin is an exact `==` specifier - which a "
            "version that does not exist satisfies perfectly. No gate in the repository resolves a "
            "declared Python pin against its index, and that is a real gap this record does not "
            "claim to have closed."
        ),
        "caveats": (
            "The pin is not dead weight: "
            "workers/research/tests/test_canonical.py::test_schema_layer_rejects_document_cases "
            "executes tests/contracts/validate_contracts.py as a subprocess, so the research "
            "worker's environment must be able to import both packages. Verified by execution: the "
            "validator exits 0 in this environment and the research worker's own tests pass."
        ),
        "exception": "No exception. The version was corrected, not floated or dropped.",
        "artifacts": SHARED_ARTIFACTS + ["workers/research/pyproject.toml"],
        "supersedes": [],
    },
    {
        "evidence_id": "EV-084",
        "work_item": "WI-183",
        "claim": (
            "The contract validation job runs the validator instead of reporting a missing "
            "dependency as a contract failure. It installed nothing, and the validator's answer to "
            "a missing package is exit 2."
        ),
        "method": (
            "The CI step named 'validate canonical schemas against the shared corpus' failed with "
            "exit code 2. The validator's own source declares exit 2 as 'the corpus or a schema "
            "could not be loaded' and writes a FATAL line naming jsonschema and referencing, so the "
            "diagnosis came from the exit-code contract rather than from a log. Both new assertions "
            "were checked by mutation: removing the install step from the workflow makes "
            "test_every_job_that_runs_the_contracts_validator_first_installs_its_dependencies fail "
            "with the offending job named."
        ),
        "result": (
            "python tests/contracts/validate_contracts.py exits 0 locally with 'CONTRACTS VALID: the "
            "canonical corpus and schemas agree', 45 of 45 cases behaving as declared. "
            "tests/ci/test_ci_workflow.py reports the two new assertions passing, and the negative "
            "case was observed failing: 'contracts (runs validate_contracts.py at step 1 with no "
            "earlier pip install of tests/contracts/requirements.txt)'."
        ),
        "defect_found_and_fixed": (
            "The contracts job ran the validator directly after actions/setup-python, which provides "
            "a clean interpreter with no third-party packages. Added tests/contracts/requirements.txt "
            "with exact pins, an install step before the validator, and two assertions: that any job "
            "running the validator installs that file first and in order, and that its pins and the "
            "research worker's dev extra pins are identical."
        ),
        "significance": (
            "This is the third job to carry the same omission, after the toolchain, spec-gate and "
            "project-brain jobs, and the first where the failure presented as something other than a "
            "missing module: the validator exits 2 with a FATAL line about required packages, so the "
            "run read as a broken corpus. The assertion is deliberately written for every job that "
            "runs the validator rather than for the one that was diagnosed, because a fix applied to "
            "the instance rather than to the class is how WI-180 happened."
        ),
        "caveats": (
            "Two files now declare this dependency set - the job's requirements file and the research "
            "worker's dev extra - because the same validator runs as a subprocess from the research "
            "worker's tests. That duplication is unavoidable in Python packaging, so it is asserted "
            "identical rather than left to be noticed."
        ),
        "exception": "No exception.",
        "artifacts": SHARED_ARTIFACTS + ["tests/contracts/requirements.txt"],
        "supersedes": [],
    },
    {
        "evidence_id": "EV-085",
        "work_item": "WI-184",
        "claim": (
            "The web typecheck now passes from a clean checkout. It previously ran before Next.js "
            "generated the route types the console's own layout declares."
        ),
        "method": (
            "The CI step named 'typecheck' failed with the annotation \"Cannot find name "
            "'LayoutProps'\". Reproduced locally by deleting apps/web/.next and running "
            "`npx tsc --noEmit`, then the same command preceded by `npx next typegen`. The available "
            "Next.js was inspected through its own bundled CLI help rather than assumed."
        ),
        "result": (
            "From a clean tree, `npx tsc --noEmit` exits 2 with "
            "app/layout.tsx(26,50): error TS2304: Cannot find name 'LayoutProps'. "
            "`npx next typegen && npx tsc --noEmit` exits 0, and `npm run typecheck` exits 0. "
            "`npm run lint` and `npm run build` both exit 0 in the same job order CI uses."
        ),
        "defect_found_and_fixed": (
            "apps/web/package.json declared `typecheck: tsc --noEmit`, which ran before build and so "
            "before Next.js generated .next/types. Changed to `next typegen && tsc --noEmit`. The "
            "generated types come from the project's own pinned Next.js 16.3.6; nothing is "
            "checked in and nothing is ignored."
        ),
        "significance": (
            "The failure was real and reproducible only on a clean checkout, which is why a "
            "developer's machine had been reporting green: a previous `next build` left .next/types "
            "in place. It is the ordinary shape of a CI-only type failure - the test that matters runs "
            "in an environment nobody prepares by hand."
        ),
        "caveats": (
            "`next typegen` is a Next.js 16 command. It was confirmed against the installed package's "
            "own --help output rather than from memory, because this repository's web app carries a "
            "generated agent-rules block instructing exactly that when writing Next.js code."
        ),
        "exception": "No exception.",
        "artifacts": SHARED_ARTIFACTS + ["apps/web/package.json", "apps/web/tsconfig.json"],
        "supersedes": [],
    },
    {
        "evidence_id": "EV-086",
        "work_item": "WI-185",
        "claim": (
            "Each SAST job now analyses the language it is named for, and the Go leg can extract "
            "this repository at all. Previously all three analysed every language because the init "
            "step passed an input the action does not define, and Go's autobuild cannot build a "
            "checkout whose root has go.work and no go.mod."
        ),
        "method": (
            "All three jobs failed with the annotation 'Extraction failed for all discovered Go "
            "projects', and each job carried the workflow's own annotation reading \"Unexpected "
            "input(s) 'language', valid inputs are ['tools', 'languages', ...]\". The Go "
            "autobuild premise was then checked locally rather than assumed: `go build ./...` at the "
            "repository root fails with 'directory prefix . does not contain modules listed in "
            "go.work or their selected dependencies', while all six modules build individually. "
            "Both new assertions were checked by mutation: restoring `language:` and `autobuild` "
            "makes both fail."
        ),
        "result": (
            "The init step now passes `languages`, and the singular input is rejected by "
            "test_every_codeql_init_step_passes_inputs_the_action_actually_defines. "
            "test_the_go_sast_leg_builds_every_workspace_module_rather_than_autobuilding_the_root "
            "observes five properties of the Go leg: the build mode resolves through the matrix to "
            "`manual`, a step builds the workspace, that step precedes the analyse step, it is "
            "gated to the Go leg, and it reads its module list from a file while refusing an empty "
            "list. FIVE, not the two originally claimed - see the correction below. Observed under "
            "mutation: 'the Go leg must not use autobuild: it builds from a root that has no "
            "go.mod and therefore extracts nothing'.\n\n"
            "CORRECTION, recorded rather than quietly fixed: this record originally said the test "
            "'observes both properties of the Go leg', and it observed neither. Both assertions "
            "sat behind `if build_mode == \"manual\":`, but the init step passes the literal string "
            "`${{ matrix.build-mode }}`, so the comparison was never true and the guarded block "
            "never executed against the real workflow. An independent review established this by "
            "deleting the build step from an in-memory copy of the workflow and observing the test "
            "still pass. The gate the test protects was correctly configured throughout; what was "
            "wrong was the claim about the test, which is the same shape as the eight defects this "
            "batch exists to fix, one level up. The test now resolves the matrix expression before "
            "comparing it, so every assertion in it executes against the real workflow. Verified by "
            "five negative controls and two positive ones, enumerated in EV-091 rather than counted "
            "here: deleting the build step, reverting the loop to a process substitution, setting "
            "the Go leg's build mode to autobuild, widening the token exception, and pointing the "
            "proof at the excused shape each make the corresponding assertion fail, while the "
            "unmodified workflow and the shipped config pass. An earlier version of this sentence "
            "said 'four negative controls' and listed three, which disagreed with EV-091's seven and "
            "five - two records of one event giving different numbers, which is the same defect as "
            "an unverified claim, one level down. A later version of it called all seven negative, "
            "which was wrong too: two of the seven assert that unmodified input passes, and calling "
            "them negative would make the count agree with the wrong label. The enumeration lives in "
            "EV-091 and this refers to it, so there is one list.\n\n"
            "NOT CLAIMED: that the Go extraction succeeds on a runner. Manual build mode with a "
            "workspace build is the documented mechanism and the step is valid bash, but no local run "
            "can execute it - it requires the CodeQL tracer. This is the same class of unmet "
            "condition as WI-107's, and it is stated rather than papered over."
        ),
        "defect_found_and_fixed": (
            "1. `.github/workflows/ci.yml` sast job passed `language: ${{ matrix.language }}`, which "
            "codeql-action v3 does not define; the action ignores unknown inputs with a warning, so "
            "all three legs initialised every language and none analysed its own. Now `languages`, "
            "with an assertion that rejects the singular form. "
            "2. Autobuild builds from the checkout root, which has go.work and no root go.mod by "
            "design. Replaced with build-mode manual and a build that iterates the modules "
            "`go work edit -json` declares, failing by name on a module with no go.mod and before "
            "the analyse step. "
            "3. The matrix now states a build mode per language rather than one constant, and "
            "setup-go was added: the job had no toolchain for whatever autobuild invoked."
        ),
        "significance": (
            "A job named 'SAST (CodeQL) (python)' that never looked at the Python is the most "
            "expensive shape of silent pass in this repository, and it was produced by a single "
            "character of input naming. The action's warning was on the job the whole time, and "
            "nothing read it. Three red jobs and a warning in the run list, and the natural reading "
            "was 'SAST is broken', not 'SAST never ran'."
        ),
        "caveats": (
            "The module list is resolved from go.work rather than hardcoded, so a module added to "
            "go.work is extracted with no workflow edit - the same reasoning the dependency-scan "
            "job already records, and asserted here in the same way.\n\n"
            "The interpreted legs use build-mode none, which removes the need for setup-node and "
            "setup-python. setup-go is installed for the whole job rather than behind the Go leg's "
            "conditional, because a job whose build leg silently stopped having a compiler is "
            "indistinguishable from a clean extraction."
        ),
        "exception": (
            "One, stated explicitly: Go extraction on a runner is not verified. The configuration is "
            "the documented mechanism, the step parses as valid bash, and the negative controls "
            "execute; the positive outcome is not claimed."
        ),
        "artifacts": SHARED_ARTIFACTS,
        "supersedes": [],
    },
    {
        "evidence_id": "EV-087",
        "work_item": "WI-186",
        "claim": (
            "The secret scan runs with the default rule set plus two value-shaped exceptions, and "
            "the committed scan command is proved able to fail - including on a credential-shaped "
            "value in the one field the exceptions cover."
        ),
        "method": (
            "The CI step failed with exit code 1 and no detail. Reproduced locally with the "
            "committed container command, which reported nine findings with rule IDs, files, lines "
            "and commits. Each was inspected in the tree and in the named historical commits. The "
            "values involved are fixture data and one phrase of prose; they are not credentials, and "
            "the reason no value was printed into the repository is that --redact is on and the "
            "exceptions are written as value shapes rather than as copied values.\n\n"
            "The allowlist's scope was then established by execution rather than by argument: with "
            "the exception narrowed to hyphenated fixture shapes it reports three high-entropy "
            "credential-shaped values under idempotency_key; with it widened to any value in that "
            "field it reports none of them."
        ),
        "result": (
            "The scan over the full history - 54 commits, 6.87 MB - reports 'no leaks found' and "
            "exits 0. scripts/prove_secret_scan_gate.py reports PASS (4 properties): a planted "
            "token fails the scan, a credential-shaped value under idempotency_key fails the scan, "
            "a clean repository passes, and the repository's own fixtures pass. Observed under "
            "mutation: widening the exception to any value in the exempted field turns 'a credential "
            "in the exempted field still fails the scan' red while the other three stay green and "
            "the real repository's scan still reports nothing."
        ),
        "defect_found_and_fixed": (
            "The job scanned full history and reported nine `generic-api-key` findings: eight "
            "`idempotency_key` fixture values across contracts/fixtures/conformance.json, "
            "contracts/schema/command-envelope.schema.json, db/tests/0004_model_registry_verify.sql "
            "and a historical backend/tests/test_orders.py, and one in prose in docs/18, where the "
            "keyword `access` in 'access is least-privilege' made the next token a 'credential'. "
            "Added .gitleaks.toml with [extend] useDefault = true, no rule disabled, and two "
            "descriptions naming the value behind each exception; passed it to the scan with "
            "--config rather than relying on gitleaks' working-directory lookup; and added "
            "scripts/prove_secret_scan_gate.py plus an assertion that the job runs it."
        ),
        "significance": (
            "An allowlist is the one change to a secret gate that can turn it into a gate that never "
            "fires, and the failure is invisible: widen the exception until every finding is excused "
            "and the job is green precisely when it is blind. Narrowness is a claim about prose, and "
            "this repository has recorded green-but-vacuous gates seven times. So the narrowness is "
            "asserted behaviourally, and the property that constrains it is the one that is hardest "
            "to obtain by reading."
        ),
        "caveats": (
            "Two things are explicitly NOT claimed.\n\n"
            "First, that the proof's original planted value tested the allowlist. It did not. It was "
            "planted under idempotency_key on the reasoning that a field-scoped exception would "
            "swallow it, and the proof passed - but for the wrong reason. Gitleaks applies an "
            "allowlist regex to the span the rule itself matched, and `github-pat` matches only the "
            "token, so that finding was never governed by the exception at all. The property that "
            "does constrain the exception is a value `generic-api-key` flags, planted under the same "
            "field, and it is a separate property in the shipped script.\n\n"
            "Second, the AWS access key shape was tried as a planted value and is not detected by "
            "this gitleaks version's default rules - established by running it, not by reading the "
            "rule. A plausible-looking planted value that is never reported would have produced a "
            "proof that passed for a fourth unexamined reason, which is the failure mode this whole "
            "exercise exists to prevent."
        ),
        "exception": "No exception. The exceptions are value-shaped and the proof fails if they widen.",
        "artifacts": SHARED_ARTIFACTS
        + [".gitleaks.toml", "scripts/prove_secret_scan_gate.py"],
        "supersedes": [],
    },
    {
        "evidence_id": "EV-088",
        "work_item": "WI-187",
        "claim": (
            "A pending G0 human attestation is now distinguishable from a mechanical G0 failure in "
            "the run list, without changing the exit code and without asserting anything about the "
            "attestation."
        ),
        "method": (
            "The gate was run locally and its full output read: G0.1 through G0.7 report PASS, G0.8 "
            "reports REQUIRES_HUMAN_ATTESTATION, the verdict is PENDING_HUMAN_ATTESTATION, and the "
            "process exits 1. GitHub's annotation for the CI step was the bare 'Process completed "
            "with exit code 1'. The classification logic was then executed against both outcomes - "
            "the real gate output, and a stand-in emitting a mechanical failure - because a "
            "classifier that cannot be made to emit its error branch is not a classifier."
        ),
        "result": (
            "Against the real pending-attestation output the step emits '::warning::G0 red by design: "
            "every mechanical check passed and human attestation (G0.8) is still outstanding' and "
            "exits 1. Against a mechanical failure it emits '::error::G0 specification integrity "
            "gate failed for a mechanical reason' and exits 1. In both cases the gate's own output "
            "is printed unchanged."
        ),
        "defect_found_and_fixed": (
            "The CI step ran `python scripts/verify_spec_gate.py` bare, so both causes of exit 1 "
            "produced the same annotation. The step now captures the gate's own output, classifies "
            "it, and re-emits it. The classification reads this run's captured output, not the "
            "report on disk, so a stale report from a previous run cannot misclassify the current "
            "one."
        ),
        "significance": (
            "The repository's red build was red for two entirely different reasons on different "
            "commits - one fixable and one requiring a human signature - and the run list said the "
            "same thing about both. Making that distinction legible is what lets the next person "
            "know whether they have work to do."
        ),
        "caveats": (
            "This does not make G0 green and is not intended to. G0 remains FAIL on every push until "
            "a named human reviewer signs the package, which is what docs/11_EXECUTION_GATES.md "
            "requires when partial completion is not a pass.\n\n"
            "Two alternatives were considered and rejected. `continue-on-error: true` would make the "
            "job report success, and a gate whose status no longer means what it means is the shape "
            "this repository has already recorded seven times. Changing verify_spec_gate.py to exit 0 "
            "while attestation is pending would do the same thing and would additionally let a green "
            "job be recorded as a passed gate.\n\n"
            "G0.8 is a human judgement and is not asserted here."
        ),
        "exception": (
            "The G0 job remains red by design. That is the documented behaviour and it is not a "
            "defect being worked around."
        ),
        "artifacts": SHARED_ARTIFACTS + ["scripts/verify_spec_gate.py"],
        "supersedes": [],
    },
    {
        "evidence_id": "EV-089",
        "work_item": "WI-188",
        "claim": (
            "No workflow step runs twice. A duplicated step had been committed into this change set "
            "and every gate in the repository passed with it present."
        ),
        "method": (
            "Found by reading this change set's own diff immediately before committing it. The "
            "assertion was then checked by mutation against an in-memory copy of the parsed "
            "workflow, rather than by asserting that the new test is not vacuous on its own terms."
        ),
        "result": (
            "The workflow parses to 12 jobs and scripts/check_workflow_bash.py reports PASS (54 run: "
            "blocks parsed). The full tests/ci suite passes, 171 tests as measured on the fix commit. "
            "The new assertion passes on "
            "the real workflow and fails on a mutation that duplicates a step, with the message "
            "\"job sast: uses 'actions/setup-go@...' appears on more than one step\"."
        ),
        "defect_found_and_fixed": (
            "The contracts job contained two identical `- name: validate canonical schemas against "
            "the shared corpus` steps, so the validator would have run twice on every future run. "
            "One copy was removed, and tests/ci/test_ci_workflow.py now asserts that no job contains "
            "two steps with the same name or two steps using the same action ref."
        ),
        "significance": (
            "The gap is the finding, not the typo. YAML permits duplicate list entries, so this was "
            "not a parse error; the bash-syntax gate validated every run block and passed; the whole "
            "CI test suite passed. Every gate in this repository checks what a step does, and none "
            "checked how many times it appears - so a step could run twice, or be edited in one copy "
            "while the other kept running something stale, with a green build throughout."
        ),
        "caveats": (
            "Both halves of the assertion are deliberate: `name` catches the readable case, and "
            "`uses` catches steps that carry no name, which is how most `uses:` steps are written in "
            "this workflow. The check would need revisiting if a job legitimately acquires two steps "
            "of the same action - for instance a second checkout at a different path."
        ),
        "exception": "No exception.",
        "artifacts": SHARED_ARTIFACTS,
        "supersedes": [],
    },
]


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    existing = set()
    if store.exists():
        for line in store.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.add(json.loads(line).get("evidence_id"))

    appended = []
    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        for record in RECORDS:
            if record["evidence_id"] in existing:
                continue
            handle.write(
                json.dumps(
                    {
                        "schema": "ecc.project-brain/evidence/v7",
                        "evidence_id": record["evidence_id"],
                        "recorded_at": STAMP,
                        "recorded_by": "team-lead",
                        "work_item": record["work_item"],
                        "claim": record["claim"],
                        "status": "RESOLVED",
                        "method": record["method"],
                        "result": record["result"],
                        "defect_found_and_fixed": record["defect_found_and_fixed"],
                        "significance": record["significance"],
                        "caveats": record["caveats"],
                        "exception": record["exception"],
                        "artifacts": record["artifacts"],
                        "supersedes": record["supersedes"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            appended.append(record["evidence_id"])

    if not appended:
        print("unchanged: EV-082 to EV-089 already recorded")
        return False

    print("recorded " + ", ".join(appended))
    return True


if __name__ == "__main__":
    record()