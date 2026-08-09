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
        return occurrences
