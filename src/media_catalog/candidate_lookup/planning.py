"""Read-only planning for bounded provider candidate lookup."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from media_catalog.adapters import (
    LookupPlanConfiguration,
    LookupPlanContext,
    LookupPlanItem,
    LookupQueryMaterial,
    LookupStrategy,
)
from media_catalog.database import CatalogDatabase

DatabaseSource = CatalogDatabase | Path | str

MAX_REQUESTS = 100
MAX_PAGES = 100
MAX_RESULTS = 10_000
MAX_SECONDS = 3_600


def _digest(*parts: object) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _connection(database: DatabaseSource) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        try:
            database.connection.backup(snapshot)
            snapshot.execute("PRAGMA query_only = ON")
        except BaseException:
            snapshot.close()
            raise
        return snapshot, True
    opened = CatalogDatabase.open_read_only(Path(database))
    return opened.connection, True


@dataclass(frozen=True, slots=True)
class LookupLimits:
    requests: int = 3
    pages: int = 3
    results: int = 200
    seconds: int = 60

    def __post_init__(self) -> None:
        values = {
            "requests": (self.requests, MAX_REQUESTS),
            "pages": (self.pages, MAX_PAGES),
            "results": (self.results, MAX_RESULTS),
            "seconds": (self.seconds, MAX_SECONDS),
        }
        for name, (value, maximum) in values.items():
            if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= maximum:
                raise ValueError(f"lookup {name} must be between 1 and {maximum}")

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "pages": self.pages,
            "results": self.results,
            "seconds": self.seconds,
        }


@dataclass(frozen=True, slots=True, repr=False)
class PlannedLookup:
    item: LookupPlanItem
    material: LookupQueryMaterial = field(repr=False)
    seed_database_id: int
    seed_revision: str
    query_kind: str

    @property
    def plan_digest(self) -> str:
        return _digest(self.item.digest, self.seed_revision, self.query_kind)

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.item.provider,
            "instance": self.item.instance,
            "strategy": self.item.strategy.value,
            "strategy_version": self.item.strategy_version,
            "adapter_version": self.item.adapter_version,
            "schema_version": self.item.schema_version,
            "seed_kind": self.item.seed_kind,
            "seed_id": self.seed_database_id,
            "seed_revision": self.seed_revision,
            "query_kind": self.query_kind,
            "material_digest": self.material.digest,
            "plan_digest": self.plan_digest,
            "limits": dict(self.item.limits),
        }

    def __repr__(self) -> str:
        return (
            "PlannedLookup("
            f"provider={self.item.provider!r}, strategy={self.item.strategy.value!r}, "
            f"seed_kind={self.item.seed_kind!r}, seed_database_id={self.seed_database_id}, "
            f"plan_digest={self.plan_digest!r})"
        )


@dataclass(frozen=True, slots=True)
class CandidateLookupPlan:
    seed: str
    provider: str
    limits: LookupLimits
    items: tuple[PlannedLookup, ...]
    exclusions: tuple[dict[str, str], ...]

    @property
    def digest(self) -> str:
        return _digest(*(item.plan_digest for item in self.items))

    def as_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "provider": self.provider,
            "limits": self.limits.as_dict(),
            "count": len(self.items),
            "aggregate_upper_bounds": {
                "requests": self.limits.requests * len(self.items),
                "pages": self.limits.pages * len(self.items),
                "results": self.limits.results * len(self.items),
                "seconds": self.limits.seconds * len(self.items),
            },
            "items": [item.as_dict() for item in self.items],
            "excluded_count": len(self.exclusions),
            "exclusions": list(self.exclusions),
            "digest": self.digest,
            "network_requested": False,
        }


def _parse_seed(value: str) -> tuple[str, int]:
    kind, separator, raw_id = value.strip().partition(":")
    if not separator or kind not in {"account", "post"} or not raw_id.isdecimal():
        raise ValueError("lookup seed must use account:ID or post:ID")
    seed_id = int(raw_id)
    if seed_id <= 0:
        raise ValueError("lookup seed ID must be positive")
    return kind, seed_id


def _x_aliases(url: str) -> tuple[str, ...]:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("source lookup requires a canonical HTTPS post URL")
    host = parsed.hostname.lower()
    path = parsed.path.rstrip("/")
    if host not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        return (urlunsplit(("https", host, path, "", "")),)
    return tuple(urlunsplit(("https", alias, path, "", "")) for alias in ("x.com", "twitter.com"))


def _post_materials(
    connection: sqlite3.Connection,
    post_id: int,
) -> tuple[sqlite3.Row, dict[LookupStrategy, list[LookupQueryMaterial]], str]:
    post = connection.execute(
        """SELECT p.post_id, p.native_post_id, p.canonical_url, p.updated_at,
                  p.raw_observation_id, platform.platform_key
             FROM posts p JOIN platforms platform USING(platform_id)
            WHERE p.post_id = ?""",
        (post_id,),
    ).fetchone()
    if post is None:
        raise ValueError("lookup seed post not found")
    materials: dict[LookupStrategy, list[LookupQueryMaterial]] = {
        strategy: [] for strategy in LookupStrategy
    }
    canonical_url = post["canonical_url"]
    if not canonical_url and post["platform_key"] == "x":
        canonical_url = f"https://x.com/i/status/{post['native_post_id']}"
    if canonical_url:
        try:
            aliases = _x_aliases(str(canonical_url))
        except ValueError:
            aliases = ()
        if aliases:
            materials[LookupStrategy.SOURCE_POST_URL].append(
                LookupQueryMaterial(LookupStrategy.SOURCE_POST_URL, aliases)
            )
    for row in connection.execute(
        """SELECT DISTINCT target.platform_key, pr.native_identifier
             FROM post_external_references per
             JOIN platform_references pr USING(platform_reference_id)
             JOIN platforms target ON target.platform_id = pr.platform_id
            WHERE per.post_id = ? AND pr.object_kind = 'post'
              AND pr.identifier_kind = 'stable_id'
              AND target.platform_key = 'pixiv'
            ORDER BY target.platform_key, pr.native_identifier""",
        (post_id,),
    ):
        materials[LookupStrategy.EXTERNAL_POST_ID].append(
            LookupQueryMaterial(
                LookupStrategy.EXTERNAL_POST_ID,
                str(row["native_identifier"]),
                platform="pixiv",
            )
        )
    for row in connection.execute(
        """SELECT DISTINCT lower(declared_md5) AS md5
             FROM media_occurrences
            WHERE post_id = ? AND declared_md5 IS NOT NULL
            ORDER BY md5""",
        (post_id,),
    ):
        materials[LookupStrategy.DECLARED_MD5].append(
            LookupQueryMaterial(LookupStrategy.DECLARED_MD5, str(row["md5"]))
        )
    for row in connection.execute(
        """SELECT DISTINCT lower(a.verified_md5) AS md5
             FROM media_occurrences mo
             JOIN occurrence_assets oa USING(media_occurrence_id)
             JOIN assets a USING(asset_id)
            WHERE mo.post_id = ? AND a.verified_md5 IS NOT NULL
              AND a.verification_method IS NOT NULL
            ORDER BY md5""",
        (post_id,),
    ):
        materials[LookupStrategy.VERIFIED_MD5].append(
            LookupQueryMaterial(LookupStrategy.VERIFIED_MD5, str(row["md5"]))
        )
    revision = _digest(
        post["post_id"],
        post["platform_key"],
        post["native_post_id"],
        post["canonical_url"],
        post["updated_at"],
        post["raw_observation_id"],
        tuple(
            (strategy.value, tuple(item.digest for item in items))
            for strategy, items in materials.items()
            if items
        ),
    )
    return post, materials, revision


def _account_materials(
    connection: sqlite3.Connection,
    account_id: int,
    strategies: tuple[LookupStrategy, ...],
    search_term: str | None,
) -> tuple[sqlite3.Row, dict[LookupStrategy, list[LookupQueryMaterial]], str]:
    account = connection.execute(
        """SELECT a.account_id, a.native_account_id, a.last_seen_at, platform.platform_key,
                  snapshot.handle, snapshot.display_name, snapshot.raw_observation_id
             FROM accounts a JOIN platforms platform USING(platform_id)
             LEFT JOIN account_snapshots snapshot ON snapshot.account_snapshot_id = (
                 SELECT s.account_snapshot_id FROM account_snapshots s
                  WHERE s.account_id = a.account_id
                  ORDER BY s.observed_at DESC, s.account_snapshot_id DESC LIMIT 1
             ) WHERE a.account_id = ?""",
        (account_id,),
    ).fetchone()
    if account is None:
        raise ValueError("lookup seed account not found")
    materials: dict[LookupStrategy, list[LookupQueryMaterial]] = {
        strategy: [] for strategy in LookupStrategy
    }
    weak = {
        LookupStrategy.ARTIST_EXACT_NAME,
        LookupStrategy.ARTIST_ALIAS,
        LookupStrategy.ARTIST_TEXT,
    }
    if any(strategy in weak for strategy in strategies):
        term = search_term.strip() if search_term is not None else ""
        if not term:
            raise ValueError("artist lookup requires an explicitly selected search term")
        if len(term) > 200 or any(ord(character) < 32 for character in term):
            raise ValueError("artist lookup search term must be between 1 and 200 characters")
        for strategy in strategies:
            if strategy in weak:
                materials[strategy].append(LookupQueryMaterial(strategy, term))
    revision = _digest(
        account["account_id"],
        account["platform_key"],
        account["native_account_id"],
        account["last_seen_at"],
        account["handle"],
        account["display_name"],
        account["raw_observation_id"],
    )
    return account, materials, revision


def plan_candidate_lookup(
    database: DatabaseSource,
    seed: str,
    instance: LookupPlanConfiguration | LookupPlanContext,
    strategies: tuple[LookupStrategy | str, ...],
    *,
    limits: LookupLimits | None = None,
    search_term: str | None = None,
) -> CandidateLookupPlan:
    """Resolve finite private query material without network or catalog writes."""

    context = instance if isinstance(instance, LookupPlanContext) else instance.lookup_plan_context
    if not strategies:
        raise ValueError("at least one lookup strategy is required")
    if limits is None:
        limits = LookupLimits()
    normalized = tuple(dict.fromkeys(LookupStrategy(strategy) for strategy in strategies))
    seed_kind, seed_id = _parse_seed(seed)
    connection, owned = _connection(database)
    try:
        if seed_kind == "post":
            _, materials, revision = _post_materials(connection, seed_id)
        else:
            _, materials, revision = _account_materials(
                connection, seed_id, normalized, search_term
            )
        items: list[PlannedLookup] = []
        exclusions: list[dict[str, str]] = []
        for strategy in normalized:
            if not context.lookup_capabilities.supports(strategy):
                exclusions.append(
                    {"strategy": strategy.value, "reason": "unsupported_provider_capability"}
                )
                continue
            strategy_materials = materials[strategy]
            if not strategy_materials:
                exclusions.append({"strategy": strategy.value, "reason": "missing_seed_material"})
                continue
            for material in strategy_materials:
                contract = LookupPlanItem(
                    provider=context.provider,
                    instance=context.instance_key,
                    strategy=strategy,
                    query_digest=material.digest,
                    limits=limits.as_dict(),
                    seed_kind=seed_kind,
                    seed_id=str(seed_id),
                    adapter_version=context.adapter_version,
                    schema_version=context.schema_version,
                )
                items.append(
                    PlannedLookup(
                        contract,
                        material,
                        seed_id,
                        revision,
                        strategy.value,
                    )
                )
        return CandidateLookupPlan(
            seed,
            context.instance_key,
            limits,
            tuple(items),
            tuple(exclusions),
        )
    finally:
        if owned:
            connection.close()
