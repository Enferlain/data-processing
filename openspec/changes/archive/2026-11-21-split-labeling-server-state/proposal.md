# Split labeling/server.py LabelingState

## What

Split `src/media_catalog/labeling/server.py` (1,362 lines) into cohesive
modules inside the existing `labeling` package, with `server.py` keeping only
the HTTP surface:

- `labeling/media.py` — post media resolution: the ~450-line
  `_resolve_post_media` body (occurrence/asset queries, candidate priority
  ranking, remote/local selection) plus `_detect_mime`.
- `labeling/render.py` — HTML generation: the `_PAGE` template, post view
  rendering (was `LabelingState._post_view` body), and page rendering
  (pair page + queue-empty page, was `LabelingState.page` body).
- `labeling/state.py` — the labeling session: `VERDICTS`, `LabelingState`
  (queue construction, managed-root matching, pair selection/cursor, verdict
  application with decision-history writes), delegating media resolution and
  rendering to the modules above.
- `labeling/server.py` — `create_handler` (endpoints), `create_server`,
  `serve`. Unchanged HTTP behavior.

Pure move/refactor: no behavior, endpoint, status-code, HTML-fragment, or
schema change. Moved code stays byte-identical except for mechanical
de-`self`ing where methods become module functions.

## Why

The 2026-11-20 file-size survey flagged `server.py` as mixing four concerns in
one class: pair-state queries, verdict application semantics, decision-history
writes, and pair selection — plus ~700 lines of media resolution and HTML
rendering that have nothing to do with either. Bead `data-processing-cne`.
The labeling package already establishes the multi-file convention
(`queue.py`, `calibration.py`, `remote.py`, `sankaku.py`).

## Scope

In:

- New `labeling/media.py`, `labeling/render.py`, `labeling/state.py`;
  `server.py` reduced to the HTTP surface.
- `LabelingState` keeps its constructor signature and the members tests and
  the handler use (`record`, `page`, `_post_view`, `_resolve_post_media`,
  `queue`, `connection`, `sankaku_media`, `_matched_root_ids`).
- Behavioral pins preserved exactly: `media_catalog.labeling.server` module
  globals `CatalogDatabase` and `serve` stay lookup-addressable there
  (monkeypatched in `tests/test_catalog_cli.py`); the handler keeps calling
  `httpx.Client()` via request-time attribute lookup; `create_server` keeps
  returning the `(HTTPServer, CatalogDatabase, LabelingState)` tuple.

Out:

- Any user-visible change: endpoints, statuses, bodies, page HTML, queue
  order, label persistence.
- Renames beyond what cross-module imports require; identifiers keep their
  current names (e.g. `_detect_mime` stays `_detect_mime`).
- Test edits: `tests/test_labeling.py` and `tests/test_labeling_remote.py`
  must stay green with zero assertion changes; their imports
  (`LabelingState`, `create_server` from `labeling.server`) keep resolving
  because `server.py` genuinely uses both.
