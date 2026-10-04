"""Correct WI-107's blocker: CI results are observable from this host, and not looking cost 18 hours.

The blocker recorded that "GitHub Actions results are not observable from this host at all, because gh
is unauthenticated for this repository - so no claim here rests on a run's reported outcome." The
conclusion drawn from that - rely on local evidence, never on a run - was the right instinct. The
premise was wrong, and it was wrong in the direction that made looking pointless.

The runs are readable without authentication. GET /repos/{owner}/{repo}/actions/runs returns each run's
head SHA, status and conclusion, and GET .../actions/runs/{id}/jobs adds per-job conclusions and
per-step conclusions. Only the job logs endpoint returns 403 without a token. So the entire signal that
matters - which commit is red, which job, which step - was available the whole time, and the blocker
recorded its absence.

What that absence cost, measured rather than argued: every run from 21330ed onward failed, with 7733977
the last green, spanning eighteen hours and twelve commits. The failure was in the toolchain job's
"Assert the gate's own tests" step, which is `python -m pytest tests/ci -q` - a suite that passed on the
host the whole time. Because that job gates the other eleven (`needs: toolchain`), all eleven were
SKIPPED rather than run, so the red produced no signal anywhere else either. Nothing in the local
evidence contradicted it, because locally it was true.

Two lessons are recorded rather than the conclusion, because both are the kind that recur. First, an
unavailable observation is a reason to change how you observe, not a licence to stop: a second endpoint
answered where the first did not, and the fix was one HTTP call rather than a redesign. Second, the
local suite passing is evidence about the host, not about CI, and the two have now been observed to
diverge - the same 262 tests pass on Linux and on Windows while the runner was failing one of them.

The root cause of the red is fixed in 4bdb45b and recorded there: a mypy invocation running outside the
repository was never reported, because the directory name that would have said so was only interpolated
into two messages, both conditional on some other problem firing first. On Windows /tmp does not exist so
one fired incidentally and the control passed; on the runner /tmp exists and neither fired.

The configuration-only exceptions in the previous text are unchanged and still true: CodeQL extraction
requires the CodeQL tracer, the container image build, SBOM emission and cosign provenance require a
registry and an OIDC identity, and the race detector on the integration suite requires the C toolchain
this host does not have. What changes is the sentence that followed them, which asserted that nothing
here rests on a run's outcome - now corrected to the position that runs are read directly, and that
this item stays IN_PROGRESS until a full run is observed green on all twelve jobs rather than inferred
from the host.

Idempotent.
"""

import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
STORE = BRAIN / "work-items.json"

BLOCKER = (
    "Corrected 2026-10-04. The previous text recorded that GitHub Actions results are not observable "
    "from this host because gh is unauthenticated, and concluded that no claim should rest on a run's "
    "reported outcome. The conclusion was sound and the premise was wrong, in the direction that "
    "removed any reason to look again.\n\n"
    "The runs are readable without authentication. GET /repos/danarprastika/web-trade/actions/runs "
    "returns each run's head SHA, status and conclusion; GET .../actions/runs/{id}/jobs adds per-job and "
    "per-step conclusions. Only the job logs endpoint returns 403 without a token. The signal that "
    "matters - which commit is red, which job, which step - was available throughout.\n\n"
    "Measured, not argued: every run from 21330ed onward failed and 7733977 was the last green, an "
    "eighteen-hour window across twelve commits. The failure sat in the toolchain job's \"Assert the "
    "gate's own tests\" step, which runs `python -m pytest tests/ci -q` - a suite that was passing on "
    "this host the entire time. That job gates the other eleven through `needs: toolchain`, so all "
    "eleven were SKIPPED rather than run, and the red produced no signal anywhere else. Nothing local "
    "contradicted it, because locally it was true.\n\n"
    "Root cause fixed in 4bdb45b: a mypy invocation running outside the repository was never reported, "
    "because the directory name that would have said so was interpolated only into two messages, both "
    "conditional on a different problem firing first. On Windows /tmp does not exist so one fired "
    "incidentally and the control passed; on the runner /tmp exists and neither fired. Worse, a "
    "well-configured directory outside the repository satisfied every per-target check and was reported "
    "as sound - the gate certifying a configuration it never read.\n\n"
    "Two lessons recorded rather than the conclusion, because both recur here. An unavailable "
    "observation is a reason to change how you observe, not a licence to stop; a second endpoint "
    "answered where the first did not. And a passing local suite is evidence about the host, not about "
    "CI - the same 262 tests pass on Linux and on Windows while the runner was failing one of them.\n\n"
    "The configuration-only exceptions are unchanged and still true: CodeQL extraction requires the "
    "CodeQL tracer; container image build, SBOM emission and cosign provenance require a registry and an "
    "OIDC identity; the integration race detector requires the C toolchain this host does not have. "
    "What changes is the closing sentence. Runs are now read directly rather than assumed unavailable, "
    "and this item stays IN_PROGRESS until a full run is observed green on all twelve jobs rather than "
    "inferred from this host."
)


def main() -> bool:
    doc = json.loads(STORE.read_text(encoding="utf-8"))
    items = doc["items"]
    index = next(i for i, item in enumerate(items) if item["id"] == "WI-107")
    if items[index].get("blocker") == BLOCKER:
        print("unchanged: WI-107")
        return False
    items[index]["blocker"] = BLOCKER
    STORE.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print("updated WI-107 blocker")
    return True


if __name__ == "__main__":
    main()