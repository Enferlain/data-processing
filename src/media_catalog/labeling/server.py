"""Minimal local labeling UI (bead data-processing-w7j).

A stdlib-only localhost server: shows one image pair at a time (served from
managed storage or the original remote URL when no local copy exists), the
queueing signal, and verdict buttons plus a free-text relation description.
Labels land in ``pair_labels`` with an append-only decision history.
"""

from __future__ import annotations

import contextlib
import html
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from media_catalog.labeling.queue import PairCandidate, build_queue

VERDICTS = ("same", "variant", "different", "unsure")

_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>label pairs</title>
<style>
 body {{ font-family: system-ui, sans-serif; background: #111; color: #eee; margin: 0; }}
 header {{ padding: 10px 16px; background: #1d1d1d; display: flex; gap: 16px;
           align-items: baseline; justify-content: space-between; }}
 header b {{ font-size: 15px; }}
 header .pos {{ color: #8ab4f8; }}
 .pair {{ display: flex; gap: 8px; padding: 8px; height: calc(100vh - 210px); }}
 .pair {{ box-sizing: border-box; }}
 .side {{ flex: 1; display: flex; flex-direction: column; min-width: 0; }}
 .side img {{ flex: 1; object-fit: contain; min-height: 0; max-width: 100%; background: #000; }}
 .meta {{ font-size: 12px; color: #999; padding: 6px 4px; overflow-wrap: anywhere; }}
 .signal {{ padding: 6px 16px; color: #fdd663; font-size: 13px; }}
 .bar {{ position: fixed; bottom: 0; left: 0; right: 0; background: #1d1d1d;
         padding: 10px 16px; display: flex; gap: 8px; align-items: center; }}
 button {{ font-size: 15px; padding: 10px 16px; border: 1px solid #444; border-radius: 6px;
           background: #2a2a2a; color: #eee; cursor: pointer; }}
 button.hot {{ background: #1f4d8f; border-color: #2b6cb0; }}
 input[type=text] {{ flex: 1; font-size: 15px; padding: 10px; border-radius: 6px;
                     border: 1px solid #444; background: #2a2a2a; color: #eee; }}
 .key {{ opacity: .6; font-size: 11px; display: block; }}
</style></head>
<body>
<header><b>label pairs</b><span class="pos">{pos} / {total} &nbsp; signal: {signal}</span></header>
<div class="signal">{detail}</div>
<div class="pair">
  <div class="side"><img src="{img_a}" loading="eager"><div class="meta">{meta_a}</div></div>
  <div class="side"><img src="{img_b}" loading="eager"><div class="meta">{meta_b}</div></div>
</div>
<div class="bar">
  <button class="hot" onclick="submit('same')">same<span class="key">1</span></button>
  <button class="hot" onclick="submit('variant')">variant<span class="key">2</span></button>
  <button class="hot" onclick="submit('different')">different<span class="key">3</span></button>
  <button class="hot" onclick="submit('unsure')">unsure<span class="key">4</span></button>
  <input id="note" type="text" placeholder="describe the relation (optional)"
         onkeydown="if(event.key==='Enter')submit(null)">
  <button onclick="location='/next?skip=1'">skip</button>
</div>
<script>
async function submit(v) {{
  if (!v) v = 'unsure';
  const note = document.getElementById('note').value;
  await fetch('/label', {{method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{pair: {pair_index}, verdict: v, note: note}})}});
  location.reload();
}}
document.addEventListener('keydown', e => {{
  if (document.activeElement === document.getElementById('note')) return;
  if (e.key === '1') submit('same');
  if (e.key === '2') submit('variant');
  if (e.key === '3') submit('different');
  if (e.key === '4') submit('unsure');
}});
</script>
</body></html>"""


class LabelingState:
    def __init__(self, connection: sqlite3.Connection, media_root: Path) -> None:
        self.connection = connection
        self.media_root = media_root
        self.queue: list[PairCandidate] = build_queue(connection)
        self.cursor = 0

    def current(self) -> PairCandidate | None:
        while self.cursor < len(self.queue):
            pair = self.queue[self.cursor]
            row = self.connection.execute(
                "SELECT 1 FROM pair_labels WHERE post_a_id = ? AND post_b_id = ?"
                " AND queue_signal = ?",
                (pair.post_a_id, pair.post_b_id, pair.queue_signal),
            ).fetchone()
            if row is None:
                return pair
            self.cursor += 1
        return None

    def _post_view(self, post_id: int) -> dict[str, str]:
        row = self.connection.execute(
            """SELECT p.platform_key, po.native_post_id, po.canonical_url,
                      m.remote_url, al.relative_path, m.width, m.height,
                      m.declared_md5
                 FROM posts po JOIN platforms p ON p.platform_id = po.platform_id
                 LEFT JOIN media_occurrences m ON m.post_id = po.post_id
                 LEFT JOIN occurrence_assets oa
                   ON oa.media_occurrence_id = m.media_occurrence_id
                 LEFT JOIN assets a ON a.asset_id = oa.asset_id
                 LEFT JOIN asset_locations al ON al.asset_id = a.asset_id
                WHERE po.post_id = ?
                ORDER BY m.media_occurrence_id LIMIT 1""",
            (post_id,),
        ).fetchone()
        if row is None:
            return {"img": "", "meta": f"post {post_id} (no media)"}
        img = (
            f"/media/{row['relative_path']}" if row["relative_path"] else (row["remote_url"] or "")
        )
        meta = (
            f"{row['platform_key']}:{row['native_post_id']} · "
            f"{row['width'] or '?'}x{row['height'] or '?'} · md5 {row['declared_md5'] or '?'}"
        )
        return {"img": html.escape(img, quote=True), "meta": html.escape(meta)}

    def page(self) -> str | None:
        pair = self.current()
        if pair is None:
            return (
                "<html><body style='background:#111;color:#eee;font-family:system-ui'>"
                "<h2>queue empty</h2><p>every queued pair is labeled — rebuild the queue"
                " after ingesting more posts.</p></body></html>"
            )
        a = self._post_view(pair.post_a_id)
        b = self._post_view(pair.post_b_id)
        return _PAGE.format(
            pos=self.cursor + 1,
            total=len(self.queue),
            signal=pair.queue_signal,
            detail=html.escape(pair.detail),
            img_a=a["img"],
            img_b=b["img"],
            meta_a=a["meta"],
            meta_b=b["meta"],
            pair_index=self.cursor,
        )

    def record(self, pair_index: int, verdict: str, note: str | None, now: str) -> None:
        if verdict not in VERDICTS:
            raise ValueError(f"unsupported verdict: {verdict}")
        if not 0 <= pair_index < len(self.queue):
            raise ValueError("pair index out of range")
        pair = self.queue[pair_index]
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
        self.cursor = pair_index + 1


def serve(catalog: Path, media_root: Path, *, port: int = 8765) -> None:
    from media_catalog.database import CatalogDatabase

    database = CatalogDatabase(catalog)
    state = LabelingState(database.connection, media_root)

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
            if parsed.path == "/" or parsed.path == "/next":
                if parse_qs(parsed.query).get("skip") and state.current() is not None:
                    state.cursor += 1
                page = state.page()
                assert page is not None
                self._send(page.encode(), "text/html; charset=utf-8")
            elif parsed.path.startswith("/media/"):
                relative = unquote(parsed.path[len("/media/") :])
                target = (media_root / relative).resolve()
                if not target.is_relative_to(media_root.resolve()):
                    self._send(b"forbidden", "text/plain", 403)
                    return
                if not target.is_file():
                    self._send(b"not found", "text/plain", 404)
                    return
                self._send(target.read_bytes(), "application/octet-stream")
            elif parsed.path == "/queue.json":
                payload = json.dumps(
                    [
                        {
                            "post_a_id": p.post_a_id,
                            "post_b_id": p.post_b_id,
                            "queue_signal": p.queue_signal,
                            "detail": p.detail,
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
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = json.loads(self.rfile.read(length))
                note = str(body["note"])[:2000] if body.get("note") else None
                state.record(int(body["pair"]), str(body["verdict"]), note, _now())
            except (KeyError, ValueError, json.JSONDecodeError, sqlite3.Error) as error:
                message = str(error).encode()
                with contextlib.suppress(sqlite3.Error):
                    state.connection.rollback()
            else:
                message = b"ok"
            self._send(message, "text/plain")

    # One operator, one connection: a single-threaded server keeps the
    # sqlite connection on one thread by construction.
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"labeling UI on http://127.0.0.1:{port} ({len(state.queue)} pairs queued)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        database.close()
