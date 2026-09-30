"""Tests for the artifact boundary: reproducibility, lineage, and non-authority.

docs/22 section 5 requires a decision to link dataset fingerprint, feature definition version,
code revision, model artifact digest, evaluation report, reviewer, approval, and deployment
scope. Two of those are deliberately absent from this worker, and the tests below assert their
absence structurally rather than trusting the prose: a field that does not exist cannot be
filled in by a later stage, whereas a field left empty can be.

The digest tests are written so that a digest computed over the wrong content fails them. A test
that only checked "two identical builds agree" would pass even if the digest were a constant.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass

import pytest
from conftest import at, bar
from webtrade_research.dataset import Dataset, DatasetError

from webtrade_backtest.artifacts import PROPOSED, ArtifactError, BacktestArtifact, build_artifact
from webtrade_backtest.harness import (
    BacktestParams,
    BacktestResult,
    Decision,
    DecisionRecord,
    LookaheadError,
    MarketView,
    run_backtest,
)

LINEAGE = {
    "code_revision": "0f1e2d3c4b5a69788796a5b4c3d2e1f001122334",
    "feature_specification_version": "features/3.1.0",
    "evaluation_report": "reports/eval-2026-01-05.md",
}


@dataclass
class AlwaysBuy:
    def decide(self, view: MarketView) -> Decision:
        return Decision(as_of=view.as_of, side="buy", quantity="1", reason="always")


def _run(dataset: Dataset, *, seed: int = 1) -> BacktestResult:
    return run_backtest(
        dataset,
        AlwaysBuy(),
        BacktestParams(seed=seed, start=at(0), end=at(60)),
        strategy_name="always-buy",
    )


def _artifact(dataset: Dataset, **overrides: object) -> BacktestArtifact:
    """Build an artifact, with any lineage field overridable for the digest tests."""
    result = overrides.pop("result", None)
    return build_artifact(
        result=result if isinstance(result, BacktestResult) else _run(dataset),
        dataset=dataset,
        code_revision=str(overrides.pop("code_revision", LINEAGE["code_revision"])),
        feature_specification_version=str(
            overrides.pop("feature_specification_version", LINEAGE["feature_specification_version"])
        ),
        evaluation_report=str(overrides.pop("evaluation_report", LINEAGE["evaluation_report"])),
        schema_version=str(overrides.pop("schema_version", "backtest-artifact/1")),
    )


# ---------------------------------------------------------------- reproducibility


def test_two_builds_of_the_same_run_produce_the_same_digest(
    simple_dataset: Dataset,
) -> None:
    """The reproducibility criterion, stated as the simplest possible equality.

    Byte-identical inputs must yield a byte-identical digest, because the digest is what a
    reviewer uses to decide whether two artifacts are the same claim.
    """
    first = _artifact(simple_dataset)
    second = _artifact(simple_dataset)
    assert first.digest == second.digest
    assert first == second
    assert first.to_canonical() == second.to_canonical()


def test_the_digest_is_a_function_of_content_not_of_a_constant(
    simple_dataset: Dataset,
) -> None:
    """Guard against the degenerate fix: a digest that ignores its input.

    A digest that always returned the same value would satisfy the equality test above. The
    only way to know the digest is actually reading the content is to change the content and
    see it move.
    """
    baseline = _artifact(simple_dataset)
    altered = _artifact(simple_dataset, evaluation_report="reports/eval-2026-01-06.md")
    assert baseline.digest != altered.digest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code_revision", "1111111111111111111111111111111111111111"),
        ("feature_specification_version", "features/9.9.9"),
        ("evaluation_report", "reports/other.md"),
        ("schema_version", "backtest-artifact/2"),
    ],
)
def test_changing_any_lineage_field_changes_the_digest(
    simple_dataset: Dataset, field: str, value: str
) -> None:
    """Lineage is inside the digest, not merely printed beside it.

    docs/22 section 5 exists because a decision is worthless without knowing what produced it.
    If lineage sat outside the digest, two artifacts could share a digest while disagreeing about
    the code revision that made them, and the digest would conceal the substitution.
    """
    baseline = _artifact(simple_dataset)
    altered = _artifact(simple_dataset, **{field: value})
    assert altered.digest != baseline.digest


def test_a_changed_dataset_changes_the_digest_even_under_the_same_name(
    simple_dataset: Dataset,
) -> None:
    """A data change is not a relabelling.

    The dataset name and schema version are part of the fingerprint, so two datasets published
    under the same name with different bars are distinguishable. Without this a corrected
    dataset could be published under the previous version's name and pass as unchanged.
    """
    corrected = Dataset.create(
        name="simple",
        schema_version="bars/1",
        bars=[*simple_dataset.bars[:-1], bar(4, 4, 4, "105")],
    )
    assert corrected.fingerprint != simple_dataset.fingerprint
    assert _artifact(corrected).digest != _artifact(simple_dataset).digest


def test_the_artifact_carries_no_ambient_state(simple_dataset: Dataset) -> None:
    """An artifact must not record when or where it was made.

    A creation time would make every artifact unique and would destroy the property the digest
    exists to provide, so the absence is asserted against the canonical wire form rather than
    left to review.
    """
    canonical = _artifact(simple_dataset).to_canonical()
    assert set(canonical) == {
        "schema_version",
        "status",
        "code_revision",
        "feature_specification_version",
        "evaluation_report",
        "dataset",
        "result",
    }
    assert set(canonical["dataset"]) == {"name", "schema_version", "fingerprint"}
    serialised = json.dumps(canonical, sort_keys=True)
    for forbidden in ("created_at", "hostname", "127.0.0.1", "C:\\\\", "run_id", "pid"):
        assert forbidden not in serialised


def test_the_canonical_form_is_stable_across_key_order(
    simple_dataset: Dataset,
) -> None:
    """Two artifacts equal by value must serialise to the same bytes.

    The digest is taken over sorted keys, so construction order cannot reach it. This is
    asserted on the bytes rather than on ``to_canonical()`` because a dict comparison would hide
    ordering that the digest is sensitive to.
    """
    from webtrade_research.content_address import canonical_bytes

    canonical = _artifact(simple_dataset).to_canonical()
    reversed_keys = dict(reversed(list(canonical.items())))
    assert canonical_bytes(canonical) == canonical_bytes(reversed_keys)


# ---------------------------------------------------------------- non-authority


def test_the_artifact_has_no_field_it_could_be_approved_with(
    simple_dataset: Dataset,
) -> None:
    """The strongest non-authority control is a field that does not exist.

    An artifact with an empty ``approved_by`` invites a later stage to fill it in; an artifact
    with no such field cannot be promoted by accident, because there is nowhere to record the
    promotion (docs/07 separation of duties, docs/25 section 4). Asserting the field names
    directly means adding one later fails the suite rather than passing review unnoticed.
    """
    names = {f.name for f in dataclasses.fields(BacktestArtifact)}
    forbidden = {
        "approved_by",
        "approver",
        "approval",
        "reviewer",
        "promoted",
        "deployment_scope",
        "deployed",
        "live",
    }
    assert not (names & forbidden), (
        f"the artifact gained an authority field: {sorted(names & forbidden)}"
    )


def test_a_status_other_than_proposed_is_refused(simple_dataset: Dataset) -> None:
    """The worker cannot represent its own output as approved."""
    artifact = _artifact(simple_dataset)
    with pytest.raises(ArtifactError, match="cannot mark its own output approved"):
        dataclasses.replace(artifact, status="approved")


def test_a_built_artifact_is_always_proposed(simple_dataset: Dataset) -> None:
    """``build_artifact`` cannot be talked into another status.

    It hardcodes ``PROPOSED`` rather than accepting one, so the default cannot be overridden by
    a caller passing an extra argument.
    """
    import inspect

    signature = inspect.signature(build_artifact)
    assert "status" not in signature.parameters
    assert _artifact(simple_dataset).status == PROPOSED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code_revision", ""),
        ("feature_specification_version", ""),
        ("evaluation_report", ""),
    ],
)
def test_incomplete_lineage_is_refused(simple_dataset: Dataset, field: str, value: str) -> None:
    """An artifact with no code revision is not reviewable.

    docs/22 section 5 requires each of these, so an empty one is a hard error rather than a
    value to be filled in later by whoever notices.
    """
    artifact = _artifact(simple_dataset)
    with pytest.raises(ArtifactError):
        dataclasses.replace(artifact, **{field: value})


def test_a_forged_digest_is_refused(simple_dataset: Dataset) -> None:
    """A digest is a claim about content, and content is what it must be derived from.

    Without this, the digest would be a label the producer chooses, and every comparison made
    with it would be a comparison of labels.
    """
    artifact = _artifact(simple_dataset)
    with pytest.raises(ArtifactError, match="does not match its content"):
        dataclasses.replace(artifact, digest="sha256:" + "0" * 64)


# ---------------------------------------------------------------- gating


def test_a_result_that_looked_ahead_cannot_become_an_artifact(
    late_publication_dataset: Dataset,
) -> None:
    """The artifact builder is the last gate, and it must actually hold.

    The harness and the verifier are separate code paths; this is the integration point where a
    leaked result is stopped from becoming something promotable. A caller who forgot to call
    ``assert_no_lookahead`` must not be able to produce an artifact.
    """
    result = _run(late_publication_dataset)
    leaked = dataclasses.replace(
        result,
        decisions=(
            DecisionRecord(
                as_of=at(1),
                side="hold",
                quantity="0",
                reason="",
                visible_sequences=(0, 1, 2),  # what event_time would have permitted
                reference_price=None,
            ),
        ),
    )
    with pytest.raises(LookaheadError, match="lookahead"):
        build_artifact(
            result=leaked,
            dataset=late_publication_dataset,
            code_revision=LINEAGE["code_revision"],
            feature_specification_version=LINEAGE["feature_specification_version"],
            evaluation_report=LINEAGE["evaluation_report"],
        )


def test_a_result_from_a_different_dataset_cannot_become_an_artifact(
    simple_dataset: Dataset,
) -> None:
    """An artifact is a claim about a specific dataset, checked rather than trusted.

    Building an artifact from a result produced over a different dataset is the quietest
    possible form of lineage failure: every field would look well-formed and the claim would be
    about data that was never used.
    """
    other = Dataset.create(
        name="other",
        schema_version="bars/1",
        bars=[bar(0, 0, 0, "200"), bar(1, 1, 1, "201")],
    )
    with pytest.raises(DatasetError, match="was produced from dataset"):
        build_artifact(
            result=_run(simple_dataset),
            dataset=other,
            code_revision=LINEAGE["code_revision"],
            feature_specification_version=LINEAGE["feature_specification_version"],
            evaluation_report=LINEAGE["evaluation_report"],
        )


def test_the_artifact_does_not_contain_credentials(
    simple_dataset: Dataset,
) -> None:
    """Nothing that could authenticate to a venue may travel with a research artifact.

    A backtest artifact is the one file most likely to be pasted into a ticket, a chat, or a
    review, so a secret field would leak by being summarised rather than by being exfiltrated.
    """
    canonical = _artifact(simple_dataset).to_canonical()
    serialised = json.dumps(canonical, sort_keys=True).lower()
    for forbidden in ("api_key", "apikey", "secret", "password", "token", "private_key"):
        assert forbidden not in serialised
