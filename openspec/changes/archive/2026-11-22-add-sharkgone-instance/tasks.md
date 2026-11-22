# Tasks

## 1. Instance and kernel registration

- [ ] 1.1 `SHARKGONE` DanbooruInstance in `adapters/danbooru/config.py` (4 post strategies, no artist, no enumeration, env-only credentials) + export
- [ ] 1.2 Migration `0040_sharkgone_platform.sql` + `records/common.py` SOURCE_OPERATIONS entry

## 2. Consumer seams

- [ ] 2.1 `adapter_factory`, `crosscheck.PROVIDERS`, discovery `LOOKUP_PROVIDERS`, lookup CLI choices + plan fallback, offline replay, library provider set, maintenance reprocess providers
- [ ] 2.2 `links.py` host table + `_POSTS_PATH_PLATFORMS`; `link_resolution.py` host resolver + RESOLVED_PLATFORMS; `doctor.py` surface with the captured suite

## 3. Tests and gates

- [ ] 3.1 `tests/test_sharkgone_adapter.py`: instance policy + capability set (no artist), registration across seams, captured-contract normalization, anonymous md5 wire render, links/resolution recognition
- [ ] 3.2 Gates: `uv run pytest`, `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`

## Workflow follow-up

- Archive the change; sync the danbooru-family delta
- CHANGELOG.md entry under Added
- Close bead `data-processing-9ds` (live authenticated probe stays an operator-side spot check)
