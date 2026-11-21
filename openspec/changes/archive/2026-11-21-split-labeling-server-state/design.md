# Design

## Context

`src/media_catalog/labeling/server.py` is 1,362 lines holding four concerns:

| Lines | Concern |
|---|---|
| 31–246 | `_PAGE` HTML template (188 lines) + `_detect_mime` |
| 249–314, 983–1043 | `LabelingState` session: queue construction, managed-root matching, pair selection cursor, verdict application + decision-history writes |
| 334–910 | Media resolution (`_resolve_post_media`, ~450 lines of occurrence/asset queries and candidate priority ranking) and post-view HTML (`_post_view`) |
| 912–981, 1046–1362 | Page rendering (`page`) and the HTTP surface (`create_handler`, `create_server`, `serve`) |

External pins that MUST survive the split unchanged (verified against
`tests/test_labeling.py`, `tests/test_labeling_remote.py`,
`tests/test_catalog_cli.py`):

- `LabelingState(connection, media_root, *, revisit_unsure=False, audit=0, seed=0)`
  constructor; members `record`, `page`, `_post_view`, `_resolve_post_media`,
  `queue` (with `skipped_count`), `connection`, `sankaku_media`,
  `_matched_root_ids` (handler reads the last three).
- `media_catalog.labeling.server` module globals `CatalogDatabase` and `serve`:
  `tests/test_catalog_cli.py:46,71` monkeypatches them on that module, and
  `create_server` must keep looking `CatalogDatabase` up via module global at
  call time.
- The `/remote-media` handler calls `httpx.Client()` through request-time
  attribute lookup (`tests/test_labeling_remote.py:412` patches `httpx.Client`).
- `create_server` returns the `(HTTPServer, CatalogDatabase, LabelingState)`
  tuple; `serve` stays lazily importable from
  `media_catalog.labeling.server` (`cli_commands/maintenance.py:220`).
- No test references `VERDICTS`, `_PAGE`, `_detect_mime`, `create_handler`,
  `cursor`, `current()`, `_session_decisions` by name — only their behavior.

## Goals / Non-Goals

**Goals:**

- Each module in `labeling/` owns exactly one concern; no module exceeds the
  largest existing package file by becoming a new dumping ground.
- Zero test edits; zero behavior change (endpoints, statuses, bodies, HTML
  fragments, queue order, persistence).
- Dependency direction is acyclic and points away from the session state.

**Non-Goals:**

- Renaming identifiers (underscore prefixes stay; e621 `shapes.py` precedent).
- Restructuring `LabelingState` into multiple classes, or extracting
  selection/application into separate modules.
- Touching `queue.py`, `remote.py`, `sankaku.py`, `calibration.py`, CLI, or
  schema.

## Decisions

### D1: Four modules — `media.py`, `render.py`, `state.py`, `server.py`

| Module | Contents (source lines moved) | Approx. size |
|---|---|---|
| `labeling/media.py` | `_detect_mime` (221–246); `resolve_post_media(connection, media_root, matched_root_ids, post_id)` — body of `_resolve_post_media` (334–781) | ~560 |
| `labeling/render.py` | `_PAGE` (31–218); `render_post_view(resolved)` — body of `_post_view` (783–910); `render_pair_page(...)` and `render_queue_empty(...)` — body of `page` (912–981) | ~320 |
| `labeling/state.py` | `VERDICTS`; `LabelingState`: `__init__`, `_find_matching_managed_roots`, `current`, `record`, thin delegates `_resolve_post_media`/`_post_view`/`page` | ~180 |
| `labeling/server.py` | `create_handler`, `create_server`, `serve` (HTTP only) | ~330 |

Alternative considered: the bead's illustrative `state/selection/application`
split. Rejected: selection (`current`) and application (`record`) share the
cursor + `_session_decisions` session state, so separating them forces either
a second class or awkward parameter passing; the actual mass is media
resolution (~450 lines) and rendering (~300 lines), which the bead's example
did not anticipate. The session concerns land together in `state.py` at ~180
lines — cohesive, not god-class scale.

Alternative considered: leaving `LabelingState` in `server.py`. Rejected: the
bead asks for labeling logic out of the HTTP surface; `state.py` makes the
session importable without HTTP machinery.

### D2: `LabelingState` stays the façade; extraction is functional, not class-based

`resolve_post_media`, `render_post_view`, `render_pair_page`,
`render_queue_empty` are module-level functions. The media resolver depends
only on `(connection, media_root, matched_root_ids)`; the renderers only on
resolved dicts and scalar counts — neither needs object state, and functions
keep the moved bodies byte-identical apart from de-`self`ing.
`LabelingState._resolve_post_media`/`_post_view`/`page` remain as two-line
delegates because tests call the underscore methods directly.

### D3: `server.py` keeps `LabelingState` and `CatalogDatabase` as real imports

`create_server` constructs `LabelingState` and returns it, and opens
`CatalogDatabase` via module-global lookup — both names therefore remain
genuine (non-re-export) attributes of `media_catalog.labeling.server`, which
is exactly what the `test_catalog_cli.py` monkeypatches pin. No import
changes needed in any test or in `maintenance.py`. `httpx` stays
`import httpx` with request-time `httpx.Client()` attribute lookup.

### D4: Pure-move discipline

Moved blocks are byte-identical; only mechanical substitutions:
`self.connection`→`connection`, `self.media_root`→`media_root`,
`self._matched_root_ids`→`matched_root_ids` in `media.py`; `resolved[...]`
locals unchanged in `render.py`. Cross-module underscore access
(`server.py` reading `state._matched_root_ids`, importing `_detect_mime`)
is accepted to avoid rename churn, matching the e621 `shapes.py` precedent.

### D5: Dependency direction

`server.py` → `state.py` → {`queue.py`, `media.py`, `render.py`,
`sankaku.py`}; `render.py` → (nothing in the package); `media.py` →
`acquisition.policies` only. No back-imports into `state.py` or `server.py`;
`__init__.py` stays empty (it is today).

## Risks / Trade-offs

- [De-`self`ing introduces a subtle SQL or ordering change] → Pure-move
  discipline + the 30 media-resolution/rendering tests in group D and the
  remote-file suite pin exact `src`/`mime`/`source_url`/HTML outcomes; full
  suite must pass with zero test edits.
- [A moved global breaks a monkeypatch pin] → D3 keeps both pinned names in
  `server.py` as used imports; `test_catalog_cli.py` is the canary.
- [`render.py` and `media.py` drift toward new god files] → Both are bounded
  by what exists today (~560/~320 lines); future growth goes to new modules,
  not these.

## Migration Plan

Single cutover in one commit: add three modules, rewrite `server.py` imports
and delegations, run full gates (`uv run pytest tests/test_labeling.py
tests/test_labeling_remote.py tests/test_catalog_cli.py`, then the full suite;
`uv run ruff check .`, `uv run ruff format` on touched files,
`uv run ty check src`). No schema or data impact; rollback is `git revert`.
