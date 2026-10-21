"""The ``post-field-sources`` projection: which source supplied each field.

One row per post with retained post metadata observations.  Every observed
field carries its complete retained value history (value, observation time,
raw-observation evidence pointer); the current value is the newest
observation's, under the stated newest-observation-wins policy.  Dissenting
values are retained in the row, never collapsed.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from media_catalog.projections.spec import ProjectionResult, enforce_allowlist

KIND = "post-field-sources"

ALLOWLIST = ("post_id", "platform", "native_post_id", "fields")

FIELD_NAMES = (
    "score_up",
    "score_down",
    "score_total",
    "favorite_count",
    "comment_count",
    "flag_deleted",
    "flag_pending",
    "flag_flagged",
)

ENTRY_FIELDS = ("value", "observed_at", "raw_observation_id")
FIELD_FIELDS = ("field", "entries", "current")

POLICIES = {
    "selection": "posts_with_retained_metadata_observations",
    "ordering": "post_id ascending",
    "dedup": "none_post_identity",
    "preferred_representation": "not_applicable",
    "field_source": "newest_observation_wins_per_field_all_values_retained",
    "url_handling": "no_urls_emitted",
}

IDENTIFIERS = {
    "row_identifier": "post_id",
    "platform_identity": "platform plus native_post_id",
    "evidence": (
        "post_id references posts; every value entry carries the raw_observation_id behind it"
    ),
}


def build(
    connection: sqlite3.Connection, *, limit: int, platform: str | None = None
) -> ProjectionResult:
    if platform is not None:
        raise ValueError("the post-field-sources projection does not support a platform filter")
    posts_total = int(connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0])
    observed_posts = connection.execute(
        """SELECT p.post_id, pl.platform_key AS platform, p.native_post_id
             FROM posts p
             JOIN platforms pl ON pl.platform_id = p.platform_id
            WHERE EXISTS (SELECT 1 FROM post_metadata_observations pmo
                           WHERE pmo.post_id = p.post_id)
         ORDER BY p.post_id
            LIMIT ?""",
        (limit,),
    ).fetchall()
    unobserved = (
        posts_total
        - connection.execute(
            "SELECT COUNT(DISTINCT post_id) FROM post_metadata_observations"
        ).fetchone()[0]
    )
    rows = [_row(connection, record) for record in observed_posts]
    selection_keys = [f"{row['post_id']}:{row['platform']}:{row['native_post_id']}" for row in rows]
    exclusions: list[dict[str, Any]] = []
    if unobserved:
        exclusions.append({"reason": "no_retained_observations", "count": unobserved})
    observed_total = posts_total - unobserved
    excluded_by_limit = max(0, observed_total - limit)
    if excluded_by_limit:
        exclusions.append({"reason": "excluded_by_limit", "count": excluded_by_limit})
    return ProjectionResult(rows, selection_keys, len(rows), exclusions)


def _row(connection: sqlite3.Connection, record: sqlite3.Row) -> dict[str, Any]:
    post_id = int(record["post_id"])
    observations = connection.execute(
        """SELECT score_up, score_down, score_total, favorite_count, comment_count,
                  flag_deleted, flag_pending, flag_flagged, observed_at,
                  raw_observation_id
             FROM post_metadata_observations
            WHERE post_id = ?
         ORDER BY observed_at, post_metadata_observation_id""",
        (post_id,),
    ).fetchall()
    histories: dict[str, list[dict[str, Any]]] = {name: [] for name in FIELD_NAMES}
    for observation in observations:
        for name in FIELD_NAMES:
            value = observation[name]
            if value is None:
                # An observation asserts only its non-null fields; a null never
                # erases an earlier value (omission-never-erases policy).
                continue
            histories[name].append(
                enforce_allowlist(
                    {
                        "value": bool(value)
                        if isinstance(value, int) and name.startswith("flag_")
                        else int(value),
                        "observed_at": str(observation["observed_at"]),
                        "raw_observation_id": (
                            int(observation["raw_observation_id"])
                            if observation["raw_observation_id"] is not None
                            else None
                        ),
                    },
                    ENTRY_FIELDS,
                )
            )
    fields = [
        enforce_allowlist(
            {"field": name, "entries": entries, "current": entries[-1]},
            FIELD_FIELDS,
        )
        for name, entries in histories.items()
        if entries
    ]
    return enforce_allowlist(
        {
            "post_id": post_id,
            "platform": str(record["platform"]),
            "native_post_id": str(record["native_post_id"]),
            "fields": fields,
        },
        ALLOWLIST,
    )
