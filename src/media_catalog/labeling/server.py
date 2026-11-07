"""Minimal local labeling UI (bead data-processing-w7j, data-processing-efw).

A localhost server: shows one pair at a time (served from managed storage or
provider-aware remote requests when no local copy exists), queueing signals,
verdict buttons, and relation descriptions. Labels land in ``pair_labels`` with
an append-only decision history in ``pair_label_decisions``.
"""

from __future__ import annotations

import contextlib
import html
import json
import mimetypes
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from media_catalog.acquisition.policies import media_request_policy_for_platform
from media_catalog.database import CatalogDatabase
from media_catalog.labeling.queue import CandidateQueue, PairCandidate, build_queue
from media_catalog.labeling.remote import RemoteMediaError, fetch_remote_media
from media_catalog.labeling.sankaku import SankakuDisplayResolver

VERDICTS = ("same", "variant", "different", "unsure")

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>label pairs</title>
<style>
 body {{ font-family: system-ui, sans-serif; background: #111; color: #eee; margin: 0; }}
 header {{ padding: 10px 16px; background: #1d1d1d; display: flex; gap: 16px;
           align-items: baseline; justify-content: space-between; }}
 header b {{ font-size: 15px; }}
 header .pos {{ color: #8ab4f8; }}
 .pair {{ display: flex; gap: 8px; padding: 8px; height: calc(100vh - 220px);
          box-sizing: border-box; }}
 .side {{ flex: 1; display: flex; flex-direction: column; min-width: 0; background: #181818;
          border-radius: 6px; overflow: hidden; position: relative; }}
 .side .media-elem {{ flex: 1; object-fit: contain; min-height: 0; max-width: 100%;
                     max-height: 100%; background: #000; }}
 .side video.media-elem {{ width: 100%; height: 100%; }}
 .meta {{ font-size: 13px; color: #ccc; padding: 8px 10px; overflow-wrap: anywhere;
          border-top: 1px solid #333; background: #1a1a1a; }}
 .meta b {{ color: #8ab4f8; }}
 .signal {{ padding: 6px 16px; color: #fdd663; font-size: 13px; background: #191919;
            border-bottom: 1px solid #282828; }}
 .media-box {{ flex: 1; display: flex; flex-direction: column; align-items: center;
               justify-content: center; background: #202020; padding: 24px; text-align: center;
               gap: 8px; color: #ccc; }}
 .media-box.missing {{ border: 1px dashed #666; }}
 .media-box.error {{ border: 1px dashed #d32f2f; background: #2b1818; }}
 .media-box.audio {{ background: #1c2636; }}
 .media-box.unsupported {{ background: #252525; }}
 .media-box a {{ color: #8ab4f8; text-decoration: underline; }}
 .box-icon {{ font-size: 32px; }}
 .badge-preview {{ background: #e65100; color: #fff; font-size: 11px; font-weight: bold;
                   padding: 4px 8px; text-align: center; letter-spacing: 0.5px;
                   text-transform: uppercase; }}
 .badge-sample {{ background: #0288d1; color: #fff; font-size: 11px; font-weight: bold;
                  padding: 4px 8px; text-align: center; letter-spacing: 0.5px;
                  text-transform: uppercase; }}
 .badge-unverified {{ background: #475569; color: #fff; font-size: 11px; font-weight: bold;
                     padding: 4px 8px; text-align: center; letter-spacing: 0.5px;
                     text-transform: uppercase; }}
 .preview-wrapper {{ flex: 1; display: flex; flex-direction: column; min-height: 0; }}
 .status-bar {{ position: fixed; bottom: 64px; left: 16px; right: 16px; padding: 8px 16px;
                font-size: 13px; border-radius: 4px; z-index: 100; }}
 .status-bar.error {{ background: #5c1d1d; color: #ffcdd2; border: 1px solid #ef5350; }}
 .status-bar.success {{ background: #1b4d2e; color: #c8e6c9; border: 1px solid #4caf50; }}
 .status-bar.info {{ background: #2a2a2a; color: #8ab4f8; border: 1px solid #444; }}
 .bar {{ position: fixed; bottom: 0; left: 0; right: 0; background: #1d1d1d; padding: 10px 16px;
         display: flex; gap: 8px; align-items: center; border-top: 1px solid #333; }}
 button {{ font-size: 15px; padding: 10px 16px; border: 1px solid #444; border-radius: 6px;
           background: #2a2a2a; color: #eee; cursor: pointer; }}
 button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
 button.hot {{ background: #1f4d8f; border-color: #2b6cb0; }}
 button.hot:hover:not(:disabled) {{ background: #2762b3; }}
 input[type=text] {{ flex: 1; font-size: 15px; padding: 10px; border-radius: 6px;
                     border: 1px solid #444; background: #2a2a2a; color: #eee; }}
 .key {{ opacity: .6; font-size: 11px; display: block; }}
</style></head>
<body>
<header>
  <b>label pairs{mode_badge}</b>
  <span class="pos">{pos} / {total} {skipped_badge}&nbsp; signal: {signal}</span>
</header>
<div class="signal">{detail}</div>
<div class="pair">
  <div class="side">{media_a}<div class="meta"><b>{name_a}</b> · {meta_a}</div></div>
  <div class="side">{media_b}<div class="meta"><b>{name_b}</b> · {meta_b}</div></div>
</div>
<div id="status-bar" class="status-bar" style="display:none;"></div>
<div class="bar">
  <button class="hot" onclick="submit('same')">same<span class="key">1</span></button>
  <button class="hot" onclick="submit('variant')">variant<span class="key">2</span></button>
  <button class="hot" onclick="submit('different')">different<span class="key">3</span></button>
  <button class="hot" onclick="submit('unsure')">unsure<span class="key">4</span></button>
  <input id="note" type="text" placeholder="new description (optional)" value="" autocomplete="off">
  <button onclick="location='/next?skip=1'">skip</button>
</div>
<script>
let submitting = false;

function setStatus(msg, isError, isSuccess) {{
  const bar = document.getElementById('status-bar');
  if (!bar) return;
  if (!msg) {{
    bar.style.display = 'none';
    return;
  }}
  bar.innerText = msg;
  bar.className = 'status-bar ' + (isError ? 'error' : (isSuccess ? 'success' : 'info'));
  bar.style.display = 'block';
}}

const savedFlash = sessionStorage.getItem('label_saved_flash');
if (savedFlash) {{
  sessionStorage.removeItem('label_saved_flash');
  setStatus(savedFlash, false, true);
  setTimeout(() => setStatus(null), 3000);
}}

function handleMediaError(elem) {{
  elem.style.display = 'none';
  const parent = elem.parentElement;
  const sourceUrl = elem.dataset.sourceUrl || '';
  const box = document.createElement('div');
  box.className = 'media-box error';
  const icon = document.createElement('span');
  icon.className = 'box-icon';
  icon.textContent = '⚠️';
  const title = document.createElement('b');
  title.textContent = 'Failed to load remote media';
  box.appendChild(icon);
  box.appendChild(title);
  if (sourceUrl) {{
    const p = document.createElement('p');
    const a = document.createElement('a');
    a.href = sourceUrl;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = 'Open original source link';
    p.appendChild(a);
    box.appendChild(p);
  }}
  parent.insertBefore(box, elem);
}}

async function submit(v) {{
  if (submitting) return;
  if (!v || !['same', 'variant', 'different', 'unsure'].includes(v)) {{
    setStatus(
      "Please choose an explicit verdict: 1: same, 2: variant, 3: different, 4: unsure",
      true
    );
    return;
  }}
  submitting = true;
  const buttons = document.querySelectorAll('.bar button');
  buttons.forEach(b => b.disabled = true);
  setStatus("Saving verdict '" + v + "'...", false);

  const noteInput = document.getElementById('note');
  const note = noteInput ? noteInput.value : '';

  try {{
    const res = await fetch('/label', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        pair: {pair_index},
        post_a_id: {post_a_id},
        post_b_id: {post_b_id},
        queue_signal: {queue_signal_json},
        verdict: v,
        note: note
      }})
    }});
    if (!res.ok) {{
      const err = await res.text();
      setStatus("Error saving label (" + res.status + "): " + err, true);
      buttons.forEach(b => b.disabled = false);
      submitting = false;
      return;
    }}
    sessionStorage.setItem('label_saved_flash', "Saved verdict '" + v + "'!");
    if (noteInput) noteInput.value = '';
    location.reload();
  }} catch (err) {{
    setStatus("Network error saving label: " + err.message, true);
    buttons.forEach(b => b.disabled = false);
    submitting = false;
  }}
}}

document.addEventListener('keydown', e => {{
  if (document.activeElement === document.getElementById('note')) {{
    if (e.key === 'Enter') {{
      e.preventDefault();
      setStatus(
        "Pressing Enter does not assign unsure. " +
        "Please choose an explicit verdict: 1: same, 2: variant, 3: different, 4: unsure",
        true
      );
    }}
    return;
  }}
  if (e.key === '1') submit('same');
  if (e.key === '2') submit('variant');
  if (e.key === '3') submit('different');
  if (e.key === '4') submit('unsure');
}});
</script>
</body></html>"""


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


class LabelingState:
    def __init__(
        self,
        connection: sqlite3.Connection,
        media_root: Path,
        *,
        revisit_unsure: bool = False,
    ) -> None:
        self.connection = connection
        self.media_root = media_root
        self.revisit_unsure = revisit_unsure
        self._matched_root_ids = self._find_matching_managed_roots()
        self.queue: CandidateQueue = build_queue(
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
        """Resolve the best media representation for a post respecting storage roots and files."""
        post_row = self.connection.execute(
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

        occ_rows = self.connection.execute(
            """SELECT media_occurrence_id, media_index, media_type, role,
                      remote_url, preview_url, mime_type, width, height,
                      declared_md5, declared_sha256, availability
                 FROM media_occurrences
                WHERE post_id = ? AND availability = 'available'
                ORDER BY media_index, media_occurrence_id""",
            (post_id,),
        ).fetchall()

        if not occ_rows:
            any_occ = self.connection.execute(
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
        asset_rows = self.connection.execute(
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
                plan_rows = self.connection.execute(
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

        resolved_root = self.media_root.resolve()
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
                    is_valid_root = managed_root_id in self._matched_root_ids
                    file_exists = False
                    if is_valid_root:
                        target = (self.media_root / rel_path).resolve()
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

    def _post_view(self, post_id: int) -> dict[str, str]:
        resolved = self._resolve_post_media(post_id)
        name = resolved["name"]
        meta = resolved["meta"]
        src = resolved["src"]
        mime = resolved["mime"]
        source_url = resolved["source_url"]
        is_preview = resolved["is_preview"]
        is_sample = resolved["is_sample"]
        is_unverified = resolved["is_unverified"]
        kind = resolved["kind"]
        source_attr = html.escape(source_url, quote=True) if source_url else ""

        if kind in ("missing", "missing_local"):
            title_esc = html.escape(resolved["missing_title"])
            detail_esc = html.escape(resolved["missing_detail"])
            link_html = (
                f'<p><a href="{source_attr}" target="_blank" rel="noopener">'
                f"Open canonical post link</a></p>"
                if source_url
                else ""
            )
            media_html = (
                f'<div class="media-box missing">'
                f'<span class="box-icon">⚠️</span><b>{title_esc}</b>'
                f"<p>{detail_esc}</p>{link_html}</div>"
            )
        elif mime.startswith("video/") or any(
            src.lower().endswith(f".{ext}") for ext in ("webm", "mp4", "mov", "ogv", "mkv")
        ):
            preview_badge = (
                '<div class="badge-preview">Preview / thumbnail only (original missing)</div>'
                if is_preview
                else (
                    '<div class="badge-sample">Sample (scaled copy; original missing)</div>'
                    if is_sample
                    else (
                        '<div class="badge-unverified">'
                        "Local copy (original status unverified)</div>"
                        if is_unverified
                        else ""
                    )
                )
            )
            src_esc = html.escape(src, quote=True)
            mime_esc = html.escape(mime)
            source_link = (
                f' <a href="{source_attr}" target="_blank" rel="noopener">Source link</a>'
                if source_url
                else ""
            )
            media_html = (
                f"{preview_badge}"
                f'<video src="{src_esc}" controls playsinline preload="metadata" '
                f'data-source-url="{source_attr}" class="media-elem" '
                f'onerror="handleMediaError(this)">'
                f'<source src="{src_esc}" type="{mime_esc}" '
                f'onerror="handleMediaError(this.parentElement)">'
                f"Video not supported.{source_link}"
                f"</video>"
            )
        elif (
            mime == "image/gif"
            or mime.startswith("image/")
            or any(
                src.lower().endswith(f".{ext}")
                for ext in ("gif", "jpg", "jpeg", "png", "webp", "avif")
            )
        ):
            preview_badge = (
                '<div class="badge-preview">Preview / thumbnail only (original missing)</div>'
                if is_preview
                else (
                    '<div class="badge-sample">Sample (scaled copy; original missing)</div>'
                    if is_sample
                    else (
                        '<div class="badge-unverified">'
                        "Local copy (original status unverified)</div>"
                        if is_unverified
                        else ""
                    )
                )
            )
            src_esc = html.escape(src, quote=True)
            media_html = (
                f"{preview_badge}"
                f'<img src="{src_esc}" data-source-url="{source_attr}" loading="eager" '
                f'alt="{html.escape(name)}" class="media-elem" onerror="handleMediaError(this)">'
            )
        elif mime.startswith("audio/") or any(
            src.lower().endswith(f".{ext}") for ext in ("mp3", "wav", "ogg", "flac")
        ):
            src_esc = html.escape(src, quote=True)
            link_html = (
                f'<p><a href="{source_attr}" target="_blank" rel="noopener">'
                f"Open source link</a></p>"
                if source_url
                else ""
            )
            media_html = (
                f'<div class="media-box audio">'
                f'<span class="box-icon">🎵</span><b>Audio media</b>'
                f'<audio src="{src_esc}" controls preload="metadata" '
                f'data-source-url="{source_attr}" onerror="handleMediaError(this)"></audio>'
                f"{link_html}"
                f"</div>"
            )
        else:
            link_html = (
                f'<p><a href="{source_attr}" target="_blank" rel="noopener">'
                f"Open original source link</a></p>"
                if source_url
                else ""
            )
            media_html = (
                f'<div class="media-box unsupported">'
                f'<span class="box-icon">📁</span><b>Unsupported media format '
                f"({html.escape(mime or 'unknown')})</b>"
                f"{link_html}"
                f"</div>"
            )

        return {
            "media_html": media_html,
            "img": html.escape(src, quote=True),
            "name": html.escape(name),
            "meta": html.escape(meta),
        }

    def page(self) -> str | None:
        pair = self.current()
        if pair is None:
            skipped_count = getattr(self.queue, "skipped_count", 0)
            msg = (
                (
                    "No more saved unsure pairs are ready to review. Deferred pairs still need "
                    "media; their labels and notes have been preserved."
                    if skipped_count
                    else "No more ready unsure pairs in this session. "
                    "Saved unsure decisions remain available for later review."
                )
                if self.revisit_unsure
                else "every queued pair is labeled — rebuild the queue after ingesting more posts."
            )
            skipped_msg = (
                f"<p style='color:#f28b82;'>({skipped_count} pairs skipped "
                f"due to missing/unavailable media)</p>"
                if skipped_count > 0
                else ""
            )
            return (
                "<!doctype html><html><head><meta charset='utf-8'><title>queue empty</title>"
                "<style>body { font-family: system-ui, sans-serif; background: #111; "
                "color: #eee; padding: 24px; }\n"
                ".status-bar { padding: 8px 16px; font-size: 13px; border-radius: 4px; "
                "margin-bottom: 16px; }\n"
                ".status-bar.success { background: #1b4d2e; color: #c8e6c9; "
                "border: 1px solid #4caf50; display: block; }\n"
                "</style></head><body>\n"
                "<div id='status-bar' class='status-bar' style='display:none;'></div>\n"
                f"<h2>queue empty</h2><p>{msg}</p>{skipped_msg}\n"
                "<p>Restart the label command to refresh the queue after fetching media.</p>\n"
                "<script>\n"
                "const flash = sessionStorage.getItem('label_saved_flash');\n"
                "if (flash) {\n"
                "  sessionStorage.removeItem('label_saved_flash');\n"
                "  const b = document.getElementById('status-bar');\n"
                "  if (b) { b.innerText = flash; b.className = 'status-bar success'; "
                "b.style.display = 'block'; }\n"
                "}\n"
                "</script></body></html>"
            )
        a = self._post_view(pair.post_a_id)
        b = self._post_view(pair.post_b_id)
        mode_badge = " (revisit unsure)" if self.revisit_unsure else ""
        skipped_count = getattr(self.queue, "skipped_count", 0)
        skipped_badge = (
            f"&nbsp; <span style='color:#f28b82;'>({skipped_count} pairs deferred)</span>"
            if skipped_count > 0
            else ""
        )
        return _PAGE.format(
            pos=self.cursor + 1,
            total=len(self.queue),
            signal=html.escape(pair.queue_signal),
            detail=html.escape(pair.detail),
            mode_badge=mode_badge,
            skipped_badge=skipped_badge,
            media_a=a["media_html"],
            media_b=b["media_html"],
            name_a=a["name"],
            name_b=b["name"],
            meta_a=a["meta"],
            meta_b=b["meta"],
            pair_index=self.cursor,
            post_a_id=pair.post_a_id,
            post_b_id=pair.post_b_id,
            queue_signal_json=json.dumps(pair.queue_signal),
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


def create_handler(state: LabelingState, media_root: Path) -> type[BaseHTTPRequestHandler]:
    """Create the HTTPRequestHandler class bound to state and media_root."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/next"):
                if parse_qs(parsed.query).get("skip") and state.current() is not None:
                    state.cursor += 1
                page = state.page()
                assert page is not None
                self._send(page.encode(), "text/html; charset=utf-8")
            elif parsed.path.startswith("/remote-media/"):
                parts = parsed.path.split("/")
                if (
                    len(parts) != 4
                    or not parts[2].isascii()
                    or not parts[2].isdecimal()
                    or len(parts[2]) > 18
                    or parts[3] not in {"primary", "preview"}
                    or parsed.query
                ):
                    self._send(b"unknown remote media", "text/plain", 404)
                    return
                try:
                    with httpx.Client() as client:
                        media = fetch_remote_media(
                            state.connection,
                            int(parts[2]),
                            parts[3],
                            range_header=self.headers.get("Range"),
                            client=client,
                            sankaku_resolver=state.sankaku_media,
                        )
                except RemoteMediaError as error:
                    self._send(str(error).encode(), "text/plain", error.status)
                    return
                except Exception:
                    self._send(b"Provider media request failed", "text/plain", 502)
                    return
                self.send_response(media.status)
                self.send_header("Content-Type", media.content_type)
                self.send_header("Content-Length", str(len(media.body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "private, max-age=60")
                if media.content_range:
                    self.send_header("Content-Range", media.content_range)
                self.end_headers()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(media.body)
            elif parsed.path.startswith("/media/"):
                relative = unquote(parsed.path[len("/media/") :])
                target = (media_root / relative).resolve()
                if not target.is_relative_to(media_root.resolve()):
                    self._send(b"forbidden", "text/plain", 403)
                    return
                if not target.is_file():
                    self._send(b"not found", "text/plain", 404)
                    return

                try:
                    total_size = target.stat().st_size
                except OSError:
                    self._send(b"not found", "text/plain", 404)
                    return

                content_type = ""
                if state._matched_root_ids:
                    placeholders = ",".join("?" * len(state._matched_root_ids))
                    with contextlib.suppress(sqlite3.Error):
                        mime_row = state.connection.execute(
                            f"""SELECT COALESCE(a.detected_mime_type, a.mime_type)
                                  FROM asset_locations al
                                  JOIN assets a ON a.asset_id = al.asset_id
                                 WHERE al.managed_root_id IN ({placeholders})
                                   AND al.relative_path = ?
                                 ORDER BY al.asset_location_id DESC
                                 LIMIT 1""",
                            (*state._matched_root_ids, relative),
                        ).fetchone()
                        if mime_row and mime_row[0]:
                            content_type = str(mime_row[0])

                if not content_type:
                    content_type = _detect_mime(None, target.name) or "application/octet-stream"

                range_header = self.headers.get("Range")
                if range_header and range_header.startswith("bytes="):
                    byte_spec = range_header[6:].strip()
                    if "," in byte_spec:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{total_size}")
                        self.end_headers()
                        return

                    if byte_spec.startswith("-"):
                        try:
                            suffix_len = int(byte_spec[1:])
                            if suffix_len <= 0 or total_size == 0:
                                self.send_response(416)
                                self.send_header("Content-Range", f"bytes */{total_size}")
                                self.end_headers()
                                return
                            start = max(0, total_size - suffix_len)
                            end = total_size - 1
                        except ValueError:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{total_size}")
                            self.end_headers()
                            return
                    elif "-" in byte_spec:
                        parts = byte_spec.split("-", 1)
                        try:
                            start = int(parts[0])
                            end = int(parts[1]) if parts[1].strip() else total_size - 1
                        except ValueError:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{total_size}")
                            self.end_headers()
                            return
                        if start >= total_size or start < 0 or start > end:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{total_size}")
                            self.end_headers()
                            return
                        if end >= total_size:
                            end = total_size - 1
                    else:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{total_size}")
                        self.end_headers()
                        return

                    length = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()

                    try:
                        with target.open("rb") as f:
                            f.seek(start)
                            remaining = length
                            while remaining > 0:
                                chunk = f.read(min(remaining, 64 * 1024))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return

                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(total_size))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                try:
                    with target.open("rb") as f:
                        while True:
                            chunk = f.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            elif parsed.path == "/queue.json":
                payload = json.dumps(
                    [
                        {
                            "post_a_id": p.post_a_id,
                            "post_b_id": p.post_b_id,
                            "queue_signal": p.queue_signal,
                            "detail": p.detail,
                            "prior_note": p.prior_note,
                        }
                        for p in state.queue
                    ]
                ).encode()
                self._send(payload, "application/json")
            else:
                self._send(b"not found", "text/plain", 404)

        def do_POST(self) -> None:
            from media_catalog.discovery.support import now as _now

            if urlparse(self.path).path != "/label":
                self._send(b"not found", "text/plain", 404)
                return

            length_header = self.headers.get("Content-Length")
            if not length_header or not length_header.isdigit():
                self._send(b"missing or invalid content length", "text/plain", 400)
                return
            length = int(length_header)
            if length <= 0 or length > 65536:
                self._send(b"request body out of bounds", "text/plain", 400)
                return

            try:
                body_raw = self.rfile.read(length)
                body = json.loads(body_raw)
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")

                if "pair" not in body:
                    raise ValueError("pair field is required")
                if "verdict" not in body:
                    raise ValueError("verdict field is required")
                if "post_a_id" not in body or "post_b_id" not in body or "queue_signal" not in body:
                    raise ValueError("post_a_id, post_b_id, and queue_signal are required")

                pair_index = int(body["pair"])
                verdict = str(body["verdict"])
                note = str(body["note"])[:2000] if body.get("note") else None
                post_a_id = int(body["post_a_id"])
                post_b_id = int(body["post_b_id"])
                queue_signal = str(body["queue_signal"])

                state.record(
                    pair_index,
                    verdict,
                    note,
                    _now(),
                    expected_post_a_id=post_a_id,
                    expected_post_b_id=post_b_id,
                    expected_queue_signal=queue_signal,
                )
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                with contextlib.suppress(sqlite3.Error):
                    state.connection.rollback()
                self._send(str(error).encode(), "text/plain", 400)
                return
            except sqlite3.Error as error:
                with contextlib.suppress(sqlite3.Error):
                    state.connection.rollback()
                self._send(f"database error: {error}".encode(), "text/plain", 500)
                return
            except Exception as error:
                with contextlib.suppress(sqlite3.Error):
                    state.connection.rollback()
                self._send(f"unexpected server error: {error}".encode(), "text/plain", 500)
                return

            self._send(b"ok", "text/plain", 200)

    return Handler


def create_server(
    catalog: Path,
    media_root: Path,
    *,
    port: int = 8765,
    host: str = "127.0.0.1",
    revisit_unsure: bool = False,
) -> tuple[HTTPServer, CatalogDatabase, LabelingState]:
    """Create the HTTPServer, CatalogDatabase, and LabelingState instances."""
    database = CatalogDatabase(catalog)
    try:
        state = LabelingState(database.connection, media_root, revisit_unsure=revisit_unsure)
        handler_class = create_handler(state, media_root)
        server = HTTPServer((host, port), handler_class)
    except BaseException:
        database.close()
        raise
    return server, database, state


def serve(
    catalog: Path,
    media_root: Path,
    *,
    port: int = 8765,
    revisit_unsure: bool = False,
) -> None:
    server, database, state = create_server(
        catalog, media_root, port=port, revisit_unsure=revisit_unsure
    )
    print(f"labeling UI on http://127.0.0.1:{port} ({len(state.queue)} pairs queued)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        database.close()
