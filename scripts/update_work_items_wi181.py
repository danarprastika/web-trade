"""Record WI-181 to WI-188: eight findings in the gates that judge every change to this repository.

Every item here was found by reading the CI run list and chasing each failure to a root cause, and
eight of them share one property: the gate had been reporting something it had not measured. Four
had never executed at all, two ran a different command than the one they named, one analysed every
language instead of its own, and one reported a credential-shaped fixture as a secret.

None is new behaviour in the repository's runtime. All of it is in the machinery that decides
whether a change is safe to merge - the class EV-064, EV-065, WI-171, WI-175, WI-179 and WI-180 have
now recorded nine times.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"

COMMON_ARTIFACTS = [
    ".github/workflows/ci.yml",
    "tests/ci/test_ci_workflow.py",
]

WI_181 = {
    "id": "WI-181",
    "phase": 2,
    "title": (
        "The vulnerability scan gate proof's resolve-step scenarios had never executed: rmdir on a "
        "non-empty directory, a fake `go` shim whose printf never parsed, and jq resolved against "
        "a different shell's PATH than the one that runs the step"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "All three resolve-step scenarios execute on a host that can run jq, and the proof reports "
        "10 properties passing with no skipped scenario",
        "The missing-module scenario removes the directory recursively and asserts the fixture is "
        "what it claims to be, so a drift in the fixture is a stated failure rather than a scenario "
        "that quietly tests the sandbox",
        "The fake `go` shim is asserted to answer `work edit -json` at construction time, because it "
        "is the entire input to three scenarios and nothing else checked that it parsed",
        "Whether jq can run is measured inside bash, which is the shell that executes the step, not "
        "with shutil.which, which answers a different question and inverts the verdict on a Windows host",
        "A host with no jq reports SKIP with an explicit statement that coverage did not happen; a "
        "host that cannot run the step's own filter never reports a gate failure instead",
    ],
    "source": "The CI run for 47a3137: `dependency + license scan` failed on its step named "
    "'prove the vulnerability scan can fail', which is the gate proving the vulnerability gate can "
    "fail. Logs were unavailable, so the script was read and executed locally instead.",
    "reproduction": "Three independent defects, all in the proof, all of which had to be true at "
    "once for the step to fail and none of which any other gate could see.\n\n"
    "1. scenario_resolve_refuses_missing_go_mod called `(repo / 'services' / 'typo').rmdir()` on a "
    "directory _build_sandbox had just populated with a go.mod. rmdir refuses a non-empty directory, "
    "so the call raised WinError 145. The exception escaped main() as a traceback, which named no "
    "scenario and no property, so a harness failure presented as a broken script.\n\n"
    "2. _write_fake_go emitted `printf '{\"Use\":[...]}\\n\"` - the single quote opened and never "
    "closed, with a stray double quote at the end. The shim died with 'unexpected EOF while looking "
    "for matching `''` on every invocation, so all three resolve scenarios were fed a `go` that "
    "printed nothing and exited non-zero.\n\n"
    "3. has_jq used `shutil.which('jq')`, which asks whether Python can start jq. The step runs "
    "under bash. On this host those disagree: Python resolves jq.exe and reports a jq, while the "
    "bash on PATH is the WSL bash, which resolves extensionless names only and cannot run it. The "
    "scenarios therefore ran and failed with exit 127, reporting a gate defect where the honest "
    "verdict was 'this host cannot execute the step's own filter'.\n\n"
    "The reason this survived is the interaction. The scenarios skip when jq is absent, so on a "
    "developer's machine they never ran; on the one host where jq was present the traceback "
    "interleaved with 'jq: command not found' in the captured output, which reads as a missing "
    "tool rather than as two dead fixtures. The CI step that executes this proof on every dependency "
    "scan had therefore been red since the scenarios were introduced.",
    "notes": "The jq launcher installs a `jq` shim into the sandbox bin dir that execs the real "
    "binary, and filters CR. Both adaptations are load-bearing and both are about the host, not the "
    "step: a native jq.exe writes CRLF, which inside WSL bash leaves a trailing \\r on every path, "
    "so `read -r m` yields 'contracts/go\\r' and the step's own `-f \"$m/go.mod\"` test fails on every "
    "module - a failure about line endings reported as a failure about the gate. On a runner, jq "
    "writes LF and `tr -d '\\r'` is a no-op. Nothing else is filtered and the block's own jq filter "
    "still does the work.\n\n"
    "Two further defects were found while fixing these and are recorded here rather than separately. "
    "_bash_can_run originally passed the command as `\"$1\"` to `bash -c`, and the bash reachable "
    "through the Windows path does not hand positional parameters to `-c` in a way that survives "
    "that call; every binary was reported unrunnable, which silently downgraded all three scenarios "
    "to a skip again. And _wsl_candidates exists because `shutil.which('jq')` returns "
    "`...\\jq.EXE` from PATHEXT while the file on disk is `jq.exe`: the Windows filesystem opens "
    "either and the WSL interop launch of the uppercase spelling fails, so both spellings are tried "
    "rather than the first being assumed.",
    "dependencies": ["WI-178", "WI-179"],
    "evidence_ref": ["EV-082"],
}

WI_182 = {
    "id": "WI-182",
    "phase": 2,
    "title": (
        "workers/research pinned jsonschema==4.26.1, a version that has never existed on PyPI, so "
        "every install of that extra failed to resolve"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "Every `pip install \"./workers/research[dev]\"` resolves, and the pin is a version that "
        "exists on PyPI",
        "referencing is declared explicitly rather than left to arrive as a transitive dependency, "
        "because validate_contracts.py imports it directly",
        "The research worker's own run of the contract validator still passes, which is the "
        "dependency's only consumer and the reason it is there at all",
    ],
    "source": "The CI run for 47a3137: `python research workers` failed on its step named "
    "'install research worker'.",
    "reproduction": "`python -m pip install --dry-run \"jsonschema==4.26.1\"` fails with 'ERROR: Could "
    "not find a version that satisfies the requirement jsonschema==4.26.1 (from versions: ... "
    "4.25.0, 4.25.1, 4.26.0)'. 4.26.0 is the current release and 4.26.1 has never been published. "
    "The pin sat in the dev extra of workers/research/pyproject.toml, so the failure took out three "
    "steps: the research worker's own install, the backtest worker's install (which resolves the "
    "same dependency set through webtrade-research), and the dependency-scan job's python audit, "
    "which installs both extras before auditing them.\n\n"
    "It survived every local check because nothing resolved that extra locally: the package was "
    "already present in the developer's environment, so `pip install` never went to the network for "
    "it, and no gate in the repository resolves a declared Python pin against PyPI. "
    "scripts/verify_toolchain.py asserts that every pin is an exact `==` specifier, which 4.26.1 "
    "satisfies perfectly.",
    "notes": "The dependency is real and is not dead weight. "
    "workers/research/tests/test_canonical.py::test_schema_layer_rejects_document_cases executes "
    "`python tests/contracts/validate_contracts.py` as a subprocess, so the research worker's "
    "environment must be able to import jsonschema and referencing. That is also why referencing is "
    "now declared: the validator imports it directly, and a direct import of a package that happens "
    "to arrive transitively is a missing pin rather than a convenience.",
    "dependencies": [],
    "evidence_ref": ["EV-083"],
}

WI_183 = {
    "id": "WI-183",
    "phase": 2,
    "title": (
        "The contract validation job installed nothing, so validate_contracts.py exited 2 in about "
        "five seconds having checked no case at all"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "The job installs a pinned dependency set before running the validator",
        "Every declared dependency in that file is an exact pin",
        "Any job that runs the validator installs that file first, asserted for every such job "
        "rather than for the one that was diagnosed, and asserted in order",
        "The pins in that file and the research worker's dev extra are asserted identical, because "
        "the same validator runs in both places",
    ],
    "source": "The CI run for 47a3137: `contract validation` failed on its step named 'validate "
    "canonical schemas against the shared corpus'.",
    "reproduction": "The job ran `python tests/contracts/validate_contracts.py` directly after "
    "actions/setup-python, which provides a clean interpreter with no third-party packages. The "
    "validator's own answer is exit 2 with 'FATAL: the jsonschema and referencing packages are "
    "required', so the job reported a contract failure that was entirely a missing install line. "
    "Every other language binding was green at the time, which is what makes the report misleading "
    "rather than merely red.",
    "notes": "This is the same defect the toolchain, spec-gate and project-brain jobs already carried "
    "and had fixed - recorded as EV-064's shape - arriving in a job nobody had extended the fix to. "
    "The assertion written for the CI suite's own dependencies generalises exactly to this case, "
    "which is why it is applied to every such job instead of to the contracts job.\n\n"
    "Two files declare this dependency set: tests/contracts/requirements.txt for the job, and "
    "workers/research/pyproject.toml for the subprocess run from the research worker's tests. That "
    "duplication is unavoidable in Python packaging and would be a drift risk, so the two are "
    "asserted identical by tests/ci/test_ci_workflow.py. The stale pin in the pyproject is what "
    "made this necessary and is WI-082.",
    "dependencies": [],
    "evidence_ref": ["EV-084"],
}

WI_184 = {
    "id": "WI-184",
    "phase": 2,
    "title": "The web typecheck ran before Next.js generated the route types its own source uses",
    "status": "COMPLETED",
    "priority": "medium",
    "acceptance_criteria": [
        "`npm run typecheck` succeeds from a clean checkout with no build output present",
        "The generated types come from the project's own pinned Next.js, not from a checked-in file",
        "The failure mode this fixes is reproducible locally rather than only on a runner",
    ],
    "source": "The CI run for 47a3137: `web typecheck + lint + build` failed on its step named "
    "'typecheck' with the annotation \"Cannot find name 'LayoutProps'\".",
    "reproduction": "apps/web/app/layout.tsx:26 declares "
    "`export default function RootLayout({ children }: LayoutProps<\"/\">)`. `LayoutProps` is a "
    "global type Next.js generates into .next/types from the route tree; tsconfig.json already "
    "includes `.next/types/**/*.ts`. The CI job runs typecheck before build, so on a clean checkout "
    "the generated directory does not exist and the type is undefined. Reproduced locally by "
    "deleting apps/web/.next and running `npx tsc --noEmit`: exit 2 with the same error. `npx next "
    "typegen` followed by `npx tsc --noEmit` exits 0.\n\n"
    "It passed locally for the same reason many CI-only failures do: a previous `next build` had "
    "left .next/types in place, so the developer's typecheck had something to resolve against.",
    "notes": "The script is `next typegen && tsc --noEmit`. `next typegen` exists in the pinned "
    "Next.js 16.3.6 and generates route, page and layout definitions without a full production "
    "build, which keeps the job's ordering intact and costs about two seconds. The alternative - "
    "reordering the job to build before typechecking - was rejected because it makes a type error "
    "surface as a build failure and makes the typecheck depend on the whole build succeeding.",
    "dependencies": [],
    "evidence_ref": ["EV-085"],
}

WI_185 = {
    "id": "WI-185",
    "phase": 2,
    "title": (
        "CodeQL was initialised with `language:`, an input the action does not define, so every SAST "
        "job analysed every language; and Go extraction cannot autobuild a go.work workspace"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "Every CodeQL init step passes an input the action defines, and the singular `language` is "
        "rejected outright rather than tolerated",
        "Each matrix leg analyses exactly the language it is named for",
        "The Go leg does not use autobuild, because the checkout root has go.work and deliberately no "
        "root go.mod",
        "The Go build resolves its module list from go.work, so a module added to go.work is "
        "extracted with no workflow edit",
        "The build happens before the analyse step, and a module listed by go.work with no go.mod is "
        "a stated failure",
    ],
    "source": "The CI run for 47a3137: all three `SAST (CodeQL)` jobs failed on their 'analyse' "
    "step with the annotation 'Extraction failed for all discovered Go projects'. The workflow's "
    "own annotation on each job reads \"Unexpected input(s) 'language', valid inputs are [...]\".",
    "reproduction": "Two independent defects, and the second was invisible behind the first.\n\n"
    "1. The init step passed `language: ${{ matrix.language }}`. codeql-action v3 takes `languages`. "
    "An input the action does not define is ignored with a warning, so all three legs initialised "
    "every language rather than their own. Each then ran Go's autobuild, each failed on Go "
    "extraction, and none of them analysed the language its own job name claimed - including the "
    "Python leg, which never looked at the Python.\n\n"
    "2. Even scoped to Go alone, autobuild cannot extract this repository. It builds from the "
    "checkout root, and the root has go.work but deliberately no go.mod, so `go build ./...` there "
    "fails with 'directory prefix . does not contain modules listed in go.work or their selected "
    "dependencies'. Verified locally: that is the exact error, on a tree whose six modules build "
    "and pass tests individually. Autobuild then failed to extract every module it found.\n\n"
    "The job also had no setup-go, no setup-node and no setup-python, so whatever autobuild chose to "
    "invoke had no toolchain to invoke it with.",
    "notes": "The fix is `languages`, a per-language build mode, and a manual Go build that iterates "
    "the modules `go work edit -json` actually declares - the same resolution the dependency-scan "
    "job already uses, rather than a hardcoded list. The interpreted languages use build-mode none, "
    "which is both correct for them and the reason the job no longer needs setup-node and "
    "setup-python.\n\n"
    "setup-go is installed for the whole job rather than behind the Go leg's `if`. A job whose build "
    "leg silently stopped having a compiler is indistinguishable from a clean extraction until a "
    "vulnerability ships, which is the EV-064 shape with an extra step in front of it.",
    "dependencies": [],
    "evidence_ref": ["EV-086"],
}

WI_186 = {
    "id": "WI-186",
    "phase": 2,
    "title": (
        "The secret scan reported nine findings, every one of them fixture data, and the only "
        "available fix - an allowlist - had no proof that it can still fail"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "Every exception in the scan configuration is shaped by value, never by path: an exception "
        "keyed on a directory would excuse any future secret pasted into it",
        "No rule is disabled, and the default rule set is explicitly extended rather than replaced",
        "Every exception carries a description naming the value that triggered it",
        "An executed proof requires the committed scan command to fail on a synthetic token and on a "
        "credential-shaped value in the exempted field, to pass on a clean repository, and to pass on "
        "the repository's own fixtures",
        "The proof fails if the exception is widened to cover any value in the exempted field, while "
        "the scan over the real repository stays green",
        "The CI job runs that proof, and passes --config explicitly rather than relying on gitleaks' "
        "working-directory lookup",
    ],
    "source": "The CI run for 47a3137: `secret scan` failed on its step named 'scan repository history "
    "for secrets' with exit code 1 and no further detail. Reproduced locally with the committed "
    "container command.",
    "reproduction": "The committed command finds nine leaks, all from the `generic-api-key` rule: "
    "four `idempotency_key` fixture values in contracts/fixtures/conformance.json, one in "
    "contracts/schema/command-envelope.schema.json, two SQL test fixtures in "
    "db/tests/0004_model_registry_verify.sql, one in a historical backend/tests/test_orders.py, and "
    "one in prose in docs/18. None is a secret. The docs finding is the clearest illustration of what "
    "this rule does: the phrase 'access is least-privilege, jurisdiction/venue eligibility is "
    "current' contains the keyword `access`, so the rule took the next token as a credential.\n\n"
    "Changing the fixtures is not available. The job checks out full history, because a secret that "
    "was committed and later removed is still exposed, so the offending values are in the history "
    "being scanned and an allowlist is the only lever that exists.",
    "notes": "The allowlist is the single change to a secret gate that can turn it into a gate that "
    "never fires: widen the exception until every finding is excused and the job is green precisely "
    "when it is blind, with nothing in the run list to say so. Narrowness is a claim about prose and "
    "prose has been wrong in this repository before, so it is asserted behaviourally instead.\n\n"
    "That proof corrected an assumption of my own. Its first planted value was a token under "
    "`idempotency_key`, on the reasoning that it tests the exception's field scoping. It passed, but "
    "for the wrong reason: gitleaks applies an allowlist regex to the span the rule itself matched, "
    "and `github-pat` matches only the token, so that finding was never governed by the field-scoped "
    "regex at all. A value that `generic-api-key` does flag - high-entropy alphanumerics under the "
    "same field - was added as a separate property, and it is that property which fails when the "
    "regex is widened. Verified by execution in both directions: the narrow regex reports it and the "
    "proof passes; the widened regex excuses it and the proof fails while the scan over the real "
    "repository still reports nothing.\n\n"
    "The AWS access key shape was also tried as a planted value and is not detected by this "
    "gitleaks version's default rules - a fact discovered by running the probe rather than by "
    "reading the rule, and worth recording because a plausible-looking planted value that is never "
    "reported would have produced a proof that passed for a fourth unexamined reason.",
    "dependencies": [],
    "evidence_ref": ["EV-087"],
}

WI_187 = {
    "id": "WI-187",
    "phase": 2,
    "title": (
        "The G0 job's red-by-design failure was indistinguishable from a mechanical failure, so a "
        "pending human attestation read as a broken gate"
    ),
    "status": "COMPLETED",
    "priority": "medium",
    "acceptance_criteria": [
        "A reader can tell from the run list whether G0 failed mechanically or because attestation "
        "is outstanding",
        "The classification reads this run's own output rather than the report on disk, so a stale "
        "report from a previous run cannot misclassify it",
        "The exit code is unchanged: a pending attestation remains FAIL",
        "No attestation is asserted, implied or auto-filled, and no report claims G0 passed",
    ],
    "source": "The CI run for 47a3137: `G0 specification integrity` failed on its step named 'Run G0 "
    "specification integrity gate' with the bare annotation 'Process completed with exit code 1'.",
    "reproduction": "The gate's own output is unambiguous - G0.1 through G0.7 all report PASS, G0.8 "
    "reports REQUIRES_HUMAN_ATTESTATION, and the verdict is PENDING_HUMAN_ATTESTATION - and GitHub "
    "shows none of it in the run list. So a repository in which every mechanical check passes and "
    "the only outstanding item is a human signature looked identical to one where a digest no longer "
    "matches a packaged byte. Both are exit 1.",
    "notes": "The step now classifies the failure and says so in an annotation, emitting a warning "
    "naming the outstanding attestation and an error for a mechanical failure. It never changes the "
    "exit code.\n\n"
    "The two alternatives were both rejected on purpose. `continue-on-error: true` would make the job "
    "report success, and docs/11_EXECUTION_GATES.md states that partial completion is FAIL rather "
    "than a percentage - a gate whose status no longer means what it means is the EV-064 shape. "
    "Changing verify_spec_gate.py to exit 0 while attestation is pending would have the same effect "
    "and would additionally let a green job be recorded as a passed gate. The honest end state is "
    "that G0 stays red on every push until a named human signs, and that this is legible from the "
    "run list rather than from a scrollback log.",
    "dependencies": [],
    "evidence_ref": ["EV-088"],
}

WI_188 = {
    "id": "WI-188",
    "phase": 2,
    "title": (
        "A workflow step was duplicated, so one command ran twice, and no gate in the repository "
        "noticed"
    ),
    "status": "COMPLETED",
    "priority": "medium",
    "acceptance_criteria": [
        "No job contains two steps with the same name, or two steps using the same action ref",
        "The check is asserted for every job rather than for the one that was diagnosed",
        "The check catches a duplicated step, verified by execution rather than by inspection",
    ],
    "source": "Review of this change set's own diff immediately before committing it.",
    "reproduction": "The contracts job's validator step had been inserted twice by an editing "
    "accident: the step was re-added beside the install step it replaced, leaving two identical "
    "`- name: validate canonical schemas against the shared corpus` entries in the job's step list. "
    "YAML permits duplicate list entries with the same keys, so this was not a parse error; "
    "scripts/check_workflow_bash.py validated every run block and passed; the full tests/ci suite "
    "passed, 171 tests as measured after the fix; and the workflow would have run the validator twice "
    "in every future run, with "
    "a change to one copy leaving the other executing something stale.",
    "notes": "Recorded because the gap is the interesting part, not the typo. Every gate in this "
    "repository checks what a step does; none of them checked how many times it appears. A gate that "
    "had noticed would have been a structural check over the parsed document, and there is now one. "
    "Both halves are asserted - `name` for the readable case and `uses` for the steps that carry no "
    "name, which is how most `uses:` steps are written here - and the negative case was executed "
    "against an in-memory mutation rather than argued.",
    "dependencies": [],
    "evidence_ref": ["EV-089"],
}


def main() -> bool:
    doc = json.loads(STORE.read_text(encoding="utf-8"))
    items = doc["items"]
    by_id = {i["id"]: i for i in items}

    changed = False
    for candidate in (
        WI_181,
        WI_182,
        WI_183,
        WI_184,
        WI_185,
        WI_186,
        WI_187,
        WI_188,
    ):
        existing = by_id.get(candidate["id"])
        if existing is None:
            items.append(candidate)
            changed = True
        elif existing != candidate:
            items[items.index(existing)] = candidate
            changed = True

    if not changed:
        print("unchanged: WI-181 to WI-188 already recorded")
        return False

    out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    with io.open(STORE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(out)

    print("WI-181 to WI-188 recorded")
    return True


if __name__ == "__main__":
    main()