"""Offline search planning: evidence x capability x policy x prior attempts.

Extracted from :mod:`media_catalog.discovery.orchestration` (change
add-discovery-search-policy) so the same explainable decisions serve executed
sessions, dry-runs, and search-state inspection without persisting anything.
Every considered (target, method) pair is reported as planned, skipped, or
excluded with the reason inline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from media_catalog.adapters.contracts import LookupStrategy
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU
from media_catalog.adapters.e621 import E621
from media_catalog.adapters.gelbooru import GELBOORU
from media_catalog.candidate_lookup.planning import (
    _account_materials,
    _file_materials,
    _post_materials,
)
from media_catalog.discovery.attempts import SearchAttemptLedger, SubjectRef
from media_catalog.discovery.policy import (
    SearchPolicy,
    freshness_verdict,
    method_version,
)
from media_catalog.search_index.projection import registered_targets

# Providers that declare bounded lookup capabilities today; safebooru/rule34/
# e926 deliberately ship none until captured, and sankaku/pixiv/pawchive have
# no lookup surface.  Stage 3 extends this registry.
LOOKUP_PROVIDERS: tuple[Any, ...] = (DANBOORU, AIBOORU, E621, GELBOORU)

LOCAL = "local"
PROVIDER = "provider"
INDEX = "index"
LOCAL_SOURCE = "catalog"

# Methods a lookup-v1 projection can serve; artist strategies stay gated by
# the active-search policy even here.
INDEX_METHODS = (
    "verified_md5",
    "declared_md5",
    "source_post_url",
    "external_post_id",
    "artist_exact_name",
    "artist_alias",
    "artist_text",
)

PLANNED = "planned"
SKIPPED = "skipped"
EXCLUDED = "excluded"


def evidence_digest(values: Any) -> str:
    """Stable digest over the sorted query-evidence values a step searches."""
    encoded = json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PlannedSearch:
    source_kind: str
    source: str
    method: str
    status: str  # planned | skipped | excluded
    detail: str | None = None
    query_digest: str | None = None
    target: str | None = None

    @property
    def strategy_version(self) -> str:
        return method_version(self.method)


# ── Query-evidence helpers (shared with the executors) ───────────────────


def post_hash_evidence(connection: Any, seed_post: int) -> list[str]:
    """Verified and declared hash values the local md5 search covers."""
    rows = connection.execute(
        """SELECT DISTINCT f.fingerprint_value
             FROM media_occurrences o
             JOIN occurrence_assets oa USING(media_occurrence_id)
             JOIN asset_fingerprints f ON f.asset_id = oa.asset_id
            WHERE o.post_id = ? AND f.fingerprint_kind IN ('md5', 'sha256')""",
        (seed_post,),
    ).fetchall()
    return [row["fingerprint_value"] for row in rows]


def post_source_urls(connection: Any, seed_post: int) -> list[str]:
    """Canonical source URLs the local source-url search covers."""
    return [
        row["canonical_url"]
        for row in connection.execute(
            """SELECT DISTINCT l.canonical_url
                 FROM post_external_references r
                 JOIN external_links l USING(external_link_id)
                WHERE r.post_id = ? AND r.reference_kind = 'source_url'""",
            (seed_post,),
        )
    ]


def post_canonical_url(connection: Any, seed_post: int) -> str | None:
    row = connection.execute(
        "SELECT canonical_url FROM posts WHERE post_id = ?", (seed_post,)
    ).fetchone()
    if row is None:
        return None
    return row["canonical_url"]


def _seed_platform_key(connection: Any, seed_post: int | None) -> str | None:
    """The platform key of a post seed, for provider-namespaced decisions."""
    if seed_post is None:
        return None
    row = connection.execute(
        """SELECT platform.platform_key FROM posts p
             JOIN platforms platform ON platform.platform_id = p.platform_id
            WHERE p.post_id = ?""",
        (seed_post,),
    ).fetchone()
    return str(row["platform_key"]) if row else None


def _seed_native_post_id(connection: Any, seed_post: int | None) -> str | None:
    """The provider-native id of a post seed."""
    if seed_post is None:
        return None
    row = connection.execute(
        "SELECT native_post_id FROM posts WHERE post_id = ?", (seed_post,)
    ).fetchone()
    return str(row["native_post_id"]) if row else None


def file_seed_hashes(connection: Any, seed_file: int) -> list[str]:
    row = connection.execute(
        "SELECT verified_md5, verified_sha256 FROM discovery_file_seeds"
        " WHERE discovery_file_seed_id = ?",
        (seed_file,),
    ).fetchone()
    if row is None:
        return []
    return [value for value in (row["verified_md5"], row["verified_sha256"]) if value]


# ── Planning ─────────────────────────────────────────────────────────────


def plan_searches(
    connection: Any,
    *,
    seed_post: int | None = None,
    seed_account: int | None = None,
    seed_file: int | None = None,
    search_term: str | None = None,
    policy: SearchPolicy | None = None,
    ledger: SearchAttemptLedger | None = None,
    now: datetime | None = None,
) -> list[PlannedSearch]:
    """Decide every (target, method) search applicable to one subject.

    Planning is offline: it reads the catalog and the attempt ledger, never
    the network.  Decision order per pair: capability and material first (as
    before this policy existed), then the policy (source, method, active
    search), then freshness under the policy's recheck mode.
    """
    subject = SubjectRef(post_id=seed_post, account_id=seed_account, file_id=seed_file)
    if ledger is None:
        ledger = SearchAttemptLedger(connection)
    if policy is None:
        policy = SearchPolicy().with_search_term(search_term)
    if now is None:
        now = datetime.now(UTC)

    materials: dict[LookupStrategy, list[Any]] = {}
    if seed_post is not None:
        _, materials, _ = _post_materials(connection, seed_post)
    elif seed_file is not None:
        _, materials, _ = _file_materials(connection, seed_file)
    elif seed_account is not None:
        strategies = tuple(
            strategy for strategy in LookupStrategy if strategy.value.startswith("artist_")
        )
        try:
            _, materials, _ = _account_materials(connection, seed_account, strategies, search_term)
        except ValueError:
            # Artist strategies need an operator-supplied search term;
            # without one they resolve to "no material" and the planner
            # reports them excluded rather than failing the session.
            materials = {}

    def decide(
        *,
        source_kind: str,
        source: str,
        method: str,
        applicable: bool,
        material_detail: str | None,
        digest_values: Any,
        target_note: str | None = None,
    ) -> PlannedSearch:
        if not applicable:
            return PlannedSearch(
                source_kind=source_kind,
                source=source,
                method=method,
                status=EXCLUDED,
                detail=material_detail,
            )
        reason = policy.source_reason(source)
        if reason is None:
            reason = policy.method_reason(method)
        if reason is not None:
            return PlannedSearch(
                source_kind=source_kind,
                source=source,
                method=method,
                status=EXCLUDED,
                detail=reason,
            )
        digest = evidence_digest(digest_values)
        attempt = ledger.latest(
            subject,
            source_kind=source_kind,
            source=source,
            method=method,
            query_digest=digest,
        )
        expected_version = (
            target_note
            if source_kind == INDEX and target_note is not None
            else method_version(method)
        )
        verdict = freshness_verdict(policy, attempt, expected_version=expected_version, now=now)
        if verdict.fresh:
            return PlannedSearch(
                source_kind=source_kind,
                source=source,
                method=method,
                status=SKIPPED,
                detail=verdict.reason,
                query_digest=digest,
                target=target_note or digest,
            )
        detail = None if attempt is None else verdict.reason
        return PlannedSearch(
            source_kind=source_kind,
            source=source,
            method=method,
            status=PLANNED,
            detail=detail,
            query_digest=digest,
            target=target_note or digest,
        )

    steps: list[PlannedSearch] = []

    # Local target: the three questions the catalog answers offline.  An
    # account seed carries none of the post-shaped material; a file seed
    # carries its verified hashes.
    steps.append(
        decide(
            source_kind=LOCAL,
            source=LOCAL_SOURCE,
            method="local_md5",
            applicable=seed_post is not None or seed_file is not None,
            material_detail="account seed carries no post material",
            digest_values=(
                post_hash_evidence(connection, seed_post)
                if seed_post is not None
                else file_seed_hashes(connection, seed_file or 0)
            ),
        )
    )
    steps.append(
        decide(
            source_kind=LOCAL,
            source=LOCAL_SOURCE,
            method="local_source_url",
            applicable=seed_post is not None,
            material_detail="seed carries no source url material",
            digest_values=(
                post_source_urls(connection, seed_post) if seed_post is not None else []
            ),
        )
    )
    steps.append(
        decide(
            source_kind=LOCAL,
            source=LOCAL_SOURCE,
            method="local_platform_identity",
            applicable=seed_post is not None,
            material_detail="seed carries no platform identity material",
            digest_values=(
                [post_canonical_url(connection, seed_post) or ""] if seed_post is not None else []
            ),
        )
    )

    # Index targets: registered provider lookup projections, offline like the
    # local steps and ordered before providers.  Each contributes the same
    # decision shape — skipped fresh with the attempt named, excluded by
    # policy or material, planned under the snapshot's revision.
    for target in registered_targets(connection):
        for method in INDEX_METHODS:
            if target.problem is not None:
                # A broken registration dominates: every method row names
                # the file problem instead of a material reason.
                steps.append(
                    PlannedSearch(
                        source_kind=INDEX,
                        source=target.name,
                        method=method,
                        status=EXCLUDED,
                        detail=target.problem,
                    )
                )
                continue
            strategy = LookupStrategy(method)
            values = materials.get(strategy) or []
            has_material = bool(values)
            # external_post_id is platform-namespaced.  Cross-platform id
            # references count only for the matching provider's index; a
            # subject that IS the provider's post can always search its own
            # id there.
            if method == "external_post_id":
                own_platform = _seed_platform_key(connection, seed_post)
                own_native = (
                    _seed_native_post_id(connection, seed_post) if seed_post is not None else None
                )
                cross_platform = any(material.platform == target.provider for material in values)
                if own_platform == target.provider and own_native is not None:
                    applicable = True
                    material_detail = None
                    digest_values: list[str] = [own_native]
                elif cross_platform:
                    applicable = True
                    material_detail = None
                    digest_values = [material.digest for material in values]
                else:
                    applicable = False
                    material_detail = "no matching provider id on the seed for this index"
                    digest_values = []
                steps.append(
                    decide(
                        source_kind=INDEX,
                        source=target.name,
                        method=method,
                        applicable=applicable,
                        material_detail=material_detail,
                        digest_values=digest_values,
                        target_note=target.version,
                    )
                )
                continue
            material_detail = (
                "no query material on the seed for this method" if not has_material else None
            )
            applicable = has_material
            steps.append(
                decide(
                    source_kind=INDEX,
                    source=target.name,
                    method=method,
                    applicable=applicable,
                    material_detail=material_detail,
                    digest_values=[material.digest for material in values],
                    target_note=target.version,
                )
            )

    # Provider targets: one decision per (provider, strategy), planned when
    # the provider declares it and the seed carries material, excluded when
    # the material is missing, skipped when undeclared — then filtered by
    # policy and freshness.
    for provider in LOOKUP_PROVIDERS:
        context = provider.lookup_plan_context
        for strategy in LookupStrategy:
            values = materials.get(strategy) or []
            has_material = bool(values)
            declared = context.lookup_capabilities.supports(strategy)
            if declared and not has_material:
                material_detail: str | None = "no query material on the seed for this strategy"
                if strategy.value.startswith("artist_"):
                    material_detail = "artist search requires an operator-supplied search term"
                applicable = False
            elif not declared:
                steps.append(
                    PlannedSearch(
                        source_kind=PROVIDER,
                        source=provider.platform_key,
                        method=strategy.value,
                        status=SKIPPED,
                        detail=f"{provider.platform_key} does not declare this strategy",
                    )
                )
                continue
            else:
                material_detail = None
                applicable = True
            steps.append(
                decide(
                    source_kind=PROVIDER,
                    source=provider.platform_key,
                    method=strategy.value,
                    applicable=applicable,
                    material_detail=material_detail,
                    digest_values=[material.digest for material in values],
                )
            )
    return steps
