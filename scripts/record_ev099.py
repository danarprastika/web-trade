"""Record WI-197 and EV-099: WI-120's cross-module-mutation rule was prose in three files.

docs/01 line 86 states "Direct table writes outside the owning module are prohibited", docs/05 line 7
states "Each schema owns its tables", and .kilo/ecc/project-brain/architecture.md line 62 restates it.
Nothing checked any of them. A generated query sat in dbgen and was callable by any package that
imported it, so the rule that the whole persistence design rests on was true only as a sentence.

This is the third of WI-120's three criteria and the second one whose enforcement gap is now closed.
WI-196 closed the second (no hand-written SQL in Go). The first - every authoritative state transition
inside a transaction - is NOT addressed here and is NOT claimed. WI-120 is untouched and still PENDING,
still depending on WI-118, which is BLOCKED on a named human reviewer.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-04T11:20:00Z"

ARTIFACTS = [
    "scripts/check_table_ownership.py",
    "tests/ci/test_table_ownership.py",
    "scripts/run_gates.py",
    "docs/01_SYSTEM_ARCHITECTURE.md",
    "docs/05_PERSISTENCE_EVENTING_RECONCILIATION.md",
    "scripts/record_ev099.py",
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_197 = {
    "id": "WI-197",
    "phase": 3,
    "title": (
        "WI-120's rule that a module may not write another module's tables was asserted in three "
        "documents and enforced nowhere"
    ),
    "status": "COMPLETED",
    "priority": "high",
    "acceptance_criteria": [
        "A gate refuses any package outside the owning module that calls a mutating query belonging to "
        "that module, demonstrated end to end on a real tracked Go file that is restored byte-for-byte",
        "A cross-module read of the same query file is accepted, so the rule cannot be satisfied by "
        "copying the read into a hand-written string",
        "Every mutating query the schema declares is either owned by a declared module or the gate "
        "fails - a new query file declaring writes cannot pass until someone says who owns it",
        "Each declared owner exists on disk and carries a reason, and a declared owner with no query "
        "file is reported rather than ignored",
        "The gate reports what it read - query count, how many are called from Go, which are not yet "
        "called - so a pass cannot be confused with a scan that read nothing",
        "The false positives the first run produced on the existing tree are fixed rather than "
        "suppressed",
    ],
    "source": (
        "Surveying what WI-120 still needs after WI-196 closed the stray-SQL gap, by asking where the "
        "ownership rule is written down and then whether anything reads it. Three files state it. "
        "Nothing checks it. This is the same defect class as WI-196 and the two found each other: the "
        "first was the rule that Go may not hand-write SQL, the second the rule that a module may not "
        "write another's tables, and each was a documented prohibition whose only enforcement was the "
        "sentence asserting it."
    ),
    "reproduction": (
        "Before: searching tests/ci for a check that maps a query file to an owning module returns "
        "nothing, while docs/01 line 86, docs/05 line 7 and architecture.md line 62 each state the "
        "prohibition. Any package could import dbgen and call any query. After: "
        "scripts/check_table_ownership.py runs as the table-ownership gate and the same search finds "
        "tests/ci/test_table_ownership.py."
    ),
    "notes": (
        "Two decisions are worth keeping because both are counter-intuitive.\n\n"
        "Reads are not restricted. The obvious strict version - one module per table, no exceptions - "
        "would have failed this repository, because a consistency check and a join legitimately read a "
        "table they do not write. Enforcing that would not have removed the coupling; it would have "
        "moved it, because the cheapest way to read a table you may not call a query on is to put the "
        "read in a string, and that is precisely what check_no_stray_sql exists to catch. A gate whose "
        "pressure points at another gate's failure mode is a gate that will be defeated the first "
        "quarter someone is behind. So the rule constrains writes, which is what the documents "
        "actually prohibit.\n\n"
        "The three-entry ownership map is not the thing being enforced. The map is data a human "
        "maintains; a gate that only checks the map is checking itself. What is enforced is that every "
        "mutating query's callers must be its owner, so a fourth query file - or a fourth module - "
        "fails the gate until someone writes down who owns it and why. Each entry carries its reason, "
        "including the one where the stems and the package names differ, because a name mapping "
        "inferred from the file name silently acquires a second owner the first time a table moves.\n\n"
        "Running it against the real tree found three false positives that a fixture would not have. "
        "`ON CONFLICT ... DO UPDATE SET` matches a naive UPDATE pattern and yields SET as the table "
        "name, so the insert target has to win where both appear. And these files document their "
        "reasoning in comments next to the code, naming the queries they deliberately do not own - so "
        "the caller scan has to blank comments out before it can distinguish an explanation from a "
        "call. Both were found by pointing the checker at the repository, which is the seventh time "
        "this program has had to learn that lesson.\n\n"
        "One hole was found by reading and is recorded rather than closed: the caller scan skips any "
        "path containing `/db/`, which today removes only the sqlc-generated package and one contract "
        "test. A future hand-written non-test file under services/control-plane/db/ would be skipped "
        "silently. It is stated in EV-099's caveats rather than fixed here, because narrowing the "
        "exclusion to the generated package and db/queries is a change to a gate that is currently "
        "green and would need its own controls."
    ),
    "dependencies": ["WI-120"],
    "dependency_exemptions": {
        "WI-120": (
            "Finished ahead of WI-120 deliberately, for the same reason as WI-196. WI-120 is PENDING "
            "and blocked behind WI-118, which is BLOCKED on a named human reviewer, and leaving a "
            "criterion unenforced for as long as that block lasts is how a documented rule decays into "
            "a belief. This work is additive and depends on nothing in WI-120: a new gate, its "
            "controls, and two documentation pointers. WI-120 itself is untouched and still PENDING. "
            "Its first criterion - every authoritative state transition inside a transaction - is not "
            "addressed by this change and is not claimed; that is the next item and it is the one that "
            "requires WI-118."
        )
    },
    "evidence_ref": ["EV-099"],
}

EV_099 = {
    "evidence_id": "EV-099",
    "work_item": "WI-197",
    "claim": (
        "No module writes another module's tables by calling its generated queries, enforced by a "
        "gate rather than asserted in three documents"
    ),
    "status": "VERIFIED",
    "method": (
        "Eleven controls. Three named ones pin the specific queries that matter (AppendAuditRecord, "
        "AppendEntry, InsertModel) by name rather than by count, so a query silently dropping out of "
        "the parse is a failure instead of a smaller number. One plants a cross-module write in a real "
        "tracked Go file, requires the script itself to exit 1 and name the offending package and "
        "query, and restores the file with a hash assertion afterwards. One proves the matching "
        "read-only case is still accepted. One removes the only owner and requires failure rather "
        "than an empty pass. Two plant the false positives the real tree produced - an ON CONFLICT DO "
        "UPDATE SET clause and prose naming tables inside a comment - and require them to be read "
        "correctly. The remainder assert the real tree is clean, that the gate read a non-zero number "
        "of queries, that every owner exists with a reason, and that every mutating query has an "
        "owner."
    ),
    "result": (
        "Before: three documents state the prohibition and nothing checks it; any package importing "
        "dbgen could call any query. After: `python scripts/check_table_ownership.py` exits 0 and "
        "reports 'PASS (10 mutating queries, 7 of them called from Go, across 3 owning modules) (not "
        "yet called from Go: AppendEntry, InsertAuditDeletionEvent, InsertLine)'. The 11 controls "
        "pass. The gate is registered in scripts/run_gates.py, making the battery 15 of 15. The three "
        "mutating queries with no Go caller are reported by name rather than hidden, which is the "
        "honest state of a write path that is deliberately not exposed. The end-to-end control was "
        "confirmed to fail the script before the change and to pass after, so the gate is not "
        "vacuous."
    ),
    "defect_found_and_fixed": (
        "1. The prohibition existed in docs/01, docs/05 and architecture.md with nothing checking "
        "it. Replaced with a gate.\n"
        "2. `ON CONFLICT ... DO UPDATE SET` matched the UPDATE pattern and reported SET as the "
        "mutated table. The insert target now wins where both appear, and a control pins it.\n"
        "3. The caller scan matched comments. This repository explains itself in comments beside the "
        "code, naming the queries it deliberately does not own, so the scan reported explanations as "
        "cross-module writes. Comments are now blanked before matching, and a control plants the "
        "prose case.\n"
        "4. An earlier version of the caller pattern required a parenthesised call and reported PASS "
        "on a method value handed straight to a function - the same cross-module write with one fewer "
        "character. It now matches the query as a selector. Found by running the control, not by "
        "reading the pattern."
    ),
    "significance": (
        "This is the criterion that decides whether the domain boundaries in docs/01 are real. The "
        "documents say a module owns its tables and that cross-module mutation goes through a command "
        "or an event. With nothing enforcing it, a table's real owner was whoever reached it first, "
        "and the boundary was a naming convention that a competent engineer would violate under "
        "deadline - reasonably, since every individual write looked correct and no tool objected. "
        "Enforcing it at the generated query is the only place the rule can be mechanical without "
        "also forbidding legitimate reads: the call site stays visible, the violation names both "
        "sides, and the correct fix is a command or an event rather than a suppressed check. It also "
        "gives WI-120's remaining work a floor to stand on - when the authoritative write path is "
        "wired under WI-120, it will be wired by commands that this gate has already required."
    ),
    "caveats": (
        "The rule is enforced at the generated query, so a cross-module write expressed as "
        "hand-written SQL is not caught here - it is caught by check_no_stray_sql (EV-098), and the "
        "two gates are complementary rather than redundant.\n\n"
        "Known hole, recorded rather than closed: the caller scan skips any path containing `/db/`. "
        "Today that removes only the sqlc-generated package and one contract test, but a future "
        "hand-written non-test file under services/control-plane/db/ would be skipped silently. "
        "Narrowing the exclusion to the generated package and db/queries would close it and needs its "
        "own controls before the change is made.\n\n"
        "The ownership map is three human-maintained entries. The gate enforces the rule that "
        "consumes it - every mutating query's callers must be its owner, and an unowned mutating "
        "query file fails - but a wrong owner in the map is not detected by anything here.\n\n"
        "Reads are deliberately unrestricted, so two modules reading one table will not be reported. "
        "That is a deliberate reading of the documents, which prohibit writes, and it is recorded "
        "here because it is a limit of the gate rather than an absence of one.\n\n"
        "Does NOT address WI-120's first criterion: every authoritative state transition running "
        "inside a transaction. That work needs WI-120 and WI-118, and is not claimed. WI-120 remains "
        "PENDING.\n\n"
        "Not verified: GitHub Actions, unreadable with the unauthenticated gh that EV-091 records. "
        "All results were measured on this host on Windows."
    ),
    "exception": (
        "No exemption from the rule itself: no module is allowed to write another's tables. Three "
        "owners are declared, each carrying a reason for why that package owns those tables, including "
        "the case where the query-file stem and the owning package name differ. Three mutating queries "
        "have no Go caller at all; the gate names them on every run rather than passing over them in "
        "silence, because a query nothing calls is unwired work, not an exemption."
    ),
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EV_099_FIELDS = (
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
    existing = by_id.get(WI_197["id"])
    if existing is None:
        items.append(WI_197)
        changed = True
        print(f"recorded {WI_197['id']}")
    elif existing != WI_197:
        items[items.index(existing)] = WI_197
        changed = True
        print(f"updated {WI_197['id']}")
    else:
        print(f"unchanged: {WI_197['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )

    records = _read_records()
    appended: list[str] = []
    recorded = {record.get("evidence_id") for record in records}
    if EV_099["evidence_id"] not in recorded:
        records.append(
            {
                "schema": "ecc.project-brain/evidence/v7",
                "evidence_id": EV_099["evidence_id"],
                "recorded_at": STAMP,
                "recorded_by": "team-lead",
                **EV_099,
            }
        )
        appended.append(EV_099["evidence_id"])
    else:
        index = next(
            i for i, record in enumerate(records) if record.get("evidence_id") == EV_099["evidence_id"]
        )
        current = {key: records[index].get(key) for key in EV_099_FIELDS}
        wanted = {key: EV_099[key] for key in EV_099_FIELDS}
        if current != wanted:
            records[index].update(EV_099)
            appended.append(f"{EV_099['evidence_id']} (updated)")
            print(f"updated {EV_099['evidence_id']}")
        else:
            print(f"unchanged: {EV_099['evidence_id']}")
    _write_records(records)

    print(f"recorded {', '.join(appended)}" if appended else "evidence already recorded")
    return changed


if __name__ == "__main__":
    main()
