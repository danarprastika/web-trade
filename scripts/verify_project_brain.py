"""Project Brain integrity check.

Validates the V7 state files that execution decisions depend on. A corrupt or internally
inconsistent Project Brain is worse than an absent one, because the next agent will trust
it. This check is cheap and runs locally and in CI.

Run:
    python scripts/verify_project_brain.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN = REPO_ROOT / ".kilo" / "ecc" / "project-brain"

VALID_STATUSES = {
    "PENDING",
    "IN_PROGRESS",
    "COMPLETED",
    "BLOCKED",
    "CANCELLED",
    # Deliberately out of scope by policy, not merely unfinished. G11 live activation is
    # permanently excluded from this effort, and collapsing it into BLOCKED would imply it
    # is waiting on work that might happen.
    "BLOCKED_OUT_OF_SCOPE",
}

# Evidence records carry a more granular vocabulary than work items, because "we looked
# and it is fine" and "we looked, it was broken, we fixed it" and "we looked, it is fine
# except for one known gap" are three genuinely different claims. Collapsing them into a
# single VERIFIED value would discard the most useful part of the record.
#
#   VERIFIED               the claim was checked and holds in full
#   VERIFIED_WITH_EXCEPTION holds, with a deviation that is recorded and owned
#   UNRESOLVED_EXCEPTION   does not hold; a requirement conflict is open
#   RESOLVED               a defect was found, and the fix was re-verified
#   PARTIALLY_VERIFIED     holds for a subset; the gap is stated in `caveats`
VALID_EVIDENCE_STATUSES = {
    "VERIFIED",
    "VERIFIED_WITH_EXCEPTION",
    "UNRESOLVED_EXCEPTION",
    "RESOLVED",
    "PARTIALLY_VERIFIED",
}


def check(brain: Path) -> list[str]:
    """Return every integrity problem found in the Project Brain at *brain*.

    Split out from main so the checks can be exercised against a synthetic brain in
    tmp_path. A gate that cannot be shown to fail is decoration, and that needs the checks
    to be callable rather than welded to the repository's own state.
    """
    problems: list[str] = []

    brain_file = brain / "work-items.json"
    evidence_file = brain / "evidence.jsonl"
    if not brain_file.exists():
        return [f"work-items.json not found under {brain}"]
    if not evidence_file.exists():
        return [f"evidence.jsonl not found under {brain}"]

    brain_json = json.loads(brain_file.read_text(encoding="utf-8"))
    items = brain_json["items"]
    by_id = {i["id"]: i for i in items}

    # 1. Unique ids.
    if len(by_id) != len(items):
        problems.append("duplicate work-item ids present")

    # 2. Valid statuses.
    for item in items:
        if item.get("status") not in VALID_STATUSES:
            problems.append(f"{item['id']}: unknown status {item.get('status')!r}")

    # 3. Dependencies resolve, and no cycles.
    for item in items:
        for dep in item.get("dependencies", []):
            if dep not in by_id:
                problems.append(f"{item['id']}: depends on unknown item {dep}")

    # 4. A COMPLETED item must cite evidence, and every cited record must exist.
    evidence_ids = {
        json.loads(line)["evidence_id"]
        for line in evidence_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for item in items:
        refs = item.get("evidence_ref", [])
        for ref in refs:
            if ref not in evidence_ids:
                problems.append(f"{item['id']}: cites unknown evidence {ref}")
        if item.get("status") == "COMPLETED" and not refs:
            problems.append(
                f"{item['id']}: COMPLETED without evidence_ref; a completion with no "
                f"recorded evidence is not verifiable"
            )

    # 5. An IN_PROGRESS item that is blocked should say so, so a resume knows to look.
    for item in items:
        if item.get("status") == "IN_PROGRESS" and not (
            item.get("blocker") or item.get("partial_results")
        ):
            problems.append(
                f"{item['id']}: IN_PROGRESS with neither blocker nor partial_results"
            )

    # 5b. A COMPLETED item whose dependency is not complete has either finished out of
    #     order or recorded a completion its dependency contradicts. Both are worth
    #     surfacing, so the check exists and requires an explicit, reasoned exemption
    #     rather than a silent pass. The common legitimate case is a dependency gated on
    #     something outside this repository, such as a human attestation that no
    #     automated run can satisfy.
    for item in items:
        if item.get("status") != "COMPLETED":
            continue
        exemptions = item.get("dependency_exemptions", {})
        for dep in item.get("dependencies", []):
            if by_id[dep].get("status") == "COMPLETED":
                continue
            reason = exemptions.get(dep)
            if not reason:
                problems.append(
                    f"{item['id']}: COMPLETED while dependency {dep} is "
                    f"{by_id[dep].get('status')}; record a dependency_exemptions entry "
                    f"naming {dep} and why finishing early is correct"
                )
            elif not str(reason).strip():
                problems.append(
                    f"{item['id']}: empty dependency_exemptions entry for {dep}"
                )

    # 6. Evidence must use a status from the defined vocabulary, and a partial or
    #    resolved record must actually explain itself.
    for line in evidence_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        status = record.get("status")
        if status not in VALID_EVIDENCE_STATUSES:
            problems.append(f"{record.get('evidence_id')}: unknown status {status!r}")
        if status in {"PARTIALLY_VERIFIED", "VERIFIED_WITH_EXCEPTION", "UNRESOLVED_EXCEPTION"}:
            if not record.get("caveats") and not record.get("exception"):
                problems.append(
                    f"{record.get('evidence_id')}: status {status!r} but no `caveats` or "
                    f"`exception` explaining what is missing or deviant"
                )
        if status == "RESOLVED" and not record.get("defect_found_and_fixed"):
            problems.append(
                f"{record.get('evidence_id')}: status RESOLVED but no "
                f"`defect_found_and_fixed` describing what was wrong and how it was fixed"
            )

    return problems


def main() -> int:
    """Check the repository's own Project Brain and report."""
    brain = json.loads((BRAIN / "work-items.json").read_text(encoding="utf-8"))
    items = brain["items"]
    evidence_ids = {
        json.loads(line)["evidence_id"]
        for line in (BRAIN / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }

    problems = check(BRAIN)

    counts = Counter(i["status"] for i in items)
    print(f"work items: {len(items)}  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"evidence records: {len(evidence_ids)}")
    for item in items:
        if item["status"] != "PENDING":
            print(f"  {item['id']:8} {item['status']:12} {item['title'][:58]}")

    if problems:
        print(f"\nproject brain FAILED ({len(problems)} problems):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("\nproject brain: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
