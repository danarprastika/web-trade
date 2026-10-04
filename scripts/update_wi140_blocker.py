"""Update WI-140: the G4 report it was blocked on now exists, and only the reviewer is outstanding.

WI-140's blocker said two G4 report fields were outstanding: a named reviewer, and a commit that did
not contain the work. Both were true when it was written. The commit half stopped being true when the
platform was committed; the report half stopped being true when scripts/verify_gate_g4.py was built,
because until then there was nothing a reviewer could read - WI-140 was waiting on a human signature
for a document no mechanism produced, which is the same defect as WI-196 and WI-197 with a signature
attached.

The gate now measures all four docs/11 G4 criteria mechanically and writes a report. Four of four
pass. The gate is registered in scripts/run_gates.py, so it runs with every other gate, and
scripts/prove_gate_g4_detects.py shows each of the four criteria failing when it should - without
which a 4/4 pass is indistinguishable from a gate that cannot fail.

WI-140 stays BLOCKED. The reviewer half is unchanged and is now the whole of what remains.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
ITEMS = BRAIN / "work-items.json"

STAMP = "2026-10-04T12:55:00Z"

BLOCKER = (
    "CORRECTED 2026-10-04, later the same day: both halves of the original blocker have been "
    "addressed except the one that cannot be. The commit half stopped being true when the platform "
    "was committed and pushed; the repository now carries the work, so a reviewer has a real diff. "
    "The report half stopped being true when scripts/verify_gate_g4.py was written: G4 previously "
    "had no gate at all, so WI-140 was blocked on a human signature for a document that no "
    "mechanism could produce.\n\n"
    "The gate now measures all four docs/11 G4 criteria as computations rather than assertions, and "
    "writes .kilo/ecc/project-brain/evidence/wi-140/G4-gate-report.{json,md}: datasets versioned "
    "(content addressing in both directions - identical content fingerprints identically across two "
    "independent constructions, altered content does not, and the registry returns each dataset under "
    "its own fingerprint); backtests deterministic (two isolated interpreters produce identical "
    "result and artifact digests for the same dataset, strategy and seed); artifacts reproducible "
    "(two builds of identical inputs agree, and altering the evaluation report changes the digest, so "
    "the digest tracks content rather than being constant); and no research worker has financial "
    "authority (the workers' own authority-boundary suite, which asserts the absence of network, "
    "database, process and credential capability and exact dependency pinning). Four of four PASS.\n\n"
    "The gate is registered in scripts/run_gates.py as gate-g4, so the battery is 16 of 16, and "
    "scripts/prove_gate_g4_detects.py shows each criterion failing when it should - a constant "
    "fingerprint, a strategy that varies between processes, a constant artifact digest, and a missing "
    "authority suite are each shown refused. Without that, a 4/4 pass would be indistinguishable from "
    "a gate that cannot fail, which is the defect this repository has now recorded repeatedly.\n\n"
    "What remains is unchanged and is the whole of the blocker: docs/11 requires a named human "
    "reviewer in every gate report, and an automated agent recording itself as that reviewer would "
    "satisfy the field and none of its purpose. The mechanism that records a genuine attestation is "
    "scripts/attestation.py, which binds it to a digest of the report and to a named commit, so it "
    "goes STALE the moment either moves and the gate refuses again. It is recorded as OUTSTANDING and "
    "no attestation exists in this commit."
)


def main() -> bool:
    doc = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = doc["items"]
    index = next(i for i, item in enumerate(items) if item["id"] == "WI-140")
    if items[index].get("blocker") == BLOCKER:
        print("unchanged: WI-140")
        return False
    items[index]["blocker"] = BLOCKER
    ITEMS.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"updated WI-140 blocker at {STAMP}")
    return True


if __name__ == "__main__":
    main()