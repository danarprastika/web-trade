"""One-off: correct two now-stale statements in WI-141's completion note.

Both sentences became false through work done after the note was written, and a completion note
is the part of a work item a human reads first, so leaving them would put the wrong information
closest to the reader.

The first is the graceful-shutdown caveat. The note said the SIGTERM drain was "not proven by
test on Windows ... exercised only by an operator's actual shutdown". That was true when written
and is no longer. The drain is now proven on every platform: serve() takes its interrupt channel
as a parameter, which lets a test drive the drain directly with a real TCP listener and a real
HTTP request, so the property is exercised without depending on a signal being deliverable. Three
tests in services/control-plane/cmd/control-plane/main_test.go cover the in-flight request
completing after the interrupt, the shutdown deadline being honoured, and a failed listener being
reported as an unexpected stop. The behaviour under test is unchanged production code; the
extraction that made it reachable is a pure refactor.

The second is a pointer to EV-064. EV-062 and EV-063 each state that the integration suite
passed, and that statement is false: both runs set TEST_DATABASE_URL while the harness reads
DATABASE_URL, so all seventeen tests skipped and go test still printed ok and exited 0. The suite
is 17 passed, 0 failed, 0 skipped against a live database. The note has to say so, because a
reader who trusts EV-062's summary would otherwise believe the integration suite was verified
when it was not.

The script refuses to act unless the exact stale text is present, because a replacement keyed on
a fragment that happens to match elsewhere would corrupt a governance record instead of fixing
one. It re-serialises in HEAD's style and verifies that the only field that changed is the note.

Idempotent, written without a BOM.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / ".kilo" / "ecc" / "project-brain" / "work-items.json"

STALE_DRAIN = (
    "And the graceful SIGTERM drain is not proven by test on Windows, where os.Process.Signal "
    "does not deliver os.Interrupt to another process; it is exercised only by an operator's "
    "actual shutdown."
)

REPLACEMENT_DRAIN = (
    "The graceful shutdown drain was, when this note was first written, unproven on Windows, where "
    "os.Process.Signal does not deliver os.Interrupt to another process, and was exercised only by "
    "an operator's actual shutdown. That limit no longer holds. serve() now takes its interrupt "
    "channel as a parameter, so a test can drive the drain directly rather than signalling another "
    "process, and the drain is proven on every platform: an in-flight request is still answered "
    "after the interrupt and is answered completely rather than truncated, new requests are "
    "refused, the shutdown deadline is honoured instead of waiting on a stuck handler, and a "
    "failed listener is reported as an unexpected stop with exit 1. The tests are in "
    "services/control-plane/cmd/control-plane/main_test.go, they exercise a real listener and a "
    "real HTTP request, and the extraction that made them reachable changed no production "
    "behaviour. The tests were themselves mutation-checked: replacing the graceful Shutdown with a "
    "hard Close fails two of them."
)

STALE_EV062 = (
    "The earlier correction stands and is not repeated: WI-141 is a G5 item, G4 belongs to "
    "WI-140, and the stale 'human G4 review' phrasing in this note and in EV-053 through EV-056 was "
    "corrected by EV-057 because the evidence log is append-only."
)

REPLACEMENT_EV062 = (
    STALE_EV062
    + " One correction supersedes part of EV-062 and EV-063 rather than their conclusions: both "
    "state that the integration suite passed, and it did not run. Both were invoked with "
    "TEST_DATABASE_URL set while the harness in integration/harness_test.go reads DATABASE_URL, so "
    "every test took its skip branch, and go test printed ok and exited 0 over seventeen skips. The "
    "suite against a live PostgreSQL 17.11 is 17 passed, 0 failed, 0 skipped, so G5.7's conclusion "
    "stands and only the description of the run was wrong; EV-064 records the correction, because "
    "the ledger is append-only and a quiet rewrite would be indistinguishable from the error it "
    "corrects. The CI integration job now fails loudly if DATABASE_URL is absent or the database "
    "is unreachable, so the invariant the harness comment had been asserting in prose is enforced."
)


def main() -> bool:
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    item = next(i for i in items if i["id"] == "WI-141")

    note = item.get("completion_note") or ""

    for stale, replacement, label in (
        (STALE_DRAIN, REPLACEMENT_DRAIN, "graceful-drain caveat"),
        (STALE_EV062, REPLACEMENT_EV062, "EV-064 correction pointer"),
    ):
        if replacement in note:
            print(f"unchanged: {label} already corrected")
            continue
        count = note.count(stale)
        if count != 1:
            print(f"refusing to act on {label}: found {count} occurrences of the exact stale "
                  "text, expected exactly 1. A governance record is not edited on a guess.")
            return False
        note = note.replace(stale, replacement)
        print(f"corrected: {label}")

    if note == (item.get("completion_note") or ""):
        print("unchanged: completion_note already correct")
        return False

    before = {i["id"]: dict(i) for i in items}
    item["completion_note"] = note

    payload = json.dumps(data, ensure_ascii=True, indent=2) + "\n"
    with io.open(ITEMS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)

    # The write is only trustworthy if the round trip changed nothing but the note.
    reloaded = json.loads(ITEMS.read_text(encoding="utf-8"))
    re_items = reloaded["items"] if isinstance(reloaded, dict) and "items" in reloaded else reloaded
    after = {i["id"]: dict(i) for i in re_items}
    if set(before) != set(after):
        print("FAILED: the item set changed during the write")
        return False
    for key in before:
        if key == "WI-141":
            differing = [f for f in before[key] if before[key][f] != after[key][f]]
            if differing != ["completion_note"]:
                print(f"FAILED: WI-141 fields changed: {differing}")
                return False
        elif before[key] != after[key]:
            print(f"FAILED: {key} changed unexpectedly")
            return False
    print("verified: completion_note is the only field that changed")
    return True


if __name__ == "__main__":
    main()
