"""Report which work items fail to reference evidence they own."""
import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

rows = [
    json.loads(l)
    for l in (BRAIN / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]
data = json.loads((BRAIN / "work-items.json").read_text(encoding="utf-8"))

owned = {}
for r in rows:
    owned.setdefault(r.get("work_item"), set()).add(r["evidence_id"])

header = "{:<9}{:>7}{:>8}  missing".format("item", "owned", "listed")
print(header)
print("-" * 60)
drifted = 0
for it in data["items"]:
    ow = owned.get(it["id"], set())
    lst = set(it.get("evidence_ref") or [])
    miss = sorted(ow - lst)
    extra = sorted(lst - ow)
    if miss or extra:
        drifted += 1
        print("{:<9}{:>7}{:>8}  missing={} unreferenced={}".format(
            it["id"], len(ow), len(lst), miss, extra))
print("\n{} item(s) drifted".format(drifted))