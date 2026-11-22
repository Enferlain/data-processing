# Design

## Context

Three writers recompute `score = SUM(strength points of supports rows)` with
the 4-tier map (`discovery/support.py:8`) duplicated as inline SQL
(interpretation.py:313-330 + 471-486, discovery/candidates.py:194-212,
discovery/posts.py:108-131). `stance='contradicts'` exists in the schema
unused. `labeling/calibration.py` provides pure `wilson_interval` and a
per-family report over `pair_labels`. Operator label counts (2026-11-22):
provider_parent 231 (85% same-or-variant), pool_member 109 (25%),
same_artist_contrast 179 (0%), same_artist_tags 54 (3.7%),
shared_source_url 27 (63%), shared_external_id 2 (0%), identical_md5
operator-verified 59/59 (the 18,765 auto rows are circular and excluded).

## Goals / Non-Goals

**Goals:** one shared deterministic policy; calibrated per-family weights
with CIs in the audit JSON; negative same-artist weight; correlated-field
compounding; version bumps; regression pins for sign and compounding.

**Non-Goals:** changing thresholds or review routing (scores stay
non-authoritative), Beta/Isotonic calibration at higher n (revisit at
100–200+ per family), emitting `contradicts` stance rows, schema changes,
re-scoring existing v1 candidates.

## Decisions

### D1: Family weights = base strength × calibrated factor

`contribution = STRENGTH_SCORES[strength] × (2·r̂ − 1)` where `r̂` is the
Laplace-smoothed same-or-variant rate `(sv+1)/(n+2)` of the family's label
distribution. r̂>0.5 adds, r̂<0.5 subtracts — same_artist families land near
−0.9, identical-md5 near +0.97. Laplace (not raw Wilson-lower) because n=2
families exist and must not swing to maximal negative; the Wilson 95% CI is
carried in the components JSON as the honest uncertainty record. Families
without calibration data keep factor 1.0 (their behavior is unchanged).

Kind→family map: `verified_exact_hash`→identical_md5 (operator 59/59
constant, documented), `provider_source_reference`→shared_source_url,
`shared_stable_external_id`→shared_external_id,
`same_artist_overlap`→same_artist_tags, others unmapped.

### D2: Compounding inside correlation groups

`CORRELATED_GROUPS` names evidence-kind sets that restate one identity
fact. Within a group, contributions combine as `100·(1−∏(1−cᵢ/100))`
(probabilistic OR) — never the plain sum. Groups today:
`{provider_source_reference, same_artist_overlap}` (artist identity inside
a source URL). Groups contribute once to the total; everything else sums.

### D3: One shared recompute, three thin callers

`scoring.score_evidence(rows)` returns `(score, components_json)` where
components carry per-family `{count, labels, rate, ci95, contribution}`,
the correlation-group compound, and `SCORING_POLICY_VERSION`. The three
writers replace their inline SQL with it and bump their writer version
strings to `-v2`. Determinism holds: same rows, same score.

### D4: same_artist_overlap producer in the lookup interpreter

When interpreting a post result whose artist tags intersect the seed
post's artist tags, attach one `same_artist_overlap` evidence row
(strength `weak`, stance `supports`, characteristic listing the shared
tags). Alone it scores negative (D1); combined with a correlated
source-URL reference it compounds (D2). The seed's artist tags come from
the same `post_tags` join the labeling queue uses.

## Risks / Trade-offs

- [v1-pinned score values shift] → Tests re-pinned to the new deterministic
  outputs with equally strong assertions; changelog records the policy
  change and version bump.
- [Small-n families mislead] → Laplace smoothing bounds swing; components
  JSON exposes n and CI so reviewers see thin families; families with zero
  labels keep factor 1.0.
- [Double-negative with future contradicts rows] → Documented: this policy
  scores supports rows only; contradicts-stance handling stays future work.

## Migration Plan

Single commit: new module, writer cutover, producer, tests; standard
gates. No data migration — old candidates keep v1 rows. Rollback is
`git revert`.
