"""Discovery orchestration (roadmap P0.1): the composition entry point.

One session binds one subject (seed post/account/file) to planned and executed
search steps.  Policy, freshness, and the attempt ledger live in
:mod:`media_catalog.discovery.policy`, :mod:`media_catalog.discovery.planning`,
and :mod:`media_catalog.discovery.attempts`; this module persists and executes
their decisions (change add-discovery-search-policy).
"""

from __future__ import annotations

import json
import sqlite3
import time as _time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters import AdapterOperation
from media_catalog.adapters.contracts import LookupStrategy
from media_catalog.candidate_lookup.planning import (
    LookupLimits,
    _account_materials,
    _file_materials,
    _post_materials,
)
from media_catalog.candidate_lookup.service import CandidateLookupService
from media_catalog.discovery.attempts import SearchAttemptLedger, SubjectRef
from media_catalog.discovery.planning import (
    INDEX,
    LOCAL,
    LOOKUP_PROVIDERS,
    PLANNED,
    PROVIDER,
    SKIPPED,
    PlannedSearch,
    evidence_digest,
    file_seed_hashes,
    plan_searches,
    post_canonical_url,
    post_hash_evidence,
    post_source_urls,
)
from media_catalog.discovery.policy import (
    FETCH_METHOD,
    SearchPolicy,
    freshness_verdict,
    method_version,
    policy_from_dict,
)
from media_catalog.link_resolution import resolve_link
from media_catalog.records import SearchAttemptRecord
from media_catalog.search_index.projection import lookup as index_lookup
from media_catalog.search_index.projection import target_by_name
from media_catalog.seeding import SeedMaterializationService

DEFERRED = "deferred"
RUNNING = "running"

_LOOKUP_PAGES = 2
_LOOKUP_RESULTS = 50


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _session_seed_ref(session: sqlite3.Row) -> str:
    if session["seed_post_id"] is not None:
        return f"post:{session['seed_post_id']}"
    if session["seed_file_id"] is not None:
        return f"file:{session['seed_file_id']}"
    return f"account:{session['seed_account_id']}"


def _session_subject(session: sqlite3.Row) -> SubjectRef:
    return SubjectRef(
        post_id=session["seed_post_id"],
        account_id=session["seed_account_id"],
        file_id=session["seed_file_id"],
    )


def _seed_platform(connection: sqlite3.Connection, session: sqlite3.Row) -> str | None:
    """The platform key of the session's seed post, when it is one."""
    if session["seed_post_id"] is None:
        return None
    row = connection.execute(
        """SELECT platform.platform_key FROM posts p
             JOIN platforms platform ON platform.platform_id = p.platform_id
            WHERE p.post_id = ?""",
        (int(session["seed_post_id"]),),
    ).fetchone()
    return str(row["platform_key"]) if row else None


@dataclass(frozen=True, slots=True)
class _StepExecution:
    """What one executed provider/fetch step did, for step and attempt rows."""

    status: str
    outcome: str
    detail: str
    result_count: int
    requests_used: int
    run_id: int | None = None


class DiscoveryOrchestrator:
    """Plan and execute one discovery session over registered sources."""

    def __init__(self, database: Any) -> None:
        self._database = database
        # Posts persisted by this session's follow-up fetches; wave B plans
        # from them.  Reset on every execute() call.
        self._followup_posts: list[int] = []

    @property
    def _ledger(self) -> SearchAttemptLedger:
        return SearchAttemptLedger(self._database.connection)

    def _session_policy(self, session: sqlite3.Row) -> SearchPolicy:
        raw = session["policy_json"]
        if raw:
            return policy_from_dict(json.loads(raw))
        return SearchPolicy().with_search_term(session["search_term"])

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
        policy: SearchPolicy | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        inputs = (url, post_id, account_id, None if url is not None else file)
        if sum(value is not None for value in inputs) != 1:
            raise ValueError("exactly one input is required (--url, --post, --account, or --file)")
        if policy is None:
            policy = SearchPolicy().with_search_term(search_term)
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
                policy,
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
            self.plan(
                session_id,
                seed_post=None,
                seed_account=None,
                seed_file=seed_file,
                policy=policy,
            )
            if not dry_run:
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
            policy,
            search_term,
        )
        self.plan(
            session_id,
            seed_post=seed_post,
            seed_account=seed_account,
            search_term=search_term,
            policy=policy,
        )
        # Local steps are catalog queries: they always run.  Provider steps
        # run only when the session carries live authorization.  A dry run
        # stops after planning: nothing executes, nothing is attempted.
        if not dry_run:
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
        policy: SearchPolicy | None = None,
    ) -> list[PlannedSearch]:
        if policy is None:
            policy = SearchPolicy().with_search_term(search_term)
        steps = plan_searches(
            self._database.connection,
            seed_post=seed_post,
            seed_account=seed_account,
            seed_file=seed_file,
            search_term=search_term,
            policy=policy,
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
                      time_budget_seconds, search_term, requests_used,
                      policy_json
                 FROM discovery_sessions WHERE discovery_session_id = ?""",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ValueError(f"discovery session {session_id} not found")
        policy = self._session_policy(session)
        subject = _session_subject(session)
        budget_total = int(session["request_budget"] or 0)
        deadline = _time.monotonic() + int(session["time_budget_seconds"] or 120)
        search_term = session["search_term"]
        spent = int(session["requests_used"] or 0)
        rows = connection.execute(
            """SELECT discovery_step_id, source_kind, source, method, status,
                      target, seed_post_id, generation, query_digest
                 FROM discovery_steps WHERE discovery_session_id = ?
                ORDER BY step_order""",
            (session_id,),
        ).fetchall()
        for row in rows:
            if row["status"] != PLANNED:
                continue
            if row["source_kind"] == LOCAL:
                self._run_local_step(session, row, subject)
                continue
            if row["source_kind"] == INDEX:
                # Index steps are local reads: offline like the catalog
                # steps, no request budget, ordered before providers.
                self._run_index_step(session, row, subject)
                continue
            if not session["live_authorized"]:
                continue
            remaining = budget_total - spent
            if _time.monotonic() >= deadline:
                self._defer_step(session, row, "session time budget spent")
                continue
            if remaining <= 0:
                self._defer_step(session, row, f"session request budget {budget_total} spent")
                continue
            remaining_seconds = max(1, int(deadline - _time.monotonic()))
            spent += self._run_remote_step(
                session, row, subject, remaining, remaining_seconds, search_term
            )
        connection.commit()

        # Generational follow-up: when live provider lookups hit, the hits
        # are fetched and their normalized references become one further
        # bounded generation of steps.  Hard cap: a single follow-up
        # generation; anything it reveals is material for a future session.
        if session["live_authorized"]:
            followed = self._plan_followup(session, policy, subject)
            for row in followed:
                if row["status"] != PLANNED:
                    # Fresh-skipped follow-ups stay skipped: neither executed
                    # nor deferred (deferral would claim unstarted work).
                    continue
                remaining = budget_total - spent
                if _time.monotonic() >= deadline or remaining <= 0:
                    self._defer_step(session, row, "session budget spent before follow-up")
                    continue
                remaining_seconds = max(1, int(deadline - _time.monotonic()))
                spent += self._run_remote_step(
                    session, row, subject, remaining, remaining_seconds, search_term
                )
            # Wave B: only after wave-A fetches persisted their posts can the
            # posts' normalized references become further steps.
            if self._followup_posts:
                for row in self._plan_followup_from_posts(
                    session, list(self._followup_posts), policy, subject
                ):
                    if row["status"] != PLANNED:
                        continue
                    remaining = budget_total - spent
                    if _time.monotonic() >= deadline or remaining <= 0:
                        self._defer_step(
                            session, row, "session budget spent before wave-B follow-up"
                        )
                        continue
                    remaining_seconds = max(1, int(deadline - _time.monotonic()))
                    spent += self._run_remote_step(
                        session, row, subject, remaining, remaining_seconds, search_term
                    )

    def _run_local_step(
        self,
        session: sqlite3.Row,
        row: sqlite3.Row,
        subject: SubjectRef,
    ) -> None:
        """Execute one catalog step and record its attempt in the ledger."""
        attempt_id = self._begin_attempt(session, row, subject)
        count, detail = self._execute_local(session, row)
        self._finish_step(
            session["discovery_session_id"],
            row["discovery_step_id"],
            "complete",
            outcome="success",
            detail=detail,
            result_count=count,
        )
        if attempt_id is not None:
            self._ledger.finish(
                attempt_id,
                status="complete",
                outcome="success",
                result_count=count,
                scope=detail,
                requests_used=0,
                finished_at=_now(),
            )

    def _run_remote_step(
        self,
        session: sqlite3.Row,
        row: sqlite3.Row,
        subject: SubjectRef,
        remaining_budget: int,
        remaining_seconds: int,
        search_term: str | None,
    ) -> int:
        """Execute one provider/fetch step; returns requests spent."""
        limits = LookupLimits(remaining_budget, _LOOKUP_PAGES, _LOOKUP_RESULTS, remaining_seconds)
        scope = (
            f"bounded lookup: requests<={limits.requests}, pages<={limits.pages},"
            f" results<={limits.results}, {limits.seconds}s"
        )
        attempt_id = self._begin_attempt(session, row, subject)
        if row["method"] == FETCH_METHOD:
            execution = self._execute_fetch(session, row, limits)
            scope = f"fetch post {row['source']}:{row['target']}"
        else:
            execution = self._execute_provider(
                _session_seed_ref(session)
                if row["seed_post_id"] is None
                else f"post:{row['seed_post_id']}",
                row,
                remaining_budget,
                remaining_seconds,
                search_term,
            )
        self._finish_step(
            session["discovery_session_id"],
            row["discovery_step_id"],
            execution.status,
            outcome=execution.outcome,
            detail=execution.detail,
            result_count=execution.result_count,
            run_id=execution.run_id,
            requests_used=execution.requests_used,
        )
        if attempt_id is not None:
            self._ledger.finish(
                attempt_id,
                status="complete" if execution.status == "complete" else "failed",
                outcome=execution.outcome,
                result_count=execution.result_count,
                scope=scope,
                requests_used=execution.requests_used,
                finished_at=_now(),
                candidate_lookup_run_id=execution.run_id,
            )
        return execution.requests_used

    def _begin_attempt(
        self, session: sqlite3.Row, row: sqlite3.Row, subject: SubjectRef
    ) -> int | None:
        """Mark the step running and open its ledger attempt.

        Legacy steps planned before the evidence digest existed carry none;
        they execute exactly as before, just without a ledger row.
        """
        if row["query_digest"] is None:
            return None
        self._database.connection.execute(
            "UPDATE discovery_steps SET status = ? WHERE discovery_step_id = ?",
            (RUNNING, row["discovery_step_id"]),
        )
        # Index steps stamp the projection's snapshot revision (carried in
        # target) as their strategy version: refresh ⇒ replan.
        version = row["target"] if row["source_kind"] == INDEX else method_version(row["method"])
        record = SearchAttemptRecord(
            source_kind=row["source_kind"],
            source=row["source"],
            method=row["method"],
            strategy_version=version,
            query_digest=row["query_digest"],
            status="running",
            started_at=_now(),
            discovery_session_id=session["discovery_session_id"],
            discovery_step_id=row["discovery_step_id"],
            subject_post_id=subject.post_id,
            subject_account_id=subject.account_id,
            subject_file_id=subject.file_id,
        )
        attempt_id = self._ledger.begin(record)
        # Commit the in-flight state: later execution paths open their own
        # catalog transactions, and a crash must leave the running attempt
        # visible rather than rolled back.
        self._database.connection.commit()
        return attempt_id

    def _run_index_step(
        self,
        session: sqlite3.Row,
        row: sqlite3.Row,
        subject: SubjectRef,
    ) -> None:
        """Execute one offline index lookup and record hits as leads."""
        connection = self._database.connection
        attempt_id = self._begin_attempt(session, row, subject)
        target = target_by_name(connection, row["source"])
        values = self._index_lookup_values(session, row, target)
        hits: list[dict[str, Any]] = []
        problem: str | None = None
        if target is None:
            problem = "index registration no longer exists"
        elif target.problem is not None:
            problem = target.problem
        elif values:
            try:
                hits = index_lookup(target, method=row["method"], values=values)
            except ValueError as error:
                problem = str(error)
        now = _now()
        for hit in hits:
            connection.execute(
                """INSERT INTO discovery_index_hits
                       (discovery_session_id, provider, post_native_id, md5,
                        snapshot_revision, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session["discovery_session_id"],
                    hit["provider"],
                    hit["post_native_id"],
                    hit["md5"],
                    target.snapshot.revision if target and target.snapshot else "",
                    now,
                ),
            )
        scope = (
            f"index lookup {row['method']} on {row['target']}:"
            f" {len(hits)} hit(s), scope {len(values)} value(s)"
        )
        if problem is not None:
            detail = problem
            outcome: str | None = "error"
            status = "failed"
        else:
            detail = scope
            outcome = "success"
            status = "complete"
        self._finish_step(
            session["discovery_session_id"],
            row["discovery_step_id"],
            status,
            outcome=outcome,
            detail=detail,
            result_count=len(hits) if problem is None else 0,
        )
        if attempt_id is not None:
            self._ledger.finish(
                attempt_id,
                status="complete" if status == "complete" else "failed",
                outcome=outcome if problem is None else "error",
                result_count=len(hits) if problem is None else 0,
                scope=detail if problem is None else None,
                requests_used=0,
                finished_at=_now(),
            )

    def _index_lookup_values(
        self,
        session: sqlite3.Row,
        row: sqlite3.Row,
        target: Any,
    ) -> list[str]:
        """Resolve the step's query values from the seed, like provider
        lookups re-resolve materials; empty when the method cannot serve."""
        method = row["method"]
        connection = self._database.connection
        if method == "external_post_id":
            # Platform-namespaced: the seed's provider id only matches an
            # index of the same provider.
            if target is None or target.provider != _seed_platform(connection, session):
                return []
            native = session["seed_post_id"]
            if native is None:
                return []
            platform_row = connection.execute(
                """SELECT p.native_post_id FROM posts p
                    WHERE p.post_id = ?""",
                (int(native),),
            ).fetchone()
            return [str(platform_row["native_post_id"])] if platform_row else []
        strategies = {
            "verified_md5": (LookupStrategy.VERIFIED_MD5,),
            "declared_md5": (LookupStrategy.DECLARED_MD5,),
            "source_post_url": (LookupStrategy.SOURCE_POST_URL,),
            "artist_exact_name": (LookupStrategy.ARTIST_EXACT_NAME,),
            "artist_alias": (LookupStrategy.ARTIST_ALIAS,),
            "artist_text": (LookupStrategy.ARTIST_TEXT,),
        }
        try:
            strategies_lookup = strategies[method]
        except KeyError:
            return []
        seed_post = session["seed_post_id"]
        if seed_post is not None:
            _, materials, _ = _post_materials(connection, int(seed_post))
        elif session["seed_file_id"] is not None:
            _, materials, _ = _file_materials(connection, int(session["seed_file_id"]))
        else:
            strategies_artist = tuple(
                strategy for strategy in LookupStrategy if strategy.value.startswith("artist_")
            )
            try:
                _, materials, _ = _account_materials(
                    connection,
                    int(session["seed_account_id"]),
                    strategies_artist,
                    session["search_term"],
                )
            except ValueError:
                return []
        values: list[str] = []
        for strategy in strategies_lookup:
            for material in materials.get(strategy) or ():
                values.extend(material.values)
        return values

    def _defer_step(self, session: sqlite3.Row, row: sqlite3.Row, detail: str) -> None:
        """Budget ran out before this step started: deferred, not failed.

        No attempt row is written (nothing was searched), so later runs plan
        the step again under every recheck mode.
        """
        self._finish_step(
            session["discovery_session_id"],
            row["discovery_step_id"],
            DEFERRED,
            outcome="budget_exhausted",
            detail=detail,
            result_count=0,
        )

    def _execute_local(self, session: sqlite3.Row, row: sqlite3.Row) -> tuple[int, str | None]:
        connection = self._database.connection
        seed_post = session["seed_post_id"]
        if row["method"] == "local_md5":
            if seed_post is not None:
                hashes = post_hash_evidence(connection, seed_post)
                if not hashes:
                    return 0, "seed carries no verified or declared hash"
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
            hashes = file_seed_hashes(connection, session["seed_file_id"])
            if not hashes:
                return 0, "file seed carries no verified hash"
            placeholders = ",".join("?" for _ in hashes)
            hits = connection.execute(
                f"""SELECT COUNT(DISTINCT oa.asset_id)
                      FROM occurrence_assets oa
                      JOIN asset_fingerprints f ON f.asset_id = oa.asset_id
                     WHERE f.fingerprint_value IN ({placeholders})""",
                hashes,
            ).fetchone()[0]
            return int(hits), f"{len(hashes)} file seed hash(es) searched"
        if row["method"] == "local_source_url":
            urls = post_source_urls(connection, seed_post)
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
        canonical = post_canonical_url(connection, seed_post)
        if canonical is None:
            return 0, "seed post carries no canonical url"
        hits = connection.execute(
            "SELECT COUNT(*) FROM posts WHERE canonical_url = ? AND post_id != ?",
            (canonical, seed_post),
        ).fetchone()[0]
        return int(hits), "seed canonical url searched"

    def _execute_provider(
        self,
        seed_ref: str,
        row: sqlite3.Row,
        remaining_budget: int,
        remaining_seconds: int,
        search_term: str | None = None,
    ) -> _StepExecution:
        platform = row["source"]
        strategy = LookupStrategy(row["method"])
        import httpx

        try:
            factory, interval = adapter_construction(platform)
            with httpx.Client() as client:
                adapter = factory(client)
                service = CandidateLookupService(
                    self._database, adapter, minimum_interval_seconds=interval
                )
                plan = service.plan(
                    seed_ref,
                    (strategy,),
                    limits=LookupLimits(
                        remaining_budget, _LOOKUP_PAGES, _LOOKUP_RESULTS, remaining_seconds
                    ),
                    search_term=search_term,
                )
                results = service.execute(plan)
        except Exception as error:
            return _StepExecution(
                status="failed",
                outcome="error",
                detail=f"{type(error).__name__}: {error}",
                result_count=0,
                requests_used=0,
            )
        total_requests = sum(result.request_count for result in results)
        run_ids = [result.candidate_lookup_run_id for result in results]
        run_id = run_ids[0] if run_ids and run_ids[0] > 0 else None
        complete = [result for result in results if result.status == "complete"]
        if len(complete) == len(results):
            return _StepExecution(
                status="complete",
                outcome="success",
                detail=f"lookup run(s) {run_ids}",
                result_count=sum(result.result_count for result in results),
                requests_used=total_requests,
                run_id=run_id,
            )
        # A paused run hit a budget boundary or a retryable provider state
        # partway: the step did not finish, so it is not fresh and later runs
        # retry it.  The boundary/outcome stays visible on the linked run.
        outcome = next(
            (result.outcome for result in results if result.status != "complete"),
            "provider_failure",
        )
        return _StepExecution(
            status="failed",
            outcome=outcome,
            detail=f"lookup run(s) {run_ids}",
            result_count=sum(result.result_count for result in results),
            requests_used=total_requests,
            run_id=run_id,
        )

    # ── Generational follow-up ─────────────────────────────────────────

    def _existing_step_identities(self, session_id: int) -> set[tuple[str, str, str]]:
        rows = self._database.connection.execute(
            """SELECT source, method, COALESCE(target, '')
                 FROM discovery_steps WHERE discovery_session_id = ?""",
            (session_id,),
        ).fetchall()
        return {(row[0], row[1], row[2]) for row in rows}

    def _followup_decision(
        self,
        subject: SubjectRef,
        policy: SearchPolicy,
        *,
        source: str,
        method: str,
        query_digest: str,
    ) -> str | None:
        """Freshness verdict for a would-be follow-up step, or None to run."""
        attempt = self._ledger.latest(
            subject,
            source_kind=PROVIDER,
            source=source,
            method=method,
            query_digest=query_digest,
        )
        verdict = freshness_verdict(
            policy, attempt, expected_version=method_version(method), now=datetime.now(UTC)
        )
        return verdict.reason if verdict.fresh else None

    def _plan_followup(
        self,
        session: sqlite3.Row,
        policy: SearchPolicy | None = None,
        subject: SubjectRef | None = None,
    ) -> list[sqlite3.Row]:
        """Wave A: fetch a post for every hit this session's lookups found.

        The hits' normalized references are consumed by wave B once their
        posts are persisted (see ``_plan_followup_from_posts``).
        """
        connection = self._database.connection
        policy = policy or self._session_policy(session)
        subject = subject or _session_subject(session)
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
        # Index hits are leads with provider-native ids already: they join
        # wave A directly, same fetch suggestions as lookup hits.
        for index_hit in connection.execute(
            """SELECT provider, post_native_id FROM discovery_index_hits
                WHERE discovery_session_id = ?""",
            (session_id,),
        ).fetchall():
            hits.append(
                {
                    "platform_key": index_hit["provider"],
                    "native_post_id": index_hit["post_native_id"],
                }
            )
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
            digest = evidence_digest([f"fetch:{hit['platform_key']}:{native_id}"])
            fresh_reason = None
            if policy.source_reason(hit["platform_key"]) is None and (
                policy.methods is None or FETCH_METHOD in policy.methods
            ):
                fresh_reason = self._followup_decision(
                    subject,
                    policy,
                    source=hit["platform_key"],
                    method=FETCH_METHOD,
                    query_digest=digest,
                )
            else:
                # Provider or method outside the policy: the generation-0
                # grid already documents that exclusion for the source.
                continue
            status = PLANNED
            detail: str | None = "fetch the hit post so its references become material"
            if fresh_reason is not None:
                status = SKIPPED
                detail = fresh_reason
            planned.append(
                self._insert_step(
                    session_id,
                    source_kind=PROVIDER,
                    source=hit["platform_key"],
                    method=FETCH_METHOD,
                    status=status,
                    detail=detail,
                    generation=1,
                    target=native_id,
                    query_digest=digest,
                )
            )
        connection.commit()
        if not planned:
            return []
        return connection.execute(
            f"""SELECT discovery_step_id, source_kind, source, method, status, target,
                       query_digest
                  FROM discovery_steps WHERE discovery_step_id IN
                  ({",".join("?" for _ in planned)}) ORDER BY step_order""",
            planned,
        ).fetchall()

    def _plan_followup_from_posts(
        self,
        session: sqlite3.Row,
        post_ids: list[int],
        policy: SearchPolicy | None = None,
        subject: SubjectRef | None = None,
    ) -> list[sqlite3.Row]:
        """Wave B: reverse lookups and source fetches from fetched posts."""
        connection = self._database.connection
        policy = policy or self._session_policy(session)
        subject = subject or _session_subject(session)
        session_id = session["discovery_session_id"]
        existing = self._existing_step_identities(session_id)
        planned: list[int] = []
        for post_id in post_ids:
            try:
                _, materials, _ = _post_materials(connection, post_id)
            except ValueError:
                continue
            for provider in LOOKUP_PROVIDERS:
                # Policy-excluded providers never enter the wave: their
                # generation-0 rows already document the exclusion.
                if policy.source_reason(provider.platform_key) is not None:
                    continue
                context = provider.lookup_plan_context
                for strategy, values in materials.items():
                    if not values or not context.lookup_capabilities.supports(strategy):
                        continue
                    if strategy.value.startswith("artist_"):
                        # Artist strategies need operator search terms; a
                        # follow-up generation never invents them.
                        continue
                    if policy.methods is not None and strategy.value not in policy.methods:
                        continue
                    for material in values:
                        # One step per material: execution replays the whole
                        # material (all its values) in a single run, so the
                        # plan must not split one material across steps.
                        identity = (provider.platform_key, strategy.value, material.digest)
                        if identity in existing:
                            continue
                        existing.add(identity)
                        fresh_reason = self._followup_decision(
                            subject,
                            policy,
                            source=provider.platform_key,
                            method=strategy.value,
                            query_digest=material.digest,
                        )
                        status = PLANNED
                        detail: str | None = f"reverse lookup from fetched post {post_id}"
                        if fresh_reason is not None:
                            status = SKIPPED
                            detail = fresh_reason
                        planned.append(
                            self._insert_step(
                                session_id,
                                source_kind=PROVIDER,
                                source=provider.platform_key,
                                method=strategy.value,
                                status=status,
                                detail=detail,
                                generation=1,
                                target=material.digest,
                                query_digest=material.digest,
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
                    if policy.source_reason(resolved.platform) is not None or (
                        policy.methods is not None and FETCH_METHOD not in policy.methods
                    ):
                        continue
                    digest = evidence_digest([f"fetch:{resolved.platform}:{resolved.target}"])
                    fresh_reason = self._followup_decision(
                        subject,
                        policy,
                        source=resolved.platform,
                        method=FETCH_METHOD,
                        query_digest=digest,
                    )
                    status = PLANNED
                    detail = f"source link from fetched post {post_id}"
                    if fresh_reason is not None:
                        status = SKIPPED
                        detail = fresh_reason
                    planned.append(
                        self._insert_step(
                            session_id,
                            source_kind=PROVIDER,
                            source=resolved.platform,
                            method=FETCH_METHOD,
                            status=status,
                            detail=detail,
                            generation=1,
                            target=resolved.target,
                            query_digest=digest,
                        )
                    )
        connection.commit()
        if not planned:
            return []
        return connection.execute(
            f"""SELECT discovery_step_id, source_kind, source, method, status, target,
                       seed_post_id, query_digest
                  FROM discovery_steps WHERE discovery_step_id IN
                  ({",".join("?" for _ in planned)}) ORDER BY step_order""",
            planned,
        ).fetchall()

    def _execute_fetch(
        self, session: sqlite3.Row, row: sqlite3.Row, limits: LookupLimits
    ) -> _StepExecution:
        import httpx

        from media_catalog.remote_sync import MetadataSyncService, SyncLimits

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
                    limits=SyncLimits(
                        limits.requests, limits.pages, limits.results, limits.seconds
                    ),
                )
        except Exception as error:
            return _StepExecution(
                status="failed",
                outcome="error",
                detail=f"{type(error).__name__}: {error}",
                result_count=0,
                requests_used=0,
            )
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
        # A fetch produces a remote run, not a candidate lookup run; the
        # step's candidate_lookup_run_id FK stays NULL and the run is named
        # in the detail.
        return _StepExecution(
            status="complete" if result.status == "complete" else "failed",
            outcome="success" if result.status == "complete" else result.outcome,
            detail=f"remote run {result.remote_run_id}",
            result_count=result.record_count,
            requests_used=result.request_count,
        )

    # ── Persistence ────────────────────────────────────────────────────

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
        query_digest: str | None = None,
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
                    method, status, detail, generation, target, seed_post_id,
                    query_digest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                query_digest,
            ),
        )
        step_id = cursor.lastrowid
        assert step_id is not None
        return int(step_id)

    def _insert_session(
        self,
        input_kind: str,
        seed_post: int | None,
        seed_account: int | None,
        input_digest: str | None,
        live: bool,
        request_budget: int,
        time_budget_seconds: int,
        policy: SearchPolicy | None = None,
        search_term: str | None = None,
    ) -> int:
        cursor = self._database.connection.execute(
            """INSERT INTO discovery_sessions
                   (input_kind, seed_post_id, seed_account_id, input_digest,
                    live_authorized, status, request_budget, time_budget_seconds,
                    search_term, policy_json, started_at)
               VALUES (?, ?, ?, ?, ?, 'planning', ?, ?, ?, ?, ?)""",
            (
                input_kind,
                seed_post,
                seed_account,
                input_digest,
                int(live),
                request_budget,
                time_budget_seconds,
                search_term,
                json.dumps(policy.as_dict(), sort_keys=True) if policy else None,
                _now(),
            ),
        )
        return int(cursor.lastrowid)

    def _store_steps(self, session_id: int, steps: list[PlannedSearch]) -> None:
        connection = self._database.connection
        connection.execute(
            "DELETE FROM discovery_steps WHERE discovery_session_id = ?", (session_id,)
        )
        for order, step in enumerate(steps):
            connection.execute(
                """INSERT INTO discovery_steps
                       (discovery_session_id, step_order, source_kind, source,
                        method, status, outcome, result_count, detail,
                        query_digest, target)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)""",
                (
                    session_id,
                    order,
                    step.source_kind,
                    step.source,
                    step.method,
                    step.status,
                    step.detail,
                    step.query_digest,
                    step.target,
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
        session_id: int,
        step_id: int,
        status: str,
        *,
        outcome: str | None,
        detail: str | None,
        result_count: int,
        run_id: int | None = None,
        requests_used: int = 0,
    ) -> None:
        self._database.connection.execute(
            """UPDATE discovery_steps
                  SET status = ?, outcome = ?, detail = ?, result_count = ?,
                      candidate_lookup_run_id = COALESCE(?, candidate_lookup_run_id)
                WHERE discovery_step_id = ?""",
            (status, outcome, detail, result_count, run_id, step_id),
        )
        self._database.connection.execute(
            """UPDATE discovery_sessions
                  SET requests_used = requests_used + ?
                WHERE discovery_session_id = ?""",
            (requests_used, session_id),
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
                          generation, target, query_digest
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
        pending = any(step["status"] == PLANNED for step in steps)
        deferred = any(step["status"] == DEFERRED for step in steps)
        status = "planned" if pending else "partial" if deferred else "complete"
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
            "requests_used": int(session["requests_used"] or 0),
            "steps": steps,
        }
        policy = self._session_policy(session)
        if policy != SearchPolicy().with_search_term(session["search_term"]):
            result["policy"] = policy.as_dict()
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
