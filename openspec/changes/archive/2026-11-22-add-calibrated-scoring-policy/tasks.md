# Tasks

## 1. Policy module

- [x] 1.1 Create `src/media_catalog/scoring.py`: family calibration constants (measured 2026-11-22, operator labels only, identical_md5 59/59 constant), Laplace-smoothed rates + Wilson CIs via `labeling.calibration.wilson_interval`, `contribution = base × (2r̂−1)`, correlation-group compounding, `score_evidence(rows)` and `score_candidate_evidence(...)`, `SCORING_POLICY_VERSION`

## 2. Writer cutover

- [x] 2.1 `candidate_lookup/interpretation.py`: post and account recompute paths use the shared policy; bump `SCORING_VERSION` to `candidate-lookup-score-v2`
- [x] 2.2 `discovery/candidates.py`: same cutover; bump to `link-evidence-v2`
- [x] 2.3 `discovery/posts.py`: same cutover (version string stays caller-supplied)

## 3. same_artist_overlap producer

- [x] 3.1 `interpretation.py`: when result artist tags intersect seed post artist tags, attach one `same_artist_overlap` evidence row (weak/supports)

## 4. Tests and gates

- [x] 4.1 Policy unit tests: negative sign for same_artist-only; correlated positives compound below their sum; CI/n in components; determinism; unmapped kinds unchanged
- [x] 4.2 Interpreter test: same-artist-only candidate scores negative and never raises a source-evidence candidate
- [x] 4.3 Re-pin shifted v1 score assertions in existing suites (none shifted — unmapped kinds keep factor 1.0; suites passed unchanged); full gates: `uv run pytest` (100%), `uv run ruff check .`, `uv run ruff format` on touched files, `uv run ty check src`

## Workflow follow-up

- Archive the change; sync the cross-platform-match-review delta
- CHANGELOG.md entry under Changed
- Close bead `data-processing-vo8`
