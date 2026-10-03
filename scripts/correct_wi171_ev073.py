"""Point WI-171 at EV-073 and record the correction to its own completion results.

WI-171's completed_results as first written included two claims that an independent review
disproved. Evidence is append-only, so the corrections live in EV-073; this entry exists so that
a reader of the work item does not take the superseded claims at face value.

Idempotent.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"


def main() -> bool:
    doc = json.loads(STORE.read_text(encoding="utf-8"))
    wi = {i["id"]: i for i in doc["items"]}["WI-171"]

    wi["evidence_ref"] = ["EV-072", "EV-073"]

    # Two claims in completed_results were disproved by review. Each is corrected in place by
    # pointing at the correction rather than by deleting the sentence, so the record shows that
    # the claim was made and why it did not hold.
    wi["completed_results"] = [
        r
        for r in wi["completed_results"]
        if not r.startswith("The evaluator moved from integration/harness_test.go")
    ]
    wi["completed_results"].insert(
        0,
        "The evaluator moved from integration/harness_test.go - a _test.go file that `go run "
        "./cmd/migrate` never executes - into services/control-plane/migrate/destructive.go as "
        "exported API. CORRECTED BY EV-073: this first claimed the harness and the command "
        "'cannot drift apart'. They could. The harness built its own DestructivePolicy literal "
        "instead of calling IntegrationOptInPolicy, so editing the constructor would have left "
        "the harness untouched while the test asserting on the constructor stayed green. The "
        "harness now delegates.",
    )
    wi["completed_results"] = [
        r
        for r in wi["completed_results"]
        if not r.startswith("The guard applies to unbounded `down` only")
    ]
    wi["completed_results"].insert(
        2,
        "The guard applies to EVERY `down`, bounded or unbounded. CORRECTED BY EV-073: this "
        "first shipped exempting `-to`, on a comment claiming a bound 'does not take the ledger "
        "or the audit schema with it'. It does. DownTo reverts the migrations ABOVE the bound, so "
        "`-to 1` plans versions 4, 3, 2 and runs 0002_audit.sql's down body - "
        "DROP TABLE IF EXISTS audit_records CASCADE - unguarded. `up` and `status` remain "
        "exempt, which is what makes a database inspectable at all.",
    )

    wi["notes"] += (
        "\n\nEV-073 supersedes part of this item. An independent review of the completed change "
        "set found a critical defect in it: the bounded-revert exemption described above, which "
        "was a hole of the same shape as the one WI-171 was raised for. It was certified by the "
        "mutation gate as 'a bounded revert is guarded too' and enshrined by a test as 'a "
        "deliberate asymmetry rather than an oversight' - both green, both describing the defect. "
        "The root cause is that the safety argument rested on a sentence about DownTo that was "
        "never read; DownTo's own doc comment, three files away, says the plan is 'the applied "
        "migrations above version'. All four review findings are fixed and verified."
    )

    out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    with io.open(STORE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(out)

    print("WI-171 corrected; evidence_ref ->", wi["evidence_ref"])
    return True


if __name__ == "__main__":
    main()