"""Record WI-199: WI-120's first acceptance criterion was never measurable, and measuring it names the blocker.

WI-120 AC1 reads "Database transactions wrap every authoritative state transition". Nothing in the
repository could answer whether that held, so the criterion could be neither met nor shown unmet. This
records the measurement, and - the part that matters - establishes that closing AC1 is blocked on
WI-121's outbox rather than on anything in AC1 itself.

Measured: four non-test files perform authoritative writes. Two of them (audit/sink.go,
model/store_sql.go, model/identity_store.go) establish a transaction; two do not
(model/identity.go's InsertRevocation, model/journal.go's InsertModel). Both of the latter are
SINGLE-STATEMENT writes, which PostgreSQL already executes atomically. Wrapping either in an explicit
transaction buys nothing on its own. It buys something the moment the transaction also has to carry
that transition's audit record and its outbox row, which is what docs/22 section 4 requires and what
WI-121's outbox exists to hold.

So AC1 is not "two files need BeginTx". It is "the transaction boundary must span mutation, audit
record and outbox row", and that boundary cannot be built until the outbox table exists.

This is a PENDING item describing a measured gap. It is not a completion, and no part of AC1 is
claimed here. WI-196 and WI-197 closed AC2 and AC3; this records why AC1 is the remaining one.

No attestation is asserted anywhere in this file. G0.8 remains REQUIRES_HUMAN_ATTESTATION.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"
EVIDENCE = BRAIN / "evidence.jsonl"

STAMP = "2026-10-04T12:05:00Z"

ARTIFACTS = [
    "scripts/report_tx_coverage.py",
    "scripts/record_wi199_tx_coverage.py",
    "scripts/check_table_ownership.py",
    ".kilo/ecc/project-brain/work-items.json",
]

WI_199 = {
    "id": "WI-199",
    "phase": 3,
    "title": (
        "WI-120's first acceptance criterion could not be measured, and measuring it shows the "
        "remaining gap is the outbox rather than a missing transaction"
    ),
    "status": "PENDING",
    "priority": "high",
    "acceptance_criteria": [
        "Every non-test file performing an authoritative write is enumerated, and whether it "
        "establishes a transaction is stated for each",
        "Each write path that does not establish a transaction is identified by name and by the "
        "query it calls, so the gap is a list rather than an adjective",
        "For each such path, whether the missing transaction is a defect on its own is determined "
        "rather than assumed",
        "The criterion that actually governs the transaction boundary is identified in the "
        "specification, and the work item whose absence blocks it is named",
        "The measurement is reproducible from the committed tree",
    ],
    "source": (
        "Immediately after WI-197 closed WI-120's second and third criteria with a gate, the first "
        "criterion was the only one left and there was no way to check it. Asking whether it held "
        "required reading every write path by hand, and the same question had been unanswerable since "
        "WI-120 was written."
    ),
    "reproduction": (
        "There was no command in the repository that answered this, which is the finding. "
        "`python scripts/report_tx_coverage.py` now does: it imports "
        "scripts/check_table_ownership.py - which already parses every `-- name:` query, already "
        "decides which are mutating, and already resolves each one's calling package - and adds one "
        "regex for BeginTx, WithTx or sql.Tx per calling file. It reports 10 mutating queries, 5 "
        "non-test files writing, 3 establishing a transaction and 2 not. The ownership work is what "
        "made the answer cheap; neither measurement existed before it."
    ),
    "notes": (
        "Five non-test files perform authoritative writes, and three of them establish a transaction: "
        "audit/sink.go, model/identity_store.go and model/store_sql.go. Two do not: model/identity.go "
        "(InsertRevocation) and model/journal.go (InsertModel).\n\n"
        "Both of the latter are single-statement writes, so PostgreSQL already executes them "
        "atomically and an explicit BEGIN/COMMIT around either changes nothing on its own. That is the "
        "part worth recording, because the obvious reading of AC1 - 'these two files lack BeginTx, add "
        "it' - produces a diff and no safety. The transaction earns its existence only when it has to "
        "carry more than the mutation: docs/22 section 4 requires the authoritative audit stream to be "
        "written transactionally with the business mutation, and WI-117 AC4 is the same requirement "
        "seen from the audit side. That makes the boundary mutation + audit record + outbox row, and "
        "the outbox row does not exist - it is WI-121, which is PENDING and gated on WI-120.\n\n"
        "So AC1 is blocked on WI-121 while nominally being the thing WI-121 waits for. That circularity "
        "is real and is not resolved by wrapping two single statements in BEGIN/COMMIT: doing so would "
        "make the criterion read as satisfied while leaving the boundary that actually matters "
        "unbuilt. Breaking it requires the outbox table, and the architect's WI-117 assessment "
        "already rejected the alternative - building a second buffering path inside WI-117 - on the "
        "grounds that it creates the two-writers problem the package exists to prevent.\n\n"
        "This item stays PENDING and claims nothing. Its value is that AC1 is now a two-line list "
        "instead of an aspiration, and the next person to pick it up learns from the measurement that "
        "the work is schema work, not a BeginTx audit."
    ),
    "dependencies": ["WI-120", "WI-121"],
    "evidence_ref": [],
}

FIELDS = (
    "id",
    "phase",
    "title",
    "status",
    "priority",
    "acceptance_criteria",
    "source",
    "reproduction",
    "notes",
    "dependencies",
    "evidence_ref",
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

    existing = by_id.get(WI_199["id"])
    if existing is None:
        items.append(WI_199)
        changed = True
        print(f"recorded {WI_199['id']}")
    elif existing != WI_199:
        items[items.index(existing)] = WI_199
        changed = True
        print(f"updated {WI_199['id']}")
    else:
        changed = False
        print(f"unchanged: {WI_199['id']}")

    if changed:
        ITEMS.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        _write_records(_read_records())

    print("WI-199 records a measurement and asserts no evidence of its own")
    return changed


if __name__ == "__main__":
    main()
