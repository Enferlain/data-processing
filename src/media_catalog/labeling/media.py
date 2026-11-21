"""Media resolution for the labeling UI (bead data-processing-cne).

Picks the best displayable representation of a post — verified local file,
remote original, or fallback preview — respecting storage roots, verified
hashes, and acquisition variant keys.
"""

from __future__ import annotations

import contextlib
import mimetypes
import sqlite3
from pathlib import Path
from typing import Any

from media_catalog.acquisition.policies import media_request_policy_for_platform


def _detect_mime(mime: str | None, src: str) -> str:
    """Determine MIME type using declared value, guess, or extension fallback."""
    if mime and "/" in mime:
        return mime.strip()
    guessed, _ = mimetypes.guess_type(src)
    if guessed:
        return guessed
    clean_src = src.split("?")[0].split("#")[0]
    ext = clean_src.rsplit(".", 1)[-1].lower() if "." in clean_src else ""
    return {
        "webm": "video/webm",
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "ogv": "video/ogg",
        "mkv": "video/x-matroska",
        "gif": "image/gif",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "avif": "image/avif",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
    }.get(ext, "")


def resolve_post_media(
    connection: sqlite3.Connection,
    media_root: Path,
    matched_root_ids: set[int],
    post_id: int,
) -> dict[str, Any]:
    """Resolve the best media representation for a post respecting storage roots and files."""
    post_row = connection.execute(
        """SELECT p.platform_key, po.native_post_id, po.canonical_url,
                  po.title, po.availability,
                  (SELECT group_concat(t.name, ', ')
                     FROM post_tags pt JOIN tags t ON t.tag_id = pt.tag_id
                    WHERE pt.post_id = po.post_id AND t.category = 'artist'
                    LIMIT 1) AS artists
             FROM posts po
             JOIN platforms p ON p.platform_id = po.platform_id
            WHERE po.post_id = ?""",
        (post_id,),
    ).fetchone()

    if post_row is None:
        return {
            "kind": "missing",
            "name": f"post_{post_id}",
            "meta": f"post {post_id} (not found)",
            "src": "",
            "mime": "",
            "source_url": "",
            "is_preview": False,
            "is_sample": False,
            "missing_title": f"Post {post_id} not found",
            "missing_detail": "Post does not exist in the catalog.",
        }

    platform_key = post_row["platform_key"]
    native_post_id = post_row["native_post_id"]
    canonical_url = post_row["canonical_url"] or ""
    title = post_row["title"]
    artists = post_row["artists"]

    occ_rows = connection.execute(
        """SELECT media_occurrence_id, media_index, media_type, role,
                  remote_url, preview_url, mime_type, width, height,
                  declared_md5, declared_sha256, availability
             FROM media_occurrences
            WHERE post_id = ? AND availability = 'available'
            ORDER BY media_index, media_occurrence_id""",
        (post_id,),
    ).fetchall()

    if not occ_rows:
        any_occ = connection.execute(
            "SELECT 1 FROM media_occurrences WHERE post_id = ? LIMIT 1",
            (post_id,),
        ).fetchone()
        parts = []
        if title:
            parts.append(str(title))
        if artists:
            parts.append(f"artist: {artists}")
        parts.append(f"{platform_key}:{native_post_id}")
        meta = " · ".join(parts)
        if any_occ is not None:
            return {
                "kind": "missing",
                "name": f"{platform_key}_{native_post_id}",
                "meta": meta,
                "src": "",
                "mime": "",
                "source_url": canonical_url,
                "is_preview": False,
                "is_sample": False,
                "is_unverified": False,
                "missing_title": "Media marked unavailable",
                "missing_detail": (
                    "All media occurrences for this post are tombstoned or marked unavailable."
                ),
            }
        return {
            "kind": "missing",
            "name": f"{platform_key}_{native_post_id}",
            "meta": meta,
            "src": "",
            "mime": "",
            "source_url": canonical_url,
            "is_preview": False,
            "is_sample": False,
            "is_unverified": False,
            "missing_title": "No media occurrences recorded",
            "missing_detail": (
                "Post has provider metadata but no media occurrences or remote URLs."
            ),
        }

    occ_ids = [row["media_occurrence_id"] for row in occ_rows]
    placeholders = ",".join("?" * len(occ_ids))
    asset_rows = connection.execute(
        f"""SELECT oa.media_occurrence_id, oa.asset_id, oa.relationship,
                   a.verified_sha256, a.verified_md5,
                   COALESCE(a.detected_mime_type, a.mime_type) AS asset_mime_type,
                   a.detected_mime_type, a.mime_type AS original_mime_type,
                   a.detected_width, a.detected_height,
                   a.width AS asset_width, a.height AS asset_height,
                   al.asset_location_id, al.managed_root_id, al.relative_path, al.location_kind
              FROM occurrence_assets oa
              JOIN assets a ON a.asset_id = oa.asset_id
              LEFT JOIN asset_locations al
                ON al.asset_id = a.asset_id AND al.location_kind <> 'legacy'
             WHERE oa.media_occurrence_id IN ({placeholders})""",
        occ_ids,
    ).fetchall()

    # Query variant keys from acquisition runs, keyed by (occurrence_id, asset_id)
    variant_keys_by_occ_asset: dict[tuple[int, int], set[str]] = {}
    with contextlib.suppress(sqlite3.Error):
        asset_ids = [row["asset_id"] for row in asset_rows]
        if asset_ids:
            a_placeholders = ",".join("?" * len(asset_ids))
            plan_rows = connection.execute(
                f"""SELECT mapi.media_occurrence_id, mari.asset_id, mapi.variant_key
                      FROM media_acquisition_run_items mari
                      JOIN media_acquisition_plan_items mapi
                        ON mapi.acquisition_plan_item_id = mari.acquisition_plan_item_id
                     WHERE mari.state IN ('complete', 'satisfied')
                       AND mari.asset_id IN ({a_placeholders})""",
                asset_ids,
            ).fetchall()
            for pr in plan_rows:
                variant_keys_by_occ_asset.setdefault(
                    (int(pr["media_occurrence_id"]), int(pr["asset_id"])), set()
                ).add(str(pr["variant_key"]).lower())

    assets_by_occ: dict[int, list[sqlite3.Row]] = {}
    for a_row in asset_rows:
        assets_by_occ.setdefault(int(a_row["media_occurrence_id"]), []).append(a_row)

    resolved_root = media_root.resolve()
    candidates: list[dict[str, Any]] = []

    for occ in occ_rows:
        occ_id = int(occ["media_occurrence_id"])
        occ_role = (occ["role"] or "").lower()
        declared_md5 = occ["declared_md5"]
        declared_sha256 = occ["declared_sha256"]
        remote_url = occ["remote_url"]
        preview_url = occ["preview_url"]
        occ_mime = occ["mime_type"]
        occ_w = occ["width"]
        occ_h = occ["height"]

        linked = assets_by_occ.get(occ_id, [])
        for a in linked:
            asset_id = int(a["asset_id"])
            rel = (a["relationship"] or "").lower()
            rel_path = a["relative_path"]
            managed_root_id = a["managed_root_id"]
            verified_md5 = a["verified_md5"]
            verified_sha256 = a["verified_sha256"]
            asset_mime = a["asset_mime_type"] or occ_mime
            # Prefer detected dimensions over catalog/occurrence dims for local files
            asset_w = a["detected_width"] or a["asset_width"] or occ_w
            asset_h = a["detected_height"] or a["asset_height"] or occ_h

            var_keys = variant_keys_by_occ_asset.get((occ_id, asset_id), set())

            if rel_path and managed_root_id is not None:
                is_valid_root = managed_root_id in matched_root_ids
                file_exists = False
                if is_valid_root:
                    target = (media_root / rel_path).resolve()
                    with contextlib.suppress(OSError):
                        if target.is_relative_to(resolved_root) and target.is_file():
                            file_exists = True

                # Hash matching and contradiction checks
                hash_matches = False
                hash_contradicts = False
                if declared_md5 and verified_md5:
                    if declared_md5.lower() == verified_md5.lower():
                        hash_matches = True
                    else:
                        hash_contradicts = True
                if declared_sha256 and verified_sha256:
                    if declared_sha256.lower() == verified_sha256.lower():
                        hash_matches = True
                    else:
                        hash_contradicts = True

                has_original_key = bool(var_keys & {"primary", "original", "full"})
                has_preview_key = bool(var_keys & {"preview", "thumbnail"})
                has_sample_key = bool(var_keys & {"sample", "large", "medium"})

                is_original = False
                is_preview = False
                is_sample = False
                is_unverified = False

                if not hash_contradicts and (
                    hash_matches
                    or has_original_key
                    or (
                        rel in ("original", "full", "source")
                        and not has_preview_key
                        and not has_sample_key
                        and rel
                        not in (
                            "preview",
                            "thumbnail",
                            "thumb",
                            "small",
                            "sample",
                            "large",
                            "medium",
                        )
                    )
                ):
                    is_original = True
                elif has_sample_key or rel in ("sample", "large", "medium"):
                    is_sample = True
                elif has_preview_key or rel in ("preview", "thumbnail", "thumb", "small"):
                    is_preview = True
                elif not hash_contradicts:
                    is_unverified = True

                detected_mime = a["detected_mime_type"]
                if detected_mime and detected_mime != "application/octet-stream":
                    asset_mime = detected_mime
                elif is_original:
                    # Exact byte identity / original acquisition ties these bytes to the
                    # occurrence. A generic inspection result supplies no format evidence.
                    asset_mime = _detect_mime(a["original_mime_type"], rel_path)
                    if not asset_mime or asset_mime == "application/octet-stream":
                        asset_mime = _detect_mime(occ_mime, remote_url or rel_path)
                elif is_preview:
                    asset_mime = _detect_mime(None, rel_path) or "image/jpeg"
                else:
                    asset_mime = a["original_mime_type"] or occ_mime

                if file_exists:
                    if is_original:
                        candidates.append(
                            {
                                "priority": 1,
                                "kind": "local",
                                "src": f"/media/{rel_path}",
                                "mime": asset_mime,
                                "source_url": remote_url or canonical_url,
                                "is_preview": False,
                                "is_sample": False,
                                "is_unverified": False,
                                "declared_md5": declared_md5 or verified_md5,
                                "rel_path": rel_path,
                                "width": asset_w,
                                "height": asset_h,
                            }
                        )
                    elif is_sample:
                        candidates.append(
                            {
                                "priority": 4,
                                "kind": "local",
                                "src": f"/media/{rel_path}",
                                "mime": asset_mime,
                                "source_url": remote_url or canonical_url,
                                "is_preview": False,
                                "is_sample": True,
                                "is_unverified": False,
                                "declared_md5": declared_md5 or verified_md5,
                                "rel_path": rel_path,
                                "width": asset_w,
                                "height": asset_h,
                            }
                        )
                    elif is_preview:
                        candidates.append(
                            {
                                "priority": 6,
                                "kind": "local",
                                "src": f"/media/{rel_path}",
                                "mime": asset_mime,
                                "source_url": remote_url or canonical_url,
                                "is_preview": True,
                                "is_sample": False,
                                "is_unverified": False,
                                "declared_md5": declared_md5 or verified_md5,
                                "rel_path": rel_path,
                                "width": asset_w,
                                "height": asset_h,
                            }
                        )
                    else:
                        # is_unverified
                        candidates.append(
                            {
                                "priority": 3,
                                "kind": "local",
                                "src": f"/media/{rel_path}",
                                "mime": asset_mime,
                                "source_url": remote_url or canonical_url,
                                "is_preview": False,
                                "is_sample": False,
                                "is_unverified": True,
                                "declared_md5": declared_md5 or verified_md5,
                                "rel_path": rel_path,
                                "width": asset_w,
                                "height": asset_h,
                            }
                        )
                else:
                    candidates.append(
                        {
                            "priority": 8,
                            "kind": "missing_local",
                            "src": "",
                            "mime": asset_mime,
                            "source_url": remote_url or canonical_url,
                            "is_preview": is_preview,
                            "is_sample": is_sample,
                            "is_unverified": is_unverified,
                            "declared_md5": declared_md5,
                            "rel_path": rel_path,
                            "width": asset_w,
                            "height": asset_h,
                            "missing_title": "Missing local media file",
                            "missing_detail": (
                                f"Catalog references file '{rel_path}', "
                                "but it does not exist in managed media root."
                            ),
                        }
                    )

        if remote_url:
            is_remote_preview = occ_role in ("preview", "thumbnail", "thumb")
            is_remote_sample = occ_role in ("sample", "large", "medium")
            is_remote_orig = not is_remote_preview and not is_remote_sample
            prio = 2 if is_remote_orig else (5 if is_remote_sample else 7)
            remote_mime = occ_mime
            if is_remote_preview and (not remote_mime or remote_mime.startswith("video/")):
                remote_mime = _detect_mime(None, remote_url) or remote_mime or "image/jpeg"
            candidates.append(
                {
                    "priority": prio,
                    "kind": "remote",
                    "remote_occurrence_id": occ_id,
                    "remote_variant": "primary",
                    "src": remote_url,
                    "mime": remote_mime,
                    "source_url": remote_url,
                    "is_preview": is_remote_preview,
                    "is_sample": is_remote_sample,
                    "is_unverified": False,
                    "declared_md5": declared_md5,
                    "rel_path": "",
                    "width": occ_w,
                    "height": occ_h,
                }
            )
        if preview_url and preview_url != remote_url:
            preview_mime = _detect_mime(None, preview_url) or occ_mime or "image/jpeg"
            candidates.append(
                {
                    "priority": 7,
                    "kind": "remote",
                    "remote_occurrence_id": occ_id,
                    "remote_variant": "preview",
                    "src": preview_url,
                    "mime": preview_mime,
                    "source_url": preview_url,
                    "is_preview": True,
                    "is_sample": False,
                    "is_unverified": False,
                    "declared_md5": declared_md5,
                    "rel_path": "",
                    "width": occ_w,
                    "height": occ_h,
                }
            )

    candidates.sort(key=lambda c: c["priority"])

    if not candidates:
        parts = []
        if title:
            parts.append(str(title))
        if artists:
            parts.append(f"artist: {artists}")
        parts.append(f"{platform_key}:{native_post_id}")
        meta = " · ".join(parts)
        return {
            "kind": "missing",
            "name": f"{platform_key}_{native_post_id}",
            "meta": meta,
            "src": "",
            "mime": "",
            "source_url": canonical_url,
            "is_preview": False,
            "is_sample": False,
            "is_unverified": False,
            "missing_title": "No media available",
            "missing_detail": (
                "Post has occurrences but neither local files nor remote URLs exist."
            ),
        }

    chosen = candidates[0]
    declared_md5 = chosen.get("declared_md5")
    src = chosen.get("src", "")
    extension = ""
    if src:
        suffix = src.rsplit(".", 1)
        if len(suffix) == 2 and suffix[1][:4].isalnum():
            extension = f".{suffix[1][:4]}"
    name = (
        f"{declared_md5}{extension}"
        if declared_md5
        else ((chosen.get("rel_path") or src).rsplit("/", 1)[-1] or "unnamed")
    )

    parts = []
    if title:
        parts.append(str(title))
    if artists:
        parts.append(f"artist: {artists}")
    parts.append(f"{platform_key}:{native_post_id}")
    w = chosen.get("width")
    h = chosen.get("height")
    parts.append(f"{w or '?'}x{h or '?'}")
    if chosen.get("is_preview"):
        parts.append("[preview only]")
    elif chosen.get("is_sample"):
        parts.append("[sample]")
    elif chosen.get("is_unverified"):
        parts.append("[local copy · unverified]")
    meta = " · ".join(parts)

    if chosen["kind"] == "remote" and media_request_policy_for_platform(platform_key):
        src = f"/remote-media/{chosen['remote_occurrence_id']}/{chosen['remote_variant']}"
        if platform_key == "sankaku" and canonical_url:
            chosen["source_url"] = canonical_url

    return {
        "kind": chosen["kind"],
        "name": name,
        "meta": meta,
        "src": src,
        "mime": _detect_mime(chosen.get("mime"), chosen.get("src", "")),
        "source_url": chosen.get("source_url") or canonical_url,
        "is_preview": chosen.get("is_preview", False),
        "is_sample": chosen.get("is_sample", False),
        "is_unverified": chosen.get("is_unverified", False),
        "missing_title": chosen.get("missing_title", ""),
        "missing_detail": chosen.get("missing_detail", ""),
    }
