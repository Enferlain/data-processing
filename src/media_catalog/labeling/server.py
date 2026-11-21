"""Minimal local labeling UI (bead data-processing-w7j, data-processing-efw).

A localhost server: shows one pair at a time (served from managed storage or
provider-aware remote requests when no local copy exists), queueing signals,
verdict buttons, and relation descriptions. Labels land in ``pair_labels`` with
an append-only decision history in ``pair_label_decisions``.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from media_catalog.database import CatalogDatabase
from media_catalog.labeling.media import _detect_mime
from media_catalog.labeling.remote import RemoteMediaError, fetch_remote_media
from media_catalog.labeling.state import LabelingState


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
    audit: int = 0,
    seed: int = 0,
) -> tuple[HTTPServer, CatalogDatabase, LabelingState]:
    """Create the HTTPServer, CatalogDatabase, and LabelingState instances."""
    database = CatalogDatabase(catalog)
    try:
        state = LabelingState(
            database.connection,
            media_root,
            revisit_unsure=revisit_unsure,
            audit=audit,
            seed=seed,
        )
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
    audit: int = 0,
    seed: int = 0,
) -> None:
    server, database, _state = create_server(
        catalog,
        media_root,
        port=port,
        revisit_unsure=revisit_unsure,
        audit=audit,
        seed=seed,
    )
    print(f"labeling UI on http://127.0.0.1:{port} ({len(_state.queue)} pairs queued)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        database.close()
