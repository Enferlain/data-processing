"""Work and relationship records: vocabulary, validation, canonical orientation.

Kernel Phase D vocabulary: works are minimal deterministic anchors; relationships are typed,
provenance-bearing conclusions carrying epistemic status.  Symmetric kinds store endpoints in
canonical order and the relationship key hashes that order, so deterministic re-materialization
is idempotent; directional kinds keep the derivative, child, page, or thumbnail on the subject
side.  Endpoint-kind contracts per relation kind are validated here rather than in SQL so the
vocabulary can grow by value, not by migration.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

WORK_KINDS = frozenset({"single", "multi_page", "unknown"})
EPISTEMIC_STATUSES = frozenset({"observed", "verified", "derived", "inferred", "reviewed"})
# Media-closed by conscious decision (non-media-consumer spike F3,
# docs/plans/non-media-consumer-spike.md): extend by addition when a non-media
# family needs typed linking; never widen with a generic "object" endpoint kind.
ENDPOINT_KINDS = frozenset({"work", "media_occurrence", "post", "asset"})

# Quote/reply discourse stays in post_relations as provider import facts; it
# joins this typed vocabulary by addition only when a consumer needs typed
# discourse linking (mirrors the ENDPOINT_KINDS policy above).

# relation kind -> (symmetric, allowed subject kinds, allowed target kinds).
# Directional kinds place the derivative, page, thumbnail, repost, or declaring
# parent on the subject side and the origin, original, source, or child on the
# target (``parent_of`` runs parent -> child, matching the adapter emission).
RELATIONSHIP_KINDS: dict[str, tuple[bool, frozenset[str], frozenset[str]]] = {
    "same_bytes": (True, frozenset({"media_occurrence"}), frozenset({"media_occurrence"})),
    "same_work": (True, frozenset({"work"}), frozenset({"work"})),
    "thumbnail_of": (False, frozenset({"media_occurrence"}), frozenset({"media_occurrence"})),
    "reposted_from": (False, frozenset({"post"}), frozenset({"post"})),
    "parent_of": (False, frozenset({"post"}), frozenset({"post"})),
    "page_of": (False, frozenset({"work", "media_occurrence"}), frozenset({"work"})),
    "variant_of": (
        False,
        frozenset({"media_occurrence", "work"}),
        frozenset({"media_occurrence", "work"}),
    ),
    "derived_from": (
        False,
        frozenset({"media_occurrence", "work"}),
        frozenset({"media_occurrence", "work"}),
    ),
    "reencoded_from": (False, frozenset({"media_occurrence"}), frozenset({"media_occurrence"})),
    "resized_from": (False, frozenset({"media_occurrence"}), frozenset({"media_occurrence"})),
    "cropped_from": (False, frozenset({"media_occurrence"}), frozenset({"media_occurrence"})),
    "censored_variant_of": (
        False,
        frozenset({"media_occurrence"}),
        frozenset({"media_occurrence"}),
    ),
    "edited_from": (False, frozenset({"media_occurrence"}), frozenset({"media_occurrence"})),
    "transcoded_from": (
        False,
        frozenset({"media_occurrence"}),
        frozenset({"media_occurrence"}),
    ),
    "extracted_from": (
        False,
        frozenset({"media_occurrence"}),
        frozenset({"media_occurrence"}),
    ),
}


def validate_work_kind(kind: str) -> str:
    if kind not in WORK_KINDS:
        raise ValueError(f"unsupported work kind: {kind}")
    return kind


def validate_epistemic_status(status: str) -> str:
    if status not in EPISTEMIC_STATUSES:
        raise ValueError(f"unsupported epistemic status: {status}")
    return status


def relationship_key(
    relation_kind: str,
    subject_kind: str,
    subject_id: int,
    target_kind: str,
    target_id: int,
) -> str:
    """Deterministic identity over the canonically oriented endpoints."""

    payload = f"{relation_kind}:{subject_kind}:{subject_id}:{target_kind}:{target_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WorkRecord:
    """A minimal deterministic work anchor: one per post with occurrences."""

    origin_post_id: int
    work_kind: str = "unknown"
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.origin_post_id <= 0:
            raise ValueError("work origin post id must be positive")
        validate_work_kind(self.work_kind)


@dataclass(frozen=True, slots=True)
class RelationshipRecord:
    """One typed, provenance-bearing conclusion between two catalog objects."""

    subject_kind: str
    subject_id: int
    relation_kind: str
    target_kind: str
    target_id: int
    epistemic_status: str
    created_at: str = ""
    relationship_key: str = ""

    def __post_init__(self) -> None:
        contract = RELATIONSHIP_KINDS.get(self.relation_kind)
        if contract is None:
            raise ValueError(f"unsupported relationship kind: {self.relation_kind}")
        symmetric, subject_kinds, target_kinds = contract
        if self.subject_kind not in ENDPOINT_KINDS or self.target_kind not in ENDPOINT_KINDS:
            raise ValueError("relationship endpoints must name a known object kind")
        if self.subject_kind not in subject_kinds or self.target_kind not in target_kinds:
            raise ValueError(
                f"relationship kind {self.relation_kind!r} does not link "
                f"{self.subject_kind} to {self.target_kind}"
            )
        if self.subject_id <= 0 or self.target_id <= 0:
            raise ValueError("relationship endpoint ids must be positive")
        if self.subject_kind == self.target_kind and self.subject_id == self.target_id:
            raise ValueError("a relationship cannot link an object to itself")
        validate_epistemic_status(self.epistemic_status)
        if symmetric and (self.subject_kind, self.subject_id) > (
            self.target_kind,
            self.target_id,
        ):
            # Canonical orientation for symmetric kinds: endpoints ordered by
            # (kind, id) so the deterministic key is stable regardless of input
            # order.
            old_subject = (self.subject_kind, self.subject_id)
            old_target = (self.target_kind, self.target_id)
            object.__setattr__(self, "subject_kind", old_target[0])
            object.__setattr__(self, "subject_id", old_target[1])
            object.__setattr__(self, "target_kind", old_subject[0])
            object.__setattr__(self, "target_id", old_subject[1])
        object.__setattr__(
            self,
            "relationship_key",
            relationship_key(
                self.relation_kind,
                self.subject_kind,
                self.subject_id,
                self.target_kind,
                self.target_id,
            ),
        )
