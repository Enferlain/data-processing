"""As-of review reports (bead ``data-processing-2ai``, change
``add-asof-review-reports``).

Read-only reconstruction over the decision ledgers, implementing the
temporal-semantics rule: review state at a cutoff is the latest decision at
or before the cutoff; subjects undecided by then did not exist yet.
Comparisons parse both sides (julianday) because stored timestamps mix
whole-second and fractional-second precision.  Nothing here writes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

_AS_OF = "julianday(replace({column}, 'Z', '+00:00'))"
_CANDIDATE_LEDGERS = (
    ("account", "account_match_candidates", "account_candidate_decisions"),
    ("post", "post_match_candidates", "post_candidate_decisions"),
    ("attribution", "attribution_match_candidates", "attribution_candidate_decisions"),
)


def validate_cutoff(value: str, *, name: str = "cutoff") -> str:
    """Calendar-validate an ISO-8601 UTC instant; return the normalized form."""

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(f"{name} must be an ISO-8601 UTC instant: {value!r}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must carry an explicit UTC offset: {value!r}")
    return value.strip()


def _at_or_before(column: str, cutoff: str) -> str:
    return f"{_AS_OF.format(column=column)} <= julianday(replace(?, 'Z', '+00:00'))"


def review_state_snapshot(connection: sqlite3.Connection, as_of: str) -> dict[str, Any]:
    """Reconstruct every review ledger's state as of ``as_of``."""

    snapshot: dict[str, Any] = {"as_of": as_of}

    # Pair labels: verdict at T = latest decision <= T (the first decision
    # is the initial labeling, so labels without a decision <= T did not
    # exist yet).
    rows = connection.execute(
        f"""SELECT signal, verdict, count(*) n FROM (
                SELECT pl.queue_signal signal,
                       (SELECT d.verdict FROM pair_label_decisions d
                         WHERE d.pair_label_id = pl.pair_label_id
                           AND {_at_or_before("d.decided_at", as_of)}
                         ORDER BY julianday(replace(d.decided_at, 'Z', '+00:00')) DESC,
                                  d.pair_label_decision_id DESC LIMIT 1) verdict
                  FROM pair_labels pl
                 WHERE EXISTS (SELECT 1 FROM pair_label_decisions d
                                WHERE d.pair_label_id = pl.pair_label_id
                                  AND {_at_or_before("d.decided_at", as_of)}))
             WHERE verdict IS NOT NULL GROUP BY 1, 2""",
        (as_of, as_of),
    ).fetchall()
    by_signal: dict[str, dict[str, int]] = {}
    for signal, verdict, count in rows:
        by_signal.setdefault(str(signal), {})[str(verdict)] = int(count)
    reversals = connection.execute(
        f"""SELECT count(*) FROM pair_label_decisions d
             WHERE {_at_or_before("d.decided_at", as_of)}
               AND d.prior_verdict IS NOT NULL AND d.prior_verdict != d.verdict""",
        (as_of,),
    ).fetchone()[0]
    snapshot["pair_labels"] = {
        "by_signal_verdict": by_signal,
        "labels_decided": sum(sum(v.values()) for v in by_signal.values()),
        "reversals_so_far": int(reversals),
    }

    # Candidate ledgers: candidates created <= T at their latest decision
    # <= T, else pending.
    candidates: dict[str, Any] = {}
    for kind, candidate_table, decision_table in _CANDIDATE_LEDGERS:
        rows = connection.execute(
            f"""SELECT state, count(*) n FROM (
                    SELECT (SELECT d.decision FROM {decision_table} d
                             WHERE d.{kind}_candidate_id = c.{kind}_candidate_id
                               AND {_at_or_before("d.decided_at", as_of)}
                             ORDER BY julianday(replace(d.decided_at, 'Z', '+00:00')) DESC,
                                      d.{kind}_decision_id DESC LIMIT 1) state
                      FROM {candidate_table} c
                     WHERE {_at_or_before("c.created_at", as_of)})
                 GROUP BY 1""",
            (as_of, as_of),
        ).fetchall()
        states = {("pending" if state is None else str(state)): int(n) for state, n in rows}
        candidates[kind] = {
            "by_state": states,
            "created": sum(states.values()),
        }
    snapshot["candidates"] = candidates

    # Relationships: rows created <= T at their latest recorded transition
    # <= T; the birth status before any transition (the earliest decision's
    # prior_state when the relationship was ever decided, else the current
    # review_state, which is valid exactly when it was never decided).
    rows = connection.execute(
        f"""SELECT COALESCE(
                    (SELECT d.decision FROM relationship_review_decisions d
                      WHERE d.relationship_id = r.relationship_id
                        AND {_at_or_before("d.decided_at", as_of)}
                      ORDER BY julianday(replace(d.decided_at, 'Z', '+00:00')) DESC,
                               d.relationship_decision_id DESC LIMIT 1),
                    COALESCE((SELECT d.prior_state FROM relationship_review_decisions d
                               WHERE d.relationship_id = r.relationship_id
                               ORDER BY julianday(replace(d.decided_at, 'Z', '+00:00')) ASC,
                                        d.relationship_decision_id ASC LIMIT 1),
                             r.review_state)) state,
               count(*) n
          FROM relationships r
         WHERE {_at_or_before("r.created_at", as_of)}
         GROUP BY 1""",
        (as_of, as_of),
    ).fetchall()
    relationship_states = {str(state): int(n) for state, n in rows}
    snapshot["relationships"] = {
        "by_state": relationship_states,
        "created": sum(relationship_states.values()),
    }
    return snapshot


def change_report(connection: sqlite3.Connection, start: str, end: str) -> dict[str, Any]:
    """What was decided and what arrived between two cutoffs.

    The window is half-open on the left: entries with timestamp ``> start``
    and ``<= end`` chain without overlap.
    """

    window = (start, end)

    def in_window(column: str) -> str:
        after = f"{_AS_OF.format(column=column)} > julianday(replace(?, 'Z', '+00:00'))"
        before = _at_or_before(column, end)
        return f"{after} AND {before}"

    report: dict[str, Any] = {"start": start, "end": end}

    pair_decisions = connection.execute(
        f"""SELECT d.verdict, d.prior_verdict, count(*) n
             FROM pair_label_decisions d
            WHERE {in_window("d.decided_at")}
            GROUP BY 1, 2""",
        window,
    ).fetchall()
    transitions = 0
    reversals = 0
    first_time = 0
    by_verdict: dict[str, int] = {}
    for verdict, prior, count in pair_decisions:
        count = int(count)
        transitions += count
        by_verdict[str(verdict)] = by_verdict.get(str(verdict), 0) + count
        if prior != verdict:
            reversals += count
    # the ledger's convention: a first decision carries its own verdict as
    # the prior, so first-time decisions are those with no earlier entry
    first_time = int(
        connection.execute(
            f"""SELECT count(*) FROM pair_label_decisions d
                 WHERE {in_window("d.decided_at")}
                   AND NOT EXISTS (SELECT 1 FROM pair_label_decisions earlier
                                    WHERE earlier.pair_label_id = d.pair_label_id
                                      AND earlier.pair_label_decision_id
                                         < d.pair_label_decision_id)""",
            window,
        ).fetchone()[0]
    )
    report["pair_labels"] = {
        "decisions": transitions,
        "first_time": first_time,
        "reversals": reversals,
        "by_verdict": by_verdict,
    }

    candidate_changes: dict[str, Any] = {}
    for kind, candidate_table, decision_table in _CANDIDATE_LEDGERS:
        decided = connection.execute(
            f"""SELECT count(*) FROM {decision_table} d
                 WHERE {in_window("d.decided_at")}""",
            window,
        ).fetchone()[0]
        created = connection.execute(
            f"""SELECT count(*) FROM {candidate_table} c
                 WHERE {in_window("c.created_at")}""",
            window,
        ).fetchone()[0]
        candidate_changes[kind] = {"decisions": int(decided), "created": int(created)}
    report["candidates"] = candidate_changes

    relationship_decisions = connection.execute(
        f"""SELECT count(*) FROM relationship_review_decisions d
             WHERE {in_window("d.decided_at")}""",
        window,
    ).fetchone()[0]
    relationships_created = connection.execute(
        f"""SELECT count(*) FROM relationships r
             WHERE {in_window("r.created_at")}""",
        window,
    ).fetchone()[0]
    report["relationships"] = {
        "decisions": int(relationship_decisions),
        "created": int(relationships_created),
    }

    observations = connection.execute(
        f"""SELECT object_kind, count(*) n FROM raw_observations o
             WHERE {in_window("o.observed_at")}
             GROUP BY 1 ORDER BY n DESC LIMIT 10""",
        window,
    ).fetchall()
    total_observations = connection.execute(
        f"""SELECT count(*) FROM raw_observations o
             WHERE {in_window("o.observed_at")}""",
        window,
    ).fetchone()[0]
    runs_finished = connection.execute(
        f"""SELECT count(*) FROM remote_runs r
             WHERE r.finished_at IS NOT NULL AND {in_window("r.finished_at")}""",
        window,
    ).fetchone()[0]
    report["arrivals"] = {
        "observations": int(total_observations),
        "observations_by_kind": {str(kind): int(n) for kind, n in observations},
        "runs_finished": int(runs_finished),
    }
    return report
