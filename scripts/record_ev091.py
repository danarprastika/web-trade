"""Record WI-190, WI-191, EV-091 and EV-092, and correct WI-107's recorded blocker.

WI-190 is an independent release review of fa2156f that returned three findings, and the first
thing done with them exposed a fourth: the secret-scan job was red on the pushed commit, because
the proof script added by that commit contains the literal it exists to plant.

WI-191 records that the integration job's acceptance criterion is now observed output rather than
configuration, and corrects WI-107's blocker, which asserted two premises that are no longer true:
that the workflow is not pushed to a remote, and that the Docker daemon is unavailable.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-03T20:45:00Z"

ARTIFACTS = [
    ".github/workflows/ci.yml",
    ".gitleaks.toml",
    "scripts/prove_secret_scan_gate.py",
    "scripts/record_ev082.py",
    "scripts/record_ev091.py",
    "tests/ci/test_ci_workflow.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_190 = {
    "id": "WI-190",
    "phase": 2,
    "title": (
        "An independent review of the CI batch found a dead assertion and an unguarded empty loop; "
        "acting on it exposed that the batch had itself turned the secret-scan job red"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "The Go SAST build step refuses an empty module list, and the assertion covers it",
        "The Go SAST test resolves the matrix build mode so no assertion in it is unreachable",
        "The committed secret scan over full history exits 0, and the proof still fails a planted token",
        "The token exception in .gitleaks.toml cannot match a realistic random token, and the "
        "proof does not plant a token the exception excuses",
        "Every new or rewritten assertion has a negative control that was executed"
    ],
    "source": (
        "An independent release-verifier pass over fa2156f and 7733977, run read-only, reporting "
        "three findings and one disclosure."
    ),
    "reproduction": (
        "Three findings. (1) The Go SAST build step fed its module list through `done < <(go work "
        "edit -json | jq ...)`; under `set -euo pipefail` a failure inside a process substitution "
        "does not propagate, and an empty list makes the loop body run zero times, so a resolution "
        "returning nothing left the leg extracting nothing and exiting 0 - and unlike three sibling "
        "steps it had no empty-list check. (2) The test that guards that step gated both its "
        "assertions behind `if build_mode == \"manual\":`, while the init step passes the literal "
        "string `${{ matrix.build-mode }}`, so the comparison was never true and lines 413-428 never "
        "executed; deleting the build step from an in-memory copy of the workflow still passed. "
        "(3) EV-086 therefore claimed the test 'observes both properties of the Go leg' when it "
        "observed neither. Separately, .gitleaks.toml's comment asserted that a UUID does not match "
        "the exception, which running the expression showed to be false."
    ),
    "notes": (
        "The fourth defect was found while fixing the first and is the one that mattered most. The "
        "secret-scan job was RED on the pushed commit: scripts/prove_secret_scan_gate.py was added "
        "by fa2156f carrying a whole PAT-shaped literal at line 67, and the job that exists to prove "
        "the secret scan works was failing on this repository's own source. The tests/ci suite never "
        "caught it because it does not run the scanner, and the previous full-history scan reported "
        "clean because it was run before that file existed.\n\n"
        "The fix has a constraint that is easy to get wrong. The scan covers history, so editing the "
        "file cannot clear the two commits that carry the literal - they are on the remote and are "
        "not being rewritten. The value therefore has to be excused, and the obvious ways to scope "
        "that excuse were tried against the scanner rather than assumed. Scoping by path: the "
        "allowlist block still suppressed the value in a scratch repository at a different path. "
        "Scoping by commit: naming the finding's exact commit SHA left it reported. A fingerprint "
        "entry naming the exact finding was accepted by the parser and suppressed nothing. A "
        "stopword could not reach it, because stopwords are matched against the secret the rule "
        "matched - here the token alone - and not against its line. So this scanner treats an "
        "allowlist block's checks as alternatives and honours none of the scoping keys for this "
        "case, and the narrowest mechanism observed to work is a value pattern. That pattern is the "
        "shape of the one synthetic value rather than the value: ten digits, then ten lowercase, "
        "then ten uppercase, then six digits, in that order. No random 36-character token has that "
        "ordering, and the config therefore contains no literal token and is not itself a finding.\n\n"
        "Because a value-shaped exception applies everywhere, the proof can no longer plant that "
        "shape or it would pass without the scan looking at all. It now plants a different "
        "synthetic token, and both facts are enforced rather than assumed: the proof refuses to run "
        "if its token is malformed or matches the excused shape, and a test in tests/ci asserts that "
        "the exception matches no realistic token and that the proof's value does not match the "
        "exception.\n\n"
        "That test was itself wrong on first writing, and its negative control is what proved it. "
        "It compiled the config's patterns and then interpolated the compiled objects into a "
        "combined pattern, producing the literal text re.compile('ghp_...'), which matches nothing "
        "- so the assertion passed for a config that excuses every token in the world. The control "
        "widened the exception to `ghp_[A-Za-z0-9]{36}` and the test still passed, which is the only "
        "reason the defect is not still in the file."
    ),
    "dependencies": ["WI-185", "WI-186"],
    "evidence_ref": ["EV-091"],
}

EV_091 = {
    "evidence_id": "EV-091",
    "work_item": "WI-190",
    "claim": (
        "The Go SAST leg cannot pass having built nothing, the test guarding it executes, and the "
        "committed secret scan is green while still failing on a planted token."
    ),
    "method": (
        "The three review findings were reproduced before being fixed: the process substitution and "
        "its missing empty-check by reading the sibling steps that already perform both, and the "
        "dead assertion by deleting the build step from an in-memory copy of the parsed workflow and "
        "observing the test pass. The red secret-scan job was found by running the committed scan "
        "command, which reported one finding with its fingerprint. Every attempt to scope that "
        "finding was then evaluated by executing the scanner against scratch repositories built for "
        "the purpose, with the finding's real fingerprint read from the scan output rather than "
        "guessed. All seven negative controls for the new and rewritten assertions were executed."
    ),
    "result": (
        "The committed scan over full history - 58 commits, 7.08 MB - reports 'no leaks found' and "
        "exits 0, against exit 1 with one finding before. scripts/prove_secret_scan_gate.py reports "
        "PASS (4 properties) with the planted token genuinely detected, so the proof is not passing "
        "on an allowlisted value. The Go SAST build step now resolves the module list to modules.txt, "
        "refuses an empty list, and iterates the file. tests/ci passes, 172 tests. All seven negative "
        "controls behave as required: the unmodified workflow and the shipped config pass, while "
        "deleting the build step, reverting the loop to a process substitution, setting the Go leg's "
        "build mode to autobuild, widening the token exception, and pointing the proof at the "
        "excused shape each make the corresponding assertion fail."
    ),
    "defect_found_and_fixed": (
        "1. ci.yml's Go SAST build step used `done < <(go work edit -json | jq ...)`, whose failure "
        "does not propagate under `set -euo pipefail`, and had no empty-list check; both failure "
        "modes exit 0 having built nothing. Now resolves to modules.txt, refuses an empty list with "
        "the same wording the go, dependency-scan and integration jobs use, and iterates the file. "
        "2. The test's assertions were unreachable behind `if build_mode == \"manual\":` because the "
        "init step passes `${{ matrix.build-mode }}`. A resolver for matrix expressions was added and "
        "the build mode is now asserted to equal `manual`, which also closes a matrix change to "
        "`autobuild` that the previous `!= \"autobuild\"` form would have accepted. The build step's "
        "existence, ordering before analyse, gating to the Go leg, file-based module list and "
        "empty-list refusal are now asserted unconditionally. "
        "3. .gitleaks.toml's comment claimed a UUID does not match the idempotency_key exception. "
        "Running the expression showed a UUID does match, and so does any hyphenated value whatever "
        "its entropy, including a hyphenated credential. The value class was narrowed to [a-z0-9] "
        "and the comment now states exactly what is and is not excused - and what still is, which is "
        "every lowercase hyphenated value including UUIDs. Narrowing was safe because every value "
        "that must stay excused was read out of the reachable history first: all seven hyphenated "
        "ones are lowercase, and the only uppercase values in history are the proof's own planted "
        "credentials, which have no hyphen and are still reported. "
        "4. scripts/prove_secret_scan_gate.py carried a whole PAT-shaped literal, turning the "
        "secret-scan job red on the pushed commit. The value is now assembled from fragments, and "
        "the historical occurrences are excused by a shape-based entry. "
        "5. The new test's combined pattern was built from compiled objects rather than strings, so "
        "it matched nothing and passed for any config. Fixed, and caught only because the negative "
        "control existed."
    ),
    "significance": (
        "Two of these are the repository's own recurring shape, and the batch that fixed eight "
        "instances of it introduced two more. A gate that passes having checked nothing, and a claim "
        "about a gate that was never exercised, are the same defect at different altitudes - and the "
        "proof script that made the secret scan red is the sharpest version available: the "
        "instrument contained the thing it hunts. It survived because the local suite does not run "
        "the scanner and the last full scan predated the file. Only running the committed command "
        "against the real history found it, which is the argument for running gates rather than "
        "reasoning about them."
    ),
    "caveats": (
        "The gitleaks allowlist scoping behaviour above was established by executing the scanner, not "
        "by reading its documentation, and only for version v8.30.1 as pinned. A future scanner "
        "upgrade may honour the scoping keys this one ignores, at which point the value-shaped entry "
        "can be replaced by a commit- or path-scoped one that is strictly narrower. Nothing here "
        "depends on that being true: the current entry is narrow by construction, since a real token "
        "is random base62 and cannot have the ordered character classes it describes.\n\n"
        "NOT VERIFIED: GitHub Actions results. The gh CLI is installed and unauthenticated for this "
        "repository, so no run's outcome is observable from here. Everything claimed above was "
        "executed locally against the committed tree.\n\n"
        "NOT VERIFIED, and unchanged: that the Go CodeQL extraction succeeds on a runner. It requires "
        "the CodeQL tracer. The configuration is corrected and its negative controls execute; the "
        "positive outcome remains unclaimed, as EV-086 states."
    ),
    "exception": (
        "One, and it is the same one EV-086 already declares: Go extraction on a runner is not "
        "verified. Nothing was skipped or weakened to reach a green result."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

WI_191 = {
    "id": "WI-191",
    "phase": 1,
    "title": (
        "The integration job's acceptance criterion is observed output rather than configuration, "
        "and WI-107's recorded blocker no longer describes the repository"
    ),
    "status": "COMPLETED",
    "priority": "medium",
    "acceptance_criteria": [
        "The integration job's steps are executed locally against a real PostgreSQL 17",
        "Every live-database test target is shown to run, with zero skips",
        "WI-107's blocker states what is still configuration-only and no longer claims the workflow "
        "is unpushed or that Docker is unavailable"
    ],
    "source": (
        "Reading WI-107's blocker while closing out this batch. It recorded that the workflow is "
        "not pushed to a remote and that the Docker-dependent jobs cannot run while the daemon is "
        "unavailable; both were false."
    ),
    "reproduction": (
        "WI-107 has been IN_PROGRESS since it was created, with a blocker naming seven criteria "
        "verified as configuration only: the container-image build, gitleaks, CodeQL, govulncheck, "
        "cosign attestation, integration, and SBOM/provenance. The workflow has been pushed to "
        "origin/main since 57160f1, and the Docker daemon is running - it answered 29.8.0 - so the "
        "blocker's two stated reasons for not running those jobs no longer held. gitleaks, "
        "govulncheck and the integration suite have since been executed locally; CodeQL, the image "
        "build, cosign attestation and SBOM emission still have not, for reasons that are now "
        "recorded rather than assumed."
    ),
    "notes": (
        "The integration job was reproduced with the same image and the same credentials the "
        "workflow's service block declares, postgres:17.11-alpine with webtrade/webtrade and "
        "database webtrade_test on port 5432, so the run is the job rather than an approximation of "
        "it. Its six steps all executed: go.work module resolution, the migration rehearsal, applying "
        "the four migrations, `migrate -direction status` against the live database, the integration "
        "tests for all six workspace modules, and the no-skip check.\n\n"
        "The no-skip step is the one that makes the rest meaningful. A live-database test that skips "
        "verifies nothing while the job stays green, so the check re-runs each live target verbosely "
        "and fails on any SKIP line: 17 passed with no skips in cmd/migrate, 52 in migrate, 29 in the "
        "integration package.\n\n"
        "One honest difference from CI: the CI job runs the integration tests with -race, and the race "
        "detector was NOT exercised locally. This host is Windows without the C toolchain the race "
        "detector requires, so the suite ran without it. The race detector is therefore still "
        "configuration-only as far as this host is concerned, and that is stated here rather than "
        "implied by the passing result."
    ),
    "dependencies": ["WI-107"],
    "evidence_ref": ["EV-092"],
}

EV_092 = {
    "evidence_id": "EV-092",
    "work_item": "WI-191",
    "claim": (
        "The integration job runs, and its live-database tests are shown to run rather than skip."
    ),
    "method": (
        "PostgreSQL was started with the image, credentials and port the workflow's own service "
        "block declares, then each step of the integration job was executed in the job's order with "
        "DATABASE_URL set to the same value the job sets. The no-skip check was executed as its own "
        "script, re-running each live target with -count=1 -v and failing on any SKIP line, which is "
        "the condition the CI step encodes."
    ),
    "result": (
        "python scripts/rehearse_migrations.py exits 0 with 'MIGRATION REHEARSAL PASSED: up, down to "
        "a clean catalog, and up again'. `go run ./services/control-plane/cmd/migrate -direction up` "
        "applies 4 migrations and exits 0; `-direction status` reports all four applied with their "
        "digests. `go test -tags=integration -count=1 ./<module>/...` passes for all six workspace "
        "modules, with components/oms, components/risk-engine, contracts/go and every "
        "services/control-plane package reporting ok and adapters/venues, components/reconciliation "
        "and services/control-plane itself reporting no test files. The no-skip check: 17 passed / 0 "
        "skipped in cmd/migrate, 52 / 0 in migrate, 29 / 0 in the integration package, exit 0."
    ),
    "defect_found_and_fixed": (
        "WI-107's blocker asserted two premises that were no longer true - that the workflow is not "
        "pushed to a remote, and that the Docker-dependent jobs cannot run while the daemon is "
        "unavailable - and listed integration among criteria verified as configuration only. "
        "Rewritten to state what is now observed and, separately, what is still configuration-only "
        "and why: CodeQL extraction needs the tracer, and cosign attestation and SBOM emission need "
        "a registry and OIDC identity."
    ),
    "significance": (
        "An IN_PROGRESS item whose blocker names the wrong reason is worse than one with no blocker: "
        "it tells the next person the work cannot be done when what actually remains is a specific, "
        "enumerated list. Correcting it does not close WI-107 - CodeQL, the image build, cosign and "
        "SBOM emission are still unobserved, and the race detector was not exercised - but it makes "
        "the remaining gap exact instead of vague."
    ),
    "caveats": (
        "The race detector was not exercised: CI runs the integration tests with -race and this host "
        "is Windows without the C toolchain it requires, so the suite ran without it.\n\n"
        "Still configuration-only, and not claimed otherwise: CodeQL extraction, the container image "
        "build, cosign provenance attestation and SBOM emission. Each needs something this host does "
        "not have - the CodeQL tracer, a registry to push to, and an OIDC identity.\n\n"
        "GitHub Actions results remain unobservable: gh is installed and unauthenticated for this "
        "repository."
    ),
    "exception": (
        "One: the race detector was not exercised locally, and is not claimed. Everything else above "
        "was executed."
    ),
    "artifacts": ARTIFACTS
    + ["scripts/rehearse_migrations.py", "evidence/gates/G5-gate-report.json"],
    "supersedes": [],
}

WI_107_NEW_BLOCKER = (
    "Corrected 2026-10-03. The previous text recorded two reasons that no longer held: that the "
    "workflow is not pushed to a remote (it has been on origin/main since 57160f1) and that the "
    "Docker-dependent jobs cannot run while the daemon is unavailable (it answers). What is now "
    "observed output rather than configuration: toolchain pins, the G0 specification gate, project "
    "brain integrity, contract validation, gofmt/vet/build/test for all six workspace modules, the "
    "web typecheck, lint and build, the vulnerability scan and its proof, the secret scan over full "
    "history and its proof, and the whole integration job against a real PostgreSQL 17 including "
    "98 live-database tests with zero skips (EV-092).\n\n"
    "What remains configuration-only, never as observed output, and why: CodeQL extraction requires "
    "the CodeQL tracer; the container image build, SBOM emission and cosign provenance attestation "
    "require a registry and an OIDC identity; and the race detector on the integration suite requires "
    "the C toolchain, which this host does not have (EV-092). GitHub Actions results are not "
    "observable from this host at all, because gh is unauthenticated for this repository - so no "
    "claim here rests on a run's reported outcome. EV-014 records this item as VERIFIED_WITH_EXCEPTION."
)


def main() -> bool:
    doc = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = doc["items"]
    by_id = {i["id"]: i for i in items}

    changed = False
    for candidate in (WI_190, WI_191):
        existing = by_id.get(candidate["id"])
        if existing is None:
            items.append(candidate)
            changed = True
            print(f"recorded {candidate['id']}")
        elif existing != candidate:
            items[items.index(existing)] = candidate
            changed = True
            print(f"updated {candidate['id']}")
        else:
            print(f"unchanged: {candidate['id']}")

    wi107 = by_id.get("WI-107")
    if wi107 is not None and wi107.get("blocker") != WI_107_NEW_BLOCKER:
        wi107["blocker"] = WI_107_NEW_BLOCKER
        changed = True
        print("corrected WI-107 blocker")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    recorded = set()
    if EVIDENCE.exists():
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                recorded.add(json.loads(line).get("evidence_id"))

    appended = []
    with io.open(EVIDENCE, "a", encoding="utf-8", newline="\n") as handle:
        for record in (EV_091, EV_092):
            if record["evidence_id"] in recorded:
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

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()