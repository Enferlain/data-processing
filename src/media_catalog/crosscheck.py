"""Whole-catalog cross-check (bead data-processing-p1t, change
add-catalog-cross-check).

Batch coordination over the existing candidate-lookup machinery: explicit
corpus selection, per-(subject x provider x strategy) outcomes keyed to
retained lookup runs, serialized writes (one process, one connection,
sequential provider lookups), item-boundary budgets with durable resume, and
item-level reporting with reasons.  Matches stay candidates — provenance lives
in the lookup runs, never in relationship facts.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from media_catalog.adapters.contracts import LookupStrategy
from media_catalog.candidate_lookup.planning import (
    LookupLimits,
    _file_materials,
    _post_materials,
)
from media_catalog.candidate_lookup.service import CandidateLookupService

PROVIDERS: tuple[str, ...] = ("danbooru", "aibooru", "e621", "gelbooru")

CORPORA = ("hash-material", "downloaded", "file-seeds", "all")
RECHECK_MODES = ("unsearched", "stale", "force")

TERMINAL_STATES = ("checked", "matched", "skipped", "failed")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CrosscheckBudget:
    max_requests: int | None = None
    max_minutes: float | None = None

    def deadline(self) -> float | None:
        return time.monotonic() + (self.max_minutes * 60) if self.max_minutes else None


class CrosscheckStore:
    """Batch/item state on the single writable connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def open_batch(self, batch_key: str, corpus: str, providers: str, recheck: str) -> int:
        row = self.connection.execute(
            "SELECT crosscheck_batch_id FROM crosscheck_batches WHERE batch_key = ?",
            (batch_key,),
        ).fetchone()
        if row is not None:
            self.connection.execute(
                "UPDATE crosscheck_batches SET stopped_at = NULL, stopped_reason = NULL"
                " WHERE crosscheck_batch_id = ?",
                (int(row[0]),),
            )
            self.connection.commit()
            return int(row[0])
        self.connection.execute(
            """INSERT INTO crosscheck_batches
                   (batch_key, corpus, providers, recheck, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            (batch_key, corpus, providers, recheck, _now()),
        )
        self.connection.commit()
        inserted = self.connection.execute(
            "SELECT crosscheck_batch_id FROM crosscheck_batches WHERE batch_key = ?",
            (batch_key,),
        ).fetchone()
        assert inserted is not None
        return int(inserted[0])

    def stop_batch(self, batch_id: int, reason: str) -> None:
        self.connection.execute(
            "UPDATE crosscheck_batches SET stopped_at = ?, stopped_reason = ?"
            " WHERE crosscheck_batch_id = ?",
            (_now(), reason, batch_id),
        )
        self.connection.commit()

    def item_state(self, batch_id: int) -> dict[tuple[str, int, str, str], str]:
        return {
            (
                str(row["seed_kind"]),
                int(row["seed_id"]),
                str(row["provider"]),
                str(row["strategy"]),
            ): str(row["state"])
            for row in self.connection.execute(
                "SELECT seed_kind, seed_id, provider, strategy, state"
                " FROM crosscheck_items WHERE crosscheck_batch_id = ?",
                (batch_id,),
            )
        }

    def record(
        self,
        batch_id: int,
        *,
        seed_kind: str,
        seed_id: int,
        provider: str,
        strategy: str,
        state: str,
        reason: str | None = None,
        run_id: int | None = None,
        matched_count: int = 0,
    ) -> None:
        self.connection.execute(
            """INSERT INTO crosscheck_items
                   (crosscheck_batch_id, seed_kind, seed_id, provider, strategy,
                    state, reason, candidate_lookup_run_id, matched_count, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(crosscheck_batch_id, seed_kind, seed_id, provider, strategy)
               DO UPDATE SET state = excluded.state, reason = excluded.reason,
                    candidate_lookup_run_id = COALESCE(excluded.candidate_lookup_run_id,
                        crosscheck_items.candidate_lookup_run_id),
                    matched_count = excluded.matched_count,
                    updated_at = excluded.updated_at""",
            (
                batch_id,
                seed_kind,
                seed_id,
                provider,
                strategy,
                state,
                reason,
                run_id,
                matched_count,
                _now(),
            ),
        )
        self.connection.commit()

    def summary(self, batch_id: int) -> dict[str, Any]:
        rows = list(
            self.connection.execute(
                """SELECT state, count(*) AS n FROM crosscheck_items
                    WHERE crosscheck_batch_id = ? GROUP BY state""",
                (batch_id,),
            )
        )
        by_state = {str(row["state"]): int(row["n"]) for row in rows}
        by_provider = {
            f"{row['provider']}:{row['state']}": int(row["n"])
            for row in self.connection.execute(
                """SELECT provider, state, count(*) AS n FROM crosscheck_items
                    WHERE crosscheck_batch_id = ? GROUP BY provider, state""",
                (batch_id,),
            )
        }
        reasons = {
            str(row["reason"]): int(row["n"])
            for row in self.connection.execute(
                """SELECT reason, count(*) AS n FROM crosscheck_items
                    WHERE crosscheck_batch_id = ? AND reason IS NOT NULL
                    GROUP BY reason ORDER BY n DESC""",
                (batch_id,),
            )
        }
        matched = int(
            self.connection.execute(
                """SELECT count(*) FROM crosscheck_items
                    WHERE crosscheck_batch_id = ? AND state = 'matched'""",
                (batch_id,),
            ).fetchone()[0]
        )
        return {
            "states": by_state,
            "by_provider": by_provider,
            "reasons": reasons,
            "matched_items": matched,
        }


def select_corpus(connection: sqlite3.Connection, corpus: str) -> list[tuple[str, int]]:
    """Deterministic subject list; (seed_kind, seed_id) pairs."""
    if corpus not in CORPORA:
        raise ValueError(f"unknown corpus {corpus!r} (valid: {', '.join(CORPORA)})")
    subjects: list[tuple[str, int]] = []
    if corpus == "hash-material":
        rows = connection.execute(
            """SELECT DISTINCT 'post' AS kind, post_id AS id FROM media_occurrences
                WHERE declared_md5 IS NOT NULL
               UNION
               SELECT DISTINCT 'post', p.post_id
                 FROM posts p
                 JOIN post_external_references r ON r.post_id = p.post_id
                WHERE r.reference_kind = 'provider_id'
               ORDER BY kind, id"""
        )
        subjects = [("post", int(row["id"])) for row in rows]
    elif corpus == "downloaded":
        rows = connection.execute(
            """SELECT DISTINCT 'post', mo.post_id
                 FROM occurrence_assets oa
                 JOIN media_occurrences mo USING(media_occurrence_id)
                ORDER BY 2"""
        )
        subjects = [("post", int(row[1])) for row in rows]
    elif corpus == "file-seeds":
        # Canonical identity only: find_file_seed_id defines the subject for a
        # verified hash pair as the lowest id; the 0031 hash index is
        # deliberately non-unique, so catalogs may hold duplicate rows.
        rows = connection.execute(
            """SELECT min(discovery_file_seed_id) AS id
                 FROM discovery_file_seeds
                GROUP BY verified_md5, verified_sha256
                ORDER BY id"""
        )
        subjects = [("file", int(row["id"])) for row in rows]
    else:
        rows = connection.execute("SELECT 'post', post_id FROM posts ORDER BY post_id")
        subjects = [("post", int(row[1])) for row in rows]
    return subjects


def _stale_seconds(stale_after: str | None) -> int | None:
    if not stale_after:
        return None
    unit = stale_after[-1]
    value = stale_after[:-1]
    if not value.isdecimal():
        raise ValueError(f"invalid --stale-after {stale_after!r}")
    multipliers = {"h": 3600, "d": 86400}
    if unit not in multipliers:
        raise ValueError(f"invalid --stale-after unit {unit!r} (h or d)")
    return int(value) * multipliers[unit]


def _reusable_run(
    connection: sqlite3.Connection,
    *,
    seed_kind: str,
    seed_id: int,
    provider: str,
    strategy: str,
    seed_revision: str,
    material_digest: str,
    adapter_version: str,
    strategy_version: str,
    stale_seconds: int | None,
) -> sqlite3.Row | None:
    """A complete run for exactly this providerxstrategyxmaterial that
    freshness can reuse (providers can never suppress each other: the
    platform is part of the match)."""
    column = "seed_post_id" if seed_kind == "post" else "seed_file_id"
    row = connection.execute(
        f"""SELECT clr.candidate_lookup_run_id, clr.finished_at
              FROM candidate_lookup_runs clr
              JOIN platforms pl ON pl.platform_id = clr.platform_id
             WHERE pl.platform_key = ? AND clr.strategy = ?
               AND clr.{column} = ? AND clr.status = 'complete'
               AND clr.seed_revision = ? AND clr.material_digest = ?
               AND clr.adapter_version = ? AND clr.strategy_version = ?
             ORDER BY clr.candidate_lookup_run_id DESC LIMIT 1""",
        (
            provider,
            strategy,
            seed_id,
            seed_revision,
            material_digest,
            adapter_version,
            strategy_version,
        ),
    ).fetchone()
    if row is None:
        return None
    if stale_seconds is not None:
        try:
            finished = datetime.fromisoformat(str(row["finished_at"]).replace("Z", "+00:00"))
        except ValueError:
            return None
        age = (datetime.now(UTC) - finished).total_seconds()
        if age < stale_seconds:
            return row
        return None
    return row


def run_crosscheck(
    database: Any,
    *,
    corpus: str = "hash-material",
    providers: tuple[str, ...] = PROVIDERS,
    recheck: str = "unsearched",
    stale_after: str | None = None,
    budget: CrosscheckBudget | None = None,
    limits: LookupLimits | None = None,
) -> dict[str, Any]:
    """One batch pass; returns the durable summary.  Resumable by re-invoking
    with the same arguments (completed items are never re-executed).

    Providers run concurrently in per-provider lanes: each lane is a
    sequential subject loop on its own WAL connection with its own adapter,
    so per-provider pacing holds and provider-disjoint items never collide;
    catalog writes serialize through WAL under the connection busy timeout.
    Budgets and stops are coordinator-owned and checked at item boundaries."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock

    import httpx

    from media_catalog.adapter_factory import adapter_construction
    from media_catalog.database import CatalogDatabase

    if recheck not in RECHECK_MODES:
        raise ValueError(f"unknown recheck mode {recheck!r}")
    if not providers:
        raise ValueError("at least one provider is required")
    connection = database.connection
    connection.row_factory = sqlite3.Row
    budget = budget or CrosscheckBudget()
    limits = limits or LookupLimits()
    stale = _stale_seconds(stale_after) if recheck == "stale" else None
    batch_key = f"{corpus}|{','.join(sorted(providers))}|{recheck}"
    store = CrosscheckStore(connection)
    batch_id = store.open_batch(batch_key, corpus, ",".join(sorted(providers)), recheck)
    prior_states = store.item_state(batch_id)

    subjects = select_corpus(connection, corpus)
    deadline = budget.deadline()
    max_requests = budget.max_requests or float("inf")
    shared: dict[str, Any] = {"requests_used": 0, "in_flight": 0, "stop_reason": None}
    shared_lock = Lock()
    # metadata-only counting is coordinator-owned: a prepass over post
    # subjects counts each subject once regardless of lane count
    material_note = {
        "metadata-only": sum(
            1
            for kind, seed_id in subjects
            if kind == "post"
            and not any(items for items in _post_materials(connection, seed_id)[1].values())
        )
    }

    def lane(provider: str) -> dict[str, int]:
        """One provider's sequential subject loop on its own connection.
        A lane-level failure trips the shared stop flag so sibling lanes
        stop issuing requests, then re-raises to the coordinator."""
        lane_counts: dict[str, int] = dict.fromkeys((*TERMINAL_STATES, "pending", "reused"), 0)
        lane_database = CatalogDatabase(database.path)
        lane_connection = lane_database.connection
        lane_connection.row_factory = sqlite3.Row
        lane_store = CrosscheckStore(lane_connection)
        client = httpx.Client()
        try:
            factory, interval = adapter_construction(provider)
            adapter = factory(client)
            service = CandidateLookupService(
                lane_database, adapter, minimum_interval_seconds=interval
            )
            declared = adapter.instance.lookup_plan_context.lookup_capabilities
            for seed_kind, seed_id in subjects:
                if shared["stop_reason"]:
                    continue
                if seed_kind == "post":
                    _, materials, revision = _post_materials(lane_connection, seed_id)
                else:
                    _, materials, revision = _file_materials(lane_connection, seed_id)
                for strategy in LookupStrategy:
                    if shared["stop_reason"]:
                        break
                    if not declared.supports(strategy):
                        continue
                    material_list = materials.get(strategy) or []
                    item_key = (seed_kind, seed_id, provider, strategy.value)
                    previous = prior_states.get(item_key)
                    if (recheck == "unsearched" and previous in TERMINAL_STATES) or (
                        recheck == "stale" and previous in ("checked", "matched", "skipped")
                    ):
                        lane_counts["reused"] += 1
                        continue
                    if not material_list:
                        if strategy.value.startswith("artist_"):
                            continue  # artist strategies always need a search term
                        lane_store.record(
                            batch_id,
                            seed_kind=seed_kind,
                            seed_id=seed_id,
                            provider=provider,
                            strategy=strategy.value,
                            state="skipped",
                            reason="no-query-material",
                        )
                        lane_counts["skipped"] += 1
                        continue
                    for material in material_list:
                        reusable = _reusable_run(
                            lane_connection,
                            seed_kind=seed_kind,
                            seed_id=seed_id,
                            provider=provider,
                            strategy=strategy.value,
                            seed_revision=revision,
                            material_digest=material.digest,
                            adapter_version=adapter.adapter_version,
                            strategy_version=adapter.schema_version,
                            stale_seconds=stale,
                        )
                        if reusable is not None and recheck != "force":
                            lane_store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="skipped",
                                reason="fresh-run-reused",
                                run_id=int(reusable["candidate_lookup_run_id"]),
                            )
                            lane_counts["skipped"] += 1
                            continue
                        with shared_lock:
                            # Reserve one request per in-flight item so N
                            # lanes cannot each pass an unreserved check;
                            # the overrun bound returns to the sequential
                            # one item's pagination beyond the budget.
                            over_budget = shared["requests_used"] + shared[
                                "in_flight"
                            ] >= max_requests or (
                                deadline is not None and time.monotonic() > deadline
                            )
                            if not over_budget:
                                shared["in_flight"] += 1
                        if over_budget:
                            with shared_lock:
                                if shared["stop_reason"] is None:
                                    shared["stop_reason"] = (
                                        "request budget reached"
                                        if shared["requests_used"] >= max_requests
                                        else "time budget reached"
                                    )
                            lane_store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="pending",
                            )
                            break
                        try:
                            plan = service.plan(
                                f"{seed_kind}:{seed_id}", (strategy,), limits=limits
                            )
                            results = service.execute(plan)
                        except Exception as error:  # surfaced as the item reason
                            reason = f"{type(error).__name__}: {error}"[:200]
                            with shared_lock:
                                shared["in_flight"] -= 1
                            lane_store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="failed",
                                reason=reason,
                            )
                            lane_counts["failed"] += 1
                            continue
                        total = sum(result.request_count for result in results)
                        with shared_lock:
                            shared["in_flight"] -= 1
                            shared["requests_used"] += total
                        run_id = next(
                            (
                                int(result.candidate_lookup_run_id)
                                for result in results
                                if result.candidate_lookup_run_id
                            ),
                            None,
                        )
                        matched = sum(result.result_count for result in results)
                        retry_after = next(
                            (
                                result.retry_after
                                for result in results
                                if getattr(result, "retry_after", None)
                            ),
                            None,
                        )
                        if retry_after:
                            lane_store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="failed",
                                reason=f"rate-limited retry_after={retry_after}",
                                run_id=run_id,
                            )
                            lane_counts["failed"] += 1
                        else:
                            lane_store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="matched" if matched else "checked",
                                run_id=run_id,
                                matched_count=matched,
                            )
                            lane_counts["matched" if matched else "checked"] += 1
            return lane_counts
        except BaseException:
            with shared_lock:
                if shared["stop_reason"] is None:
                    shared["stop_reason"] = "lane failure"
            raise
        finally:
            client.close()
            lane_database.close()

    counts: dict[str, int] = dict.fromkeys((*TERMINAL_STATES, "pending", "reused"), 0)
    lane_error: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = [executor.submit(lane, provider) for provider in providers]
        for future in futures:
            try:
                for key, value in future.result().items():
                    counts[key] += value
            except BaseException as error:
                with shared_lock:
                    if shared["stop_reason"] is None:
                        shared["stop_reason"] = "lane failure"
                lane_error.append(error)
    if lane_error:
        raise lane_error[0]
    stop_reason = shared["stop_reason"]
    summary = store.summary(batch_id)
    # pending is the durable row count, not a per-lane tally: subjects a
    # stopped lane never reached simply have no rows and resume on re-run
    counts["pending"] = int(summary["states"].get("pending", 0))
    if stop_reason:
        store.stop_batch(batch_id, stop_reason)
    return {
        "batch_id": batch_id,
        "batch_key": batch_key,
        "corpus": corpus,
        "providers": list(providers),
        "recheck": recheck,
        "subjects": len(subjects),
        "requests_used": shared["requests_used"],
        "stopped_reason": stop_reason,
        "counts": counts,
        "material_note": material_note,
        "summary": summary,
    }
