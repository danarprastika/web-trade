"""Record WI-195 and EV-096: the SAST empty-list guard accepted a test on any file, negated or not.

WI-193 rebuilt the check that refuses to run the Go SAST leg over an empty module list. Its accepted
forms were derived from the step, but one branch read `! -s` without reading what was negated, so
`if [ ! -s "$GITHUB_ENV" ]` satisfied it - measured, not assumed. The module list is then never
tested, the loop body runs zero times, and the step reports success having built nothing, which is
the precise failure the guard exists to prevent.

The fix reads operands from the whole bracketed test, because a numeric comparison puts the value
under test before the operator. Seven positive controls state the accepted spellings, since a rule
tightened against one hole can be tightened into another.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-04T08:45:00Z"

ARTIFACTS = [
    "tests/ci/test_ci_workflow.py",
    "scripts/record_ev096.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_195 = {
    "id": "WI-195",
    "phase": 2,
    "title": (
        "The SAST empty-list guard accepts a negated file-size test on any file, so the module "
        "list can go untested while the check reports a passing build"
    ),
    "status": "COMPLETED",
    "priority": "medium",
    "acceptance_criteria": [
        "A negated `-s` test is accepted or rejected on its operand, not on the presence of `-s`",
        "Every accepted form tests either `modules.txt` or a module count this step computes",
        "The operand is read from the whole bracketed test, so `if [ \"$count\" -eq 0 ]` is read as "
        "testing `$count` rather than as testing the literal `0`",
        "A test whose operator is not an emptiness test is rejected even when it names the list, so "
        "the rule cannot be satisfied by an unrelated property of the same file",
        "Seven accepted spellings are pinned by positive controls, and the negative mutants are "
        "shown to fail against the previous implementation rather than assumed to have been holes",
    ],
    "source": (
        "Found by reading the rebuilt rule rather than by a failing gate, and named in the WI-193 "
        "handover as the one known false negative left in a gate assertion. The branch read "
        "`!-s` without reading the operand, so the two safe spellings and every unsafe one were "
        "indistinguishable to it."
    ),
    "reproduction": (
        "Replaying the previous implementation unchanged over the new mutants: "
        '`if [ ! -s "$GITHUB_ENV" ]; then` was ACCEPTED as the module-list guard, and '
        '`if [ "$module_total" -lt 1 ]; then` was already rejected. The first is a real hole; the '
        "second was not, and its control says so rather than claiming a second defect."
    ),
    "notes": (
        "The consequence of the hole is the one this gate exists to prevent, one level up. The step "
        "resolves the module list with `go work edit -json`, loops over it building each module, "
        "and the loop body running zero times is exit 0 with nothing built - the same silent no-op "
        "the process-substitution form had. A guard on an unrelated file's emptiness changes "
        "nothing about the module list.\n\n"
        "The operand is read from the bracketed test rather than from after the operator because "
        "`-eq` puts the value under test first. The first attempt at this fix kept reading "
        "right-of-the-operator and rejected the SHIPPED guard - caught by the positive controls "
        "before it was committed, which is what they are for. The operator set is explicit rather "
        "than a character class, so `-f` and `-d` on the same file stay rejected.\n\n"
        "The second mutant is kept as a control even though the previous code already rejected it, "
        "because this change replaces a literal `-eq 0` with a set of operators - precisely the "
        "rewrite that would reintroduce the acceptance. It pins the rejection across both "
        "implementations instead of only the current one."
    ),
    "dependencies": ["WI-193"],
    "evidence_ref": ["EV-096"],
}

EV_096 = {
    "evidence_id": "EV-096",
    "work_item": "WI-195",
    "claim": (
        "The SAST empty-list guard accepts an emptiness test only when the value tested is the "
        "module list or a count this step computes, in every spelling bash allows"
    ),
    "status": "VERIFIED",
    "method": (
        "The previous implementation replayed unchanged over each new mutant, so the claim that one "
        "was a hole and the claim that the other was not are measurements. Five negative controls "
        "and seven positive controls run against the real check through the real mutation helper, "
        "then the whole tests/ci suite and all 13 gates."
    ),
    "result": (
        "Before: `if [ ! -s \"$GITHUB_ENV\" ]` satisfied the guard, and `if [ \"$module_total\" "
        "-lt 1 ]` did not. After: both are rejected, the shipped guard is still accepted, and the "
        "six further accepted spellings are each asserted. The first version of the fix rejected "
        "the shipped guard as well - it read the operand from after the operator, so `-eq 0` was "
        "read as testing `0` - and the positive controls caught it before any commit. tests/ci 211 "
        "passed, up from 202."
    ),
    "defect_found_and_fixed": (
        "1. A negated file-size test satisfied the guard without regard to what was negated, so the "
        "module list could go entirely untested while the check reported a passing build.\n"
        "2. In the fix, reading the operand from after the operator rejected the guard the "
        "repository actually ships. Fixed by reading the bracketed test as a whole, and recorded "
        "because the first attempt was green on every negative control and wrong on the real one."
    ),
    "significance": (
        "Both directions of this rule are defects with the same consequence, and the repository has "
        "now recorded three separate instances of one and two of the other. A gate that accepts an "
        "empty gate is worse than no gate, because it converts an absence of work into a green "
        "result that a reviewer reads as evidence the work happened."
    ),
    "caveats": (
        "The check is syntactic. It requires an emptiness test on the right operand before the "
        "loop, and it cannot tell whether the branch refuses on empty or proceeds - an inverted "
        "conditional would satisfy it. Verifying the branch would mean executing the step, which is "
        "what the gate for the gate would have to do. Not verified: GitHub Actions, unreadable with "
        "an unauthenticated gh."
    ),
    "exception": (
        "None. The change narrows what counts as a guard and adds controls; no threshold was "
        "loosened and no previously reported problem stops being reported."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EV_096_FIELDS = (
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
    existing = by_id.get(WI_195["id"])
    if existing is None:
        items.append(WI_195)
        changed = True
        print(f"recorded {WI_195['id']}")
    elif existing != WI_195:
        items[items.index(existing)] = WI_195
        changed = True
        print(f"updated {WI_195['id']}")
    else:
        print(f"unchanged: {WI_195['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    records = _read_records()
    appended: list[str] = []

    recorded = {record.get("evidence_id") for record in records}
    if EV_096["evidence_id"] not in recorded:
        records.append(
            {
                "schema": "ecc.project-brain/evidence/v7",
                "evidence_id": EV_096["evidence_id"],
                "recorded_at": STAMP,
                "recorded_by": "team-lead",
                **EV_096,
            }
        )
        appended.append(EV_096["evidence_id"])
    else:
        index = next(
            i
            for i, record in enumerate(records)
            if record.get("evidence_id") == EV_096["evidence_id"]
        )
        current = {key: records[index].get(key) for key in EV_096_FIELDS}
        wanted = {key: EV_096[key] for key in EV_096_FIELDS}
        if current != wanted:
            records[index].update(EV_096)
            appended.append(f"{EV_096['evidence_id']} (updated)")
            print(f"updated {EV_096['evidence_id']}")
        else:
            print(f"unchanged: {EV_096['evidence_id']}")
    _write_records(records)

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()