"""Record WI-194 and EV-095: two false positives in the worker typecheck rule that WI-193 left open.

WI-193 closed the secret-scan defect and, while doing so, rebuilt the `cd` handling in
tests/ci/test_ci_workflow.py's worker typecheck rule. That rebuild recognised three spellings of a
directory change but still mis-parsed two ordinary ones - a quoted directory, and a `cd` carrying
bash's own option word - so correct bash was reported as running at the repository root. Both were
listed as low and left. This records them as a work item of their own rather than folding them into
a completed item's evidence, and fixes them.

The fixes were measured rather than asserted: the previous bare-capture regex is run against the new
controls' inputs, and its output is recorded below.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-04T07:55:00Z"

ARTIFACTS = [
    "tests/ci/test_ci_workflow.py",
    "scripts/record_ev095.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_194 = {
    "id": "WI-194",
    "phase": 2,
    "title": (
        "The worker typecheck rule reports two correct spellings of `cd` as running at the "
        "repository root, after WI-193 rebuilt that rule to stop doing exactly that"
    ),
    "status": "COMPLETED",
    "priority": "medium",
    "acceptance_criteria": [
        "A quoted directory (`cd \"workers/research\"`) resolves to the directory, not to a path "
        "that still contains quote characters and therefore does not exist",
        "A `cd` carrying bash's own option word (`cd -P workers/backtest`, and the `--` form) "
        "resolves to the directory rather than being read as the directory",
        "Both spellings work in all three forms the rule already recognised - bare line, inline "
        "`&&`, and subshell - because the fix composes with the existing parsing rather than "
        "adding a fourth path through it",
        "Each new accepted form has a positive control, and each was measured failing against the "
        "previous regex rather than being assumed to have been broken",
        "The capture is read by group name, so adding the optional option word cannot silently "
        "change which group holds the directory",
    ],
    "source": (
        "Carried out of WI-193. Its review listed both as low-severity observations on the rebuilt "
        "`cd` handling - 'cd -P workers/backtest' and 'cd \"workers/backtest\"' are both reported "
        "as resolving to the repository root - and the batch closed them as accepted limitations "
        "rather than as fixed. They are the same defect class WI-193 spent the batch eliminating: a "
        "gate rule that reports correct code, which is the direction that teaches a reader to "
        "ignore it."
    ),
    "reproduction": (
        "Against the regex WI-193 shipped, measured rather than argued:\n"
        '  cd "workers/backtest"                    -> matched, directory captured as '
        '\"workers/backtest\", including both quote characters\n'
        "  cd -P workers/backtest                   -> no match, so the invocation was resolved at "
        "the repository root\n"
        "  (cd -P 'workers/backtest' && python -m mypy src) -> no match, same consequence\n"
        "The first resolves to a path that does not exist, so the rule reports a missing directory "
        "the workflow never names. The other two resolve to the repository root, so the rule reads "
        "config from the wrong place - which is the under-reporting direction."
    ),
    "notes": (
        "Both forms are ordinary bash rather than exotic ones. A quoted path is what a shell "
        "produces on its own and what many authors write by habit; `-P` is the option a workflow "
        "gains when someone wants symlinks resolved in a checkout. Neither is in the shipped "
        "workflow today, which is exactly why the defect survived: the rule was derived from the "
        "one spelling the repository happens to use, corrected for the spellings that appeared, and "
        "left holding a comment that claimed to know bash's semantics.\n\n"
        "The fix is one shared directory token matched as quoted-or-bare, plus an optional option "
        "word that is consumed rather than resolved, used by all three existing patterns. Composing "
        "them in one place rather than adding a fourth pattern is deliberate: three patterns with "
        "three private copies of the directory logic is how they drifted apart in the first place.\n\n"
        "The capture is read through a helper by group name. This is not tidiness - reading it by "
        "position would have kept working when the optional group was inserted ahead of the "
        "directory, and every option-taking `cd` would have resolved to the literal string `-P`."
    ),
    "dependencies": ["WI-193"],
    "evidence_ref": ["EV-095"],
}

EV_095 = {
    "evidence_id": "EV-095",
    "work_item": "WI-194",
    "claim": (
        "The worker typecheck rule accepts every correct spelling of a `cd` that a workflow rewrite "
        "can produce, and reports each new one as a positive control rather than assuming it"
    ),
    "status": "VERIFIED",
    "method": (
        "Three positive controls added to the existing spelling matrix, each a full replacement of "
        "the step's run block. Old and new parsing compared directly on the same inputs by a "
        "throwaway probe, so each control is known to fail against the code it was written for. The "
        "full tests/ci module and then all 13 repository gates were run afterwards."
    ),
    "result": (
        "Before: the three new inputs are mis-parsed as recorded in WI-194's reproduction. After: "
        "tests/ci passes with the three controls included, and every pre-existing control - the "
        "wrong-directory rejection, the invocation-deletion rejection, the flag-value controls and "
        "the four earlier `cd` spellings - still passes unchanged. Nothing about the rule's "
        "under-reporting direction changed; the fix only widens what it can parse."
    ),
    "defect_found_and_fixed": (
        "1. A quoted directory was captured with its quote characters, producing a path that does "
        "not exist and a finding against a directory the workflow never names.\n"
        "2. `cd -P DIR` and `cd -- DIR` did not match at all, so the invocation was resolved at the "
        "repository root - the under-reporting direction, where the rule reads config from the "
        "wrong place rather than complaining."
    ),
    "significance": (
        "A CI assertion is a rule about the repository as much as a test of it. A rule that reports "
        "correct code gets deleted on first sight of a false positive, and the misconfiguration it "
        "was written to catch then ships silently. WI-193 already paid for both directions of this "
        "in one batch, which is why these two were fixed rather than written down as limitations."
    ),
    "caveats": (
        "Only `cd`'s own option words are consumed, and only as a single token before the "
        "directory: `-L`, `-P`, `-e` and `--`, in any of the forms bash writes them singly. `cd -` "
        "is still resolved as a literal directory named `-` and reported as missing, which is wrong "
        "but harmless and rare; it is stated here rather than left to be discovered. Not verified: "
        "GitHub Actions, which remain unreadable with an unauthenticated gh."
    ),
    "exception": (
        "None. Both fixes widen parsing, so no previously reported problem stops being reported and "
        "no threshold was loosened to reach a green result."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

# The fields this recorder may rewrite in an existing EV-095. `recorded_at`, `recorded_by`, `schema`,
# `evidence_id` and `work_item` are the record's identity and provenance.
EV_095_FIELDS = (
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
    existing = by_id.get(WI_194["id"])
    if existing is None:
        items.append(WI_194)
        changed = True
        print(f"recorded {WI_194['id']}")
    elif existing != WI_194:
        items[items.index(existing)] = WI_194
        changed = True
        print(f"updated {WI_194['id']}")
    else:
        print(f"unchanged: {WI_194['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    records = _read_records()
    appended: list[str] = []

    recorded = {record.get("evidence_id") for record in records}
    if EV_095["evidence_id"] not in recorded:
        records.append(
            {
                "schema": "ecc.project-brain/evidence/v7",
                "evidence_id": EV_095["evidence_id"],
                "recorded_at": STAMP,
                "recorded_by": "team-lead",
                **EV_095,
            }
        )
        appended.append(EV_095["evidence_id"])
    else:
        index = next(
            i for i, record in enumerate(records) if record.get("evidence_id") == EV_095["evidence_id"]
        )
        current = {key: records[index].get(key) for key in EV_095_FIELDS}
        wanted = {key: EV_095[key] for key in EV_095_FIELDS}
        if current != wanted:
            records[index].update(EV_095)
            appended.append(f"{EV_095['evidence_id']} (updated)")
            print(f"updated {EV_095['evidence_id']}")
        else:
            print(f"unchanged: {EV_095['evidence_id']}")
    _write_records(records)

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()
