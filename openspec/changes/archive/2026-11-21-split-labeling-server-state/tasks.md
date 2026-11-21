# Tasks

## 1. Extract leaf modules (no intra-package dependencies)

- [x] 1.1 Create `src/media_catalog/labeling/media.py`: move `_detect_mime` and the `_resolve_post_media` body as `resolve_post_media(connection, media_root, matched_root_ids, post_id)`, byte-identical apart from de-`self`ing
- [x] 1.2 Create `src/media_catalog/labeling/render.py`: move `_PAGE`, `_post_view` body as `render_post_view(resolved)`, and split `page` into `render_pair_page(...)` + `render_queue_empty(...)`

## 2. Session state and HTTP cutover (single commit)

- [x] 2.1 Create `src/media_catalog/labeling/state.py`: move `VERDICTS` and `LabelingState` (`__init__`, `_find_matching_managed_roots`, `current`, `record`); add two-line delegates `_resolve_post_media`, `_post_view`, `page`
- [x] 2.2 Rewrite `src/media_catalog/labeling/server.py` to the HTTP surface only: import `LabelingState` (used by `create_server`), keep `CatalogDatabase` module global, keep `import httpx` + request-time `httpx.Client()`, `create_handler`/`create_server`/`serve` bodies unchanged

## 3. Verification

- [x] 3.1 `uv run pytest tests/test_labeling.py tests/test_labeling_remote.py tests/test_catalog_cli.py` green with zero test-file edits
- [x] 3.2 Full gates: `uv run pytest`, `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`

## Workflow follow-up

- Archive the change (`openspec archive split-labeling-server-state`)
- Add CHANGELOG.md entry under Changed
- Close bead `data-processing-cne`
