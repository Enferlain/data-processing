"""Multi-subject discovery runs: one policy, one shared budget, visible progress.

A run is a synchronous, sequential loop over explicit subjects — each subject
gets its own session through the existing orchestrator — under one request
budget and deadline.  Freshness makes re-running the same command cheap:
previously successful work is skipped, deferred work resumes.  Concurrency is
deliberately out of scope (change add-discovery-search-policy); the persisted
queue states are the contract a later executor can build on.
"""

from __future__ import annotations

import hashlib
import time as _time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from media_catalog.discovery.attempts import SearchAttemptLedger, SubjectRef
from media_catalog.discovery.orchestration import DiscoveryOrchestrator
from media_catalog.discovery.policy import (
    SearchPolicy,
    method_version,
)
from media_catalog.link_resolution import resolve_link
from media_catalog.seeding import find_file_seed_id

ProgressCallback = Callable[[int, int, dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class SubjectInput:
    """One explicit discovery subject; exactly one identity field is set."""

    url: str | None = None
    file: str | Path | None = None
    post_id: int | None = None
    account_id: int | None = None

    def __post_init__(self) -> None:
        if (
            sum(value is not None for value in (self.url, self.file, self.post_id, self.account_id))
            != 1
        ):
            raise ValueError("a discovery subject requires exactly one input")

    @property
    def label(self) -> str:
        if self.url is not None:
            return self.url
        if self.file is not None:
            return Path(self.file).name
        if self.post_id is not None:
            return f"post:{self.post_id}"
        assert self.account_id is not None
        return f"account:{self.account_id}"


def resolve_subject(connection: Any, subject: SubjectInput) -> SubjectRef | None:
    """Resolve a subject to its catalog identity without writing anything.

    Unresolvable subjects (a URL never seeded, a file never discovered) have
    no durable identity yet, so they also have no search state.
    """
    if subject.post_id is not None:
        row = connection.execute(
            "SELECT post_id FROM posts WHERE post_id = ?", (subject.post_id,)
        ).fetchone()
        return SubjectRef(post_id=subject.post_id) if row else None
    if subject.account_id is not None:
        row = connection.execute(
            "SELECT account_id FROM accounts WHERE account_id = ?",
            (subject.account_id,),
        ).fetchone()
        return SubjectRef(account_id=subject.account_id) if row else None
    if subject.url is not None:
        resolved = resolve_link(subject.url)
        row = connection.execute(
            """SELECT po.post_id FROM posts po
                 JOIN platforms p ON p.platform_id = po.platform_id
                WHERE p.platform_key = ? AND po.native_post_id = ?""",
            (resolved.platform, resolved.target),
        ).fetchone()
        return SubjectRef(post_id=int(row["post_id"])) if row else None
    assert subject.file is not None
    path = Path(subject.file)
    if not path.is_file():
        return None
    payload = path.read_bytes()
    seed_id = find_file_seed_id(
        connection,
        hashlib.md5(payload).hexdigest(),
        hashlib.sha256(payload).hexdigest(),
    )
    return SubjectRef(file_id=seed_id) if seed_id is not None else None


def _session_summary(result: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(step["status"] for step in result["steps"])
    summary: dict[str, Any] = {
        "session_id": result["session_id"],
        "input_kind": result["input_kind"],
        "status": result["status"],
        "requests_used": result["requests_used"],
        "step_counts": dict(sorted(counts.items())),
    }
    for key in ("seed_post_id", "seed_account_id", "seed_file_id"):
        if result.get(key) is not None:
            summary[key] = result[key]
    return summary


class DiscoveryRunService:
    """Execute explicit subjects sequentially under one shared budget."""

    def __init__(self, database: Any, *, progress: ProgressCallback | None = None) -> None:
        self._database = database
        self._orchestrator = DiscoveryOrchestrator(database)
        self._progress = progress

    def run(
        self,
        subjects: list[SubjectInput],
        *,
        policy: SearchPolicy,
        live: bool = False,
        request_budget: int = 12,
        time_budget_seconds: int = 120,
        search_term: str | None = None,
        dry_run: bool = False,
        declared_md5: str | None = None,
        media_root: str | Path | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        if not subjects:
            raise ValueError("a discovery run requires at least one subject")
        deadline = _time.monotonic() + int(time_budget_seconds)
        remaining = int(request_budget)
        sessions: list[dict[str, Any]] = []
        totals: Counter[str] = Counter()
        total_requests = 0
        for index, subject in enumerate(subjects, start=1):
            remaining_seconds = max(1, int(deadline - _time.monotonic()))
            result = self._orchestrator.start(
                url=subject.url,
                file=subject.file,
                post_id=subject.post_id,
                account_id=subject.account_id,
                media_root=media_root,
                declared_md5=declared_md5,
                note=note,
                live=live,
                # Each session receives the run's remaining budget; spent
                # requests are subtracted after every subject, so exhaustion
                # defers later subjects' remote steps instead of overrunning.
                request_budget=remaining,
                time_budget_seconds=remaining_seconds,
                search_term=search_term,
                policy=policy,
                dry_run=dry_run,
            )
            used = int(result["requests_used"])
            remaining -= used
            total_requests += used
            summary = _session_summary(result)
            summary["subject"] = subject.label
            sessions.append(summary)
            totals.update(step["status"] for step in result["steps"])
            if self._progress is not None:
                self._progress(
                    index,
                    len(subjects),
                    {
                        "subject": subject.label,
                        "session_id": result["session_id"],
                        "status": result["status"],
                        "requests_used": used,
                        "step_counts": summary["step_counts"],
                    },
                )
        report: dict[str, Any] = {
            "subjects": len(subjects),
            "live_authorized": live,
            "dry_run": dry_run,
            "requests_budget": int(request_budget),
            "requests_used": total_requests,
            "step_totals": dict(sorted(totals.items())),
            "sessions": sessions,
        }
        if policy != SearchPolicy():
            report["policy"] = policy.as_dict()
        return report

    def search_state(
        self,
        subjects: list[SubjectInput],
        *,
        policy: SearchPolicy,
    ) -> dict[str, Any]:
        """Offline per-subject search state: decisions, attempts, freshness.

        Nothing is written: no session, no step, no attempt.  The planner's
        decisions are re-derived against the current catalog and joined with
        the attempt ledger.
        """
        from datetime import UTC, datetime

        from media_catalog.discovery.planning import (
            plan_searches,
        )
        from media_catalog.discovery.policy import freshness_verdict

        connection = self._database.connection
        ledger = SearchAttemptLedger(connection)
        results: list[dict[str, Any]] = []
        for subject in subjects:
            resolved = resolve_subject(connection, subject)
            if resolved is None:
                results.append(
                    {
                        "subject": subject.label,
                        "resolved": False,
                        "note": "subject has no catalog identity yet; nothing searched",
                        "entries": [],
                    }
                )
                continue
            steps = plan_searches(
                connection,
                seed_post=resolved.post_id,
                seed_account=resolved.account_id,
                seed_file=resolved.file_id,
                policy=policy,
                now=datetime.now(UTC),
            )
            latest = ledger.latest_for_subject(resolved)
            entries = []
            for step in steps:
                entry: dict[str, Any] = {
                    "source_kind": step.source_kind,
                    "source": step.source,
                    "method": step.method,
                    "status": step.status,
                    "detail": step.detail,
                }
                if step.query_digest is not None:
                    entry["query_digest"] = step.query_digest
                    entry["strategy_version"] = step.strategy_version
                    attempt = latest.get(
                        (step.source_kind, step.source, step.method, step.query_digest)
                    )
                    if attempt is not None:
                        entry["latest_attempt"] = {
                            "discovery_search_attempt_id": attempt["discovery_search_attempt_id"],
                            "status": attempt["status"],
                            "outcome": attempt["outcome"],
                            "result_count": attempt["result_count"],
                            "scope": attempt["scope"],
                            "requests_used": attempt["requests_used"],
                            "strategy_version": attempt["strategy_version"],
                            "started_at": attempt["started_at"],
                            "finished_at": attempt["finished_at"],
                            "session_id": attempt["discovery_session_id"],
                        }
                    verdict = freshness_verdict(
                        policy,
                        attempt,
                        expected_version=step.target
                        if step.source_kind == "index" and step.target
                        else method_version(step.method),
                        now=datetime.now(UTC),
                    )
                    entry["fresh"] = verdict.fresh
                    entry["freshness"] = verdict.reason
                else:
                    entry["fresh"] = False
                    entry["freshness"] = "no query evidence for this method"
                entries.append(entry)
            results.append(
                {
                    "subject": resolved.label,
                    "resolved": True,
                    "entries": entries,
                }
            )
        return {
            "subjects": [subject.label for subject in subjects],
            "policy": policy.as_dict(),
            "state": results,
        }
