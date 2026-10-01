"""One-off: update WI-141's status notes after G5 passed.

Only text that EV-062 made false is changed: the REMAINING list still described the driver gap,
the write-only stores and the missing entrypoint as open, and the completion note still said the
gate verdict is FAIL and carried an already-corrected G4/G5 error. The acceptance criteria
themselves are untouched, because EV-042 through EV-058 already verified all four and nothing
here changes that.

The status stays IN_PROGRESS. G5 is mechanically PASS and the report's human_reviewer is null;
the project reserves a named human sign-off, and this script does not manufacture one.

Idempotent, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"

WORK_ITEM = "WI-141"

MARKER = " REMAINING, in severity order:"

REMAINING = (
    " REMAINING, in severity order, after EV-062. Closed by this entry: the pinned-driver gap, "
    "where no Go process had ever connected to a database and SQLStore, SQLIdentityStore and "
    "SQLSink kept unproven transaction, commit, isolation-level and mid-commit-error paths - "
    "EV-062 exercises all three against PostgreSQL 17.11 through services/control-plane, and "
    "adopts github.com/lib/pq v1.10.9 without weakening the pinning gate. Closed: the store and "
    "identity store being write-only, so a restarted WorkloadRegistry used to authenticate against "
    "an empty live set and lose the containment widening EV-040 describes - the snapshot reader "
    "and rehydration path are now implemented and proven live, with a revoked identity restored as "
    "revoked and excluded from the live registry. Closed: the missing composition root and the "
    "missing entrypoint, so no code in the repository called the durable assembly - "
    "services/control-plane/cmd/control-plane is now a real process that rebuilds its stack from "
    "a live database on startup, asserted from outside over HTTP. Open, and assigned elsewhere: "
    "there is no cross-store transaction on either the model or the identity path, so a refused "
    "durable write leaves a SUCCEEDED audit record describing a change that did not take effect - "
    "that is WI-120 and WI-121, and G5 does not claim cross-store atomicity. Open, and not "
    "assigned to this item: Authenticate performs no cryptographic verification; Contain does not "
    "itself perform the model's lifecycle quarantine; containment quarantines only the artifacts "
    "named in the declaration; workload_revocations.evidence_ref is free text rather than a "
    "foreign key to a forensic store; and the graceful shutdown path is unproven by test on "
    "Windows. Unchanged for the whole item: Mint and Revoke default to context.Background() for "
    "the existing callers. GATE VERDICT PASS: all seven G5 criteria, G5.7 now mechanically "
    "verified against a running OS process and a live PostgreSQL. The work item remains "
    "IN_PROGRESS pending a named human reviewer."
)

NOTE_ANCHOR = "The item remains IN_PROGRESS because human G4 review is outstanding"

NOTE_TAIL = (
    "EV-062 closes what this note previously described as outstanding. The gate verdict is PASS: "
    "all seven G5 criteria, with G5.7 mechanically verified by "
    "TestARunningProcessRebuildsItsStackFromPostgreSQLOnStartup, which compiles "
    "services/control-plane/cmd/control-plane, seeds a model, an audit trail and a revocation "
    "through the real write paths, runs the binary as a separate OS process, and asserts over "
    "HTTP that it recovered them from PostgreSQL. The entrypoint also fails closed, which is "
    "asserted rather than assumed: a registry that cannot be corroborated against the rehydrated "
    "audit chain produces exit code 2 and nothing listening. Two limits are recorded rather than "
    "smoothed over. The process exposes no write path, because audit records reach storage through "
    "a caller-driven accept-then-export pair that no background loop can substitute for, so "
    "/readyz reports write_path_exposed as false. And the graceful SIGTERM drain is not proven by "
    "test on Windows, where os.Process.Signal does not deliver os.Interrupt to another process; it "
    "is exercised only by an operator's actual shutdown. Cross-store atomicity between a registry "
    "write and its audit record remains WI-120 and WI-121's and is not claimed by this item. The "
    "earlier correction stands and is not repeated: WI-141 is a G5 item, G4 belongs to WI-140, and "
    "the stale 'human G4 review' phrasing in this note and in EV-053 through EV-056 was corrected "
    "by EV-057 because the evidence log is append-only. The item remains IN_PROGRESS because the "
    "G5 report's human_reviewer is null and the project reserves a named human sign-off, not "
    "because G5 evidence is incomplete."
)


def normalise_partial(value):
    """Return partial_results as a string, repairing a character-split value.

    An earlier version of this script iterated the field, which was a plain string, and wrote the
    result back as a list of 3916 single characters. That is a data-corruption bug in the tooling
    rather than a change to any content: joining the list restores the exact original text, and
    this function is what makes the script safe to run against that state as well as a healthy
    one. It is kept rather than dropped because a future reader looking at a list of one-character
    strings in this repository deserves to find why.
    """
    if isinstance(value, list):
        if all(isinstance(e, str) and len(e) == 1 for e in value):
            return "".join(value)
        return value
    return value


def update() -> bool:
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    item = next(i for i in items if i["id"] == WORK_ITEM)

    changed = False

    partial = normalise_partial(item.get("partial_results"))
    if isinstance(partial, str):
        if MARKER in partial:
            head, _, _ = partial.partition(MARKER)
            rebuilt = head + REMAINING
            if rebuilt != partial:
                partial = rebuilt
                changed = True
        item["partial_results"] = partial
    elif isinstance(item.get("partial_results"), list):
        changed = True  # normalisation alone is a change

    note = item.get("completion_note") or ""
    if NOTE_ANCHOR in note:
        note = note.replace(NOTE_ANCHOR, NOTE_TAIL)
        changed = True
    item["completion_note"] = note

    for ref in ("EV-062", "EV-063"):
        if ref not in (item.get("evidence_ref") or []):
            item.setdefault("evidence_ref", []).append(ref)
            changed = True

    if not changed:
        print("unchanged: " + WORK_ITEM + " notes already current")
        return False

    # ensure_ascii=True because that is how HEAD stores this file, and a writer that changes the
    # serialisation re-encodes every non-ASCII character in every work item. The values would be
    # equal and the diff would touch the whole file, burying the three fields that actually
    # changed. restore_work_items_style.py repairs that damage; not causing it is better.
    payload = json.dumps(data, ensure_ascii=True, indent=2) + "\n"
    with io.open(ITEMS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    print("updated " + WORK_ITEM + " notes")
    return True


if __name__ == "__main__":
    update()