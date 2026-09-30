"""Tests for lineage proposals and the research worker's lack of authority over them.

Two things are being asserted here, and the second is the one that matters.

The first is ordinary validation: a proposal with a truncated digest, a missing code
revision, or no prompt digest is refused. That is the same shape as the dataset tests and it
is easy to write.

The second is the authority boundary, and it is asserted against the *type* rather than
against behaviour. The argument is that a research worker does not hold model-governance
authority because there is nowhere in its vocabulary to put it: no field for a lifecycle
state, no field for an approver, no field asserting that the proposal is promotable. A test
that asserted "the worker does not approve models" by calling an approve method and checking
it raises would pass against a type that has an ``approve`` method, a flag defaulting to
false, and a method that forgot to set it. The structural test below fails if any of those
appear, because it inspects what the type can hold.

This is the Python half of a boundary whose other half is
services/control-plane/model. Neither side can substitute for the other, and each is tested
against the possibility that the other is wrong.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from webtrade_research import lineage
from webtrade_research.content_address import canonical_bytes, digest_bytes, hex_digest
from webtrade_research.lineage import (
    LineageProposal,
    ProposalError,
    RetrievalRecord,
    ToolCallRecord,
    build_proposal,
    normalise_digest,
)

# Real sha-256 digests, distinct so that a test using the wrong one fails visibly.
D_DATASET = "a" * 64
D_DATASET_2 = "b" * 64
D_PROMPT = "c" * 64
D_CONTEXT = "d" * 64
D_ARGS = "e" * 64

# Fields that would grant the worker authority it must not hold. The list is the inverse of
# what LineageProposal is allowed to carry, and a field named here appearing on the type is a
# failure, not a warning.
FORBIDDEN_FIELDS = (
    "approved",
    "approver",
    "approved_by",
    "state",
    "lifecycle_state",
    "status",
    "promoted",
    "promotable",
    "authoritative",
    "can_approve",
    "validation_passed",
    "evaluated",
    "risk_vetoed",
    "signed",
    "signature",
)


class FakeDataset:
    """Minimal stand-in carrying only what a proposal reads."""

    def __init__(self, fingerprint: str = D_DATASET) -> None:
        self.fingerprint = fingerprint


def valid_proposal(**overrides: object) -> LineageProposal:
    kwargs: dict[str, object] = {
        "model_name": "momentum-ensemble",
        "model_version": "3.2.1",
        "training_dataset_fingerprint": D_DATASET,
        "code_revision": "9f3c1a7e5b2d8046af13c9e2b7d05f84a6c3e1d97b2a4f6c8e0d2b4a6f8c0e1d",
        "feature_specification": "features/momentum_v4.yaml",
        "prompt_digests": (D_PROMPT,),
    }
    kwargs.update(overrides)
    return LineageProposal(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------


def test_a_complete_proposal_is_accepted() -> None:
    p = valid_proposal()
    assert p.model_version == "3.2.1"
    # The registry wire format is bare hex; the proposal digest is what the control plane
    # records, so it must satisfy the Go side's 64-lowercase-hex rule.
    digest = p.proposal_digest()
    assert len(digest) == 64, f"proposal digest {digest!r} is not the registry wire format"
    assert all(ch in "0123456789abcdef" for ch in digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("training_dataset_fingerprint", ""),
        ("training_dataset_fingerprint", "abc"),
        ("training_dataset_fingerprint", "A" * 64),
        ("training_dataset_fingerprint", "a" * 63),
        ("training_dataset_fingerprint", "a" * 65),
        ("code_revision", ""),
        ("code_revision", "   "),
        ("feature_specification", ""),
        ("model_name", ""),
        ("prompt_digests", ()),
        ("prompt_digests", ("short",)),
        ("prompt_digests", (D_PROMPT, "also-bad")),
    ],
)
def test_incomplete_proposals_are_refused(field: str, value: object) -> None:
    with pytest.raises(ProposalError):
        valid_proposal(**{field: value})


@pytest.mark.parametrize("version", ["", "3", "3.2", "v3.2.1", "3.2.1.4.5", "latest", "3.2.1 "])
def test_a_version_outside_the_grammar_is_refused(version: str) -> None:
    with pytest.raises(ProposalError):
        valid_proposal(model_version=version)


@pytest.mark.parametrize("version", ["0.0.1", "3.2.1", "12.0.99", "3.2.1-rc.1"])
def test_versions_inside_the_grammar_are_accepted(version: str) -> None:
    assert valid_proposal(model_version=version).model_version == version


def test_a_truncated_digest_is_refused_with_a_reason() -> None:
    with pytest.raises(ProposalError) as excinfo:
        valid_proposal(training_dataset_fingerprint="a" * 63)
    # The message must explain the failure, because a rejected registration is read by a
    # human who cannot see the rule that rejected it.
    assert "truncated" in str(excinfo.value) or "sha-256" in str(excinfo.value)


# ---------------------------------------------------------------------------------------
# The authority boundary
# ---------------------------------------------------------------------------------------


def test_the_proposal_type_carries_no_authority_bearing_field() -> None:
    """A field that could record an approval or a promotable verdict must not exist."""
    names = {f.name for f in dataclasses.fields(LineageProposal)}
    forbidden = names.intersection(FORBIDDEN_FIELDS)
    assert not forbidden, (
        f"LineageProposal carries authority-bearing fields {sorted(forbidden)}; the research "
        f"worker is the model author and docs/07 forbids an author approving their own model"
    )


def test_the_proposal_type_exposes_no_approval_or_promotion_operation() -> None:
    """No method may be named for approving, promoting, authorising, or signing."""
    banned = ("approve", "promote", "authorise", "authorize", "sign", "attest", "deploy")
    for name in dir(LineageProposal):
        lowered = name.lower()
        for verb in banned:
            assert verb not in lowered, (
                f"LineageProposal exposes {name!r}; the research worker must not be able to "
                f"{verb} a model. A method that raises is still a method a later change "
                f"could implement."
            )


def test_the_proposal_is_frozen() -> None:
    """A proposal cannot be mutated into a state it was not built as."""
    p = valid_proposal()
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.model_version = "9.9.9"  # type: ignore[misc]


def test_replacing_a_proposal_cannot_add_an_authority_field() -> None:
    """dataclasses.replace cannot smuggle in a field the type does not declare."""
    p = valid_proposal()
    with pytest.raises(TypeError):
        dataclasses.replace(p, approved=True)  # type: ignore[call-arg]


def test_the_worker_names_no_approver() -> None:
    """docs/07 requires an independent reviewer, so the worker must have no way to name one."""
    source = inspect.getsource(lineage)
    for banned in ("approver=", "reviewed_by", "reviewer=", "approved_by"):
        assert banned not in source, (
            f"the lineage module mentions {banned!r}; the research worker must not be able "
            f"to name an approver, or a self-approval could be expressed as data"
        )


def test_a_financial_call_off_the_command_path_cannot_be_encoded() -> None:
    """The contradiction is refused at construction, not left for a consumer to detect."""
    with pytest.raises(ProposalError) as excinfo:
        ToolCallRecord(
            tool_name="order.submit",
            financial=True,
            went_through_command_path=False,
            arguments_digest=D_ARGS,
        )
    assert "command path" in str(excinfo.value)

    # And a proposal carrying one cannot be built, so the invariant is not reachable
    # through the higher-level constructor either.
    with pytest.raises(ProposalError):
        valid_proposal(
            tool_calls=(
                ToolCallRecord(
                    tool_name="order.submit",
                    financial=True,
                    went_through_command_path=False,
                    arguments_digest=D_ARGS,
                ),
            )
        )


def test_a_financial_call_through_the_command_path_is_encodable() -> None:
    """The positive control: the rule rejects the contradiction, not all financial calls."""
    call = ToolCallRecord(
        tool_name="order.submit",
        financial=True,
        went_through_command_path=True,
        arguments_digest=D_ARGS,
    )
    assert call.classification == "FINANCIAL"
    p = valid_proposal(tool_calls=(call,))
    assert p.financial_calls_off_command_path() == ()


def test_a_non_financial_call_needs_no_command_path() -> None:
    call = ToolCallRecord(
        tool_name="market_data.read",
        financial=False,
        went_through_command_path=False,
        arguments_digest=D_ARGS,
    )
    assert call.classification == "READ_ONLY"
    assert valid_proposal(tool_calls=(call,)).financial_calls_off_command_path() == ()


def test_a_tool_call_record_cannot_assert_its_own_authorization() -> None:
    """A worker that could record 'this was permitted' could satisfy a permission check."""
    names = {f.name for f in dataclasses.fields(ToolCallRecord)}
    assert "authorized" not in names, (
        "ToolCallRecord carries an 'authorized' field; the worker asserts what it called, "
        "not whether the call was permitted. Recording authorization would let a worker "
        "satisfy a permission check by writing the answer into its own evidence."
    )
    assert "permitted" not in names


def test_a_retrieval_record_stores_the_identifier_not_the_content() -> None:
    """docs/07 names retrieved context identifiers; storing content would duplicate the
    most sensitive data into the least-protected copy."""
    names = {f.name for f in dataclasses.fields(RetrievalRecord)}
    assert names == {"identifier", "digest"}, (
        f"RetrievalRecord carries {sorted(names)}; it must hold the identifier and the "
        f"content digest and nothing else"
    )


# ---------------------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------------------


def test_the_proposal_digest_is_order_independent() -> None:
    """Two equal proposals must have one digest, or lineage depends on iteration order."""
    a = valid_proposal(
        prompt_digests=(D_PROMPT, D_CONTEXT),
        retrievals=(
            RetrievalRecord(identifier="ctx/a", digest=D_CONTEXT),
            RetrievalRecord(identifier="ctx/b", digest=D_DATASET_2),
        ),
    )
    b = valid_proposal(
        prompt_digests=(D_CONTEXT, D_PROMPT),
        retrievals=(
            RetrievalRecord(identifier="ctx/b", digest=D_DATASET_2),
            RetrievalRecord(identifier="ctx/a", digest=D_CONTEXT),
        ),
    )
    assert a.proposal_digest() == b.proposal_digest()


def test_a_changed_field_changes_the_digest() -> None:
    base = valid_proposal().proposal_digest()
    for name, value in (
        ("model_version", "3.2.2"),
        ("code_revision", "0" * 40),
        ("feature_specification", "features/other.yaml"),
        ("limitations", "different limitations"),
    ):
        assert valid_proposal(**{name: value}).proposal_digest() != base, (
            f"changing {name} did not change the proposal digest; the digest would then fail "
            f"to identify the evidence a registration was based on"
        )


def test_the_proposal_digest_is_stable_across_calls() -> None:
    p = valid_proposal()
    assert p.proposal_digest() == p.proposal_digest()


# ---------------------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------------------


def test_the_builder_reads_the_dataset_fingerprint() -> None:
    p = build_proposal(
        model_name="momentum-ensemble",
        model_version="3.2.1",
        dataset=FakeDataset(D_DATASET),
        code_revision="9f3c1a7",
        feature_specification="features/momentum_v4.yaml",
        prompt_digests=(D_PROMPT,),
    )
    assert p.training_dataset_fingerprint == D_DATASET


def test_the_builder_refuses_a_dataset_without_a_fingerprint() -> None:
    with pytest.raises(ProposalError):
        build_proposal(
            model_name="momentum-ensemble",
            model_version="3.2.1",
            dataset=object(),
            code_revision="9f3c1a7",
            feature_specification="features/momentum_v4.yaml",
            prompt_digests=(D_PROMPT,),
        )


def test_the_builder_refuses_a_non_string_fingerprint() -> None:
    class Numeric:
        fingerprint = 12345  # type: ignore[assignment]

    with pytest.raises(ProposalError):
        build_proposal(
            model_name="momentum-ensemble",
            model_version="3.2.1",
            dataset=Numeric(),
            code_revision="9f3c1a7",
            feature_specification="features/momentum_v4.yaml",
            prompt_digests=(D_PROMPT,),
        )


def test_the_builder_refuses_a_malformed_dataset_fingerprint() -> None:
    with pytest.raises(ProposalError):
        build_proposal(
            model_name="momentum-ensemble",
            model_version="3.2.1",
            dataset=FakeDataset("not-a-digest"),
            code_revision="9f3c1a7",
            feature_specification="features/momentum_v4.yaml",
            prompt_digests=(D_PROMPT,),
        )


def test_limitations_may_be_empty_at_proposal_time() -> None:
    """The worker reports what the author knows; the control plane decides what is enough.

    A proposal without limitations is legitimate here and is refused at registration by the
    Go side. The asymmetry is intentional and worth pinning: a worker that refused to emit
    such a proposal would be inventing a completeness rule the control plane never asked for,
    and the control plane's rule could then not be relaxed without changing the worker.
    """
    assert valid_proposal(limitations="").limitations == ""


def test_the_registry_wire_format_is_bare_hex_on_both_sides() -> None:
    """The Go registry's model.Digest accepts 64 lowercase hex and nothing else.

    The worker's own artifacts carry a ``sha256:`` prefix so a human reading a log can see
    what hashed them, and the proposal strips it. The two sides disagreed about what a
    digest is until a research-produced fingerprint would have been rejected by the registry
    that consumes it; this test pins the proposal side of that contract so the next change
    to either representation has to meet the other.
    """
    bare = hex_digest({"probe": "wi-141"})
    assert len(bare) == 64
    assert not bare.startswith("sha256:")

    # The same canonical value under digest_bytes differs only by the prefix.
    prefixed = digest_bytes(canonical_bytes({"probe": "wi-141"}))
    assert prefixed == "sha256:" + bare
    assert normalise_digest(prefixed) == bare

    # A proposal built from a prefixed dataset fingerprint carries the bare form.
    p = build_proposal(
        model_name="momentum-ensemble",
        model_version="3.2.1",
        dataset=FakeDataset("sha256:" + D_DATASET),
        code_revision="9f3c1a7",
        feature_specification="features/momentum_v4.yaml",
        prompt_digests=(D_PROMPT,),
    )
    assert p.training_dataset_fingerprint == D_DATASET


def test_only_the_sha256_prefix_is_accepted() -> None:
    """A proposal must not name a digest computed under an unverified algorithm."""
    for bad in ("md5:" + "a" * 32, "sha512:" + "a" * 128, "sha256:" + "short"):
        with pytest.raises(ProposalError):
            normalise_digest(bad)
