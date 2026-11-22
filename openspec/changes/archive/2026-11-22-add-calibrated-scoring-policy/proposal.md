# Proposal

## What

Bead `data-processing-vo8`: fold per-family calibrated priors into the
versioned candidate-scoring policy. Today three score writers
(`candidate_lookup/interpretation.py`, `discovery/candidates.py`,
`discovery/posts.py`) each duplicate a flat additive SUM of four-tier
strength points over supporting evidence — no per-family calibration, no
negative weights, no handling of correlated identity fields.

- New shared policy module (`media_catalog/scoring.py`): one deterministic
  recompute used by all three writers; per-family weights derived from
  operator label rates (`pair_labels` via the existing calibration report)
  with Laplace-smoothed rates and Wilson 95% CIs carried into
  `score_components_json`; families whose labels are majority-`different`
  contribute **negative** weight; correlated identity evidence
  (artist-name-inside-source-URL) **compounds** instead of summing.
- The lookup interpreter attaches a `same_artist_overlap` evidence row when
  a result shares an artist tag with the seed post — under the calibrated
  policy that agreement alone scores negative (same_artist_* labels are
  96–100% `different`), exactly the abstention-first negative-edge
  behavior the ER triage requires.
- Writer `SCORING_VERSION` strings bump to `-v2`; prior candidates keep
  their v1 rows and versions.

## Why

`docs/research/Abstention-First Entity Resolution.md` and
`docs/research/TRIAGE.md` (41–48): additive independent-evidence scoring
double-counts correlated fields, and uncalibrated strengths overstate weak
agreement. The operator's own labels are now a usable per-family calibration
set (provider_parent 231, pool_member 109+, same_artist_contrast 179, …),
and same-artist agreement alone is measured evidence *against* same-work —
it must subtract, not add.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `cross-platform-match-review`: new requirement covering calibrated
  per-family scoring (rates with CIs, negative same-artist weight,
  correlated-field compounding, versioned policy).

## Impact

- Code: new `src/media_catalog/scoring.py`; the three writers replace
  duplicated scoring SQL with the shared policy and bump their version
  strings; `candidate_lookup/interpretation.py` gains the
  `same_artist_overlap` evidence producer.
- No schema migrations: `match_evidence.stance` already admits the needed
  values and `evidence_kind` is free-form; `score_components_json` is the
  audit surface for per-family contributions.
- Existing suites: tests pinning v1 score values are re-pinned to the new
  deterministic outputs (assertions stay equally strong); no assertion is
  deleted.
