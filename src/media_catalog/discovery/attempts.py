"""Durable cross-session search-attempt ledger (change add-discovery-search-policy).

Rows are keyed by subject x search target (kind + source) x method x
query-evidence digest; the strategy version lives on the row so freshness can
explain version drift instead of silently missing.  The ledger is append-only
history: freshness reads the latest row per key, and history reads keep every
prior attempt answerable after restarts.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from media_catalog.records import (
    SearchAttemptRecord,
    validate_search_attempt_outcome,
    validate_search_attempt_status,
)

_SUBJECT_COLUMNS = (
    "subject_post_id",
    "subject_account_id",
    "subject_file_id",
)
_ATTEMPT_COLUMNS = """discovery_search_attempt_id, subject_post_id,
    subject_account_id, subject_file_id, source_kind, source, method,
    strategy_version, query_digest, status, outcome, result_count, scope,
    requests_used, discovery_session_id, discovery_step_id,
    candidate_lookup_run_id, started_at, finished_at"""


@dataclass(frozen=True, slots=True)
class SubjectRef:
    """The exactly-one subject identity a search attempt belongs to."""

    post_id: int | None = None
    account_id: int | None = None
    file_id: int | None = None

    def __post_init__(self) -> None:
        if sum(value is not None for value in (self.post_id, self.account_id, self.file_id)) != 1:
            raise ValueError("a search subject requires exactly one id")

    @property
    def label(self) -> str:
        if self.post_id is not None:
            return f"post:{self.post_id}"
        if self.account_id is not None:
            return f"account:{self.account_id}"
        assert self.file_id is not None
        return f"file:{self.file_id}"

    @property
    def _column_value(self) -> tuple[str, int]:
        if self.post_id is not None:
            return "subject_post_id", self.post_id
        if self.account_id is not None:
            return "subject_account_id", self.account_id
        assert self.file_id is not None
        return "subject_file_id", self.file_id

    def where_clause(self) -> tuple[str, tuple[int, ...]]:
        column, value = self._column_value
        return f"{column} = ?", (value,)


class SearchAttemptLedger:
    """Read/append the search-attempt ledger for one catalog connection."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def begin(
        self,
        record: SearchAttemptRecord,
    ) -> int:
        if record.status != "running":
            raise ValueError("a search attempt begins in the running state")
        cursor = self.connection.execute(
            """INSERT INTO discovery_search_attempts
                   (subject_post_id, subject_account_id, subject_file_id,
                    source_kind, source, method, strategy_version,
                    query_digest, status, outcome, result_count, scope,
                    requests_used, discovery_session_id, discovery_step_id,
                    candidate_lookup_run_id, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.subject_post_id,
                record.subject_account_id,
                record.subject_file_id,
                record.source_kind,
                record.source,
                record.method,
                record.strategy_version,
                record.query_digest,
                record.status,
                record.outcome,
                record.result_count,
                record.scope,
                record.requests_used,
                record.discovery_session_id,
                record.discovery_step_id,
                record.candidate_lookup_run_id,
                record.started_at,
                record.finished_at,
            ),
        )
        return int(cursor.lastrowid)

    def finish(
        self,
        attempt_id: int,
        *,
        status: str,
        outcome: str | None,
        result_count: int,
        scope: str | None,
        requests_used: int,
        finished_at: str,
        candidate_lookup_run_id: int | None = None,
    ) -> None:
        if status == "running":
            raise ValueError("finish closes a search attempt; running is not terminal")
        validate_search_attempt_status(status)
        if outcome is not None:
            validate_search_attempt_outcome(outcome)
        if result_count < 0 or requests_used < 0:
            raise ValueError("search attempt counts must not be negative")
        if scope is not None and len(scope) > 1000:
            raise ValueError("search attempt scope exceeds 1000 characters")
        self.connection.execute(
            """UPDATE discovery_search_attempts
                  SET status = ?, outcome = ?, result_count = ?, scope = ?,
                      requests_used = ?, finished_at = ?,
                      candidate_lookup_run_id =
                          COALESCE(?, candidate_lookup_run_id)
                WHERE discovery_search_attempt_id = ?""",
            (
                status,
                outcome,
                result_count,
                scope,
                requests_used,
                finished_at,
                candidate_lookup_run_id,
                attempt_id,
            ),
        )

    def latest(
        self,
        subject: SubjectRef,
        *,
        source_kind: str,
        source: str,
        method: str,
        query_digest: str,
    ) -> sqlite3.Row | None:
        subject_where, subject_params = subject.where_clause()
        return self.connection.execute(
            f"""SELECT {_ATTEMPT_COLUMNS}
                  FROM discovery_search_attempts
                 WHERE {subject_where} AND source_kind = ? AND source = ?
                   AND method = ? AND query_digest = ?
                 ORDER BY discovery_search_attempt_id DESC LIMIT 1""",
            (*subject_params, source_kind, source, method, query_digest),
        ).fetchone()

    def latest_for_subject(
        self, subject: SubjectRef
    ) -> dict[tuple[str, str, str, str], sqlite3.Row]:
        """Latest attempt per (source_kind, source, method, query_digest).

        The strategy version is deliberately not part of the lookup key so
        version drift surfaces as an explainable verdict rather than an
        invisible miss.
        """
        subject_where, subject_params = subject.where_clause()
        rows = self.connection.execute(
            f"""SELECT {_ATTEMPT_COLUMNS}
                  FROM discovery_search_attempts
                 WHERE {subject_where}
                   AND discovery_search_attempt_id IN (
                       SELECT MAX(discovery_search_attempt_id)
                         FROM discovery_search_attempts
                        WHERE {subject_where}
                        GROUP BY source_kind, source, method, query_digest)""",
            (*subject_params, *subject_params),
        ).fetchall()
        return {
            (
                row["source_kind"],
                row["source"],
                row["method"],
                row["query_digest"],
            ): row
            for row in rows
        }

    def history(self, subject: SubjectRef, *, limit: int = 50) -> list[dict[str, Any]]:
        subject_where, subject_params = subject.where_clause()
        rows = self.connection.execute(
            f"""SELECT {_ATTEMPT_COLUMNS}
                  FROM discovery_search_attempts
                 WHERE {subject_where}
                 ORDER BY discovery_search_attempt_id DESC LIMIT ?""",
            (*subject_params, limit),
        ).fetchall()
        return [dict(row) for row in rows]
