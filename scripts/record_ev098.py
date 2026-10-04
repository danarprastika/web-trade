"""Record WI-196 and EV-098: WI-120's second acceptance criterion was enforced by a comment.

sqlc.yaml states the rule - the Go layer must not reach PostgreSQL with hand-written SQL, because a
query in a string does not have to agree with the schema - and credits tests/ci with enforcing it.
Tests/ci contained no such check. The rule existed in exactly one place: the comment claiming it was
enforced. That is the defect class this repository has now recorded five times, and this was the
sixth, in the one file that declares itself the authority on how Go reaches the database.

This recorder does not complete WI-120. WI-120 is PENDING and still depends on WI-118, which is
BLOCKED on a named human reviewer. What is closed here is the enforcement gap on one of its three
criteria; the transaction-wrapping criterion is not addressed by this change and is not claimed.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-04T09:40:00Z"

ARTIFACTS = [
    "scripts/check_no_stray_sql.py",
    "tests/ci/test_no_stray_sql.py",
    "scripts/run_gates.py",
    "sqlc.yaml",
    "scripts/record_ev098.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_196 = {
    "id": "WI-196",
    "phase": 3,
    "title": (
        "WI-120's rule that Go may not reach PostgreSQL with hand-written SQL was asserted by a "
        "comment in sqlc.yaml and enforced nowhere"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "A repository gate fails when a statement-shaped SQL literal appears in a tracked Go file "
        "outside the generated package, demonstrated end to end on a real tracked file",
        "Every statement shape the rule claims to cover has a control that is shown to be found",
        "The exemptions are named, each with a reason, and the list is proven to exactly equal the "
        "set of files that actually contain SQL - no unused allowance and no unlisted violation",
        "The gate reports how many files it checked, so a pass cannot be confused with a scan that "
        "read nothing",
        "The false positive it produced on the existing tree is fixed rather than suppressed",
    ],
    "source": (
        "Read while surveying what WI-120 still needs, by searching tests/ci for the check sqlc.yaml "
        "credits it with and finding none. The gap was a documented enforcement claim with no "
        "enforcement, found in the file that is the declared authority on the subject."
    ),
    "reproduction": (
        "Before: Select-String for the SQL-literal rule across tests/ci returns nothing, while "
        "sqlc.yaml states 'the Go layer must not contain statement literals holding SQL is asserted "
        "by tests/ci'. After: scripts/check_no_stray_sql.py runs as the no-stray-sql gate and the "
        "same search finds tests/ci/test_no_stray_sql.py."
    ),
    "notes": (
        "Writing the check found two things that reading it would not have. First, the migrator's "
        "advisory-lock pair - `SELECT pg_advisory_lock($1)` - is a query with no FROM, so none of "
        "the nine statement shapes match it and it passed; enumerating shapes cannot close that, so "
        "the rule now also fires on a SQL keyword and a bind placeholder in the same statement, "
        "which catches the shapes nobody wrote down without matching prose. Second, the first "
        "SELECT pattern carried an untempered 400-character window and reported "
        "`SELECT pg_advisory_lock($1)` by finding the FROM of whatever statement followed it - a "
        "false positive in the checker, found by running it against the real tree rather than "
        "against a sample.\n\n"
        "Both were found because the check was run against this repository instead of a fixture. "
        "That is the sixth time this program has learned it, and it is why the end-to-end control "
        "mutates a real tracked file rather than asserting the patterns in isolation.\n\n"
        "The exemptions are proven complete in both directions by a test that walks every tracked Go "
        "file: the set of files holding SQL must equal the exempt set. That test is what found the "
        "second exemption - migrate/store_sql.go was not listed when the rule first ran."
    ),
    "dependencies": ["WI-120"],
    "dependency_exemptions": {
        "WI-120": (
            "Finished ahead of WI-120 deliberately. WI-120's second acceptance criterion is that no "
            "direct table write happens outside the owning module, and the only thing enforcing it "
            "was a comment in sqlc.yaml; leaving that unenforced while WI-120 waits on a human "
            "reviewer would mean the criterion has no guard for as long as the block lasts. The "
            "work is additive and depends on nothing in WI-120: a new gate and its controls. WI-120 "
            "itself is untouched and still PENDING - its other two criteria, transaction-wrapping "
            "and cross-module mutation, are not addressed here and are not claimed."
        )
    },
    "evidence_ref": ["EV-098"],
}

EV_098 = {
    "evidence_id": "EV-098",
    "work_item": "WI-196",
    "claim": (
        "No statement-shaped SQL reaches the Go layer outside the generated package, enforced by a "
        "gate rather than asserted by a comment"
    ),
    "status": "VERIFIED",
    "method": (
        "Nine statement shapes and the bind-placeholder rule each planted and confirmed found; three "
        "negative controls for prose, comments and Go identifiers; the exemption list pinned to the "
        "files that actually hold SQL, in both directions; and one end-to-end control that plants a "
        "DELETE in a real tracked Go file and requires the script itself to exit 1 and name the file "
        "and the statement, restoring the file byte-for-byte with a hash assertion afterwards."
    ),
    "result": (
        "Before: no check existed and sqlc.yaml claimed tests/ci held one. After: the no-stray-sql "
        "gate passes over 78 Go files outside the exemptions, 18 controls pass, and the battery is "
        "14 of 14. The real tree holds two statements outside the generated package, both in the "
        "migrator and both exempt with a stated reason. The end-to-end control was confirmed to "
        "fail the script before the change and to pass after, so the gate is not vacuous."
    ),
    "defect_found_and_fixed": (
        "1. The rule existed only as a comment claiming tests/ci enforced it. Replaced with a gate.\n"
        "2. The enumerating approach missed `SELECT pg_advisory_lock($1)`, a real query in a Go "
        "string that passed the check. Added a keyword-plus-bind-placeholder rule.\n"
        "3. The first SELECT pattern matched across statement boundaries and reported a false "
        "positive on the existing tree. Tempered on semicolons and quotes.\n"
        "4. The exemption list was incomplete: migrate/store_sql.go held SQL and was not listed. "
        "Found by the completeness control, not by reading."
    ),
    "significance": (
        "This is the criterion that keeps a database-enforced constraint from quietly ceasing to be "
        "enforced. Hand-written SQL in a Go string cannot be checked against the schema by sqlc, by "
        "the compiler or by go vet, so a query that drifts out of agreement with the migration that "
        "created its table is invisible to every tool in the repository. A gate here is the "
        "difference between a constraint that holds and one that was believed to."
    ),
    "caveats": (
        "The rule is lexical, not semantic: it matches statement shapes and a bind placeholder, so a "
        "statement written in a shape none of the rules name and without a placeholder would pass. "
        "The coverage limit is stated here rather than left to be discovered. Exempt files are still "
        "read by their own module's tests and, for the generated package, by sqlc itself. Does NOT "
        "address WI-120's other two criteria - transaction-wrapping of every authoritative "
        "transition, and cross-module mutation only through commands or events - neither of which is "
        "claimed here. Not verified: GitHub Actions, unreadable with an unauthenticated gh."
    ),
    "exception": (
        "Three named exemptions, each carrying a reason: the sqlc-generated package, and two files "
        "in the migrator module that owns its own applied_set bookkeeping and its advisory locks. "
        "The completeness control proves no exemption is unearned and no violation is unlisted, so "
        "none of the three is a blanket allowance."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EV_098_FIELDS = (
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
    existing = by_id.get(WI_196["id"])
    if existing is None:
        items.append(WI_196)
        changed = True
        print(f"recorded {WI_196['id']}")
    elif existing != WI_196:
        items[items.index(existing)] = WI_196
        changed = True
        print(f"updated {WI_196['id']}")
    else:
        print(f"unchanged: {WI_196['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    records = _read_records()
    appended: list[str] = []
    recorded = {record.get("evidence_id") for record in records}
    if EV_098["evidence_id"] not in recorded:
        records.append(
            {
                "schema": "ecc.project-brain/evidence/v7",
                "evidence_id": EV_098["evidence_id"],
                "recorded_at": STAMP,
                "recorded_by": "team-lead",
                **EV_098,
            }
        )
        appended.append(EV_098["evidence_id"])
    else:
        index = next(
            i for i, record in enumerate(records) if record.get("evidence_id") == EV_098["evidence_id"]
        )
        current = {key: records[index].get(key) for key in EV_098_FIELDS}
        wanted = {key: EV_098[key] for key in EV_098_FIELDS}
        if current != wanted:
            records[index].update(EV_098)
            appended.append(f"{EV_098['evidence_id']} (updated)")
            print(f"updated {EV_098['evidence_id']}")
        else:
            print(f"unchanged: {EV_098['evidence_id']}")
    _write_records(records)

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()