"""Labeling tool: pair queues, media resolution, and label recording."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from media_catalog.database import CatalogDatabase
from media_catalog.labeling.queue import build_queue
from media_catalog.labeling.server import LabelingState, create_server

NOW = "2026-11-07T14:00:00Z"


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(path):
        pass
    return path


def _seed_pair(catalog: Path, *, md5_a: str, md5_b: str, tag: str) -> tuple[int, int]:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        ids = []
        for index, md5 in enumerate((md5_a, md5_b)):
            platform = ("e621", "gelbooru")[index]
            connection.execute(
                "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES (?, ?)",
                (platform, platform),
            )
            platform_id = int(
                connection.execute(
                    "SELECT platform_id FROM platforms WHERE platform_key = ?", (platform,)
                ).fetchone()[0]
            )
            connection.execute(
                """INSERT INTO posts (platform_id, native_post_id, availability,
                                          first_seen_at, last_seen_at)
                   VALUES (?, ?, 'available', ?, ?)""",
                (platform_id, f"{900 + index}", NOW, NOW),
            )
            post_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.execute(
                """INSERT INTO media_occurrences
                       (post_id, source_key, media_index, media_type, role,
                        remote_url, declared_md5, availability, observed_at)
                   VALUES (?, 'seed', 0, 'original', 'original',
                           'https://example.invalid/a.jpg', ?, 'available', ?)""",
                (post_id, md5, NOW),
            )
            connection.execute(
                "INSERT OR IGNORE INTO tags (platform_id, name, category,"
                " normalization_version, created_at)"
                " VALUES ((SELECT platform_id FROM platforms WHERE platform_key='e621'),"
                " ?, 'artist', 'seed-v1', ?)",
                (tag, NOW),
            )
            tag_id = int(
                connection.execute("SELECT tag_id FROM tags WHERE name = ?", (tag,)).fetchone()[0]
            )
            connection.execute(
                "INSERT INTO post_tags (post_id, tag_id, first_seen_at, last_seen_at)"
                " VALUES (?, ?, ?, ?)",
                (post_id, tag_id, NOW, NOW),
            )
            ids.append(post_id)
        connection.commit()
        return ids[0], ids[1]


def test_identical_md5_cross_platform_queues(catalog: Path) -> None:
    a, b = _seed_pair(catalog, md5_a="a" * 32, md5_b="a" * 32, tag="artist_x")
    with CatalogDatabase(catalog) as database:
        queue = build_queue(database.connection)
    assert (a, b, "identical_md5") in {(p.post_a_id, p.post_b_id, p.queue_signal) for p in queue}


def test_same_artist_contrast_pairs_queue(catalog: Path) -> None:
    a, b = _seed_pair(catalog, md5_a="a" * 32, md5_b="b" * 32, tag="artist_x")
    with CatalogDatabase(catalog) as database:
        queue = build_queue(database.connection)
    signals = {(p.post_a_id, p.post_b_id): p.queue_signal for p in queue}
    assert signals.get((a, b)) == "same_artist_contrast"


def test_identical_md5_pairs_autoconfirm_instead_of_queueing(catalog: Path) -> None:
    """59/59 operator calibration: identical md5 pairs are byte-identical
    assets — confirmed automatically, never queued for review."""
    from media_catalog.labeling.queue import autoconfirm_identical_md5_pairs

    a, b = _seed_pair(catalog, md5_a="9" * 32, md5_b="9" * 32, tag="artist_auto")
    with CatalogDatabase(catalog) as database:
        written = autoconfirm_identical_md5_pairs(database.connection)
    assert written == 1
    with CatalogDatabase(catalog) as database:
        row = database.connection.execute(
            "SELECT verdict, relation_note FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?",
            (a, b),
        ).fetchone()
    assert row["verdict"] == "same"
    assert row["relation_note"].startswith("auto:")
    # idempotent, and the pair no longer queues
    with CatalogDatabase(catalog) as database:
        assert autoconfirm_identical_md5_pairs(database.connection) == 0
        queue = build_queue(database.connection)
    assert all((p.post_a_id, p.post_b_id) != (a, b) for p in queue)


def test_labels_record_with_history_and_exclude_requeue(catalog: Path) -> None:
    a, b = _seed_pair(catalog, md5_a="a" * 32, md5_b="m" * 32, tag="artist_x")
    with CatalogDatabase(catalog) as database:
        state = LabelingState(database.connection, catalog.parent)
        state.record(
            0,
            "variant",
            "text overlay removed",
            NOW,
            expected_post_a_id=a,
            expected_post_b_id=b,
            expected_queue_signal="same_artist_contrast",
        )
        row = database.connection.execute(
            "SELECT verdict, relation_note FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?",
            (a, b),
        ).fetchone()
        assert tuple(row) == ("variant", "text overlay removed")
        history = database.connection.execute(
            "SELECT prior_verdict, verdict FROM pair_label_decisions"
        ).fetchall()
        assert [tuple(h) for h in history] == [("variant", "variant")]
        # The labeled pair drops out of a rebuilt queue.
        assert all((p.post_a_id, p.post_b_id) != (a, b) for p in build_queue(database.connection))


def test_verdict_vocabulary_is_enforced(catalog: Path) -> None:
    _seed_pair(catalog, md5_a="a" * 32, md5_b="b" * 32, tag="artist_x")
    with (
        CatalogDatabase(catalog) as database,
        pytest.raises(ValueError, match="verdict"),
    ):
        LabelingState(database.connection, catalog.parent).record(0, "similar-ish", None, NOW)


def test_signal_detail_clarifications(catalog: Path) -> None:
    # Pair 1 for same-artist contrast
    _seed_pair(catalog, md5_a="a" * 32, md5_b="b" * 32, tag="artist_contrast")

    # Pair 2 for provider parent (separate posts to avoid deduplication)
    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES ('e621', 'e621')"
        )
        p_id = int(
            conn.execute("SELECT platform_id FROM platforms WHERE platform_key='e621'").fetchone()[
                0
            ]
        )
        conn.execute(
            """INSERT INTO posts (platform_id, native_post_id, availability,
                                  first_seen_at, last_seen_at)
               VALUES (?, 'p1', 'available', ?, ?)""",
            (p_id, NOW, NOW),
        )
        parent_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """INSERT INTO media_occurrences
                   (post_id, source_key, media_index, media_type, role,
                    remote_url, declared_md5, availability, observed_at)
               VALUES (?, 'k1', 0, 'orig', 'orig', 'https://example.invalid/p1.jpg', ?,
                       'available', ?)""",
            (parent_id, "1" * 32, NOW),
        )

        conn.execute(
            """INSERT INTO posts (platform_id, native_post_id, availability,
                                  first_seen_at, last_seen_at)
               VALUES (?, 'p2', 'available', ?, ?)""",
            (p_id, NOW, NOW),
        )
        child_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """INSERT INTO media_occurrences
                   (post_id, source_key, media_index, media_type, role,
                    remote_url, declared_md5, availability, observed_at)
               VALUES (?, 'k2', 0, 'orig', 'orig', 'https://example.invalid/p2.jpg', ?,
                       'available', ?)""",
            (child_id, "2" * 32, NOW),
        )

        conn.execute(
            """INSERT INTO post_relations (source_post_id, target_post_id, relation_type)
               VALUES (?, ?, 'parent_of')""",
            (parent_id, child_id),
        )
        conn.commit()

        queue = build_queue(conn)

    details = {p.queue_signal: p.detail for p in queue}
    assert "different works expected" in details.get("same_artist_contrast", "")
    assert "parent does not prove variant" in details.get("provider_parent", "")


def test_storage_root_selection_and_managed_root_identity(catalog: Path, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    other_root = tmp_path / "other"
    other_root.mkdir()

    # Create dummy local files
    local_file = media_root / "original.jpg"
    local_file.write_bytes(b"JPEG_DATA")
    other_file = other_root / "unrelated.jpg"
    other_file.write_bytes(b"OTHER_DATA")

    # Accurate device:inode identity from media_root stat
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"

    a, b = _seed_pair(catalog, md5_a="c" * 32, md5_b="o" * 32, tag="artist_y")

    sha_1 = "1" * 64
    sha_2 = "2" * 64

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        # Register managed root 1 (matching media_root strictly by device:inode)
        conn.execute(
            """INSERT INTO managed_roots
                   (managed_root_id, root_kind, root_identity, display_label,
                    private_path, created_at)
               VALUES (1, 'managed', ?, 'Primary Media', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        # Register managed root 2 (unrelated identity)
        conn.execute(
            """INSERT INTO managed_roots
                   (managed_root_id, root_kind, root_identity, display_label,
                    private_path, created_at)
               VALUES (2, 'managed', 'dev2:ino2', 'Other Media', ?, ?)""",
            (str(other_root), NOW),
        )

        # Asset 1 in matching root 1
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size, mime_type,
                                   storage_kind, verification_method)
               VALUES (101, ?, ?, 9, 'image/jpeg', 'managed', 'sha256')""",
            (sha_1, "c" * 32),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (101, 1, 'original.jpg', 'managed', ?)""",
            (NOW,),
        )
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES ((SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ?),
                       101, 'original', 'local')""",
            (a,),
        )

        # Asset 2 in unrelated root 2
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size, mime_type,
                                   storage_kind, verification_method)
               VALUES (102, ?, ?, 10, 'image/jpeg', 'managed', 'sha256')""",
            (sha_2, "c" * 32),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (102, 2, 'unrelated.jpg', 'managed', ?)""",
            (NOW,),
        )
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES ((SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ?),
                       102, 'original', 'local')""",
            (b,),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_a = state._post_view(a)
        view_b = state._post_view(b)

        # Asset A in root 1 resolves to local /media/original.jpg
        assert "/media/original.jpg" in view_a["media_html"]
        # Asset B in root 2 does NOT resolve to /media/unrelated.jpg; falls back to remote URL
        assert "/media/unrelated.jpg" not in view_b["media_html"]
        assert "https://example.invalid/a.jpg" in view_b["media_html"]

        state.record(0, "unsure", "compare local copies", NOW)
        conn.execute("UPDATE media_occurrences SET remote_url = NULL")
        conn.commit()
        # A same-named file cannot make a location from another root eligible.
        (media_root / "unrelated.jpg").write_bytes(b"OTHER_DATA")
        deferred = LabelingState(conn, media_root, revisit_unsure=True)
        assert not deferred.queue
        assert deferred.queue.skipped_count == 1
        conn.execute("UPDATE asset_locations SET managed_root_id = 1 WHERE asset_id = 102")
        conn.commit()
        ready = LabelingState(conn, media_root, revisit_unsure=True)
        assert [(p.post_a_id, p.post_b_id) for p in ready.queue] == [(a, b)]
        assert ready.queue.skipped_count == 0


def test_missing_local_file_feedback(catalog: Path, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"
    sha_3 = "3" * 64

    a, _ = _seed_pair(catalog, md5_a="d" * 32, md5_b="p" * 32, tag="artist_z")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            """INSERT INTO managed_roots
                   (managed_root_id, root_kind, root_identity, display_label,
                    private_path, created_at)
               VALUES (1, 'managed', ?, 'Primary Media', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size, mime_type,
                                   storage_kind, verification_method)
               VALUES (201, ?, ?, 100, 'image/jpeg', 'managed', 'sha256')""",
            (sha_3, "d" * 32),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (201, 1, 'non_existent.jpg', 'managed', ?)""",
            (NOW,),
        )
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES ((SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ?),
                       201, 'original', 'local')""",
            (a,),
        )
        # Clear remote_url to test missing local file feedback
        conn.execute(
            "UPDATE media_occurrences SET remote_url = NULL WHERE post_id = ?",
            (a,),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_a = state._post_view(a)

        assert "media-box missing" in view_a["media_html"]
        assert "Missing local media file" in view_a["media_html"]
        assert "non_existent.jpg" in view_a["media_html"]


def test_media_types_rendering(catalog: Path, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES ('test', 'Test')"
        )
        p_id = int(
            conn.execute("SELECT platform_id FROM platforms WHERE platform_key='test'").fetchone()[
                0
            ]
        )

        def make_post(native_id: str, remote_url: str, mime: str, role: str = "original") -> int:
            conn.execute(
                """INSERT INTO posts (platform_id, native_post_id, availability,
                                      first_seen_at, last_seen_at)
                   VALUES (?, ?, 'available', ?, ?)""",
                (p_id, native_id, NOW, NOW),
            )
            post_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                """INSERT INTO media_occurrences
                       (post_id, source_key, media_index, media_type, role,
                        remote_url, mime_type, availability, observed_at)
                   VALUES (?, 'src', 0, 'media', ?, ?, ?, 'available', ?)""",
                (post_id, role, remote_url, mime, NOW),
            )
            return post_id

        video_post = make_post("10", "https://example.invalid/clip.webm", "video/webm")
        gif_post = make_post("11", "https://example.invalid/anim.gif", "image/gif")
        audio_post = make_post("12", "https://example.invalid/sound.mp3", "audio/mpeg")
        preview_post = make_post(
            "13", "https://example.invalid/thumb.jpg", "image/jpeg", role="preview"
        )
        conn.commit()

        state = LabelingState(conn, media_root)

        # Video: renders <video controls
        v_view = state._post_view(video_post)
        assert "<video" in v_view["media_html"] and "controls" in v_view["media_html"]
        assert 'type="video/webm"' in v_view["media_html"]
        assert 'data-source-url="https://example.invalid/clip.webm"' in v_view["media_html"]

        # GIF: renders native <img>
        g_view = state._post_view(gif_post)
        assert "<img" in g_view["media_html"]
        assert "<video" not in g_view["media_html"]
        assert 'data-source-url="https://example.invalid/anim.gif"' in g_view["media_html"]

        # Audio: renders <audio controls
        a_view = state._post_view(audio_post)
        assert "<audio" in a_view["media_html"] and "controls" in a_view["media_html"]

        # Preview: shows badge and metadata notice
        p_view = state._post_view(preview_post)
        assert "badge-preview" in p_view["media_html"]
        assert "[preview only]" in p_view["meta"]


def test_thumbnail_does_not_override_original_remote(catalog: Path, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()
    thumb_file = media_root / "thumb.jpg"
    thumb_file.write_bytes(b"THUMB")
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"
    sha_4 = "4" * 64

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES ('test', 'Test')"
        )
        p_id = int(
            conn.execute("SELECT platform_id FROM platforms WHERE platform_key='test'").fetchone()[
                0
            ]
        )
        conn.execute(
            """INSERT INTO posts (platform_id, native_post_id, availability,
                                  first_seen_at, last_seen_at)
               VALUES (?, '20', 'available', ?, ?)""",
            (p_id, NOW, NOW),
        )
        post_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        # Original occurrence with remote URL and declared MD5
        conn.execute(
            """INSERT INTO media_occurrences
                   (post_id, source_key, media_index, media_type, role,
                    remote_url, declared_md5, availability, observed_at)
               VALUES (?, 'orig', 0, 'original', 'original',
                       'https://example.invalid/full.png', ?, 'available', ?)""",
            (post_id, "o" * 32, NOW),
        )
        orig_occ_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        # Preview occurrence with local asset
        conn.execute(
            """INSERT INTO managed_roots (managed_root_id, root_kind, root_identity,
                                         display_label, private_path, created_at)
               VALUES (1, 'managed', ?, 'Media', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size,
                                   mime_type, storage_kind, verification_method)
               VALUES (301, ?, ?, 5, 'image/jpeg', 'managed', 'sha256')""",
            (sha_4, "t" * 32),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (301, 1, 'thumb.jpg', 'managed', ?)""",
            (NOW,),
        )
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES (?, 301, 'preview', 'downloaded')""",
            (orig_occ_id,),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view = state._post_view(post_id)

        # Original remote must win over preview local asset
        assert "https://example.invalid/full.png" in view["media_html"]
        assert "/media/thumb.jpg" not in view["media_html"]


@pytest.mark.parametrize("new_note", [None, "confirmed same after zoom"])
def test_revisit_unsure_queue_mode(catalog: Path, new_note: str | None) -> None:
    a, b = _seed_pair(catalog, md5_a="e" * 32, md5_b="q" * 32, tag="artist_revisit")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        state = LabelingState(conn, catalog.parent)
        state.record(
            0,
            "unsure",
            "unclear resolution difference",
            NOW,
            expected_post_a_id=a,
            expected_post_b_id=b,
            expected_queue_signal="same_artist_contrast",
        )

        # In normal mode, labeled pair is excluded
        normal_queue = build_queue(conn, revisit_unsure=False)
        assert all((p.post_a_id, p.post_b_id) != (a, b) for p in normal_queue)

        # In revisit mode, pair retains its prior note as context.
        revisit_queue = build_queue(conn, revisit_unsure=True)
        matching = [p for p in revisit_queue if (p.post_a_id, p.post_b_id) == (a, b)]
        assert len(matching) == 1
        assert matching[0].prior_note == "unclear resolution difference"

        # Previous descriptions stay visible without becoming new submissions.
        revisit_state = LabelingState(conn, catalog.parent, revisit_unsure=True)
        page_html = revisit_state.page()
        assert page_html is not None
        assert "prior note &#x27;unclear resolution difference&#x27;" in page_html
        assert 'placeholder="new description (optional)" value="" autocomplete="off"' in page_html

        # Relabeling to 'same' updates pair_labels and appends to pair_label_decisions
        revisit_state.record(
            0,
            "same",
            new_note,
            NOW,
            expected_post_a_id=a,
            expected_post_b_id=b,
            expected_queue_signal="same_artist_contrast",
        )
        row = conn.execute(
            "SELECT verdict, relation_note FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?",
            (a, b),
        ).fetchone()
        assert tuple(row) == ("same", new_note)

        decisions = conn.execute(
            """SELECT prior_verdict, verdict, note
                 FROM pair_label_decisions
                ORDER BY pair_label_decision_id"""
        ).fetchall()
        assert [tuple(d) for d in decisions] == [
            ("unsure", "unsure", "unclear resolution difference"),
            ("unsure", "same", new_note),
        ]

        # Drops out of unsure queue now that verdict is 'same'
        refreshed_unsure = build_queue(conn, revisit_unsure=True)
        assert all((p.post_a_id, p.post_b_id) != (a, b) for p in refreshed_unsure)


def test_resaved_unsure_remains_available_for_later_review(catalog: Path) -> None:
    _seed_pair(catalog, md5_a="e" * 32, md5_b="q" * 32, tag="artist_revisit")
    with CatalogDatabase(catalog) as database:
        conn = database.connection
        LabelingState(conn, catalog.parent).record(0, "unsure", "first look", NOW)
        revisit = LabelingState(conn, catalog.parent, revisit_unsure=True)
        revisit.record(0, "unsure", "still unsure", NOW)
        page = revisit.page()
        assert page is not None
        assert "Saved unsure decisions remain available for later review" in page
        assert "every unsure pair has been relabeled" not in page
        assert len(LabelingState(conn, catalog.parent, revisit_unsure=True).queue) == 1


@pytest.mark.parametrize("missing", ["stub", "post", "occurrence", "url"])
def test_revisit_defers_unusable_pairs_without_losing_labels(catalog: Path, missing: str) -> None:
    a, b = _seed_pair(catalog, md5_a="e" * 32, md5_b="q" * 32, tag="artist_revisit")
    with CatalogDatabase(catalog) as database:
        conn = database.connection
        platform = conn.execute("SELECT platform_id FROM posts WHERE post_id = ?", (a,)).fetchone()[
            0
        ]
        stub = conn.execute(
            """INSERT INTO posts
                   (platform_id, native_post_id, availability, first_seen_at, last_seen_at)
               VALUES (?, 'missing-target', ?, ?, ?)""",
            (platform, "unavailable" if missing == "post" else "available", NOW, NOW),
        ).lastrowid
        if missing != "stub":
            conn.execute(
                """INSERT INTO media_occurrences
                       (post_id, source_key, media_index, media_type, remote_url,
                        availability, observed_at)
                   VALUES (?, 'missing-media', 0, 'image/png', ?, ?, ?)""",
                (
                    stub,
                    None if missing == "url" else "https://example.invalid/parent.png",
                    "unavailable" if missing == "occurrence" else "available",
                    NOW,
                ),
            )
        conn.execute(
            """INSERT INTO pair_labels
                   (post_a_id, post_b_id, queue_signal, verdict, relation_note, labeled_at)
               VALUES (?, ?, 'provider_parent', 'unsure', 'waiting for parent media', ?)""",
            (a, stub, NOW),
        )
        conn.commit()
        LabelingState(conn, catalog.parent).record(0, "unsure", "ready pair note", NOW)
        before = conn.execute("SELECT * FROM pair_labels ORDER BY pair_label_id").fetchall()
        history = conn.execute("SELECT * FROM pair_label_decisions").fetchall()

        # A deferred first entry must not consume the queue's limit.
        queue = build_queue(conn, revisit_unsure=True, limit=1)
        assert [(p.post_a_id, p.post_b_id, p.prior_note) for p in queue] == [
            (a, b, "ready pair note")
        ]
        assert queue.skipped_count == 1
        assert conn.execute("SELECT * FROM pair_labels ORDER BY pair_label_id").fetchall() == before
        assert conn.execute("SELECT * FROM pair_label_decisions").fetchall() == history

        state = LabelingState(conn, catalog.parent, revisit_unsure=True)
        state.record(0, "same", "reviewed the available pair", NOW)
        page = LabelingState(conn, catalog.parent, revisit_unsure=True).page()
        assert page is not None
        assert "No more saved unsure pairs are ready" in page
        assert "labels and notes have been preserved" in page
        assert "every unsure pair has been relabeled" not in page
        assert conn.execute(
            "SELECT verdict, relation_note FROM pair_labels WHERE post_b_id = ?", (stub,)
        ).fetchone()[:] == ("unsure", "waiting for parent media")


def test_unavailable_and_no_media_posts_excluded_from_normal_queue(catalog: Path) -> None:
    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name) VALUES ('e621', 'e621')"
        )
        p_id = int(
            conn.execute("SELECT platform_id FROM platforms WHERE platform_key='e621'").fetchone()[
                0
            ]
        )

        # Post 1: available with media
        conn.execute(
            """INSERT INTO posts (platform_id, native_post_id, availability,
                                  first_seen_at, last_seen_at)
               VALUES (?, '1', 'available', ?, ?)""",
            (p_id, NOW, NOW),
        )
        post_1 = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """INSERT INTO media_occurrences
                   (post_id, source_key, media_index, media_type, role,
                    remote_url, declared_md5, availability, observed_at)
               VALUES (?, 'k1', 0, 'orig', 'orig', 'https://example.invalid/1.jpg',
                       'md5_1', 'available', ?)""",
            (post_1, NOW),
        )

        # Post 2: unavailable (tombstoned)
        conn.execute(
            """INSERT INTO posts (platform_id, native_post_id, availability,
                                  first_seen_at, last_seen_at)
               VALUES (?, '2', 'unavailable', ?, ?)""",
            (p_id, NOW, NOW),
        )
        post_2 = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            """INSERT INTO media_occurrences
                   (post_id, source_key, media_index, media_type, role,
                    remote_url, declared_md5, availability, observed_at)
               VALUES (?, 'k2', 0, 'orig', 'orig', 'https://example.invalid/2.jpg',
                       'md5_1', 'available', ?)""",
            (post_2, NOW),
        )

        # Post 3: available but NO media occurrences
        conn.execute(
            """INSERT INTO posts (platform_id, native_post_id, availability,
                                  first_seen_at, last_seen_at)
               VALUES (?, '3', 'available', ?, ?)""",
            (p_id, NOW, NOW),
        )
        post_3 = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        # Link post_1 and post_3 via parent_of relation
        conn.execute(
            """INSERT INTO post_relations (source_post_id, target_post_id, relation_type)
               VALUES (?, ?, 'parent_of')""",
            (post_1, post_3),
        )
        conn.commit()

        queue = build_queue(conn)
        # Pair with post_2 (unavailable) must not be queued
        assert all(post_2 not in (p.post_a_id, p.post_b_id) for p in queue)
        # Pair with post_3 (no media) must not be queued and must be counted as skipped
        assert all(post_3 not in (p.post_a_id, p.post_b_id) for p in queue)
        assert queue.skipped_count >= 1


def test_production_http_server_media_streaming_and_save_feedback(
    catalog: Path, tmp_path: Path
) -> None:
    media_root = tmp_path / "media"
    media_root.mkdir()

    # Use extensionless CAS filename to verify DB detected_mime_type lookup
    cas_name = "5" * 64
    cas_file = media_root / cas_name
    cas_file.write_bytes(b"0123456789ABCDEF")
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"
    sha_5 = "5" * 64

    # Seed asset to test detected_mime_type lookup from DB on /media/ endpoint
    with CatalogDatabase(catalog) as db:
        c = db.connection
        c.execute(
            """INSERT INTO managed_roots (managed_root_id, root_kind, root_identity,
                                         display_label, private_path, created_at)
               VALUES (1, 'managed', ?, 'M', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        c.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size,
                                   detected_mime_type, storage_kind, verification_method)
               VALUES (501, ?, ?, 16, 'video/webm', 'managed', 'sha256')""",
            (sha_5, "5" * 32),
        )
        c.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (501, 1, ?, 'managed', ?)""",
            (cas_name, NOW),
        )
        # Trigger to test forced database failure and rollback
        c.execute(
            """CREATE TRIGGER test_fail_trigger BEFORE INSERT ON pair_label_decisions
               WHEN NEW.note = 'FORCE_FAIL'
               BEGIN
                   SELECT RAISE(ABORT, 'forced decision failure');
               END;"""
        )
        c.commit()

    a, b = _seed_pair(catalog, md5_a="f" * 32, md5_b="r" * 32, tag="artist_net")

    # Start PRODUCTION server entirely inside background thread
    server_holder: list[object] = []
    ready = threading.Event()

    def run_worker() -> None:
        server, db, state = create_server(catalog, media_root, port=0)
        server_holder.append(server)
        server_holder.append(db)
        server_holder.append(state)
        ready.set()
        try:
            server.serve_forever()
        finally:
            server.server_close()
            db.close()

    th = threading.Thread(target=run_worker, daemon=True)
    th.start()
    ready.wait()
    server = server_holder[0]
    port = server.server_port  # type: ignore[attr-defined]
    base_url = f"http://127.0.0.1:{port}"

    try:
        # 1. Full GET on extensionless media (verifying Content-Type from DB detected_mime_type)
        req = Request(f"{base_url}/media/{cas_name}")
        with urlopen(req) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "video/webm"
            assert resp.headers.get("Accept-Ranges") == "bytes"
            assert resp.read() == b"0123456789ABCDEF"

        # 2. Range request GET on media: bytes=0-9
        req_range = Request(f"{base_url}/media/{cas_name}", headers={"Range": "bytes=0-9"})
        with urlopen(req_range) as resp:
            assert resp.status == 206
            assert resp.headers.get("Content-Range") == "bytes 0-9/16"
            assert resp.read() == b"0123456789"

        # 3. Suffix range request: bytes=-6 (last 6 bytes)
        req_suffix = Request(f"{base_url}/media/{cas_name}", headers={"Range": "bytes=-6"})
        with urlopen(req_suffix) as resp:
            assert resp.status == 206
            assert resp.headers.get("Content-Range") == "bytes 10-15/16"
            assert resp.read() == b"ABCDEF"

        # 4. Out-of-bounds Range returns 416
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", f"/media/{cas_name}", headers={"Range": "bytes=99-100"})
        resp = conn.getresponse()
        assert resp.status == 416
        resp.read()

        # 5. Missing required pair identity fields in save POST returns 400
        conn.request(
            "POST",
            "/label",
            body=json.dumps({"pair": 0, "verdict": "same"}),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 400
        assert b"post_a_id, post_b_id, and queue_signal are required" in resp.read()

        # 6. Invalid verdict returns 400
        conn.request(
            "POST",
            "/label",
            body=json.dumps(
                {
                    "pair": 0,
                    "post_a_id": a,
                    "post_b_id": b,
                    "queue_signal": "same_artist_contrast",
                    "verdict": "unknown",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 400
        resp.read()

        # 7. Stale pair mismatch returns 400
        conn.request(
            "POST",
            "/label",
            body=json.dumps(
                {
                    "pair": 0,
                    "post_a_id": 99999,
                    "post_b_id": 88888,
                    "queue_signal": "stale",
                    "verdict": "same",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 400
        assert b"stale pair mismatch" in resp.read()

        # 8. Forced DB failure returns 500 and rolls back
        conn.request(
            "POST",
            "/label",
            body=json.dumps(
                {
                    "pair": 0,
                    "post_a_id": a,
                    "post_b_id": b,
                    "queue_signal": "same_artist_contrast",
                    "verdict": "same",
                    "note": "FORCE_FAIL",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 500
        assert b"database error: forced decision failure" in resp.read()

        # Verify from independent connection that transaction rolled back
        with CatalogDatabase(catalog) as verify_db:
            c_check = verify_db.connection
            count_labels = c_check.execute(
                "SELECT count(*) FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?",
                (a, b),
            ).fetchone()[0]
            count_decisions = c_check.execute(
                "SELECT count(*) FROM pair_label_decisions"
            ).fetchone()[0]
            assert count_labels == 0
            assert count_decisions == 0

            # Drop trigger so subsequent save succeeds
            c_check.execute("DROP TRIGGER test_fail_trigger")
            c_check.commit()

        # 9. Valid save returns 200 and commits
        conn.request(
            "POST",
            "/label",
            body=json.dumps(
                {
                    "pair": 0,
                    "post_a_id": a,
                    "post_b_id": b,
                    "queue_signal": "same_artist_contrast",
                    "verdict": "same",
                    "note": "verified identical",
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == b"ok"
        conn.close()

        # Verify persisted label and decision
        with CatalogDatabase(catalog) as verify_db:
            c_check = verify_db.connection
            row = c_check.execute(
                "SELECT verdict, relation_note FROM pair_labels "
                "WHERE post_a_id = ? AND post_b_id = ?",
                (a, b),
            ).fetchone()
            assert tuple(row) == ("same", "verified identical")

    finally:
        server.shutdown()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("first_variant", "second_variant"),
    [("primary", "preview"), ("preview", "primary")],
)
def test_primary_variant_and_multiple_history_order(
    catalog: Path, tmp_path: Path, first_variant: str, second_variant: str
) -> None:
    """Primary acquisition variant key resolves as original regardless of history row order."""
    media_root = tmp_path / "media"
    media_root.mkdir()
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"
    sha_val = "4" * 64
    local_file = media_root / "primary_asset.jpg"
    local_file.write_bytes(b"content")

    a, _ = _seed_pair(catalog, md5_a="1" * 32, md5_b="1" * 32, tag="artist_p")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            """INSERT INTO managed_roots
                   (managed_root_id, root_kind, root_identity, display_label,
                    private_path, created_at)
               VALUES (1, 'managed', ?, 'Primary Media', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size, mime_type,
                                   storage_kind, verification_method)
               VALUES (301, ?, NULL, 100, 'image/jpeg', 'managed', 'sha256')""",
            (sha_val,),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (301, 1, 'primary_asset.jpg', 'managed', ?)""",
            (NOW,),
        )
        occ_id = conn.execute(
            "SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ?",
            (a,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES (?, 301, 'downloaded', 'local')""",
            (occ_id,),
        )

        plan_id = int(
            conn.execute(
                """INSERT INTO media_acquisition_plans (
                       plan_version, selection_digest, requested_count, eligible_count,
                       satisfied_count, excluded_count, created_at
                   ) VALUES ('plan-v1', ?, 1, 1, 0, 0, ?)""",
                ("d" * 64, NOW),
            ).lastrowid
        )

        for idx, var in enumerate((first_variant, second_variant)):
            plan_item_id = int(
                conn.execute(
                    """INSERT INTO media_acquisition_plan_items (
                           acquisition_plan_id, item_key, media_occurrence_id, variant_key,
                           material_digest, request_policy_key, request_policy_version,
                           eligibility, created_at
                       ) VALUES (?, ?, ?, ?, ?, 'policy', 'v1', 'eligible', ?)""",
                    (plan_id, f"item-{idx}", occ_id, var, "e" * 64, NOW),
                ).lastrowid
            )
            run_id = int(
                conn.execute(
                    """INSERT INTO media_acquisition_runs (
                           acquisition_plan_id, managed_root_id, max_items, max_item_bytes,
                           max_total_bytes, max_attempts_per_item, max_seconds, max_redirects,
                           max_quarantine_bytes, concurrency, planned_count, started_at
                       ) VALUES (?, 1, 1, 1000, 1000, 2, 30, 3, 1000, 1, 1, ?)""",
                    (plan_id, NOW),
                ).lastrowid
            )
            conn.execute(
                """INSERT INTO media_acquisition_run_items (
                       acquisition_run_id, acquisition_plan_item_id, state, outcome, asset_id,
                       created_at, updated_at
                   ) VALUES (?, ?, 'complete', 'downloaded', 301, ?, ?)""",
                (run_id, plan_item_id, NOW, NOW),
            )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_a = state._post_view(a)

        assert "/media/primary_asset.jpg" in view_a["media_html"]
        assert "badge-preview" not in view_a["media_html"]
        assert "badge-sample" not in view_a["media_html"]
        assert "badge-unverified" not in view_a["media_html"]
        assert "[preview only]" not in view_a["meta"]
        assert "[sample]" not in view_a["meta"]
        assert "[local copy · unverified]" not in view_a["meta"]


def test_hash_match_outranks_preview_history(catalog: Path, tmp_path: Path) -> None:
    """Exact non-contradictory MD5/SHA match outranks preview history on the asset."""
    media_root = tmp_path / "media"
    media_root.mkdir()
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"
    local_file = media_root / "hash_match.jpg"
    local_file.write_bytes(b"content")

    match_md5 = "9" * 32
    a, _ = _seed_pair(catalog, md5_a=match_md5, md5_b=match_md5, tag="artist_h")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            """INSERT INTO managed_roots
                   (managed_root_id, root_kind, root_identity, display_label,
                    private_path, created_at)
               VALUES (1, 'managed', ?, 'Primary Media', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size, mime_type,
                                   storage_kind, verification_method)
               VALUES (302, ?, ?, 100, 'image/jpeg', 'managed', 'calculated')""",
            ("8" * 64, match_md5),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (302, 1, 'hash_match.jpg', 'managed', ?)""",
            (NOW,),
        )
        occ_id = conn.execute(
            "SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ?",
            (a,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES (?, 302, 'downloaded', 'local')""",
            (occ_id,),
        )

        plan_id = int(
            conn.execute(
                """INSERT INTO media_acquisition_plans (
                       plan_version, selection_digest, requested_count, eligible_count,
                       satisfied_count, excluded_count, created_at
                   ) VALUES ('plan-v1', ?, 1, 1, 0, 0, ?)""",
                ("d" * 64, NOW),
            ).lastrowid
        )
        plan_item_id = int(
            conn.execute(
                """INSERT INTO media_acquisition_plan_items (
                       acquisition_plan_id, item_key, media_occurrence_id, variant_key,
                       material_digest, request_policy_key, request_policy_version,
                       eligibility, created_at
                   ) VALUES (?, 'item-prev', ?, 'preview', ?, 'policy', 'v1', 'eligible', ?)""",
                (plan_id, occ_id, "e" * 64, NOW),
            ).lastrowid
        )
        run_id = int(
            conn.execute(
                """INSERT INTO media_acquisition_runs (
                       acquisition_plan_id, managed_root_id, max_items, max_item_bytes,
                       max_total_bytes, max_attempts_per_item, max_seconds, max_redirects,
                       max_quarantine_bytes, concurrency, planned_count, started_at
                   ) VALUES (?, 1, 1, 1000, 1000, 2, 30, 3, 1000, 1, 1, ?)""",
                (plan_id, NOW),
            ).lastrowid
        )
        conn.execute(
            """INSERT INTO media_acquisition_run_items (
                   acquisition_run_id, acquisition_plan_item_id, state, outcome, asset_id,
                   created_at, updated_at
               ) VALUES (?, ?, 'complete', 'downloaded', 302, ?, ?)""",
            (run_id, plan_item_id, NOW, NOW),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_a = state._post_view(a)

        assert "/media/hash_match.jpg" in view_a["media_html"]
        assert "badge-preview" not in view_a["media_html"]
        assert "[preview only]" not in view_a["meta"]


def test_verified_webm_preview_cas_preserves_detected_mime(catalog: Path, tmp_path: Path) -> None:
    """Extensionless CAS file with detected_mime_type video/webm preserves video rendering."""
    media_root = tmp_path / "media"
    media_root.mkdir()
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"
    cas_path = "7a/8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b"
    cas_file = media_root / cas_path
    cas_file.parent.mkdir(parents=True, exist_ok=True)
    cas_file.write_bytes(b"\x1a\x45\xdf\xa3fake-webm")

    a, _ = _seed_pair(catalog, md5_a="6" * 32, md5_b="6" * 32, tag="artist_cas")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            """INSERT INTO managed_roots
                   (managed_root_id, root_kind, root_identity, display_label,
                    private_path, created_at)
               VALUES (1, 'managed', ?, 'Primary Media', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size,
                                   mime_type, detected_mime_type, storage_kind,
                                   verification_method)
               VALUES (303, ?, NULL, 200, 'video/webm', 'video/webm', 'managed', 'calculated')""",
            ("7" * 64,),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (303, 1, ?, 'managed', ?)""",
            (cas_path, NOW),
        )
        occ_id = conn.execute(
            "SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ?",
            (a,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES (?, 303, 'preview', 'local')""",
            (occ_id,),
        )
        conn.execute(
            "UPDATE media_occurrences SET remote_url = NULL WHERE post_id = ?",
            (a,),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_a = state._post_view(a)

        assert "<video" in view_a["media_html"]
        assert "<img" not in view_a["media_html"]
        assert 'type="video/webm"' in view_a["media_html"]
        assert f"/media/{cas_path}" in view_a["media_html"]


@pytest.mark.parametrize(
    ("detected", "element"),
    [("application/octet-stream", "video"), ("image/jpeg", "img")],
)
def test_original_format_hint_only_fills_generic_inspection(
    catalog: Path, tmp_path: Path, detected: str, element: str
) -> None:
    root = tmp_path / "media"
    root.mkdir()
    (root / "extensionless").write_bytes(b"bytes")
    identity = f"{root.stat().st_dev}:{root.stat().st_ino}"
    a, _ = _seed_pair(catalog, md5_a="a" * 32, md5_b="a" * 32, tag="video_artist")
    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            """INSERT INTO managed_roots
                   (root_kind, root_identity, display_label, private_path, created_at)
               VALUES ('managed', ?, 'media', ?, ?)""",
            (identity, str(root), NOW),
        )
        root_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO assets
                   (verified_sha256, verified_md5, detected_mime_type, storage_kind,
                    verification_method)
               VALUES (?, ?, ?, 'managed', 'sha256')""",
            ("b" * 64, "a" * 32, detected),
        )
        asset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO asset_locations
                   (asset_id, managed_root_id, relative_path, location_kind, created_at)
               VALUES (?, ?, 'extensionless', 'managed', ?)""",
            (asset_id, root_id, NOW),
        )
        conn.execute(
            """INSERT INTO occurrence_assets
                   (media_occurrence_id, asset_id, relationship, verification_source)
               SELECT media_occurrence_id, ?, 'downloaded', 'acquisition'
                 FROM media_occurrences WHERE post_id = ?""",
            (asset_id, a),
        )
        conn.execute(
            "UPDATE media_occurrences SET mime_type = 'video/webm' WHERE post_id = ?", (a,)
        )
        conn.commit()
        view = LabelingState(conn, root)._post_view(a)
        assert f"<{element} " in view["media_html"]
        assert "/media/extensionless" in view["media_html"]
        assert "Unsupported media format" not in view["media_html"]


def test_mixed_availability_occurrences(catalog: Path, tmp_path: Path) -> None:
    """Resolver skips tombstoned/unavailable occurrences and explains all-unavailable posts."""
    media_root = tmp_path / "media"
    media_root.mkdir()
    a, _ = _seed_pair(catalog, md5_a="2" * 32, md5_b="2" * 32, tag="artist_avail")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            "UPDATE media_occurrences "
            "SET availability = 'tombstoned', remote_url = 'https://example.invalid/dead.jpg' "
            "WHERE post_id = ?",
            (a,),
        )
        conn.execute(
            """INSERT INTO media_occurrences (
                   media_occurrence_id, post_id, source_key, media_index, media_type,
                   remote_url, availability, observed_at
               ) VALUES (901, ?, 'avail_occ', 1, 'image', 'https://example.invalid/live.jpg',
                         'available', ?)""",
            (a, NOW),
        )

        platform_id = int(conn.execute("SELECT platform_id FROM platforms LIMIT 1").fetchone()[0])
        conn.execute(
            """INSERT INTO posts (
                   post_id, platform_id, native_post_id, availability, first_seen_at, last_seen_at
               ) VALUES (999, ?, 'post_c', 'available', ?, ?)""",
            (platform_id, NOW, NOW),
        )
        conn.execute(
            """INSERT INTO media_occurrences (
                   media_occurrence_id, post_id, source_key, media_index, media_type,
                   remote_url, availability, observed_at
               ) VALUES (902, 999, 'unavail_occ', 0, 'image', 'https://example.invalid/gone.jpg',
                         'unavailable', ?)""",
            (NOW,),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_a = state._post_view(a)
        view_c = state._post_view(999)

        assert "https://example.invalid/live.jpg" in view_a["media_html"]
        assert "https://example.invalid/dead.jpg" not in view_a["media_html"]

        assert "media-box missing" in view_c["media_html"]
        assert "Media marked unavailable" in view_c["media_html"]
        assert (
            "All media occurrences for this post are tombstoned or marked unavailable"
            in (view_c["media_html"])
        )


def test_video_original_with_jpeg_preview(catalog: Path, tmp_path: Path) -> None:
    """Video occurrence with JPEG preview renders as <img>, not <video>."""
    media_root = tmp_path / "media"
    media_root.mkdir()
    a, _ = _seed_pair(catalog, md5_a="3" * 32, md5_b="3" * 32, tag="artist_v")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            """UPDATE media_occurrences
                  SET mime_type = 'video/webm',
                      media_type = 'video',
                      remote_url = NULL,
                      preview_url = 'https://example.invalid/thumb.jpg'
                WHERE post_id = ?""",
            (a,),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_a = state._post_view(a)

        assert "<img" in view_a["media_html"]
        assert "<video" not in view_a["media_html"]
        assert "https://example.invalid/thumb.jpg" in view_a["media_html"]
        assert "badge-preview" in view_a["media_html"]
        assert "[preview only]" in view_a["meta"]


def test_unverified_local_copy_neutral_badge(catalog: Path, tmp_path: Path) -> None:
    """Local file with no hashes/history renders neutral badge and does not claim to be sample."""
    media_root = tmp_path / "media"
    media_root.mkdir()
    st = media_root.stat()
    actual_identity = f"{st.st_dev}:{st.st_ino}"
    local_file = media_root / "copy.jpg"
    local_file.write_bytes(b"content")

    a, _ = _seed_pair(catalog, md5_a="4" * 32, md5_b="4" * 32, tag="artist_u")

    with CatalogDatabase(catalog) as database:
        conn = database.connection
        conn.execute(
            """INSERT INTO managed_roots
                   (managed_root_id, root_kind, root_identity, display_label,
                    private_path, created_at)
               VALUES (1, 'managed', ?, 'Primary Media', ?, ?)""",
            (actual_identity, str(media_root), NOW),
        )
        conn.execute(
            """INSERT INTO assets (asset_id, verified_sha256, verified_md5, byte_size, mime_type,
                                   storage_kind, verification_method)
               VALUES (401, ?, NULL, 50, 'image/jpeg', 'managed', 'calculated')""",
            ("5" * 64,),
        )
        conn.execute(
            """INSERT INTO asset_locations (asset_id, managed_root_id, relative_path,
                                           location_kind, created_at)
               VALUES (401, 1, 'copy.jpg', 'managed', ?)""",
            (NOW,),
        )
        occ_id = conn.execute(
            "SELECT media_occurrence_id FROM media_occurrences WHERE post_id = ?",
            (a,),
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO occurrence_assets (media_occurrence_id, asset_id, relationship,
                                             verification_source)
               VALUES (?, 401, 'downloaded', 'local')""",
            (occ_id,),
        )

        conn.execute(
            "UPDATE media_occurrences SET declared_md5 = NULL, declared_sha256 = NULL "
            "WHERE post_id = ?",
            (a,),
        )
        conn.commit()

        # Case 1: Remote original takes priority over unverified local
        state = LabelingState(conn, media_root)
        view_1 = state._post_view(a)
        assert "https://example.invalid/a.jpg" in view_1["media_html"]

        # Case 2: No remote original -> unverified local copy renders with neutral badge
        conn.execute(
            "UPDATE media_occurrences SET remote_url = NULL WHERE post_id = ?",
            (a,),
        )
        conn.commit()

        state = LabelingState(conn, media_root)
        view_2 = state._post_view(a)
        assert "/media/copy.jpg" in view_2["media_html"]
        assert "badge-unverified" in view_2["media_html"]
        assert "Local copy (original status unverified)" in view_2["media_html"]
        assert "[local copy · unverified]" in view_2["meta"]
        assert "badge-sample" not in view_2["media_html"]
        assert "badge-preview" not in view_2["media_html"]
        assert "[sample]" not in view_2["meta"]
        assert "[preview only]" not in view_2["meta"]
