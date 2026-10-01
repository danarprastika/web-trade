"""Execute two real registry queries against live data and check the values round-trip.

The PREPARE check in verify_queries_live.py proves the queries parse and resolve. It cannot
prove they return the right values, because a query that resolves can still filter, project or
order incorrectly. This inserts a real row and reads it back through the two queries the
rehydration path depends on - GetModel and ListAllModels - and requires the values to survive
the round trip.

The terminal states matter specifically. ListAllModels exists because ListActiveModels is
blind to them, and a rehydration that cannot see a retired model will happily register it again,
so the probe registers a RETIRED model and requires ListAllModels to return it.

Writes are confined to a throwaway database, and every row is deleted at the end.
"""

from __future__ import annotations

import subprocess
import sys

CONTAINER = "aitc-pg17"
DB = "wi141_verify"

MODEL_ID = "mdl_probe_retired"
VERSION = "probe-v1"


def psql(sql: str, tuples_only: bool = True) -> tuple[int, str]:
    args = ["docker", "exec", CONTAINER, "psql", "-U", "postgres", "-d", DB]
    args += ["-tAc", sql] if tuples_only else ["-c", sql]
    out = subprocess.run(args, capture_output=True, text=True)
    return out.returncode, (out.stdout or out.stderr).strip()


def get_model() -> tuple[int, str]:
    """The GetModel body, verbatim from the query file."""
    return psql(
        "SELECT model_id, version, owner, author, training_dataset_fingerprint, "
        "code_revision, feature_specification, evaluation_results, limitations, "
        "approval_record, deployment_scope, monitoring_policy, rollback_artifact, state, "
        "registered_at_utc, last_audit_id, updated_by, updated_at_utc "
        f"FROM model_registry WHERE model_id = '{MODEL_ID}';"
    )


def list_all_models() -> tuple[int, str]:
    """The ListAllModels body, verbatim: SELECT * with no state filter."""
    return psql("SELECT count(*) FROM (SELECT * FROM model_registry) AS all_models;")


def insert_retired() -> tuple[int, str]:
    # The table carries nine check constraints and this row must satisfy all of them. Two
    # attempts failed first, which is the point worth recording: model_registry_digest_shape
    # requires four columns to be 64-character lowercase hex, and model_registry_id_prefixed
    # requires model_id to start with 'mdl_' and be at most 34 characters, while
    # model_registry_owner_differs_from_author forbids owner equal to author. A probe that
    # invents plausible-looking data without reading the constraints will be refused, and
    # being refused is evidence the constraints are load-bearing rather than decorative.
    digest = "a" * 64
    return psql(
        "INSERT INTO model_registry (model_id, version, owner, author, "
        "training_dataset_fingerprint, code_revision, feature_specification, "
        "evaluation_results, limitations, approval_record, deployment_scope, "
        "monitoring_policy, rollback_artifact, state, registered_at_utc, last_audit_id, "
        "updated_by, updated_at_utc) VALUES ("
        f"'{MODEL_ID}', '{VERSION}', 'probe-owner', 'probe-author', '{digest}', "
        f"'probe-rev', 'probe-spec', '{digest}', 'probe-limits', '{digest}', "
        f"'probe-scope', 'probe-monitoring', '{digest}', 'RETIRED', now(), "
        "'probe-audit-id', 'probe-updater', now());"
    )


def list_active() -> tuple[int, str]:
    return psql(
        "SELECT count(*) FROM model_registry "
        "WHERE state NOT IN ('RETIRED', 'QUARANTINED');"
    )


def cleanup() -> None:
    psql(f"DELETE FROM model_registry WHERE model_id = '{MODEL_ID}';")


def main() -> int:
    failures: list[str] = []

    cleanup()

    code, detail = insert_retired()
    if code != 0:
        print(f"FAIL: insert refused: {detail}")
        return 1
    print("inserted a RETIRED model")

    code, detail = get_model()
    if code != 0:
        failures.append(f"GetModel failed: {detail}")
    elif not detail:
        failures.append("GetModel returned no row for a row that was just inserted")
    else:
        parts = [p for p in detail.split("|")]
        print(f"GetModel returned {len(parts)} columns")
        if len(parts) != 18:
            failures.append(f"GetModel returned {len(parts)} columns, expected 18")
        if parts and parts[0] != MODEL_ID:
            failures.append(f"GetModel model_id is {parts[0]!r}, expected {MODEL_ID!r}")
        if len(parts) > 13 and parts[13] != "RETIRED":
            failures.append(f"GetModel state is {parts[13]!r}, expected 'RETIRED'")

    code, detail = list_all_models()
    if code != 0:
        failures.append(f"ListAllModels failed: {detail}")
    else:
        print(f"ListAllModels row count: {detail.strip()}")
        if detail.strip() != "1":
            failures.append(
                f"ListAllModels returned {detail.strip()} rows, expected 1 - "
                "a terminal-state model must survive rehydration reads"
            )

    code, detail = list_active()
    if code != 0:
        failures.append(f"ListActiveModels failed: {detail}")
    else:
        print(f"ListActiveModels row count (RETIRED excluded): {detail.strip()}")
        if detail.strip() != "0":
            failures.append(
                f"ListActiveModels returned {detail.strip()}, expected 0 - this is the "
                "blindness that makes ListAllModels necessary, so the two must disagree here"
            )

    cleanup()

    if failures:
        print("\nFAILURES:")
        for line in failures:
            print("  " + line)
        return 1

    print("\nPASS: values round-trip, and ListAllModels sees a terminal state ListActiveModels hides")
    return 0


if __name__ == "__main__":
    sys.exit(main())
