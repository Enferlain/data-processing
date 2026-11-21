"""Labeling session state (bead data-processing-cne).

Owns the candidate queue, the managed-root match, the review cursor, and
verdict application (``pair_labels`` upsert plus the append-only
``pair_label_decisions`` history). Media resolution and HTML rendering
live in sibling modules; this class is the session facade the HTTP layer
drives.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

from media_catalog.labeling.media import resolve_post_media
from media_catalog.labeling.queue import CandidateQueue, PairCandidate, build_queue
from media_catalog.labeling.render import render_pair_page, render_post_view, render_queue_empty
from media_catalog.labeling.sankaku import SankakuDisplayResolver

VERDICTS = ("same", "variant", "different", "unsure")


class LabelingState:
    def __init__(
        self,
        connection: sqlite3.Connection,
        media_root: Path,
        *,
        revisit_unsure: bool = False,
        audit: int = 0,
        seed: int = 0,
    ) -> None:
        self.connection = connection
        self.media_root = media_root
        self.revisit_unsure = revisit_unsure
        self._matched_root_ids = self._find_matching_managed_roots()
        # 59/59 operator calibration: identical md5 pairs are byte-identical
        # assets and never need review — confirm them before building the
        # queue so they never consume operator attention.  In audit mode the
        # confirm still runs: the auto labels are one of the sampled
        # populations.
        from media_catalog.labeling.queue import (
            autoconfirm_identical_md5_pairs,
            build_audit_queue,
        )

        autoconfirm_identical_md5_pairs(connection)
        if audit > 0:
            self.queue: CandidateQueue = build_audit_queue(
                connection,
                sample_size=audit,
                seed=seed,
                media_root=media_root,
                matched_root_ids=self._matched_root_ids,
            )
        else:
            self.queue = build_queue(
                connection,
                revisit_unsure=revisit_unsure,
                media_root=media_root,
                matched_root_ids=self._matched_root_ids,
            )
        self.cursor = 0
        self._session_decisions: set[tuple[int, int, str]] = set()
        self.sankaku_media = SankakuDisplayResolver()

    def _find_matching_managed_roots(self) -> set[int]:
        """Find managed roots that match the media root via strict dev:ino identity."""
        resolved = self.media_root.resolve()
        current_identity = None
        with contextlib.suppress(OSError):
            st = resolved.stat()
            current_identity = f"{st.st_dev}:{st.st_ino}"
        if not current_identity:
            return set()

        matched: set[int] = set()
        with contextlib.suppress(sqlite3.Error):
            rows = self.connection.execute(
                "SELECT managed_root_id, root_identity "
                "FROM managed_roots WHERE root_kind = 'managed'"
            ).fetchall()
            for row in rows:
                root_id = int(row[0])
                root_identity = str(row[1]) if row[1] is not None else None
                if root_identity == current_identity:
                    matched.add(root_id)
        return matched

    def current(self) -> PairCandidate | None:
        while self.cursor < len(self.queue):
            pair = self.queue[self.cursor]
            if self.revisit_unsure:
                if (pair.post_a_id, pair.post_b_id, pair.queue_signal) in self._session_decisions:
                    self.cursor += 1
                    continue
                return pair
            row = self.connection.execute(
                "SELECT 1 FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?"
                " AND queue_signal = ?",
                (pair.post_a_id, pair.post_b_id, pair.queue_signal),
            ).fetchone()
            if row is None:
                return pair
            self.cursor += 1
        return None

    def _resolve_post_media(self, post_id: int) -> dict[str, Any]:
        return resolve_post_media(self.connection, self.media_root, self._matched_root_ids, post_id)

    def _post_view(self, post_id: int) -> dict[str, str]:
        return render_post_view(self._resolve_post_media(post_id))

    def page(self) -> str | None:
        pair = self.current()
        if pair is None:
            return render_queue_empty(self.revisit_unsure, getattr(self.queue, "skipped_count", 0))
        a = self._post_view(pair.post_a_id)
        b = self._post_view(pair.post_b_id)
        return render_pair_page(
            pair,
            a,
            b,
            pos=self.cursor + 1,
            pair_index=self.cursor,
            total=len(self.queue),
            revisit_unsure=self.revisit_unsure,
            skipped_count=getattr(self.queue, "skipped_count", 0),
        )

    def record(
        self,
        pair_index: int,
        verdict: str,
        note: str | None,
        now: str,
        *,
        expected_post_a_id: int | None = None,
        expected_post_b_id: int | None = None,
        expected_queue_signal: str | None = None,
    ) -> None:
        if verdict not in VERDICTS:
            raise ValueError(f"unsupported verdict: {verdict}")
        if not 0 <= pair_index < len(self.queue):
            raise ValueError("pair index out of range")
        pair = self.queue[pair_index]
        if expected_post_a_id is not None and pair.post_a_id != expected_post_a_id:
            raise ValueError(
                f"stale pair mismatch: expected post_a {expected_post_a_id}, got {pair.post_a_id}"
            )
        if expected_post_b_id is not None and pair.post_b_id != expected_post_b_id:
            raise ValueError(
                f"stale pair mismatch: expected post_b {expected_post_b_id}, got {pair.post_b_id}"
            )
        if expected_queue_signal is not None and pair.queue_signal != expected_queue_signal:
            raise ValueError(
                f"stale signal mismatch: expected {expected_queue_signal}, got {pair.queue_signal}"
            )

        prior_row = self.connection.execute(
            "SELECT verdict FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?"
            " AND queue_signal = ?",
            (pair.post_a_id, pair.post_b_id, pair.queue_signal),
        ).fetchone()
        prior_verdict = prior_row[0] if prior_row is not None else verdict
        self.connection.execute(
            """INSERT INTO pair_labels
                   (post_a_id, post_b_id, queue_signal, verdict, relation_note, labeled_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(post_a_id, post_b_id, queue_signal) DO UPDATE SET
                   verdict = excluded.verdict,
                   relation_note = excluded.relation_note,
                   labeled_at = excluded.labeled_at""",
            (pair.post_a_id, pair.post_b_id, pair.queue_signal, verdict, note, now),
        )
        label_id = int(
            self.connection.execute(
                "SELECT pair_label_id FROM pair_labels WHERE post_a_id = ?"
                " AND post_b_id = ? AND queue_signal = ?",
                (pair.post_a_id, pair.post_b_id, pair.queue_signal),
            ).fetchone()[0]
        )
        self.connection.execute(
            """INSERT INTO pair_label_decisions
                   (pair_label_id, prior_verdict, verdict, note, decided_at)
               VALUES (?, ?, ?, ?, ?)""",
            (label_id, prior_verdict, verdict, note, now),
        )
        self.connection.commit()
        self._session_decisions.add((pair.post_a_id, pair.post_b_id, pair.queue_signal))
        self.cursor = pair_index + 1
