"""Record WI-193 and EV-094, and correct EV-091, which recorded a scan result that was no longer true.

WI-193 is an independent adversarial review of the two commits that closed out the previous batch.
It found that the secret-scan job was RED at origin/main, and that the thing making it red was a
whole PAT-shaped control token written into tests/ci/test_ci_workflow.py in the very commit that
claimed to have fixed the same defect in a different file. The proof that exists to catch exactly
this could not catch it, because it only ever scanned scratch repositories.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-04T00:05:00Z"

ARTIFACTS = [
    ".gitleaks.toml",
    "tests/ci/test_ci_workflow.py",
    "scripts/prove_secret_scan_gate.py",
    "scripts/record_ev082.py",
    "scripts/record_ev094.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_193 = {
    "id": "WI-193",
    "phase": 2,
    "title": (
        "The secret-scan job was red at origin/main, on a PAT-shaped literal committed by the fix "
        "that removed the previous one, and the proof built to catch it could not see it"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "The committed scan over full history exits 0, and the exception that achieves it is the "
        "narrowest that works, established by running the scanner rather than by reasoning",
        "No commit after this one contains a credential-shaped literal, and the control token in "
        "the test is assembled from fragments",
        "The proof fails when this repository's history carries a finding, demonstrated by "
        "removing the exception and observing the named finding",
        "The proof's planted values are checked against the patterns the committed config actually "
        "declares, not against a copy of one pattern held in the proof",
        "The empty-list guard assertion requires the guard to concern the module list and to "
        "precede the loop",
        "The worker typecheck rule accepts a bare `cd X` line, carries it across the lines in "
        "between the way bash does, and resolves every target, not only the first",
        "EV-091's scan and test-count claims are corrected rather than left standing",
    ],
    "source": (
        "An independent read-only review of 21330ed..5d84f14, run after those commits were pushed, "
        "which reported the secret-scan job red at HEAD with one finding and named the file and "
        "line. Both were confirmed by executing the committed scan command before anything was "
        "changed."
    ),
    "reproduction": (
        "The committed command - docker run --rm -v \"$PWD:/repo\" zricethezav/gitleaks:v8.30.1 "
        "detect --source /repo --config /repo/.gitleaks.toml --redact --no-banner --exit-code 1 - "
        "over 60 commits reports 'leaks found: 1' and exits 1, rule github-pat, file "
        "tests/ci/test_ci_workflow.py line 632, commit 25bf81f9c84ec73d1900a8d6f816db8db7696e94. "
        "That line held a realistic 36-character base62 control token written out whole, as the "
        "control proving .gitleaks.toml's token exception is too narrow to hide a real credential. "
        "WI-190 had removed a whole PAT-shaped literal from prove_secret_scan_gate.py for exactly "
        "this reason, and the assertion added with that fix wrote another one into the test file."
    ),
    "notes": (
        "How it escaped is the finding, not the typo. `gitleaks detect` scans committed history, so "
        "the scan run before a commit cannot see what is about to be committed - and the only scan "
        "of this tree in the whole batch was run before the commit, over 58 commits, and reported "
        "clean. After the commit it is 60 commits and one finding. Nothing else could see it "
        "either: gh is installed and unauthenticated for this repository, so the red job's log was "
        "unreadable, and prove_secret_scan_gate.py - the instrument whose entire purpose is this - "
        "scanned only scratch repositories it builds itself. It reported PASS (4 properties) in the "
        "same tree where the real scan was red. Those are two independent gaps: a secret committed "
        "to this repository is invisible until someone reads a CI log.\n\n"
        "The second gap is the one worth closing, and it is closed by a fifth property that scans "
        "THIS repository's committed history with the committed command. Its negative control is "
        "the proof: with the new exception removed, the property fails and names "
        "'github-pat in tests/ci/test_ci_workflow.py at 25bf81f9c84e' - so it observes real "
        "history rather than asserting something about the harness. The one rewrite it performs is "
        "expanding the command's own `$PWD`, because this script executes the argument list "
        "directly rather than through a shell; left literal, docker fails on the volume name and "
        "the property would report a harness problem as a repository finding.\n\n"
        "Two smaller holes were open in the same place and are closed with it. The proof's "
        "self-check compared its planted token against a hardcoded copy of ONE allowlist pattern, "
        "which is exactly the drift the repository keeps recording - and .gitleaks.toml grew a "
        "second token exception while this was being fixed, at which point that check would have "
        "kept reporting success if the planted token had started matching it. It now reads the "
        "committed config's regexes. And the planted credential's fragments did not reassemble to "
        "the value the comment said they did: 31 characters where the value in history has 32, "
        "with the `c` dropped. The scenario still worked, so this was a comment asserting an "
        "equivalence that no longer held - in the file whose whole argument is that its literals "
        "can be trusted. The fragments are fixed and the guard now enforces the shape.\n\n"
        "The exception itself was chosen by execution. With `regexTarget = \"match\"`, both an "
        "exact-literal pattern and a twelve-character run of the value suppress the finding, and a "
        "random well-formed 36-character token is reported under both. The exact-literal form was "
        "rejected because it would put a credential-shaped string in .gitleaks.toml, which is the "
        "defect being fixed. Twelve characters is the shortest run that still identifies this value, "
        "and a random base62 token containing that exact run does not occur.\n\n"
        "One trap is recorded because it nearly produced the wrong conclusion, and so is a correction of "
        "it. An early probe of these candidates reported that NO value-shaped exception suppresses "
        "the finding, which contradicts the working exception already in the config. The probe had "
        "omitted `regexTarget = \"match\"`. That explanation was recorded here and is WRONG, and "
        "measuring it again against the pinned image is what caught it: deleting the key still "
        "suppresses this finding, because `github-pat`'s expression has no capture group, so the "
        "rule's secret and the span it matched are the same string. The key is inert on this entry "
        "and is kept only for consistency with the first entry, where it does matter because "
        "`generic-api-key` excludes the field name. What the failing probe had actually shown was "
        "that it scanned a repository containing no finding to suppress - the same failure mode as "
        "the fourth property it was written to rule out, one level down. The config's own "
        "description now says this, including that the key is inert here and why it is not on the "
        "first entry.\n\n"
        "Two defects the same review found in the WI-192 assertion are fixed rather than left. The "
        "empty-list guard was satisfied by any `-eq 0` in the step, including one unrelated to the "
        "module list, and its position was not checked at all - so a guard placed after `done <` "
        "passed, which builds first and refuses second. And the mypy rule recognised only the "
        "parenthesised subshell form, so a working two-line `cd X` then `python -m mypy src` was "
        "reported as broken, and it resolved the config from the first target only, so "
        "`mypy workers/research/src workers/backtest/src` was reported clean. A rule that blocks "
        "correct code is as bad as one that waves through incorrect code, and this repository has "
        "recorded both directions.\n\n"
        "The check's own code had a defect of its own, found before anything was committed. Its first "
        "version cleared the carried directory on any line that was not a `cd` or a mypy command. "
        "Bash does not: a bare `cd X` holds until another `cd` says otherwise, and an unrelated "
        "command between them does not undo it. A block that `cd`s, echoes, then runs mypy was "
        "therefore read as running at the repository root. That direction under-reports rather than "
        "over-reports, which is the worse one for a rule whose job is to catch the misconfiguration - "
        "the real problem would have been reported against the wrong directory, or not at all. The "
        "carry now behaves as bash does, and both directions are held by a control pair: a `cd`, an "
        "unrelated line, and a correct invocation is accepted, while the same block one level too "
        "deep is rejected naming `mypy_path 'src'`. Reverting the carry fails both, which is what "
        "distinguishes that pair from a rule that reaches the right answer by accident.\n\n"
    ),
    "dependencies": ["WI-190"],
    "evidence_ref": ["EV-094"],
}

EV_091_CORRECTION = (
    "\n\nCORRECTION, recorded rather than quietly fixed, and the most important sentence in this "
    "record. Everything above about the scan being clean was true when measured and false by the "
    "time the commit carrying this record reached the remote: that commit itself introduced a "
    "PAT-shaped literal into tests/ci/test_ci_workflow.py, so the committed scan over full history "
    "reported one finding and exited 1 at 25bf81f. The pre-commit measurement was 58 commits and "
    "no leaks; the post-commit state is 60 commits and one leak, because `gitleaks detect` scans "
    "committed history and cannot see a file that has not been committed yet. See EV-094 and "
    "WI-193. The test count has the same shape: 172 was correct when measured, and the commit that "
    "carries this record contains 178, because WI-192's five tests were added before it was "
    "written."
)

EV_094 = {
    "evidence_id": "EV-094",
    "work_item": "WI-193",
    "status": "RESOLVED",
    "claim": (
        "The secret-scan job is green again, and this time a secret committed to this repository "
        "is a failing command rather than a CI log nobody here can read."
    ),
    "method": (
        "The finding was confirmed by executing the committed command before anything was changed, "
        "so the fix was never reasoned about from a report. The exception's shape was then chosen "
        "by running the pinned scanner against scratch repositories built for the purpose, with "
        "three candidate patterns and a realistic random token as the control, each candidate "
        "measured for both suppression and continued reporting. The new proof property was "
        "controlled by deleting the exception it depends on and observing the failure name the "
        "finding, with the config restored byte-for-byte and verified by SHA-256. The two "
        "tightened assertions were controlled by moving the guard after the loop, by removing it, "
        "and by leaving the step unchanged."
    ),
    "result": (
        "Before: the committed command over 60 commits reports 'leaks found: 1', exit 1, rule "
        "github-pat at tests/ci/test_ci_workflow.py:632 in commit 25bf81f. After: 'no leaks found', "
        "exit 0, over the same 60 commits. Re-measured on the commit that carries this "
        "fix, 69fb028: 'no leaks found', exit 0, over 61 commits scanned, with "
        "`git rev-list --count HEAD` = 57. On 64f8ceb, the gate-report re-stamp that follows it, "
        "the same command reports 62 commits scanned and the rev-list is 58 - the count moves with "
        "each commit, so both numbers are named against the commit they were measured on instead "
        "of being quoted as the repository's size. "
        "scripts/prove_secret_scan_gate.py reports PASS (5 "
        "properties), up from four; the fifth is 'this repository's committed history passes the "
        "scan: exit 0, 61 commits scanned' as measured on 69fb028. tests/ci passes, 199 tests, up "
        "from 177.\n\n"
        "Controls, each executed rather than argued:\n\n"
        "1. Removing the third exception from .gitleaks.toml makes the new property fail and name "
        "'github-pat in tests/ci/test_ci_workflow.py at 25bf81f9c84e' - so it observes real history "
        "rather than asserting something about the harness. Config restored byte-for-byte.\n"
        "2. The Go SAST empty-list guard moved after `done <` is rejected with the ordering message.\n"
        "3. The same guard removed is rejected.\n"
        "4. The unmodified step passes.\n"
        "5-11. All seven mutations of the worker typecheck wiring produce their expected problem: "
        "invoked from the root, `cd` one level too deep, invocation deleted, both workers in one "
        "root-relative invocation, `cd` followed by an unrelated line and a correct invocation, a "
        "flag whose value is not a target, and two `cd` hops inside one subshell.\n"
        "12. Four mutations of that rule's own code, each failing its own control: reverting the "
        "`cd` carry fails both of the `cd`-plus-unrelated-line controls at once - the negative one "
        "for reporting the wrong directory and the positive one for rejecting correct bash; "
        "dropping any of the three `cd` spellings fails its own control; reverting the "
        "value-flag handling fails the `-p` positive control with exactly "
        "'webtrade_backtest does not exist relative to the working directory it runs in, "
        "workers\\\\backtest'; and removing the outside-the-repository naming makes `cd /tmp` raise "
        "rather than report. All eight mutations in this list were executed against the real file and "
        "restored byte-for-byte afterwards, verified by SHA-256 on each run.\n"
        "13. Three widenings of the gitleaks exception are caught by the narrowing check - dropping "
        "the `ghp_` prefix from the excepted run, widening to any 36-character token, and widening "
        "to `.*` - and the shipped patterns are the positive case, asserted through the same "
        "function so the passing case cannot come from a pattern that was never tested.\n"
        "14. Four ways of losing the SAST empty-list refusal are caught: the guard deleted, replaced "
        "by a comment describing it, replaced by a conditional on an unrelated variable, and placed "
        "after `done <`.\n"
        "15. Three conditions that would make property 5 report a scan that never happened are "
        "refused: a volume that does not resolve to this checkout, an exit 0 reporting `0 commits "
        "scanned`, and a non-zero exit with no finding block.\n\n"
        "Five positive controls, because a rule that only fails is not shown to be right: a "
        "root-relative invocation of the worker that declares no mypy_path; a `cd` followed by an "
        "unrelated line and a correct invocation; `cd X && cmd` without parentheses; `-p package` "
        "with its value correctly not read as a target; and a `cd` chain across separate lines.\n\n"
        "A second independent review of this change set, before it was committed, returned WARNING "
        "with no critical or high finding and thirteen items. Every one was checked and the "
        "verified ones fixed rather than deferred, and several of them are the same class as the "
        "defect this batch exists to repair - a claim about a gate that had never been executed. "
        "They are listed in `defect_found_and_fixed` and the controls they added are counted there "
        "too, so the enumeration lives in one place.\n\n"
        "One number here is the scanner's, not the repository's: 60 is what gitleaks printed, and it "
        "counts every ref it was given rather than `HEAD`, which is 56 commits in this clone. The "
        "figure is a faithful transcription of the tool's output and is quoted as such; it will not "
        "reproduce identically on a clone with a different set of refs. `git rev-list --count HEAD` "
        "is the number to quote if the point is how much history exists."
    ),
    "defect_found_and_fixed": (
        "1. tests/ci/test_ci_workflow.py:632 carried a whole realistic PAT-shaped control token. "
        "It is now assembled from fragments, and the comment says why - the scan covers history, so "
        "a PAT-shaped string written into this file is a committed finding. 2. .gitleaks.toml "
        "carries a third exception for the two commits that are already pushed: a twelve-character "
        "run of that one value, anchored to the `ghp_` prefix, measured against the pinned scanner "
        "in both directions. The `regexTarget = \"match\"` key on that entry is inert, which is a "
        "correction to an earlier claim in this file, and the config now says so. 3. scripts/prove_secret_scan_gate.py gains a fifth property that scans this "
        "repository's committed history, which is the only check here that could have caught either "
        "occurrence; the docstring's claim that it never scans this repository is corrected, "
        "because it no longer holds. 4. Its self-check compared the planted token against a "
        "hardcoded copy of one allowlist pattern; it now reads the committed config's regexes, "
        "which matters because the config gained a second token exception while this was being "
        "fixed. 5. The planted credential's fragments reassembled to 31 characters where the value "
        "in history has 32; fixed, and the guard now enforces the shape. 6. The Go SAST empty-list "
        "assertion accepted any `-eq 0` and ignored ordering; it now requires the guard to concern "
        "the module list and to precede the loop. 7. The worker typecheck rule recognised only "
        "`(cd X && ...)` and resolved only the first target; it now honours a bare `cd X` line and "
        "resolves every target. 8. The first version of that fix cleared the carried directory on "
        "any line that was not a `cd` or a mypy command, so a `cd`, an unrelated line, then mypy "
        "was read as running at the repository root - under-reporting, which is the worse direction "
        "for this rule; it now carries the directory as bash does, with a control on each side. "
        "9. EV-091's scan and test-count claims carry a correction, and scripts/record_ev082.py's "
        "'four negative controls' is reconciled with EV-091's five negative and two positive.\n\n"
        "Items 10 to 16 are the second review's, all verified by execution before being fixed:\n\n"
        "10. .gitleaks.toml claimed `regexTarget = \"match\"` was load-bearing on the third entry. It "
        "is not, and the claim was repeated in WI-193 and in this record - the same failure mode as "
        "the eight defects this batch repairs, committed by the repair. Re-measured against the "
        "pinned image: deleting the key still suppresses the finding, because `github-pat` has no "
        "capture group, so the rule's secret and the span it matched are the same string. The key is "
        "kept for consistency with the first entry, where it IS load-bearing because "
        "`generic-api-key` excludes the field name from its secret, and the config now says both "
        "things.\n"
        "11. The gitleaks narrowing check filtered the config's patterns to those containing `ghp_` "
        "before testing them, so the prefix-dropped widening was never evaluated. It is a measured "
        "widening - unanchored, it excuses the run at any of the 25 offsets a 12-character run could "
        "occupy - and it was invisible to every check in the repository. All patterns are tested "
        "now, and the control token carries the run at a displaced offset so the mutation is caught. "
        "One widening remains undetectable by this check and is stated in the test's docstring "
        "rather than papered over: a pattern that lengthens the run by a few characters, because "
        "every token it would excuse is already excepted.\n"
        "12. Property 5 could pass while scanning nothing: `gitleaks detect` exits 0 with `0 commits "
        "scanned` for a directory that is not a git repository, which was measured. It now requires "
        "a commit count greater than zero, refuses to run if `$PWD` expansion does not mention this "
        "checkout, and treats a non-zero exit with no finding block as a HARNESS failure - the "
        "distinction the other four properties make and this one originally did not.\n"
        "13. That same property had no timeout, so a hung scan hung the proof.\n"
        "14. `_check_planted_values` read `regexes` only, so an exception added as a `stopword` would "
        "silence the planted values with the self-check still reporting success - and this config "
        "already carries one stopword entry. It reads both now, guards the combined compile, and "
        "checks each planted value bare and inside the assignment the scanner matches.\n"
        "15. The Go SAST empty-list guard could still be satisfied by a comment line describing the "
        "refusal, or by a conditional on a differently named variable, because the rule searched for "
        "the words `count` and `-eq 0`. The accepted forms are now derived from the step's own "
        "`wc -l < modules.txt` assignment, with a control for each vacuous form.\n"
        "16. The worker typecheck rule knew only two of the three spellings bash allows, so "
        "`cd workers/backtest && python -m mypy src` - correct, working bash - was reported as "
        "running at the repository root. It now knows all three, resolves `cd` chains inside a "
        "subshell, treats `-p` and the other value-taking mypy flags as flags rather than targets, "
        "and names a working directory outside the repository instead of raising ValueError from "
        "inside the checker.\n\n"
        "17. The fifth property failed on the commit that introduced it, which is the outcome it "
        "exists to produce. Binding the planted idempotency value as "
        "`PLANTED_CREDENTIAL_VALUE = \"<23 characters>\" + \"<9>\"` is a `generic-api-key` finding: "
        "that rule pairs a keyword with an adjacent high-entropy value and reports the pair, and the "
        "keyword was inside the variable's own name. The reassembled bytes were identical to the "
        "historical value and the fragments were both shorter than the credential, so every shape "
        "check in this repository passed while the scanner reported a finding at 4907b8e. The "
        "literals are now eleven characters or fewer and the binding is named without a keyword in "
        "it. 4907b8e was never pushed and was amended rather than followed by a fourth allowlist "
        "entry.\n\n"
        "18. That failure also showed the pre-commit literal check was too narrow, and the gap is "
        "now closed by measurement. It looked for three published credential shapes and nothing "
        "else, so it did not see a value that is no rule's shape. The keyword list is now gitleaks' "
        "own, matched as a substring rather than at word boundaries - `\\bcredential\\b` does not "
        "match `PLANTED_CREDENTIAL_VALUE`, which is the line that failed - paired with a "
        "twenty-character mixed-case run on the same line. Over this repository's tracked files the "
        "threshold isolates the real finding: at 16 and 18 it also matches four lines the scanner "
        "attributes to github-pat because the fragment follows `ghp_`, and at 24 it matches nothing "
        "while missing nothing. Both directions have a control, and a filesystem-wide scan confirms "
        "every remaining hit is in gitignored build output and __pycache__, none of it committable."
    ),
    "significance": (
        "The repository's recurring shape, committed by the fix for it. WI-190 removed a whole "
        "PAT-shaped literal from the proof script and, in the same change set, wrote another into "
        "the test that guards the exception added alongside it. Each was individually defensible - "
        "both were controls, and a control that is not a real credential shape tests nothing - and "
        "together they put a credential-shaped string in history twice. The reason neither was seen "
        "is structural and is now fixed: every existing property of the proof scans a scratch "
        "repository, so the proof was structurally incapable of observing the repository it ships "
        "in. A gate that cannot see its own repository cannot report on it."
    ),
    "caveats": (
        "The new property scans COMMITTED history. A secret that is staged but not committed is "
        "invisible to it, and to the CI step, until it is committed - inherent to `gitleaks "
        "detect`, stated rather than hidden. It is why the property runs in CI on the pushed "
        "commit and not only on a developer machine.\n\n"
        "The exception is honoured wherever that twelve-character run appears, as the two existing "
        "ones are. No new commit may contain it; the control token is assembled from fragments and "
        "the proof plants a differently shaped value, and tests/ci asserts both facts on every run.\n\n"
        "A secret-shaped literal is now a harder thing to commit than it was, because the property "
        "and the working-tree check between them cover both shapes: a published credential shape "
        "anywhere in a committable file, and a long high-entropy value next to a credential keyword "
        "anywhere in one. The first of those two was demonstrated by this batch rather than "
        "asserted - the pre-commit check missed the line that the post-commit scan caught - so both "
        "are recorded as measured rather than as designed.\n\n"
        "Not verified: GitHub Actions results, which remain unreadable with an unauthenticated gh. "
        "Everything above was executed locally against the committed tree."
    ),
    "exception": (
        "One, and it is forced rather than chosen: commits 25bf81f and 5d84f14 are pushed and "
        "cannot be un-written, so an exception for them is the only available remedy - the same "
        "position WI-190 recorded for fa2156f. Nothing was skipped or weakened, and no check was "
        "removed to reach a green result."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

# The fields this recorder is allowed to rewrite in an existing EV-094. `recorded_at`,
# `recorded_by`, `schema`, `evidence_id` and `work_item` are excluded on purpose: they are the
# record's identity and provenance, and an update that changed them would be a different record.
EV_094_FIELDS = (
    "claim",
    "status",
    "method",
    "result",
    "defect_found_and_fixed",
    "significance",
    "caveats",
    "exception",
    "artifacts",
    "supersedes",
)


def _read_records() -> list[dict]:
    if not EVIDENCE.exists():
        return []
    return [
        json.loads(line)
        for line in EVIDENCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_records(records: list[dict]) -> None:
    with io.open(EVIDENCE, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> bool:
    doc = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = doc["items"]
    by_id = {i["id"]: i for i in items}

    changed = False
    existing = by_id.get(WI_193["id"])
    if existing is None:
        items.append(WI_193)
        changed = True
        print(f"recorded {WI_193['id']}")
    elif existing != WI_193:
        items[items.index(existing)] = WI_193
        changed = True
        print(f"updated {WI_193['id']}")
    else:
        print(f"unchanged: {WI_193['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    records = _read_records()
    appended = []

    for index, record in enumerate(records):
        if record.get("evidence_id") != "EV-091":
            continue
        if "CORRECTION, recorded rather than quietly fixed" in record.get("result", ""):
            print("unchanged: EV-091 correction already present")
            break
        records[index]["result"] = record["result"] + EV_091_CORRECTION
        records[index]["caveats"] = (
            record.get("caveats", "")
            + "\n\nCORRECTED BY EV-094: the scan result above was superseded within the same commit "
            "that recorded it. The correction is appended to `result` rather than written over it, "
            "so the record still shows what was measured and when it stopped being true."
        )
        print("corrected EV-091")
        break

    recorded = {record.get("evidence_id") for record in records}
    if EV_094["evidence_id"] not in recorded:
        # The payload carries every field except the record's own identity and provenance, so the
        # append path and the update path cannot drift into writing different records.
        records.append(
            {
                "schema": "ecc.project-brain/evidence/v7",
                "evidence_id": EV_094["evidence_id"],
                "recorded_at": STAMP,
                "recorded_by": "team-lead",
                **EV_094,
            }
        )
        appended.append(EV_094["evidence_id"])
    else:
        # Rewrite in place when the payload changes, the same way WI-193 above is handled. Appending
        # only would mean a re-run silently keeps the first wording, so a claim edited here would
        # never reach the record - and this file's whole subject is a claim that stopped being true.
        # Only EV-094 is eligible: records for work items that are already closed elsewhere are
        # corrected by appending a dated correction, never by rewriting what they originally said.
        index = next(
            i for i, record in enumerate(records) if record.get("evidence_id") == EV_094["evidence_id"]
        )
        current = {key: records[index].get(key) for key in EV_094_FIELDS}
        wanted = {key: EV_094[key] for key in EV_094_FIELDS}
        if current != wanted:
            records[index].update(EV_094)
            appended.append(f"{EV_094['evidence_id']} (updated)")
            print(f"updated {EV_094['evidence_id']}")
        else:
            print(f"unchanged: {EV_094['evidence_id']}")
    _write_records(records)

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()
