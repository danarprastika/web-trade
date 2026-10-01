"""One-off: compare work-items.json against HEAD, field by field, and report real differences.

Needed because record_wi141_g5_pass.py rewrote the whole file with json.dumps, which can change
serialisation style - ASCII escapes versus literal UTF-8 - across every work item. A diff full of
those is noise that hides the three fields actually intended to change, and a reviewer cannot tell
which is which by reading it.

This script answers one question: is the current file semantically equal to HEAD apart from the
fields this session meant to touch? It compares parsed values, not bytes.

Read-only. Writes nothing.

    python scripts/compare_work_items_to_head.py [path...]
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS_REL = ".kilo/ecc/project-brain/work-items.json"

# The fields intended to differ from HEAD, with why each one changed.
#
# WI-141: this session. The G5 verdict became PASS, so the REMAINING list, the completion note
# and the evidence references all had to change.
#
# WI-117: earlier in this same effort, recorded by EV-044. That record found WI-117's fourth
# acceptance criterion - bounded durable buffering that blocks sensitive operations before
# evidence can be lost - is not implemented, so the item's COMPLETED status overstated the state
# and was reopened. The note, the blocker, the results and the two added evidence references are
# that correction, not drift.
EXPECTED = {
    ("WI-141", "partial_results"),
    ("WI-141", "completion_note"),
    ("WI-141", "evidence_ref"),
    ("WI-117", "status"),
    ("WI-117", "blocker"),
    ("WI-117", "completion_note"),
    ("WI-117", "partial_results"),
    ("WI-117", "evidence_ref"),
}


def head_version(rel: str) -> dict | None:
    """Return the committed version of rel, or None if it is untracked."""
    try:
        raw = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    return json.loads(raw.decode("utf-8"))


def index_of(data):
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    return {i["id"]: i for i in items}


def diff_fields(old: dict, new: dict) -> list[tuple[str, str]]:
    """Return (item_id, field) pairs whose values differ, plus synthetic ids for add/remove."""
    out: list[tuple[str, str]] = []
    old_items, new_items = index_of(old), index_of(new)

    for item_id in sorted(set(old_items) | set(new_items)):
        if item_id not in new_items:
            out.append((item_id, "<REMOVED>"))
            continue
        if item_id not in old_items:
            out.append((item_id, "<ADDED>"))
            continue
        o, n = old_items[item_id], new_items[item_id]
        for field in sorted(set(o) | set(n)):
            if o.get(field) != n.get(field):
                out.append((item_id, field))
    return out


def main() -> int:
    paths = sys.argv[1:] or [ITEMS_REL]

    rc = 0
    for rel in paths:
        head = head_version(rel)
        if head is None:
            print(f"{rel}: not tracked at HEAD; nothing to compare")
            continue

        current = json.loads((ROOT / rel).read_text(encoding="utf-8"))

        raw_head = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode("utf-8")

        if raw_head == (ROOT / rel).read_text(encoding="utf-8"):
            print(f"{rel}: byte-identical to HEAD")
            continue

        differences = diff_fields(head, current)

        # Serialisation style, reported separately so it is never mistaken for a content change.
        head_ascii_escaped = all(ord(ch) < 128 for ch in raw_head)
        current_ascii_escaped = all(ord(ch) < 128 for ch in (ROOT / rel).read_text(encoding="utf-8"))
        style_changed = head_ascii_escaped != current_ascii_escaped

        print(f"{rel}: {len(differences)} field(s) differ from HEAD")
        for item_id, field in differences:
            marker = "expected" if (item_id, field) in EXPECTED else "UNEXPECTED"
            print(f"  [{marker}] {item_id}.{field}")
        if style_changed:
            print(
                "  [style] ASCII-escaped at HEAD: "
                f"{head_ascii_escaped}; now: {current_ascii_escaped}"
            )
            print(
                "  [style] values are equal, so this is json.dumps re-encoding the whole "
                "file, not a content change"
            )

        unexpected = [d for d in differences if d not in EXPECTED]
        if unexpected:
            rc = 1
            print(f"  FAIL: {len(unexpected)} unexpected difference(s)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
