"""Record EV-079: WI-177 - the pinned Go toolchain carried seven reachable standard-library CVEs.

Idempotent, append-only, written without a BOM.
"""

import io
import json
import pathlib

BRAIN = pathlib.Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"

EVIDENCE_ID = "EV-079"
STAMP = "2026-10-03T12:27:16Z"
WORK_ITEM = "WI-177"

CLAIM = (
    "The Go toolchain is pinned at go1.26.8, and govulncheck reports no reachable vulnerability in "
    "any of the six modules. The seven standard-library findings that were open at 1.26.2 are "
    "closed, and they were closed by the pinned toolchain itself rather than by any dependency."
)

METHOD = (
    "The bump was chosen by reading what was actually reported rather than by taking the newest "
    "release. govulncheck v1.8.0 against the tree at 1.26.2 named seven reachable vulnerabilities, "
    "all in the Go standard library: GO-2026-6090 and GO-2026-5856 (crypto/tls), GO-2026-6089 "
    "(net/http), GO-2026-5972 (encoding/asn1), GO-2026-5039 (net/textproto), GO-2026-5037 "
    "(crypto/x509) and GO-2026-4971 (net).\n\n"
    "Every one was in the pinned toolchain and none was attributed to a dependency. That is worth "
    "stating precisely rather than loosely, because the workspace is not dependency-free and an "
    "earlier draft of this record said it was. Its only external Go dependency is "
    "github.com/lib/pq v1.10.9, marked // indirect in services/control-plane/go.mod and pinned in "
    "go.sum; the other five modules require nothing beyond workspace-local modules resolved by "
    "`replace`. govulncheck reported nothing against lib/pq in either direction - it named seven "
    "findings and every one was standard library. So the finding set was entirely the toolchain, "
    "not because there was nothing to find in a dependency, but because the one dependency had none.\n\n"
    "1.26.8 was selected over 1.27 deliberately. docs/00 requires an ADR for a toolchain change; a "
    "patch within a supported release line is not the change that rule is about, and moving to a "
    "new minor line would pull in language and standard-library changes that have nothing to do "
    "with closing these seven findings. 1.26.8 is the newest patch of the still-supported 1.26 "
    "line, and it is beyond 1.26.6, where the highest of the seven is fixed.\n\n"
    "The pin had to move in eight places, not one. toolchain/versions.env is the single source of "
    "truth, the CI workflow's GO_VERSION duplicates it, and the duplication is deliberate - the "
    "toolchain job asserts the two agree so it cannot rot silently. The six go.mod files and go.work "
    "each carry their own go directive. go.work was the one that was easy to miss and would have "
    "broken the build on its own: a workspace whose go directive is lower than a module's is "
    "rejected outright, so leaving it at 1.26.2 while the modules moved to 1.26.8 fails the build "
    "rather than degrading quietly.\n\n"
    "Verification was run at the new version rather than assumed from the pin: gofmt -l, go vet, go "
    "build and go test across all six modules, go vet -tags=integration, go test -race on the "
    "control-plane, and the integration package against a live PostgreSQL. govulncheck was then "
    "re-run per module at 1.26.8."
)

RESULT = (
    "All six modules at go1.26.8: gofmt clean, go vet exit 0, go build exit 0, go test -count=1 "
    "exit 0 (contracts/go, control-plane's twelve packages, risk-engine, oms; reconciliation and "
    "venues report no test files). go test -race -count=1 clean across the control-plane. go vet "
    "-tags=integration exit 0. The integration package against postgres://webtrade:webtrade@"
    "localhost:55440/webtrade_test passed in 18.363s.\n\n"
    "govulncheck per module at 1.26.8: 'No vulnerabilities found.' for all six. The seven "
    "standard-library findings at 1.26.2 are gone.\n\n"
    "The local toolchain confirmed the pin is live rather than decorative: `go version` reported "
    "go1.26.2 at the start of the work and go1.26.8 after the modules were repinned, because "
    "GOTOOLCHAIN=auto fetched the version the modules require. That is the same path CI takes, "
    "except that CI installs the pinned version explicitly through actions/setup-go.\n\n"
    "scripts/verify_toolchain.py passes with 14 checks."
)

DEFECT_FOUND_AND_FIXED = (
    "1. toolchain/versions.env pinned GO_VERSION=1.26.2, a version with seven reachable "
    "standard-library vulnerabilities, while the repository presented it as a verified baseline.\n"
    "2. go.work was found still at `go 1.26.2` after the six go.mod files had been repinned. This "
    "was not a cosmetic leftover: a go.work whose go directive is below a module's is rejected, so "
    "the workspace would have failed to build. It was caught by reading the build rather than by "
    "assuming the search-and-replace had been complete."
)

SIGNIFICANCE = (
    "The interesting property is that the vulnerable component was the pin itself. The usual reason "
    "to run a dependency scan is a transitive package nobody chose directly, and here the workspace's "
    "entire external surface is one indirect module - github.com/lib/pq v1.10.9 - while all seven "
    "findings sat in the Go standard library that the version string selects. A scan of manifests "
    "alone would have had nothing to say about any of it: scripts/verify_toolchain.py can confirm "
    "lib/pq is an exact tagged pin, and that check was green the whole time the toolchain carried "
    "seven reachable CVEs. The gate that should have found this one reads manifests, and the gate "
    "that would find it reads the toolchain. Both were 'passing'.\n\n"
    "The second lesson is about the pin's shape. The version lives in eight files because the "
    "repository deliberately duplicates it rather than reading it at run time, so a mismatch has to "
    "fail loudly. It did - scripts/verify_toolchain.py compares every go directive against "
    "versions.env - but only for the go.mod files. go.work is not covered by that gate, so nothing "
    "in the repository would have caught the workspace being left behind, and the build is what "
    "caught it. A gate that checks five of the six places a value appears is a gate that has "
    "decided, without saying so, that the sixth place does not matter."
)

CAVEATS = (
    "The seven findings are reported as fixed at the pinned version. That is a claim about the "
    "vulnerability database govulncheck consults today, not a guarantee about findings published "
    "later against the same code paths. The pin is a point-in-time statement, and the same gate "
    "will report any new entry on its next run.\n\n"
    "govulncheck is reachability-aware, so 'no vulnerabilities found' means no REACHABLE "
    "vulnerability. An unreachable one is not reported and is not claimed to be fixed. This is the "
    "right trade for a blocking gate, and it is a real limit on the strength of the claim.\n\n"
    "Verification ran on this host, go1.26.8 windows/amd64, against a local PostgreSQL 17 container. "
    "The Ubuntu runner installs the same version through actions/setup-go, so the toolchain matches, "
    "but no GitHub runner has executed this tree since the bump.\n\n"
    "NOT DONE and not claimed: no ADR was written, because a patch within a supported release line "
    "is not the toolchain change docs/00 reserves an ADR for. If that reading is wrong, the ADR is "
    "still owed and this entry should not be taken as having settled it."
)

EXCEPTION = (
    "No exception. The pin was the thing filed against and it moved."
)

ARTIFACTS = [
    ".kilo/ecc/project-brain/evidence.jsonl",
    ".kilo/ecc/project-brain/work-items.json",
    "toolchain/versions.env",
    "go.work",
    ".github/workflows/ci.yml",
    "scripts/record_ev079.py",
]

SUPERSEDES = []


def record() -> bool:
    store = BRAIN / "evidence.jsonl"

    line = json.dumps(
        {
            "schema": "ecc.project-brain/evidence/v7",
            "evidence_id": EVIDENCE_ID,
            "recorded_at": STAMP,
            "recorded_by": "team-lead",
            "work_item": WORK_ITEM,
            "claim": CLAIM,
            "status": "RESOLVED",
            "method": METHOD,
            "result": RESULT,
            "defect_found_and_fixed": DEFECT_FOUND_AND_FIXED,
            "significance": SIGNIFICANCE,
            "caveats": CAVEATS,
            "exception": EXCEPTION,
            "artifacts": ARTIFACTS,
            "supersedes": SUPERSEDES,
        },
        ensure_ascii=False,
    )

    if store.exists():
        for existing in store.read_text(encoding="utf-8").splitlines():
            if existing.strip() and json.loads(existing).get("evidence_id") == EVIDENCE_ID:
                print("unchanged: " + EVIDENCE_ID + " already recorded")
                return False

    with io.open(store, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    print("recorded " + EVIDENCE_ID)
    return True


if __name__ == "__main__":
    record()