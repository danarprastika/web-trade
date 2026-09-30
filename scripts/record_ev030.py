"""One-off: append EV-030 and close WI-108.

Follows the same pattern as scripts/record_ev026.py through record_ev029.py: idempotent,
auditable, and kept in the repository so the Project Brain edit is reproducible rather than an
opaque mutation of state.

It writes JSON without a BOM on purpose. PowerShell 5.1 `Set-Content -Encoding UTF8` adds one,
and a BOM at the start of a JSONL line corrupts the record it introduces.

The defect narrative below is longer than usual for this work item, and deliberately so. The
interesting failures in WI-108 were not in the artifacts: they were in the checks that were
supposed to prove the artifacts, including two checks that reported success while proving
nothing. Recording only "6 checks pass" would misrepresent how much of the green was earned.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / ".kilo" / "ecc" / "project-brain"
EVIDENCE_ID = "EV-030"
STAMP = "2026-09-29T09:55:00Z"

CLAIM = (
    "All three of WI-108's acceptance criteria hold against a running PostgreSQL 17, not merely "
    "on inspection. The compose stack comes up healthy, refuses to start when any credential is "
    "unset, and the whole migration set applies into the dev database as the application role "
    "rather than as the bootstrap superuser. The dev role is refused by the test database and the "
    "test role is refused by the dev database, both by permission denial rather than by a failed "
    "connection, and no database named paper, shadow, or live exists at all. No credential is "
    "written down anywhere in the repository: every secret in the compose file is a required "
    "environment reference, .env is git-ignored and untracked, and .env.example declares each "
    "secret with an empty value."
)

METHOD = (
    "Wrote infra/compose.yaml, a single pinned postgres:17-alpine service published on loopback "
    "only, with all three secrets expressed as ${VAR:?message} so the stack refuses to start "
    "rather than falling back to a default. Wrote "
    "infra/postgres/init/10-environments.sh, which creates one NOSUPERUSER NOCREATEDB "
    "NOCREATEROLE role and one owned database per local environment, revokes CONNECT from "
    "PUBLIC before granting it to the owning role alone, and then proves the isolation by "
    "attempting both cross-environment connections and aborting initialisation if either "
    "succeeds. Wrote scripts/verify_local_env.py, which brings the stack up, replays every "
    "migration up body as the application role over TCP, and asserts the isolation in both "
    "directions. Because the no-credential criterion is a property of the committed tree rather "
    "than of a running container, it is asserted statically in tests/ci/test_local_env.py, which "
    "runs without Docker. Every static check was then mutation-tested: "
    "scripts/mutation_check_local_env.py breaks each of eleven properties in turn, in the real "
    "artifacts, and requires the suite to go red for each. The live check was run end to end, "
    "and all eleven mutations were detected with both files restored byte-for-byte afterwards."
)

RESULT = (
    "Live, against a real PostgreSQL 17 container: all 6 local-environment checks pass. "
    "'compose resolves' passes; 'credentials required' passes and names WEBTRADE_DEV_PASSWORD "
    "when it is removed; 'stack healthy' reports webtrade-postgres-1 healthy; 'migrations "
    "apply' reports 3 migrations applied as web_trade_dev, namely 0001_ledger.sql, "
    "0002_audit.sql, and 0003_authz.sql; 'environments isolated' reports web_trade_dev refused by "
    "web_trade_test and web_trade_test refused by web_trade_dev; 'paper/shadow/live absent' "
    "reports a readable catalog and none of 6 forbidden names present. The server's own log "
    "independently shows two FATAL permission-denied lines during initialisation and "
    "'environment isolation verified: neither dev nor test can reach the other'. Static: "
    "pytest tests/ci is 113 passed, of which 13 are the new local-environment checks. Mutation: "
    "all 11 mutations detected and all files restored byte-for-byte. The mutation set is: "
    "credential given a default password, isolation revoke removed, application role made "
    "superuser, loopback binding widened to all interfaces, paper environment provisioned "
    "locally, isolation failure no longer aborting initialisation, isolation probe result no "
    "longer gating the abort, init directory mounted writable, postgres image unpinned, init "
    "script converted to CRLF, and the LF rule dropped from .gitattributes. The full "
    "repository gate set was not re-run, because this work item adds no Go code and touches no "
    "specification; the earlier 11-of-11 gate result from WI-106 and the 7-of-7 G0 mechanical "
    "verification are unchanged, G0.8 remains REQUIRES_HUMAN_ATTESTATION, and the overall verdict "
    "remains PENDING_HUMAN_ATTESTATION."
)

DEFECTS = (
    "Seven defects were found and fixed. Four were in the artifacts or the harness; three were in "
    "the checks, and those three are the ones worth carrying forward. "
    "(1) The isolation check could prove nothing. check_nonlocal_environments_absent read "
    "pg_database for each forbidden name and treated a result set that did not contain '1' as "
    "proof the database was absent. A connection failure also produces a result set containing no "
    "1, so the check passed while never having reached PostgreSQL at all, and it did so on the "
    "first run against a stack where every role login was failing. The catalog is now probed for "
    "reachability first, and each catalog query must itself succeed. This is the same failure "
    "class as the negative-vector suite recorded in EV-028: a test that cannot distinguish 'the "
    "control worked' from 'the control was never consulted' will report success in both cases. "
    "(2) Two mutations were reported caught for the wrong reason. The loopback-binding test "
    "scanned compose for lines matching an IP-and-port shape, so a binding widened to all "
    "interfaces, which contains no literal IP, matched nothing and was skipped, while the ports "
    "block itself failed to parse because a comment line inside it broke the run of list items. "
    "The mutation was recorded as CAUGHT because the suite went red, but the suite was already "
    "red on the unmutated file; running the whole file and finding two of eleven tests failing "
    "on the real artifacts is what exposed it. The block is now parsed line by line with quotes "
    "stripped, and a mutation is only accepted as caught when the file passes beforehand. A "
    "related weakness was in the isolation-assertion test: requiring that some 'exit 1' existed "
    "was satisfied by the second direction alone, so deleting the first direction's abort still "
    "passed, and replacing its condition with 'if false' left both the probe and the abort in "
    "place while making the check permanently pass. Each failure message must now be followed by "
    "an abort, and each captured probe result must be tested in a condition. "
    "(3) The mutation harness damaged the artifact it was checking. It read and wrote the shell "
    "script in text mode, and Path.write_text on Windows translates every LF to CRLF. A shell "
    "script with CRLF is not a cosmetic problem: /bin/sh reads the carriage return as part of "
    "the command, so the script aborts before creating any role, the container reports itself "
    "unhealthy, and the cause is nowhere near the symptom. The harness reported all mutations "
    "detected and every static test kept passing while the live stack was broken. The harness now "
    "works in bytes, verifies the restore byte-for-byte, and two tests plus a .gitattributes rule "
    "make the property permanent. A related failure: one run of the harness was killed by a "
    "command timeout, which left a mutation in the committed file, and the isolation revoke was "
    "absent from the init script until it was restored and re-verified. That is a real hazard of "
    "a harness that edits the repository, and the byte-for-byte restore check is what makes the "
    "damage visible rather than silent. "
    "Four harness bugs were also fixed, each of which produced a misleading error: "
    "docker run -e 'PGPASSWORD=$PGPASSWORD' sets the container variable to the literal seven-"
    "character string '$PGPASSWORD', so every connection failed with a password error that looked "
    "like a broken role; a psql client container on the compose network connecting to 127.0.0.1 "
    "reaches itself rather than the host, so the published port must be reached through "
    "host.docker.internal with --add-host host.docker.internal:host-gateway for Linux parity; "
    "--interactive is a docker run flag and was being passed to psql because it followed the "
    "image name; and make_environment was called with four arguments while reading a global for "
    "its label, which happened to work only because the global was set from the script's own "
    "unset positional parameter."
)

SIGNIFICANCE = (
    "The three check defects are one lesson rather than three. A verification result records that "
    "something passed, and it carries no record of what would have made it fail. Two of these "
    "checks reported success, or reported a caught mutation, for reasons unrelated to the property "
    "they claim to test, and in both cases the artifact was fine and the check was hollow. The "
    "practice that surfaced them was cheap and worth keeping: after adding a mutation harness, run "
    "the test file on the unmodified artifacts and confirm it is green before believing any "
    "mutation result, and treat a mutation that cannot be run as inconclusive rather than as "
    "undetected. Separately, a harness that edits the repository in place is a hazard to the "
    "repository and not only to itself; working in bytes and proving the restore is what keeps "
    "such a tool from becoming the reason a control silently disappeared."
)

CAVEATS = (
    "Four limitations are worth stating plainly. First, isolation is established per database at "
    "initialisation, by revoking CONNECT from PUBLIC on web_trade_dev and web_trade_test "
    "specifically. It is not a server-wide default: a database created later by any other means "
    "would carry PostgreSQL's default grant to PUBLIC and would be reachable by every role. If "
    "isolation is ever meant to hold for databases this script does not create, it belongs in a "
    "template or an ALTER ROLE SET default_privileges, not here. Second, the harness applies the "
    "migrations through psql rather than through the Go migrate package, so this is not an "
    "independent confirmation of the Go runner; WI-106 already rehearsed that path up, down, and "
    "up again. Third, the harness generates throwaway passwords into its own process environment "
    "when none are set, which is what makes it runnable with no .env and which is also why it is "
    "not a test of the developer's real .env; that remains covered only by the static checks and by "
    "the documented contract. Fourth, the default run destroys the local volume, deliberately, "
    "because /docker-entrypoint-initdb.d runs only against an empty data directory and a harness "
    "that inherits a previous run's volume reports results that depend on what that run left "
    "behind; --no-fresh reuses it, and the live check has no TLS, no backup or restore "
    "verification, and no paper, shadow, or live environment by design. No Go PostgreSQL driver is "
    "involved; that remains parked from WI-106 for the pinning reason recorded there. No live "
    "venue connectivity, production credential, or Terraform was touched, docs/ is untouched and "
    "all manifest digests still verify, G0.8 human attestation remains outstanding, and no commit "
    "has been made."
)

ARTIFACTS = [
    "infra/compose.yaml",
    "infra/postgres/init/10-environments.sh",
    "scripts/verify_local_env.py",
    "scripts/mutation_check_local_env.py",
    "tests/ci/test_local_env.py",
    ".env.example",
    ".gitattributes",
]

RECORD = {
    "schema": "ecc.project-brain/evidence/v7",
    "evidence_id": EVIDENCE_ID,
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-108",
    "claim": CLAIM,
    "status": "RESOLVED",
    "method": METHOD,
    "result": RESULT,
    "defect_found_and_fixed": DEFECTS,
    "significance": SIGNIFICANCE,
    "limitations": CAVEATS,
    "artifacts": ARTIFACTS,
    "supersedes": [],
}

EVENT = {
    "schema": "ecc.project-brain/event/v7",
    "event_id": "EVT-WI-108-COMPLETED",
    "recorded_at": STAMP,
    "recorded_by": "team-lead",
    "work_item": "WI-108",
    "event": "work_item_completed",
    "status": "COMPLETED",
    "evidence_ref": EVIDENCE_ID,
    "summary": (
        "WI-108 Local development environment completed. All 3 acceptance criteria hold against "
        "a running PostgreSQL 17: the stack comes up healthy and refuses to start without "
        "credentials, the full migration set applies as the non-superuser application role, dev "
        "and test are refused by each other by permission denial in both directions, and no "
        "paper, shadow, or live database exists. 13 static checks in tests/ci and 11 mutations, "
        "all detected, files restored byte-for-byte. Seven defects fixed, three of them in the "
        "checks themselves, including an isolation check that passed without ever reaching the "
        "database and two mutations reported caught for reasons unrelated to the property tested."
    ),
}


def append_jsonl(path: Path, record: dict) -> None:
    with io.open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def main() -> int:
    evidence_path = BRAIN / "evidence.jsonl"
    existing = [
        json.loads(line)
        for line in io.open(evidence_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(r.get("evidence_id") == EVIDENCE_ID for r in existing):
        print(f"{EVIDENCE_ID} already recorded; nothing appended.")
    else:
        append_jsonl(evidence_path, RECORD)
        print(f"appended {EVIDENCE_ID} to {evidence_path.name}")

    work_path = BRAIN / "work-items.json"
    doc = json.loads(io.open(work_path, encoding="utf-8").read())
    changed = False
    for item in doc["items"]:
        if item["id"] == "WI-108":
            # evidence_ref is a list: the gate iterates it, so a bare string would be
            # read one character at a time as several unknown evidence ids.
            if item.get("status") != "COMPLETED" or item.get("evidence_ref") != [EVIDENCE_ID]:
                item["status"] = "COMPLETED"
                item["evidence_ref"] = [EVIDENCE_ID]
                item["completed_at"] = STAMP
                changed = True
    if changed:
        io.open(work_path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
        )
        print("WI-108 -> COMPLETED")
    else:
        print("WI-108 already COMPLETED")

    events_path = BRAIN / "events.jsonl"
    seen = [
        json.loads(line)
        for line in io.open(events_path, encoding="utf-8").read().splitlines()
        if line.strip()
    ]
    if any(e.get("event_id") == EVENT["event_id"] for e in seen):
        print(f"{EVENT['event_id']} already recorded; nothing appended.")
    else:
        append_jsonl(events_path, EVENT)
        print(f"appended {EVENT['event_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
