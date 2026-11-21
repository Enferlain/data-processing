"""HTML rendering for the labeling UI (bead data-processing-cne).

The pair page template, per-post media view rendering, and the queue-empty
page. Pure string generation: no database or filesystem access.
"""

from __future__ import annotations

import html
import json
from typing import Any

from media_catalog.labeling.queue import PairCandidate

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
      if (err.startsWith("stale pair mismatch")) {{
        sessionStorage.setItem('label_saved_flash',
          "The queue changed (server restart or another tab); " +
          "this page reloaded to the current queue.");
        setTimeout(() => location.reload(), 800);
        return;
      }}
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


def render_post_view(resolved: dict[str, Any]) -> dict[str, str]:
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
                    '<div class="badge-unverified">Local copy (original status unverified)</div>'
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
            src.lower().endswith(f".{ext}") for ext in ("gif", "jpg", "jpeg", "png", "webp", "avif")
        )
    ):
        preview_badge = (
            '<div class="badge-preview">Preview / thumbnail only (original missing)</div>'
            if is_preview
            else (
                '<div class="badge-sample">Sample (scaled copy; original missing)</div>'
                if is_sample
                else (
                    '<div class="badge-unverified">Local copy (original status unverified)</div>'
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
            f'<p><a href="{source_attr}" target="_blank" rel="noopener">Open source link</a></p>'
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


def render_pair_page(
    pair: PairCandidate,
    view_a: dict[str, str],
    view_b: dict[str, str],
    *,
    pos: int,
    pair_index: int,
    total: int,
    revisit_unsure: bool,
    skipped_count: int,
) -> str:
    mode_badge = " (revisit unsure)" if revisit_unsure else ""
    skipped_badge = (
        f"&nbsp; <span style='color:#f28b82;'>({skipped_count} pairs deferred)</span>"
        if skipped_count > 0
        else ""
    )
    return _PAGE.format(
        pos=pos,
        total=total,
        signal=html.escape(pair.queue_signal),
        detail=html.escape(pair.detail),
        mode_badge=mode_badge,
        skipped_badge=skipped_badge,
        media_a=view_a["media_html"],
        media_b=view_b["media_html"],
        name_a=view_a["name"],
        name_b=view_b["name"],
        meta_a=view_a["meta"],
        meta_b=view_b["meta"],
        pair_index=pair_index,
        post_a_id=pair.post_a_id,
        post_b_id=pair.post_b_id,
        queue_signal_json=json.dumps(pair.queue_signal),
    )


def render_queue_empty(revisit_unsure: bool, skipped_count: int) -> str:
    msg = (
        (
            "No more saved unsure pairs are ready to review. Deferred pairs still need "
            "media; their labels and notes have been preserved."
            if skipped_count
            else "No more ready unsure pairs in this session. "
            "Saved unsure decisions remain available for later review."
        )
        if revisit_unsure
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
