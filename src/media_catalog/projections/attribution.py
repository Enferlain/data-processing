"""The ``attribution-disagreements`` projection: a review worklist, not a verdict.

One row per retained post-level relationship whose ends both carry artist
attribution and no cross-pair of attribution identities is joined by a
confirmed identity membership.  Attribution comes from account participants
(artist/author roles) and from provider attribution entities implied by the
post's tags.  The name-equality hint is weak evidence — it sorts nothing and
concludes nothing.  The projection is report-only: it never writes a review
decision, candidate, or relationship.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from media_catalog.projections.spec import ProjectionResult, enforce_allowlist

KIND = "attribution-disagreements"

ALLOWLIST = (
    "relationship_id",
    "relation_kind",
    "epistemic_status",
    "subject",
    "target",
    "name_match",
)

ENDPOINT_FIELDS = ("post_id", "platform", "native_post_id", "attribution")

PARTICIPANT_FIELDS = (
    "identity_kind",
    "platform",
    "native_id",
    "primary_name",
    "review_state",
)

ARTIST_ROLES = ("artist", "author")

POST_LEVEL_KINDS = ("reposted_from", "same_work")

POLICIES = {
    "selection": "linked_post_pairs_with_attributed_ends",
    "ordering": "relationship_id ascending",
    "dedup": "one_row_per_relationship",
    "preferred_representation": "not_applicable",
    "field_source": "participants_and_tag_implied_attribution_with_name_hint",
    "url_handling": "no_urls_emitted",
}

IDENTIFIERS = {
    "row_identifier": "relationship_id",
    "platform_identity": "subject and target post platform/native ids",
    "evidence": (
        "relationship_id references relationships; attribution entries reference "
        "post_participants/accounts and attribution_entities"
    ),
}


def build(
    connection: sqlite3.Connection, *, limit: int, platform: str | None = None
) -> ProjectionResult:
    if platform is not None:
        raise ValueError("the attribution-disagreements projection does not support filters")
    scanned = connection.execute(
        """SELECT r.relationship_id, r.relation_kind, r.epistemic_status, r.review_state,
                  r.subject_id AS subject_post_id, r.target_id AS target_post_id
             FROM relationships r
            WHERE r.relation_kind IN ('reposted_from', 'same_work')
              AND r.subject_kind = 'post' AND r.target_kind = 'post'
         ORDER BY r.relationship_id"""
    ).fetchall()
    exclusions: dict[str, int] = {}
    candidates: list[dict[str, Any]] = []
    for row in scanned:
        if row["review_state"] == "rejected":
            exclusions["rejected_relationship"] = exclusions.get("rejected_relationship", 0) + 1
            continue
        subject = _endpoint(connection, int(row["subject_post_id"]))
        target = _endpoint(connection, int(row["target_post_id"]))
        if not subject["attribution"] or not target["attribution"]:
            exclusions["attribution_missing_on_end"] = (
                exclusions.get("attribution_missing_on_end", 0) + 1
            )
            continue
        if _confirmed_join(connection, subject, target):
            exclusions["confirmed_identity_join"] = exclusions.get("confirmed_identity_join", 0) + 1
            continue
        candidates.append(
            enforce_allowlist(
                {
                    "relationship_id": int(row["relationship_id"]),
                    "relation_kind": str(row["relation_kind"]),
                    "epistemic_status": str(row["epistemic_status"]),
                    "subject": subject,
                    "target": target,
                    "name_match": _name_match(subject, target),
                },
                ALLOWLIST,
            )
        )
    excluded_by_limit = max(0, len(candidates) - limit)
    rows = candidates[:limit]
    if excluded_by_limit:
        exclusions["excluded_by_limit"] = excluded_by_limit
    selection_keys = [str(row["relationship_id"]) for row in rows]
    return ProjectionResult(
        rows,
        selection_keys,
        len(rows),
        [{"reason": reason, "count": count} for reason, count in sorted(exclusions.items())],
    )


def _endpoint(connection: sqlite3.Connection, post_id: int) -> dict[str, Any]:
    post = connection.execute(
        """SELECT p.post_id, pl.platform_key, p.native_post_id
             FROM posts p JOIN platforms pl ON pl.platform_id = p.platform_id
            WHERE p.post_id = ?""",
        (post_id,),
    ).fetchone()
    return enforce_allowlist(
        {
            "post_id": int(post["post_id"]),
            "platform": str(post["platform_key"]),
            "native_post_id": str(post["native_post_id"]),
            "attribution": [
                *_participants(connection, post_id),
                *_tag_implied(connection, post_id),
            ],
        },
        ENDPOINT_FIELDS,
    )


def _participants(connection: sqlite3.Connection, post_id: int) -> list[dict[str, Any]]:
    return [
        enforce_allowlist(
            {
                "identity_kind": "participant",
                "platform": str(row["platform_key"]),
                "native_id": str(row["native_account_id"]),
                "primary_name": (
                    str(row["primary_name"]) if row["primary_name"] is not None else None
                ),
                "review_state": str(row["review_state"]),
            },
            PARTICIPANT_FIELDS,
        )
        for row in connection.execute(
            """SELECT pl.platform_key, a.native_account_id, pp.review_state,
                      (SELECT COALESCE(s.display_name, s.handle)
                         FROM account_snapshots s
                        WHERE s.account_id = a.account_id
                     ORDER BY s.account_snapshot_id DESC LIMIT 1) AS primary_name
                 FROM post_participants pp
                 JOIN accounts a ON a.account_id = pp.account_id
                 JOIN platforms pl ON pl.platform_id = a.platform_id
                WHERE pp.post_id = ? AND pp.role IN ('artist', 'author')
             ORDER BY a.native_account_id""",
            (post_id,),
        )
    ]


def _tag_implied(connection: sqlite3.Connection, post_id: int) -> list[dict[str, Any]]:
    return [
        enforce_allowlist(
            {
                "identity_kind": "attribution_entity",
                "platform": str(row["platform_key"]),
                "native_id": str(row["provider_attribution_id"]),
                "primary_name": (
                    str(row["primary_name"]) if row["primary_name"] is not None else None
                ),
                "review_state": "observed",
            },
            PARTICIPANT_FIELDS,
        )
        for row in connection.execute(
            """SELECT pl.platform_key, ae.provider_attribution_id,
                      (SELECT n.name FROM attribution_names n
                        WHERE n.attribution_entity_id = ae.attribution_entity_id
                          AND n.name_kind = 'primary'
                     ORDER BY n.attribution_name_id DESC LIMIT 1) AS primary_name
                 FROM post_tags pt
                 JOIN tags t ON t.tag_id = pt.tag_id
                 JOIN attribution_tag_links atl ON atl.tag_id = t.tag_id
                 JOIN attribution_entities ae
                   ON ae.attribution_entity_id = atl.attribution_entity_id
                 JOIN platforms pl ON pl.platform_id = ae.platform_id
                WHERE pt.post_id = ?
             ORDER BY ae.provider_attribution_id""",
            (post_id,),
        )
    ]


def _confirmed_join(
    connection: sqlite3.Connection, subject: dict[str, Any], target: dict[str, Any]
) -> bool:
    """True when a confirmed identity membership joins any account pair."""

    subject_native_ids = [
        entry["native_id"]
        for entry in subject["attribution"]
        if entry["identity_kind"] == "participant"
    ]
    target_native_ids = [
        entry["native_id"]
        for entry in target["attribution"]
        if entry["identity_kind"] == "participant"
    ]
    if not subject_native_ids or not target_native_ids:
        return False
    query, values = _confirmed_join_query(subject_native_ids, target_native_ids)
    return connection.execute(query, values).fetchone() is not None


def _confirmed_join_query(
    subject_native_ids: list[str], target_native_ids: list[str]
) -> tuple[str, list[str]]:
    subject_marks = ",".join("?" * len(subject_native_ids))
    target_marks = ",".join("?" * len(target_native_ids))
    query = f"""
        SELECT 1
          FROM identity_accounts ia
          JOIN identity_accounts ib ON ib.identity_id = ia.identity_id
          JOIN accounts sa ON sa.account_id = ia.account_id
          JOIN accounts tb ON tb.account_id = ib.account_id
         WHERE sa.native_account_id IN ({subject_marks})
           AND tb.native_account_id IN ({target_marks})
           AND sa.account_id <> tb.account_id
         LIMIT 1
    """
    return query, [*subject_native_ids, *target_native_ids]


def _name_match(subject: dict[str, Any], target: dict[str, Any]) -> bool:
    """Exact casefolded primary-name equality across the ends — a hint only."""

    subject_names = {
        entry["primary_name"].casefold()
        for entry in subject["attribution"]
        if entry["primary_name"]
    }
    target_names = {
        entry["primary_name"].casefold() for entry in target["attribution"] if entry["primary_name"]
    }
    return bool(subject_names & target_names)
