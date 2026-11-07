from __future__ import annotations

from typing import Any

from media_catalog.links import account_occurrences, post_occurrences
from media_catalog.records import LinkOccurrence


class LinkOccurrenceScanner:
    """Collect link-bearing fields from retained account and post records."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def scan(self, counts: dict[str, int]) -> list[LinkOccurrence]:
        occurrences: list[LinkOccurrence] = []
        snapshots = self.connection.execute(
            """SELECT account_id, account_snapshot_id, observed_at, website_url, profile_url,
                      bio, raw_observation_id FROM account_snapshots"""
        )
        for row in snapshots:
            occurrences.extend(account_occurrences(dict(row)))
        posts = self.connection.execute(
            """SELECT p.post_id, p.canonical_url, p.text_content,
                      COALESCE(ro.observed_at, p.last_seen_at) AS observed_at,
                      p.raw_observation_id, rp.payload
               FROM posts p
               LEFT JOIN raw_observations ro ON ro.raw_observation_id = p.raw_observation_id
               LEFT JOIN raw_payloads rp ON rp.raw_payload_id = ro.raw_payload_id"""
        )
        for row in posts:
            try:
                occurrences.extend(post_occurrences(dict(row), row["payload"]))
            except (TypeError, ValueError):
                counts["failed"] += 1
        # Artist-record URLs: attribution_urls rows are the provider's own
        # stable account links for an artist; observing them feeds the
        # recognized link graph so the tag <-> handle identity bridge flows
        # (bead data-processing-9er).  Domain-only rows are not URLs.
        attributions = self.connection.execute(
            """SELECT attribution_entity_id, url, observed_at, raw_observation_id
                 FROM attribution_urls
                WHERE url_kind IS NULL OR url_kind != 'domain'"""
        )
        for row in attributions:
            occurrences.append(
                LinkOccurrence(
                    "attribution",
                    int(row["attribution_entity_id"]),
                    "attribution.url",
                    str(row["url"]),
                    str(row["observed_at"]),
                    raw_observation_id=(
                        int(row["raw_observation_id"])
                        if row["raw_observation_id"] is not None
                        else None
                    ),
                )
            )
        return occurrences
