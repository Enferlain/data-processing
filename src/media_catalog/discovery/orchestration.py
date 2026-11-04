"""Discovery orchestration (roadmap P0.1): the composition entry point.

One input — a URL (materialized through the operator seed path), or an
existing post/account record — initiates a bounded discovery session.  The
planner considers the local catalog and every registered lookup-capable
provider, reporting every (source, method) pair as planned, skipped with the
source's capability reason, or excluded with why.  Local steps run as catalog
queries; provider steps run only under explicit live authorization through
the existing candidate lookup machinery.  Sessions bind results; they never
duplicate them.
"""

from __future__ import annotations

import sqlite3
import time as _time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.contracts import LookupStrategy
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU
from media_catalog.adapters.e621 import E621
from media_catalog.adapters.gelbooru import GELBOORU
from media_catalog.candidate_lookup.planning import (
    LookupLimits,
    _account_materials,
    _file_materials,
    _post_materials,
)
from media_catalog.candidate_lookup.service import CandidateLookupService
from media_catalog.link_resolution import resolve_link
from media_catalog.seeding import SeedMaterializationService

# Providers that declare bounded lookup capabilities today; safebooru/rule34/
# e926 deliberately ship none until captured, and sankaku/pixiv/pawchive have
# no lookup surface.
LOOKUP_PROVIDERS: tuple[Any, ...] = (DANBOORU, AIBOORU, E621, GELBOORU)

_LOCAL = "local"
_PROVIDER = "provider"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _session_seed_ref(session: sqlite3.Row) -> str:
    if session["seed_post_id"] is not None:
        return f"post:{session['seed_post_id']}"
    if session["seed_file_id"] is not None:
        return f"file:{session['seed_file_id']}"
    return f"account:{session['seed_account_id']}"


@dataclass(frozen=True, slots=True)
class DiscoveryStepPlan:
    source_kind: str
    source: str
    method: str
    status: str  # planned | skipped | excluded
    detail: str | None = None


class DiscoveryOrchestrator:
    """Plan and execute one discovery session over registered sources."""

    def __init__(self, database: Any) -> None:
        self._database = database
        # Posts persisted by this session's follow-up fetches; wave B plans
        # from them.  Reset on every execute() call.
        self._followup_posts: list[int] = []

    # ── Session entry ──────────────────────────────────────────────────

    def start(
        self,
        *,
        url: str | None = None,
        file: str | Path | None = None,
        media_root: str | Path | None = None,
        declared_md5: str | None = None,
        note: str | None = None,
        post_id: int | None = None,
        account_id: int | None = None,
        live: bool = False,
        request_budget: int = 12,
        time_budget_seconds: int = 120,
        search_term: str | None = None,
    ) -> dict[str, Any]:
        inputs = (url, post_id, account_id, None if url is not None else file)
        if sum(value is not None for value in inputs) != 1:
            raise ValueError("exactly one input is required (--url, --post, --account, or --file)")
        connection = self._database.connection
        input_digest: str | None = None
        seed_post: int | None = None
        seed_account: int | None = None
        seed_file: int | None = None
        input_kind: str
        if file is not None and url is None:
            # The bare-file root: intrinsic verified identity only.  The
            # session row exists before the seed so the seed can reference
            # it; no stub post, no platform identity.
            session_id = self._insert_session(
                "local_file",
                None,
                None,
                None,
                live,
                request_budget,
                time_budget_seconds,
                search_term,
            )
            result = SeedMaterializationService(self._database).materialize_file(
                file, session_id=session_id, note=note, observed_at=_now()
            )
            seed_file = int(result["file_seed_id"])
            connection.execute(
                """UPDATE discovery_sessions
                      SET seed_file_id = ?, input_digest = ?
                    WHERE discovery_session_id = ?""",
                (seed_file, f"file_seed:{seed_file}", session_id),
            )
            connection.commit()
            self.plan(session_id, seed_post=None, seed_account=None, seed_file=seed_file)
            self.execute(session_id)
            return self.report(session_id)
        if url is not None:
            result = SeedMaterializationService(self._database).materialize(
                [url],
                note=note,
                declared_md5=declared_md5,
                observed_at=_now(),
                file=file,
                media_root=media_root,
            )
            seed_post = int(result["post_id"])
            input_digest = f"seed:{result['import_run_id']}"
            input_kind = "url"
        elif post_id is not None:
            row = connection.execute(
                "SELECT post_id FROM posts WHERE post_id = ?", (post_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"post {post_id} not found")
            seed_post = post_id
            input_kind = "post"
        else:
            assert account_id is not None
            row = connection.execute(
                "SELECT account_id FROM accounts WHERE account_id = ?", (account_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"account {account_id} not found")
            seed_account = account_id
            input_kind = "account"

        session_id = self._insert_session(
            input_kind,
            seed_post,
            seed_account,
            input_digest,
            live,
            request_budget,
            time_budget_seconds,
        )
        self.plan(
            session_id, seed_post=seed_post, seed_account=seed_account, search_term=search_term
        )
        # Local steps are catalog queries: they always run.  Provider steps
        # run only when the session carries live authorization.
        self.execute(session_id)
        return self.report(session_id)

    # ── Planning ───────────────────────────────────────────────────────

    def plan(
        self,
        session_id: int,
        *,
        seed_post: int | None,
        seed_account: int | None,
        search_term: str | None = None,
        seed_file: int | None = None,
    ) -> list[DiscoveryStepPlan]:
        connection = self._database.connection
        steps: list[DiscoveryStepPlan] = []
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
                _, materials, _ = _account_materials(
                    connection, seed_account, strategies, search_term
                )
            except ValueError:
                # Artist strategies need an operator-supplied search term;
                # without one they resolve to "no material" and the planner
                # reports them excluded rather than failing the session.
                materials = {}

        # Local steps: the three questions the catalog answers offline.  An
        # account seed carries none of the post-shaped material, so those
        # methods are excluded naming the missing material.  A file seed
        # carries its verified hash, so the md5 search runs; the two
        # url-shaped methods name the material a bare file cannot carry.
        for method, exclusion_reason in (
            (
                "local_md5",
                None
                if seed_post is not None or seed_file is not None
                else "account seed carries no post material",
            ),
            (
                "local_source_url",
                None if seed_post is not None else "seed carries no source url material",
            ),
            (
                "local_platform_identity",
                None if seed_post is not None else "seed carries no platform identity material",
            ),
        ):
            steps.append(
                DiscoveryStepPlan(
                    source_kind=_LOCAL,
                    source="catalog",
                    method=method,
                    status="planned" if exclusion_reason is None else "excluded",
                    detail=exclusion_reason,
                )
            )

        # Provider steps: one per (provider, strategy), planned when the
        # provider declares it and the seed carries material, excluded when
        # the material is missing, skipped when undeclared.
        for provider in LOOKUP_PROVIDERS:
            context = provider.lookup_plan_context
            for strategy in LookupStrategy:
                has_material = bool(materials.get(strategy))
                declared = context.lookup_capabilities.supports(strategy)
                if has_material and declared:
                    detail = None
                    status = "planned"
                elif declared:
                    detail = "no query material on the seed for this strategy"
                    status = "excluded"
                else:
                    detail = f"{provider.platform_key} does not declare this strategy"
                    status = "skipped"
                steps.append(
                    DiscoveryStepPlan(
                        source_kind=_PROVIDER,
                        source=provider.platform_key,
                        method=strategy.value,
                        status=status,
                        detail=detail,
                    )
                )
        self._store_steps(session_id, steps)
        return steps

    # ── Execution ──────────────────────────────────────────────────────

    def execute(self, session_id: int) -> None:
        connection = self._database.connection
        self._followup_posts = []
        session = connection.execute(
            """SELECT discovery_session_id, seed_post_id, seed_account_id,
                      seed_file_id, live_authorized, request_budget,
                      time_budget_seconds, search_term
                 FROM discovery_sessions WHERE discovery_session_id = ?""",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError(f"discovery session {session_id} not found")
        budget_total = int(session["request_budget"] or 0)
        deadline = _time.monotonic() + int(session["time_budget_seconds"] or 120)
        search_term = session["search_term"]
        spent = 0
        rows = connection.execute(
            """SELECT discovery_step_id, source_kind, source, method, status,
                      target, seed_post_id, generation
                 FROM discovery_steps WHERE discovery_session_id = ?
                ORDER BY step_order""",
            (session_id,),
        ).fetchall()
        for row in rows:
            if row["source_kind"] == _LOCAL:
                if row["status"] == "planned":
                    self._execute_local(session, row)
            elif row["status"] == "planned":
                if not session["live_authorized"]:
                    continue
                remaining = budget_total - spent
                if _time.monotonic() >= deadline:
                    self._finish_step(
                        row["discovery_step_id"],
                        "failed",
                        outcome="budget_exhausted",
                        detail="session time budget spent",
                        result_count=0,
                    )
                    continue
                remaining_seconds = max(1, int(deadline - _time.monotonic()))
                if remaining <= 0:
                    self._finish_step(
                        row["discovery_step_id"],
                        "failed",
                        outcome="budget_exhausted",
                        detail=f"session request budget {budget_total} spent",
                        result_count=0,
                    )
                    continue
                spent += self._execute_provider(
                    _session_seed_ref(session), row, remaining, remaining_seconds, search_term
                )
        connection.commit()

        # Generational follow-up: when live provider lookups hit, the hits
        # are fetched and their normalized references become one further
        # bounded generation of steps.  Hard cap: a single follow-up
        # generation; anything it reveals is material for a future session.
        if session["live_authorized"]:
            followed = self._plan_followup(session)
            for row in followed:
                remaining = budget_total - spent
                if _time.monotonic() >= deadline or remaining <= 0:
                    self._finish_step(
                        row["discovery_step_id"],
                        "failed",
                        outcome="budget_exhausted",
                        detail="session budget spent before follow-up",
                        result_count=0,
                    )
                    continue
                remaining_seconds = max(1, int(deadline - _time.monotonic()))
                spent += self._execute_followup(session, row, remaining, remaining_seconds)
            # Wave B: only after wave-A fetches persisted their posts can the
            # posts' normalized references become further steps.
            if self._followup_posts:
                for row in self._plan_followup_from_posts(session, list(self._followup_posts)):
                    remaining = budget_total - spent
                    if _time.monotonic() >= deadline or remaining <= 0:
                        self._finish_step(
                            row["discovery_step_id"],
                            "failed",
                            outcome="budget_exhausted",
                            detail="session budget spent before wave-B follow-up",
                            result_count=0,
                        )
                        continue
                    remaining_seconds = max(1, int(deadline - _time.monotonic()))
                    spent += self._execute_followup(session, row, remaining, remaining_seconds)

    def _execute_local(self, session: sqlite3.Row, row: sqlite3.Row) -> None:
        seed_post = session["seed_post_id"]
        if row["method"] == "local_md5":
            if seed_post is not None:
                count, detail = self._local_md5(seed_post)
            else:
                count, detail = self._local_md5_from_file(session["seed_file_id"])
        elif row["method"] == "local_source_url":
            count, detail = self._local_source_url(seed_post)
        else:
            count, detail = self._local_identity(seed_post)
        self._finish_step(
            row["discovery_step_id"],
            "complete",
            outcome="success",
            detail=detail,
            result_count=count,
        )

    def _local_md5_from_file(self, seed_file: int | None) -> tuple[int, str | None]:
        connection = self._database.connection
        assert seed_file is not None
        seed = connection.execute(
            "SELECT verified_md5, verified_sha256 FROM discovery_file_seeds"
            " WHERE discovery_file_seed_id = ?",
            (seed_file,),
        ).fetchone()
        assert seed is not None
        hashes = (seed["verified_md5"], seed["verified_sha256"])
        placeholders = ",".join("?" for _ in hashes)
        hits = connection.execute(
            f"""SELECT COUNT(DISTINCT oa.asset_id)
                  FROM occurrence_assets oa
                  JOIN asset_fingerprints f ON f.asset_id = oa.asset_id
                 WHERE f.fingerprint_value IN ({placeholders})""",
            hashes,
        ).fetchone()[0]
        return int(hits), "file seed verified hash(es) searched"

    def _local_md5(self, seed_post: int | None) -> tuple[int, str | None]:
        connection = self._database.connection
        assert seed_post is not None
        rows = connection.execute(
            """SELECT DISTINCT f.fingerprint_value
                 FROM media_occurrences o
                 JOIN occurrence_assets oa USING(media_occurrence_id)
                 JOIN asset_fingerprints f ON f.asset_id = oa.asset_id
                WHERE o.post_id = ? AND f.fingerprint_kind IN ('md5', 'sha256')""",
            (seed_post,),
        ).fetchall()
        if not rows:
            return 0, "seed carries no verified or declared hash"
        hashes = [row["fingerprint_value"] for row in rows]
        placeholders = ",".join("?" for _ in hashes)
        hits = connection.execute(
            f"""SELECT COUNT(DISTINCT oa.asset_id)
                  FROM occurrence_assets oa
                  JOIN asset_fingerprints f ON f.asset_id = oa.asset_id
                 WHERE f.fingerprint_value IN ({placeholders})
                   AND oa.media_occurrence_id NOT IN
                       (SELECT media_occurrence_id FROM media_occurrences
                         WHERE post_id = ?)""",
            (*hashes, seed_post),
        ).fetchone()[0]
        return int(hits), f"{len(hashes)} seed hash(es) searched"

    def _local_source_url(self, seed_post: int | None) -> tuple[int, str | None]:
        connection = self._database.connection
        assert seed_post is not None
        urls = [
            row["canonical_url"]
            for row in connection.execute(
                """SELECT DISTINCT l.canonical_url
                     FROM post_external_references r
                     JOIN external_links l USING(external_link_id)
                    WHERE r.post_id = ? AND r.reference_kind = 'source_url'""",
                (seed_post,),
            )
        ]
        if not urls:
            return 0, "seed carries no source url"
        placeholders = ",".join("?" for _ in urls)
        hits = connection.execute(
            f"""SELECT COUNT(DISTINCT r2.post_id)
                  FROM post_external_references r2
                  JOIN external_links l2 USING(external_link_id)
                 WHERE l2.canonical_url IN ({placeholders}) AND r2.post_id != ?""",
            (*urls, seed_post),
        ).fetchone()[0]
        return int(hits), f"{len(urls)} seed source url(s) searched"

    def _local_identity(self, seed_post: int | None) -> tuple[int, str | None]:
        connection = self._database.connection
        assert seed_post is not None
        row = connection.execute(
            "SELECT canonical_url FROM posts WHERE post_id = ?", (seed_post,)
        ).fetchone()
        if row is None or not row["canonical_url"]:
            return 0, "seed post carries no canonical url"
        hits = connection.execute(
            "SELECT COUNT(*) FROM posts WHERE canonical_url = ? AND post_id != ?",
            (row["canonical_url"], seed_post),
        ).fetchone()[0]
        return int(hits), "seed canonical url searched"

    def _execute_provider(
        self,
        seed_ref: str,
        row: sqlite3.Row,
        remaining_budget: int,
        remaining_seconds: int,
        search_term: str | None = None,
    ) -> int:
        platform = row["source"]
        strategy = LookupStrategy(row["method"])
        seed = seed_ref
        import httpx

        try:
            factory, interval = adapter_construction(platform)
            with httpx.Client() as client:
                adapter = factory(client)
                service = CandidateLookupService(
                    self._database, adapter, minimum_interval_seconds=interval
                )
                plan = service.plan(
                    seed,
                    (strategy,),
                    limits=LookupLimits(remaining_budget, 2, 50, remaining_seconds),
                    search_term=search_term,
                )
                results = service.execute(plan)
        except Exception as error:
            self._finish_step(
                row["discovery_step_id"],
                "failed",
                outcome="error",
                detail=f"{type(error).__name__}: {error}",
                result_count=0,
            )
            return 0
        total_requests = sum(result.request_count for result in results)
        run_ids = [result.candidate_lookup_run_id for result in results]
        ok = all(result.status == "complete" for result in results)
        self._finish_step(
            row["discovery_step_id"],
            "complete" if ok else "failed",
            outcome="success" if ok else "provider_failure",
            detail=f"lookup run(s) {run_ids}",
            result_count=sum(result.result_count for result in results),
            run_id=run_ids[0] if run_ids and run_ids[0] > 0 else None,
        )
        return total_requests

    # ── Generational follow-up ─────────────────────────────────────────

    def _existing_step_identities(self, session_id: int) -> set[tuple[str, str, str]]:
        rows = self._database.connection.execute(
            """SELECT source, method, COALESCE(target, '')
                 FROM discovery_steps WHERE discovery_session_id = ?""",
            (session_id,),
        ).fetchall()
        return {(row[0], row[1], row[2]) for row in rows}

    def _plan_followup(self, session: sqlite3.Row) -> list[sqlite3.Row]:
        """Wave A: fetch a post for every hit this session's lookups found.

        The hits' normalized references are consumed by wave B once their
        posts are persisted (see ``_plan_followup_from_posts``).
        """
        connection = self._database.connection
        session_id = session["discovery_session_id"]
        hits = connection.execute(
            """SELECT DISTINCT p.platform_key, po.native_post_id
                 FROM candidate_lookup_runs run
                 JOIN candidate_lookup_results r
                   ON r.candidate_lookup_run_id = run.candidate_lookup_run_id
                 JOIN platforms p ON p.platform_id = run.platform_id
                 JOIN posts po ON po.post_id = r.normalized_post_id
                WHERE (run.seed_file_id = ?
                       OR run.seed_post_id = ?
                       OR run.seed_account_id = ?)
                  AND r.result_kind = 'post_match'
                  AND r.normalized_post_id IS NOT NULL""",
            (
                session["seed_file_id"],
                session["seed_post_id"],
                session["seed_account_id"],
            ),
        ).fetchall()
        existing = self._existing_step_identities(session_id)
        planned: list[int] = []
        for hit in hits:
            # The provider-native id is the fetch target; the local surrogate
            # post id is never a provider identity.
            native_id = str(hit["native_post_id"])
            identity = (hit["platform_key"], "fetch_post", native_id)
            if identity in existing:
                continue
            existing.add(identity)
            planned.append(
                self._insert_step(
                    session_id,
                    source_kind=_PROVIDER,
                    source=hit["platform_key"],
                    method="fetch_post",
                    status="planned",
                    detail="fetch the hit post so its references become material",
                    generation=1,
                    target=native_id,
                )
            )
        connection.commit()
        if not planned:
            return []
        return connection.execute(
            f"""SELECT discovery_step_id, source_kind, source, method, status, target
                  FROM discovery_steps WHERE discovery_step_id IN
                  ({",".join("?" for _ in planned)}) ORDER BY step_order""",
            planned,
        ).fetchall()

    def _plan_followup_from_posts(
        self,
        session: sqlite3.Row,
        post_ids: list[int],
    ) -> list[sqlite3.Row]:
        """Wave B: reverse lookups and source fetches from fetched posts."""
        connection = self._database.connection
        session_id = session["discovery_session_id"]
        existing = self._existing_step_identities(session_id)
        planned: list[int] = []
        for post_id in post_ids:
            try:
                _, materials, _ = _post_materials(connection, post_id)
            except ValueError:
                continue
            for provider in LOOKUP_PROVIDERS:
                context = provider.lookup_plan_context
                for strategy, values in materials.items():
                    if not values or not context.lookup_capabilities.supports(strategy):
                        continue
                    if strategy.value.startswith("artist_"):
                        # Artist strategies need operator search terms; a
                        # follow-up generation never invents them.
                        continue
                    for material in values:
                        # One step per material: execution replays the whole
                        # material (all its values) in a single run, so the
                        # plan must not split one material across steps.
                        identity = (provider.platform_key, strategy.value, material.digest)
                        if identity in existing:
                            continue
                        existing.add(identity)
                        planned.append(
                            self._insert_step(
                                session_id,
                                source_kind=_PROVIDER,
                                source=provider.platform_key,
                                method=strategy.value,
                                status="planned",
                                detail=f"reverse lookup from fetched post {post_id}",
                                generation=1,
                                target=material.digest,
                                seed_post_id=post_id,
                            )
                        )
            for material in materials.get(LookupStrategy.SOURCE_POST_URL, ()):
                for url in material.values:
                    try:
                        resolved = resolve_link(url)
                    except ValueError:
                        continue
                    identity = (resolved.platform, "fetch_post", resolved.target)
                    if identity in existing:
                        continue
                    existing.add(identity)
                    planned.append(
                        self._insert_step(
                            session_id,
                            source_kind=_PROVIDER,
                            source=resolved.platform,
                            method="fetch_post",
                            status="planned",
                            detail=f"source link from fetched post {post_id}",
                            generation=1,
                            target=resolved.target,
                        )
                    )
        connection.commit()
        if not planned:
            return []
        return connection.execute(
            f"""SELECT discovery_step_id, source_kind, source, method, status, target,
                       seed_post_id
                  FROM discovery_steps WHERE discovery_step_id IN
                  ({",".join("?" for _ in planned)}) ORDER BY step_order""",
            planned,
        ).fetchall()

    def _execute_followup(
        self,
        session: sqlite3.Row,
        row: sqlite3.Row,
        remaining_budget: int,
        remaining_seconds: int,
    ) -> int:
        """Execute one follow-up step; returns its persisted post id count
        via ``self._followup_posts`` accumulation and requests spent."""
        import httpx

        from media_catalog.remote_sync import MetadataSyncService, SyncLimits

        if row["method"] == "fetch_post":
            platform, target = row["source"], str(row["target"])
            try:
                factory, interval = adapter_construction(platform)
                with httpx.Client() as client:
                    adapter = factory(client)
                    result = MetadataSyncService(
                        self._database,
                        adapter,
                        minimum_interval_seconds=interval,
                    ).synchronize(
                        AdapterOperation.FETCH_POST,
                        target,
                        limits=SyncLimits(remaining_budget, 1, 50, remaining_seconds),
                    )
            except Exception as error:
                self._finish_step(
                    row["discovery_step_id"],
                    "failed",
                    outcome="error",
                    detail=f"{type(error).__name__}: {error}",
                    result_count=0,
                )
                return 0
            if result.outcome == "success":
                connection = self._database.connection
                post = connection.execute(
                    """SELECT po.post_id FROM posts po
                         JOIN platforms p ON p.platform_id = po.platform_id
                        WHERE p.platform_key = ? AND po.native_post_id = ?""",
                    (platform, target),
                ).fetchone()
                if post is not None:
                    self._followup_posts.append(int(post["post_id"]))
            # A fetch produces a remote run, not a candidate lookup run;
            # the step's candidate_lookup_run_id FK stays NULL and the run
            # is named in the detail.
            self._finish_step(
                row["discovery_step_id"],
                "complete" if result.status == "complete" else "failed",
                outcome="success" if result.status == "complete" else "provider_failure",
                detail=f"remote run {result.remote_run_id}",
                result_count=result.record_count,
            )
            return result.request_count
        # Reverse lookup step: material lives on the fetched seed post, so
        # dispatch through the ordinary provider path with that seed.
        return self._execute_provider(
            f"post:{row['seed_post_id']}",
            row,
            remaining_budget,
            remaining_seconds,
            session["search_term"],
        )

    def _insert_step(
        self,
        session_id: int,
        *,
        source_kind: str,
        source: str,
        method: str,
        status: str,
        detail: str | None,
        generation: int,
        target: str | None,
        seed_post_id: int | None = None,
    ) -> int:
        order = self._database.connection.execute(
            "SELECT COALESCE(MAX(step_order), -1) + 1 FROM discovery_steps"
            " WHERE discovery_session_id = ?",
            (session_id,),
        ).fetchone()[0]
        cursor = self._database.connection.execute(
            """INSERT INTO discovery_steps
                   (discovery_session_id, step_order, source_kind, source,
                    method, status, detail, generation, target, seed_post_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                order,
                source_kind,
                source,
                method,
                status,
                detail,
                generation,
                target,
                seed_post_id,
            ),
        )
        step_id = cursor.lastrowid
        assert step_id is not None
        return int(step_id)

    # ── Persistence ────────────────────────────────────────────────────

    def _insert_session(
        self,
        input_kind: str,
        seed_post: int | None,
        seed_account: int | None,
        input_digest: str | None,
        live: bool,
        request_budget: int,
        time_budget_seconds: int,
        search_term: str | None = None,
    ) -> int:
        cursor = self._database.connection.execute(
            """INSERT INTO discovery_sessions
                   (input_kind, seed_post_id, seed_account_id, input_digest,
                    live_authorized, status, request_budget, time_budget_seconds,
                    search_term, started_at)
               VALUES (?, ?, ?, ?, ?, 'planning', ?, ?, ?, ?)""",
            (
                input_kind,
                seed_post,
                seed_account,
                input_digest,
                int(live),
                request_budget,
                time_budget_seconds,
                search_term,
                _now(),
            ),
        )
        return int(cursor.lastrowid)

    def _store_steps(self, session_id: int, steps: list[DiscoveryStepPlan]) -> None:
        connection = self._database.connection
        connection.execute(
            "DELETE FROM discovery_steps WHERE discovery_session_id = ?", (session_id,)
        )
        for order, step in enumerate(steps):
            connection.execute(
                """INSERT INTO discovery_steps
                       (discovery_session_id, step_order, source_kind, source,
                        method, status, outcome, result_count, detail)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?)""",
                (
                    session_id,
                    order,
                    step.source_kind,
                    step.source,
                    step.method,
                    step.status,
                    step.detail,
                ),
            )
        connection.execute(
            """UPDATE discovery_sessions
                  SET step_count = ?, status = 'planned'
                WHERE discovery_session_id = ?""",
            (len(steps), session_id),
        )
        connection.commit()

    def _finish_step(
        self,
        step_id: int,
        status: str,
        *,
        outcome: str | None,
        detail: str | None,
        result_count: int,
        run_id: int | None = None,
    ) -> None:
        self._database.connection.execute(
            """UPDATE discovery_steps
                  SET status = ?, outcome = ?, detail = ?, result_count = ?,
                      candidate_lookup_run_id = COALESCE(?, candidate_lookup_run_id)
                WHERE discovery_step_id = ?""",
            (status, outcome, detail, result_count, run_id, step_id),
        )
        # Step outcomes commit immediately: any later provider step's
        # lookup planning snapshots the catalog (sqlite backup), and an
        # open write transaction here would block that snapshot forever.
        self._database.connection.commit()

    # ── Reporting ──────────────────────────────────────────────────────

    def report(self, session_id: int) -> dict[str, Any]:
        connection = self._database.connection
        session = connection.execute(
            "SELECT * FROM discovery_sessions WHERE discovery_session_id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError(f"discovery session {session_id} not found")
        steps = [
            dict(row)
            for row in connection.execute(
                """SELECT source_kind, source, method, status, outcome,
                          result_count, detail, candidate_lookup_run_id,
                          generation, target
                     FROM discovery_steps WHERE discovery_session_id = ?
                    ORDER BY step_order""",
                (session_id,),
            )
        ]
        generations = [
            {
                "generation": generation,
                "steps": [step for step in steps if step["generation"] == generation],
            }
            for generation in sorted({step["generation"] for step in steps})
        ]
        pending = any(step["status"] == "planned" for step in steps)
        status = "planned" if pending else "complete"
        if session["finished_at"] is None:
            connection.execute(
                """UPDATE discovery_sessions
                      SET status = ?, finished_at = ?
                    WHERE discovery_session_id = ?""",
                (status, _now(), session_id),
            )
            connection.commit()
        result: dict[str, Any] = {
            "session_id": session_id,
            "input_kind": session["input_kind"],
            "seed_post_id": session["seed_post_id"],
            "seed_account_id": session["seed_account_id"],
            "seed_file_id": session["seed_file_id"],
            "live_authorized": bool(session["live_authorized"]),
            "status": status,
            "steps": steps,
        }
        if session["seed_file_id"] is not None:
            # The file seed's identity is intrinsic evidence; the operator's
            # local path stays out of the report.
            seed_row = connection.execute(
                """SELECT verified_md5, verified_sha256, width, height,
                          mime_type, byte_size
                     FROM discovery_file_seeds
                    WHERE discovery_file_seed_id = ?""",
                (session["seed_file_id"],),
            ).fetchone()
            if seed_row is not None:
                result["file_seed"] = dict(seed_row)
        if any(step["generation"] > 0 for step in steps):
            result["generations"] = generations
        return result
