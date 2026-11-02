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
from media_catalog.adapters.contracts import LookupStrategy
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU
from media_catalog.adapters.e621 import E621
from media_catalog.adapters.gelbooru import GELBOORU
from media_catalog.candidate_lookup.planning import (
    LookupLimits,
    _account_materials,
    _post_materials,
)
from media_catalog.candidate_lookup.service import CandidateLookupService
from media_catalog.seeding import SeedMaterializationService

# Providers that declare bounded lookup capabilities today; safebooru/rule34/
# e926 deliberately ship none until captured, and sankaku/pixiv/pawchive have
# no lookup surface.
LOOKUP_PROVIDERS: tuple[Any, ...] = (DANBOORU, AIBOORU, E621, GELBOORU)

_LOCAL = "local"
_PROVIDER = "provider"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
        if (url is not None) + (post_id is not None) + (account_id is not None) != 1:
            raise ValueError("exactly one input is required (--url, --post, or --account)")
        connection = self._database.connection
        input_digest: str | None = None
        seed_post: int | None = None
        seed_account: int | None = None
        input_kind: str
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
    ) -> list[DiscoveryStepPlan]:
        connection = self._database.connection
        steps: list[DiscoveryStepPlan] = []
        materials: dict[LookupStrategy, list[Any]] = {}
        if seed_post is not None:
            _, materials, _ = _post_materials(connection, seed_post)
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
        # methods are excluded naming the missing material.
        for method, requires_post in (
            ("local_md5", True),
            ("local_source_url", True),
            ("local_platform_identity", True),
        ):
            excluded = requires_post and seed_post is None
            steps.append(
                DiscoveryStepPlan(
                    source_kind=_LOCAL,
                    source="catalog",
                    method=method,
                    status="excluded" if excluded else "planned",
                    detail="account seed carries no post material" if excluded else None,
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
        session = connection.execute(
            """SELECT discovery_session_id, seed_post_id, seed_account_id,
                      live_authorized, request_budget, time_budget_seconds,
                      search_term
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
            """SELECT discovery_step_id, source_kind, source, method, status
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
                    session, row, remaining, remaining_seconds, search_term
                )
        connection.commit()

    def _execute_local(self, session: sqlite3.Row, row: sqlite3.Row) -> None:
        seed_post = session["seed_post_id"]
        if row["method"] == "local_md5":
            count, detail = self._local_md5(seed_post)
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
        session: sqlite3.Row,
        row: sqlite3.Row,
        remaining_budget: int,
        remaining_seconds: int,
        search_term: str | None = None,
    ) -> int:
        platform = row["source"]
        strategy = LookupStrategy(row["method"])
        seed = (
            f"post:{session['seed_post_id']}"
            if session["seed_post_id"] is not None
            else f"account:{session['seed_account_id']}"
        )
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
                          result_count, detail, candidate_lookup_run_id
                     FROM discovery_steps WHERE discovery_session_id = ?
                    ORDER BY step_order""",
                (session_id,),
            )
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
        return {
            "session_id": session_id,
            "input_kind": session["input_kind"],
            "seed_post_id": session["seed_post_id"],
            "seed_account_id": session["seed_account_id"],
            "live_authorized": bool(session["live_authorized"]),
            "status": status,
            "steps": steps,
        }
