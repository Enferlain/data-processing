"""Attribution URLs feed the recognized link graph (bead data-processing-9er).

An artist-record fetch persists its stable account URLs into
attribution_urls as opaque strings; the link pass now observes them as
attribution-subject link occurrences, so they are canonicalized, recognized
against the platform registry, and become platform references — the
tag-to-handle identity bridge stops dying one table short.
"""

from __future__ import annotations

from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.discovery import DiscoveryService

NOW = "2026-11-05T12:00:00Z"


def _seed_artist(catalog: Path) -> int:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.execute("INSERT OR IGNORE INTO platforms (platform_key) VALUES ('e621')")
        connection.execute(
            """INSERT INTO attribution_entities
                   (platform_id, provider_attribution_id, adapter_version,
                    availability, first_seen_at, last_seen_at)
               VALUES ((SELECT platform_id FROM platforms WHERE platform_key = 'e621'),
                       '24584', 'e621-native-v2', 'available', ?, ?)""",
            (NOW, NOW),
        )
        entity_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.executemany(
            """INSERT INTO attribution_urls
                   (attribution_entity_id, url, observed_at) VALUES (?, ?, ?)""",
            [
                (entity_id, "https://twitter.com/d_rex_too", NOW),
                (entity_id, "https://www.hentai-foundry.com/user/D-rex/profile", NOW),
            ],
        )
        # Domain-shaped rows are not URLs and must not be scanned.
        connection.execute(
            """INSERT INTO attribution_urls
                   (attribution_entity_id, url, url_kind, observed_at)
               VALUES (?, 'd-rex-art.tumblr.com', 'domain', ?)""",
            (entity_id, NOW),
        )
        connection.commit()
        return entity_id


def test_attribution_urls_become_recognized_link_observations(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    entity_id = _seed_artist(catalog)

    with CatalogDatabase(catalog) as database:
        report = DiscoveryService(database).discover()
    assert report.status == "complete"
    # All three rows scanned; the domain row produced no occurrence, the
    # unrecognized host stays unresolved, the x URL is recognized.
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        rows = connection.execute(
            """SELECT lo.source_context, lo.subject_attribution_id,
                      el.resolution_state, p.platform_key, pr.object_kind
                 FROM link_observations lo
                 JOIN external_links el USING (external_link_id)
                 LEFT JOIN external_link_references elr USING (external_link_id)
                 LEFT JOIN platform_references pr USING (platform_reference_id)
                 LEFT JOIN platforms p ON p.platform_id = pr.platform_id
                WHERE lo.subject_kind = 'attribution'
                ORDER BY lo.link_observation_id"""
        ).fetchall()
    assert len(rows) == 2
    assert all(row["subject_attribution_id"] == entity_id for row in rows)
    assert all(row["source_context"] == "attribution.url" for row in rows)
    states = {row["resolution_state"] for row in rows}
    assert "recognized" in states
    recognized = next(row for row in rows if row["resolution_state"] == "recognized")
    assert recognized["platform_key"] == "x"
    assert recognized["object_kind"] == "account"
    # The unrecognized artist-home URL survives as unresolved evidence.
    assert "unresolved" in states

    # Idempotent: a second pass observes nothing new.
    with CatalogDatabase(catalog) as database:
        second = DiscoveryService(database).discover()
    assert second.as_dict()["counts"]["observed"] == 0


def test_links_query_surfaces_attribution_subjects(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    entity_id = _seed_artist(catalog)
    with CatalogDatabase(catalog) as database:
        DiscoveryService(database).discover()
        result = DiscoveryService(database).links(subject_kind="attribution", subject_id=entity_id)
    assert result["filters"] == {"subject_kind": "attribution", "subject_id": entity_id}
    assert len(result["results"]) == 2  # type: ignore[arg-type]
