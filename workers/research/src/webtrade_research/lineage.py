"""Lineage proposals: what the research worker may assert, and what it may not.

docs/07 requires that "Prompts, model versions, tool calls, retrieved context identifiers, and
generated decisions are recorded for material trading decisions", and that a model record
carries a training dataset fingerprint and a code revision. The research worker produces
the artifacts those fields are computed from, so it has to be able to state them. It has to
be able to *propose* a model registration.

It has no authority over one. This module is deliberately the only place the research worker
touches the vocabulary of model governance, and it exists to draw the boundary rather than
cross it:

* it produces a :class:`LineageProposal`, an immutable set of digests;
* it cannot mark a proposal approved, evaluated, validated, or promoted, because
  :class:`LineageProposal` has no field in which such a state could be written;
* it cannot name an approver, so it cannot satisfy a separation-of-duties check even by
  accident;
* it cannot assert that its own proposal is promotable, because promotability is decided by
  the Go control plane from evidence this worker does not hold.

That last point is the one that is easy to get wrong. A worker that emitted a
``approved: true`` field would not be a worker that had become authoritative; it would be a
worker whose output some later component trusted, which is authority by a different and much
harder to see route. The refusal here is structural - the field does not exist - so a
consumer that reads a proposal has nothing to be misled by.

The Go side of the same boundary is services/control-plane/model. Between the two, a
registration is proposed by the worker and decided by the control plane, and neither can
substitute for the other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from webtrade_research.content_address import hex_digest

__all__ = [
    "LineageError",
    "ProposalError",
    "LineageProposal",
    "RetrievalRecord",
    "ToolCallRecord",
    "build_proposal",
]

# A content digest is a lowercase hex SHA-256. The rule is duplicated from the Go side
# rather than imported, because importing the control plane from the research worker is
# precisely the coupling the authority boundary forbids. The duplication is deliberate and
# is the cost of keeping the two sides unable to reach each other.
_DIGEST_RE: Final = re.compile(r"\A[0-9a-f]{64}\Z")

# A model version is a dotted numeric string, optionally with a pre-release suffix. The
# grammar is narrow on purpose: a version that ends up in an audit record and a rollback
# instruction should not be free text.
_VERSION_RE: Final = re.compile(r"\A\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\Z")

# An identity is a non-empty, non-whitespace token. It is deliberately not validated
# against a directory or a certificate, because this worker has no authority to resolve an
# identity to anything; it can only repeat the string the control plane gave it.
_IDENTITY_RE: Final = re.compile(r"\A[^\s]{1,128}\Z")

# The algorithm prefix the worker puts on its own artifact digests. It is accepted as an
# input prefix and stripped, and is never emitted in a field the registry parses.
_SHA256_PREFIX: Final = "sha256:"


class LineageError(ValueError):
    """Base class for lineage failures."""


class ProposalError(LineageError):
    """A proposal could not be built from the evidence supplied."""


def _require_digest(value: str, field_name: str) -> str:
    """Return *value* if it is a well-formed lowercase sha-256, else raise.

    A truncated digest is the failure this exists to catch. A proposal carrying a
    thirty-nine-character fingerprint would look complete to any consumer that only checks
    for presence, and would be indistinguishable from a recorded one in a lineage record.
    """
    if not isinstance(value, str) or not _DIGEST_RE.match(value):
        msg = (
            f"{field_name} must be a lowercase hex sha-256 digest, got {value!r}. A "
            f"truncated digest is not a digest: it cannot identify bytes, and a lineage "
            f"that points at nothing is worse than one that admits a gap."
        )
        raise ProposalError(msg)
    return value


def _require_identity(value: str, field_name: str) -> str:
    """Return *value* if it is a plausible identity token, else raise."""
    if not isinstance(value, str) or not _IDENTITY_RE.match(value):
        msg = f"{field_name} must be a non-empty identity token, got {value!r}"
        raise ProposalError(msg)
    return value


def normalise_digest(value: str) -> str:
    """Return *value* as bare lowercase hex, accepting an optional ``sha256:`` prefix.

    The worker names its own artifacts with the algorithm prefix so a human reading a log
    can see what hashed them, while the control plane's ``model.Digest`` accepts exactly 64
    lowercase hex characters. A dataset fingerprint arrives here in the worker's prefixed
    form and leaves in the registry's bare form.

    Only ``sha256:`` is accepted as a prefix, and only to be removed. Accepting a general
    ``<algorithm>:<hex>`` shape would let a proposal name a digest it did not compute under
    an algorithm nobody verified, which is precisely the ambiguity the registry's strict
    type exists to prevent.
    """
    if not isinstance(value, str):
        msg = f"a digest must be a string, got {type(value).__name__}"
        raise ProposalError(msg)
    candidate = value[len(_SHA256_PREFIX) :] if value.startswith(_SHA256_PREFIX) else value
    return _require_digest(candidate, "digest")


@dataclass(frozen=True, slots=True)
class RetrievalRecord:
    """One item of retrieved context supplied to a model.

    docs/07 section 6 names "retrieved context identifiers" rather than the context itself,
    and the distinction is load-bearing. The ledger stores the identifier so a decision can
    be traced to its inputs, while the content stays under whatever classification and
    retention govern it. Copying the content here would make the lineage record the
    least-protected copy of the most sensitive data in the system.
    """

    identifier: str
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            msg = "a retrieval record must carry the context identifier"
            raise ProposalError(msg)
        _require_digest(self.digest, f"retrieval {self.identifier!r} digest")


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """One tool call made while producing a model.

    ``financial`` and ``went_through_command_path`` are recorded so the control plane can
    check, without trusting this worker's classification, that an authorized financial call
    went through the Go command path. The worker asserts them because it knows what it
    called; it does not decide whether the call was permitted, which is why there is no
    ``authorized`` field here. A worker that could record its own authorization decision
    could satisfy a permission check by writing the answer into the evidence.
    """

    tool_name: str
    financial: bool
    went_through_command_path: bool
    arguments_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or not self.tool_name.strip():
            msg = "a tool call record must name the tool"
            raise ProposalError(msg)
        _require_digest(self.arguments_digest, f"tool call {self.tool_name!r} arguments")
        # A financial call that did not pass the Go command path is a contradiction the
        # worker can detect in its own record, and refusing to encode it is better than
        # emitting it and letting a consumer decide. The refusal is not a security
        # control - the Go side checks this independently - it is an assertion that a
        # self-inconsistent record is never produced.
        if self.financial and not self.went_through_command_path:
            msg = (
                f"tool call {self.tool_name!r} is recorded as financial but did not go "
                f"through the command path; docs/07 permits financial tools only through "
                f"the Go command path, so this record is self-contradictory"
            )
            raise ProposalError(msg)

    @property
    def classification(self) -> str:
        """The classification name, for a proposal that carries these calls."""
        return "FINANCIAL" if self.financial else "READ_ONLY"


@dataclass(frozen=True, slots=True)
class LineageProposal:
    """An immutable, unapproved proposal to register a model version.

    The type is frozen and has no field for a lifecycle state, an approver, or a
    promotability flag. That is the mechanism: there is nowhere to write "approved" or
    "promotable" even by accident, and ``dataclasses.replace`` cannot add one. A consumer
    that receives a proposal receives evidence, and the decision built on that evidence
    happens in the control plane, where a human approval and the risk veto already live.

    The worker is the *author* of a model in the docs/07 sense, and docs/07 forbids the
    author approving their own model for live use. Expressing the proposal in a type that
    cannot carry an approval is the same rule applied one layer earlier: the author cannot
    assert the thing they are forbidden from deciding.
    """

    model_name: str
    model_version: str
    training_dataset_fingerprint: str
    code_revision: str
    feature_specification: str
    retrievals: tuple[RetrievalRecord, ...] = field(default_factory=tuple)
    tool_calls: tuple[ToolCallRecord, ...] = field(default_factory=tuple)
    prompt_digests: tuple[str, ...] = field(default_factory=tuple)
    # limitations may legitimately be empty at proposal time, and the control plane
    # requires it to be non-empty at registration. The asymmetry is intentional: the worker
    # reports what the author knows, and the control plane decides what is enough to
    # register. A worker that refused to emit a proposal without limitations would be
    # inventing a completeness rule the control plane has not asked for, and the control
    # plane's rule could then not be relaxed without changing the worker.
    limitations: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.model_name, str) or not self.model_name.strip():
            msg = "a proposal must name the model"
            raise ProposalError(msg)
        if not isinstance(self.model_version, str) or not _VERSION_RE.match(self.model_version):
            msg = (
                f"model_version must be a dotted numeric version such as 3.2.1, got "
                f"{self.model_version!r}. A version lands in an audit record and a rollback "
                f"instruction, so it is a grammar rather than free text."
            )
            raise ProposalError(msg)
        _require_digest(
            self.training_dataset_fingerprint, "training_dataset_fingerprint"
        )
        if not isinstance(self.code_revision, str) or not self.code_revision.strip():
            msg = "a proposal must record the code revision the model was built from"
            raise ProposalError(msg)
        if (
            not isinstance(self.feature_specification, str)
            or not self.feature_specification.strip()
        ):
            msg = "a proposal must name the feature specification the model consumes"
            raise ProposalError(msg)
        for i, digest in enumerate(self.prompt_digests):
            _require_digest(digest, f"prompt digest at index {i}")
        if not self.prompt_digests:
            msg = (
                "a proposal must record at least one prompt digest; a model record with no "
                "recorded prompt cannot be reconstructed or challenged"
            )
            raise ProposalError(msg)

    def proposal_digest(self) -> str:
        """Return the content digest of this proposal.

        The digest is what the control plane records against the model, so that a later
        reader can tell whether the evidence a registration was based on is the same
        evidence. It is computed over the canonical form, so two equal proposals have one
        digest regardless of the order their retriever happened to return results in.
        """
        return hex_digest(
            {
                "model_name": self.model_name,
                "model_version": self.model_version,
                "training_dataset_fingerprint": self.training_dataset_fingerprint,
                "code_revision": self.code_revision,
                "feature_specification": self.feature_specification,
                "prompt_digests": sorted(self.prompt_digests),
                "retrievals": sorted(
                    ({"identifier": r.identifier, "digest": r.digest} for r in self.retrievals),
                    key=lambda item: item["identifier"],
                ),
                "tool_calls": sorted(
                    (
                        {
                            "tool_name": c.tool_name,
                            "financial": c.financial,
                            "went_through_command_path": c.went_through_command_path,
                            "arguments_digest": c.arguments_digest,
                        }
                        for c in self.tool_calls
                    ),
                    key=lambda item: (item["tool_name"], item["arguments_digest"]),
                ),
                "limitations": self.limitations,
            }
        )

    def financial_calls_off_command_path(self) -> tuple[ToolCallRecord, ...]:
        """Return financial calls recorded without the Go command path.

        Always empty, because ``ToolCallRecord`` refuses to be constructed in that state.
        The method exists so the control plane's second check has something to call, and so
        a reader can see that the invariant is enforced at construction rather than left to
        whoever reads the record.
        """
        return tuple(
            c for c in self.tool_calls if c.financial and not c.went_through_command_path
        )


def build_proposal(
    *,
    model_name: str,
    model_version: str,
    dataset: object,
    code_revision: str,
    feature_specification: str,
    prompt_digests: tuple[str, ...],
    retrievals: tuple[RetrievalRecord, ...] = (),
    tool_calls: tuple[ToolCallRecord, ...] = (),
    limitations: str = "",
) -> LineageProposal:
    """Build a proposal from a research dataset and the evidence around it.

    ``dataset`` is duck-typed on its ``fingerprint`` attribute rather than imported as
    :class:`~webtrade_research.dataset.Dataset`, so that this module's authority boundary
    can be stated without depending on the dataset module's internals. The type check is
    deliberate and is the reason a caller cannot pass an arbitrary object whose
    ``fingerprint`` happens to be a string: the value must be a 64-character lowercase hex
    digest, verified by the proposal's own constructor.

    Nothing here is a decision. The function assembles evidence; the control plane decides
    what to do with it.
    """
    fingerprint = getattr(dataset, "fingerprint", None)
    if not isinstance(fingerprint, str):
        msg = (
            "dataset must expose a 'fingerprint' string; a proposal's training dataset is "
            "identified by its content digest and by nothing else"
        )
        raise ProposalError(msg)
    return LineageProposal(
        model_name=model_name,
        model_version=model_version,
        training_dataset_fingerprint=normalise_digest(fingerprint),
        code_revision=code_revision,
        feature_specification=feature_specification,
        prompt_digests=prompt_digests,
        retrievals=retrievals,
        tool_calls=tool_calls,
        limitations=limitations,
    )
