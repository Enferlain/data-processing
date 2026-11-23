# Tasks

## 1. Kernel widening

- [x] 1.1 Migration `0041_series_object_kind.sql`: rebuild `platform_references` with `series` in the object_kind CHECK (0003 idiom, incl. the six candidate-guard trigger drops/recreates), preserve ids, recreate the lookup index
- [x] 1.2 `records/common.py`: widen `OBJECT_KINDS` with `"series"`

## 2. Recognition and retention

- [x] 2.1 `links.py`: pixiv-series recognizer branch (`/artworks/series/<id>` → series/stable_id), placed before the artwork branch
- [x] 2.2 `adapters/pixiv/transport.py`: read the artwork `series` field; emit one `external_reference` item targeting the pixiv series stable id when non-null
- [x] 2.3 Pixiv fixture: add one series-nonnull artwork case, manifest-documented per the suite's reference-corroborated precedent

## 3. Tests and gates

- [x] 3.2 Gates: `uv run pytest`, `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src` (includes repairing two sharkgone-night regressions the full suite caught: lost `sankaku` SOURCE_OPERATIONS entry and lost `pawchive.pw` host mapping; platform-count and backup schema-version pins re-pinned)

## Workflow follow-up

- Archive the change; sync both deltas
- CHANGELOG.md entry under Added
- Close bead `data-processing-7jx`; note cyp's series slice as unblocked-pending-this
