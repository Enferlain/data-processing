# Tasks

## 1. Queue assembly

- [x] 1.1 `build_queue` normal mode: sort by signal for deterministic grouping, then assemble with `zip_longest` round-robin and slice the limit after interleaving

## 2. Tests and verification

- [x] 2.1 Test: scratch catalog with a dominant family (6 pool pairs) plus a small family (3 same-artist pairs) — queue alternates families, the small family's pairs all appear in the first rotations; signal details unchanged
- [x] 2.2 Gates: `uv run pytest` (full), `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`

## Workflow follow-up

- Archive the change; sync the labeling delta
- CHANGELOG.md entry under Changed
- Close bead `data-processing-xm9`
