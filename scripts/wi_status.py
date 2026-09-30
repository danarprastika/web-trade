"""One-off: summarise work-item status and list the actionable ones.

Read-only. Written as a file because the shell mangles multi-line ``python -c`` payloads, and
the same query is worth re-running as items move between states.
"""

from __future__ import annotations

import collections
import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"


def main() -> int:
    doc = json.loads(io.open(BRAIN / "work-items.json", encoding="utf-8").read())
    items = doc["items"]
    counts = collections.Counter(i["status"] for i in items)
    print(f"total items: {len(items)}")
    for status, count in sorted(counts.items()):
        print(f"  {status:22} {count}")

    actionable = ("PENDING", "IN_PROGRESS", "NOT_STARTED", "PENDING_ATTESTATION")
    print("\n--- actionable ---")
    for item in items:
        if item["status"] in actionable:
            print(f"  {item['id']:8} {item.get('gate', '-'):6} {item['title'][:60]}")

    print("\n--- blocked ---")
    for item in items:
        if "BLOCKED" in item["status"]:
            print(f"  {item['id']:8} {item['status']:22} {item['title'][:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
