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

CORPORA = ("hash-material", "downloaded", "all")
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
    with the same arguments (completed items are never re-executed)."""
    import httpx

    from media_catalog.adapter_factory import adapter_construction

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
    requests_used = 0
    stop_reason: str | None = None
    counts: dict[str, int] = dict.fromkeys((*TERMINAL_STATES, "pending", "reused"), 0)
    material_note = {"metadata-only": 0}

    adapters: dict[str, tuple[Any, Any, float]] = {}
    try:
        for seed_kind, seed_id in subjects:
            if stop_reason:
                counts["pending"] += 1
                continue
            if seed_kind == "post":
                _, materials, revision = _post_materials(connection, seed_id)
                if not any(items for items in materials.values()):
                    material_note["metadata-only"] += 1
            else:
                _, materials, revision = _file_materials(connection, seed_id)
            for provider in providers:
                if stop_reason:
                    break
                entry = adapters.get(provider)
                if entry is None:
                    factory, interval = adapter_construction(provider)
                    client = httpx.Client()
                    adapters[provider] = (factory(client), client, interval)
                    entry = adapters[provider]
                adapter, _client, interval = entry
                service = CandidateLookupService(
                    database, adapter, minimum_interval_seconds=interval
                )
                declared = adapter.instance.lookup_plan_context.lookup_capabilities
                for strategy in LookupStrategy:
                    if not declared.supports(strategy):
                        continue
                    material_list = materials.get(strategy) or []
                    item_key = (seed_kind, seed_id, provider, strategy.value)
                    previous = prior_states.get(item_key)
                    if (recheck == "unsearched" and previous in TERMINAL_STATES) or (
                        recheck == "stale" and previous in ("checked", "matched", "skipped")
                    ):
                        counts["reused"] += 1
                        continue
                    if not material_list:
                        if strategy.value.startswith("artist_"):
                            continue  # artist strategies always need a search term
                        store.record(
                            batch_id,
                            seed_kind=seed_kind,
                            seed_id=seed_id,
                            provider=provider,
                            strategy=strategy.value,
                            state="skipped",
                            reason="no-query-material",
                        )
                        counts["skipped"] += 1
                        continue
                    for material in material_list:
                        reusable = _reusable_run(
                            connection,
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
                            store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="skipped",
                                reason="fresh-run-reused",
                                run_id=int(reusable["candidate_lookup_run_id"]),
                            )
                            counts["skipped"] += 1
                            continue
                        if requests_used >= (budget.max_requests or float("inf")):
                            stop_reason = "request budget reached"
                            store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="pending",
                            )
                            counts["pending"] += 1
                            break
                        if deadline is not None and time.monotonic() > deadline:
                            stop_reason = "time budget reached"
                            store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="pending",
                            )
                            counts["pending"] += 1
                            break
                        try:
                            plan = service.plan(
                                f"{seed_kind}:{seed_id}", (strategy,), limits=limits
                            )
                            results = service.execute(plan)
                        except Exception as error:  # surfaced as the item reason
                            reason = f"{type(error).__name__}: {error}"[:200]
                            store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="failed",
                                reason=reason,
                            )
                            counts["failed"] += 1
                            continue
                        total = sum(result.request_count for result in results)
                        requests_used += total
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
                            store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="failed",
                                reason=f"rate-limited retry_after={retry_after}",
                                run_id=run_id,
                            )
                            counts["failed"] += 1
                        else:
                            store.record(
                                batch_id,
                                seed_kind=seed_kind,
                                seed_id=seed_id,
                                provider=provider,
                                strategy=strategy.value,
                                state="matched" if matched else "checked",
                                run_id=run_id,
                                matched_count=matched,
                            )
                            counts["matched" if matched else "checked"] += 1
    finally:
        for _adapter, client, _interval in adapters.values():
            client.close()
    if stop_reason:
        store.stop_batch(batch_id, stop_reason)
    return {
        "batch_id": batch_id,
        "batch_key": batch_key,
        "corpus": corpus,
        "providers": list(providers),
        "recheck": recheck,
        "subjects": len(subjects),
        "requests_used": requests_used,
        "stopped_reason": stop_reason,
        "counts": counts,
        "material_note": material_note,
        "summary": store.summary(batch_id),
    }
