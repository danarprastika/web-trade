"""Content-addressed backtest artifacts.

docs/01 draws the boundary in one line — "Python Research/Backtest ---- versioned artifacts
----> Control Plane validation" — and docs/22 section 5 requires a decision to link dataset
fingerprint, feature definition version, code revision, model artifact digest, evaluation
report, reviewer, approval, and deployment scope. An artifact that carries only its own result
cannot satisfy that, so lineage is part of the artifact rather than a companion note.

Two properties do the work here.

**Reproducible.** The artifact digest is a function of its canonical content, including its
lineage, so two runs of the same strategy over the same data produce the same digest and a
digest difference always means a real difference. Nothing ambient enters: no run timestamp, no
host, no path, no counter. That is why :class:`BacktestArtifact` has no creation time — a
timestamp would make every artifact unique and destroy the property the digest exists to
provide.

**Non-authoritative.** The artifact carries :attr:`BacktestArtifact.status`, which is always
``proposed``, and it has no field for an approver, an approval, or a deployment scope. Those are
omitted rather than left empty on purpose: an artifact with an empty ``approved_by`` invites a
later stage to fill it in, and an artifact that has no such field at all cannot be promoted by
accident. Promotion is a reviewed control-plane workflow, and a research worker holding an
approval field is a research worker that can eventually approve itself (docs/07 separation of
duties, docs/25 section 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from webtrade_research.content_address import canonical_digest
from webtrade_research.dataset import Dataset

from webtrade_backtest.harness import BacktestResult, assert_no_lookahead

__all__ = [
    "ArtifactError",
    "BacktestArtifact",
    "build_artifact",
    "PROPOSED",
]

PROPOSED: Final = "proposed"


class ArtifactError(ValueError):
    """The artifact is malformed or its lineage is incomplete."""


@dataclass(frozen=True, slots=True)
class BacktestArtifact:
    """A proposed, content-addressed backtest result with its lineage.

    Frozen and slotted for the same reason a :class:`~webtrade_research.dataset.Dataset` is:
    an artifact is a claim about a specific run, and a mutable one would let the claim drift
    away from the evidence.
    """

    schema_version: str
    result: BacktestResult
    dataset_name: str
    dataset_schema_version: str
    code_revision: str
    feature_specification_version: str
    evaluation_report: str
    digest: str
    status: str = PROPOSED

    def __post_init__(self) -> None:
        if not self.code_revision:
            msg = "an artifact must name the code revision that produced it"
            raise ArtifactError(msg)
        if not self.feature_specification_version:
            msg = "an artifact must name the feature specification version (docs/22 section 5)"
            raise ArtifactError(msg)
        if not self.evaluation_report:
            msg = "an artifact must reference an evaluation report (docs/22 section 5)"
            raise ArtifactError(msg)
        if self.status != PROPOSED:
            # The reason this is a hard error rather than a permissive default: a research
            # worker that can produce an artifact with any other status is a research worker
            # that can represent its output as approved. Nothing here may claim authority.
            msg = (
                f"status must be {PROPOSED!r}; a research worker cannot mark its own output "
                f"approved (docs/07 separation of duties, docs/25 section 4)"
            )
            raise ArtifactError(msg)
        expected = self.compute_digest(
            schema_version=self.schema_version,
            result=self.result,
            dataset_name=self.dataset_name,
            dataset_schema_version=self.dataset_schema_version,
            code_revision=self.code_revision,
            feature_specification_version=self.feature_specification_version,
            evaluation_report=self.evaluation_report,
        )
        if self.digest != expected:
            msg = (
                f"artifact digest {self.digest!r} does not match its content ({expected!r})"
            )
            raise ArtifactError(msg)

    @staticmethod
    def compute_digest(
        *,
        schema_version: str,
        result: BacktestResult,
        dataset_name: str,
        dataset_schema_version: str,
        code_revision: str,
        feature_specification_version: str,
        evaluation_report: str,
    ) -> str:
        """Return the content digest of the artifact and its lineage.

        The lineage fields are inside the digest, not merely beside it. A digest covering only
        the result would be unchanged by a different code revision or a different feature set,
        which is exactly the substitution lineage exists to make visible.
        """
        return canonical_digest(
            {
                "schema_version": schema_version,
                "dataset": {
                    "name": dataset_name,
                    "schema_version": dataset_schema_version,
                    "fingerprint": result.dataset_fingerprint,
                },
                "code_revision": code_revision,
                "feature_specification_version": feature_specification_version,
                "evaluation_report": evaluation_report,
                "status": PROPOSED,
                "result": result.to_canonical(),
            }
        )

    def to_canonical(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "code_revision": self.code_revision,
            "feature_specification_version": self.feature_specification_version,
            "evaluation_report": self.evaluation_report,
            "dataset": {
                "name": self.dataset_name,
                "schema_version": self.dataset_schema_version,
                "fingerprint": self.result.dataset_fingerprint,
            },
            "result": self.result.to_canonical(),
        }


def build_artifact(
    *,
    result: BacktestResult,
    dataset: Dataset,
    code_revision: str,
    feature_specification_version: str,
    evaluation_report: str,
    schema_version: str = "backtest-artifact/1",
) -> BacktestArtifact:
    """Build a verified artifact from *result*.

    The no-lookahead assertion runs here rather than being left to the caller. Building an
    artifact is the point at which a result stops being a computation and starts being a claim
    someone might act on, so this is the last moment at which a leaked view can be caught, and
    a caller who forgot to check should not be able to produce a promotable artifact.
    """
    assert_no_lookahead(result, dataset)
    return BacktestArtifact(
        schema_version=schema_version,
        result=result,
        dataset_name=dataset.name,
        dataset_schema_version=dataset.schema_version,
        code_revision=code_revision,
        feature_specification_version=feature_specification_version,
        evaluation_report=evaluation_report,
        digest=BacktestArtifact.compute_digest(
            schema_version=schema_version,
            result=result,
            dataset_name=dataset.name,
            dataset_schema_version=dataset.schema_version,
            code_revision=code_revision,
            feature_specification_version=feature_specification_version,
            evaluation_report=evaluation_report,
        ),
        status=PROPOSED,
    )
