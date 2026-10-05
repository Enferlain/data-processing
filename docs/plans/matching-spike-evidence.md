# Matching spike evidence: perceptual-hash distance distributions

Status: complete (2026-10-05)
Bead: `data-processing-8nj` (kernel Phase D research half)

This document answers the catalog plan's "pHash thresholds" research spike row
([cross-platform-media-catalog.md §18](cross-platform-media-catalog.md): distance
distribution, candidate threshold, documented false-positive set) with measurements
over real fixture bytes. It reports aggregates and method only — no URLs, post,
tweet, or media identifiers. **No metric or threshold here establishes identity,
authorship, same-work, source direction, or preferred quality; those conclusions
require provenance and review.**

Maintainer decision (2026-10-05): these measurements are research evidence only.
Catalog hashes — MD5, SHA-256, and stored perceptual fingerprints — are
identification metadata; no similarity mechanism belongs in a product surface
unless a generic, evidence-backed one is proven, and established libraries
provide the candidate metrics to take from when that time comes. The measurement
code lives in the research harness (`scripts/matching-spike/signals.py`), not in
the catalog package.

## Method

Fixtures were assembled under `private-exports/matching-spike/` by the tracked
harness in `scripts/matching-spike/` (manifest-driven, host-allowlisted, bounded,
resumable; fixture bytes and results stay out of the tracked tree):

- 139 fixture files, 133 labeled pairs.
- Perceptual hashes computed with `imagehash` 4.3.2 `phash` at hash sizes 8
  (64-bit, the format `assets.phash` stores) and 16 (256-bit, computed fresh by
  the harness; not stored by the catalog), distances are Hamming distances
  between hex digests via the harness's `signals` module.
- Exact hashes recomputed locally per fixture (SHA-256, MD5); declared provider
  MD5s verified the fetched originals at fetch time.

## Fixture classes

| Class | Pairs | Meaning |
| --- | --- | --- |
| `x_variant` | 62 | X `name=orig` vs `name=small` of one image — provider-labeled resize/re-encode |
| `gelbooru_sample` | 5 | booru post file vs its provider-generated sample (downscale) |
| `gelbooru_preview` | 5 | booru post file vs its provider-generated thumbnail |
| `cross_provider_same_work` | 8 | X original vs booru file of the same underlying work (per curated example groups) |
| `gelbooru_group3_candidate` | 3 | the curated three-variation group's inter-post pairs — measured candidates, labels unconfirmed |
| `cross_artist_negative` | 50 | random cross-author X originals — unrelated works |
| `same_artist_near_negative` | 0 | intended same-author/different-post probes; none existed in the deterministic sample (limitation below) |

Positives for the sweep are the first five classes (group-3 candidates included
with the caveat that their labels are unconfirmed); negatives are the negative
classes. One curated example status could not be resolved (provider 404), so its
group contributes no X side.

## Distance distributions

Hamming distance min / median / max per class:

| Class | phash@8 (64-bit) | phash@16 (256-bit) | same bytes |
| --- | --- | --- | --- |
| `x_variant` | 0 / 0 / 2 | 0 / 0 / 4 | 0 |
| `gelbooru_sample` | 0 / 0 / 0 | 0 / 0 / 0 | 0 |
| `gelbooru_preview` | 0 / 0 / 0 | 0 / 0 / 2 | 0 |
| `cross_provider_same_work` | 0 / 2 / 10 | 0 / 10 / 36 | 2 of 8 |
| `gelbooru_group3_candidate` | 4 / 10 / 10 | 20 / 32 / 36 | 0 |
| `cross_artist_negative` | 22 / 32 / 40 | 114 / 130 / 146 | 0 |

Same-bytes evidence: two cross-provider pairs (X original vs booru file of the
same work) had byte-identical SHA-256 — real provider mirrors exist and exact
hashes catch them at distance 0.

## Threshold sweep

phash@8 against the class labels (83 positives, 50 negatives):

| Threshold | True-positive rate | False-positive rate |
| --- | --- | --- |
| 8 | 0.952 | 0.000 |
| 10 | 1.000 | 0.000 |
| 16 | 1.000 | 0.000 |
| 21 | 1.000 | 0.000 |
| 22 | 1.000 | 0.040 |

Every measured positive sits at phash@8 distance ≤ 10; every measured negative
sits at ≥ 22. On this fixture set any threshold in 10–21 separates the classes
perfectly; the first false positives appear at 22. phash@16 separates with a
wider margin (positives ≤ 36, negatives ≥ 114; thresholds around 36–64 keep
TPR ≥ 0.96 at FPR 0.000).

**Candidate threshold band:** 10–12 captures every measured positive with zero
measured false positives on this set; 8 is the conservative end (misses the
re-encode-heaviest cross-provider pairs, which measured up to distance 10);
above 21 starts admitting unrelated works. This band is research evidence for
a future generic matching design, not a shipped default.

## Observations

- **Thumbnails and samples are visually identical to their originals** at
  phash@8 (distance 0): perceptual hashing cannot flag "this is a thumbnail."
  Variant roles and dimensions carry that signal — projections that exclude
  thumbnails should filter on variant role and dimension, not on hash distance.
- **The curated three-variation group self-separates**: one pair measures 4
  (consistent with the annotated same-work text/no-text variants) while its
  pairs to the third post measure 10 — the same distance band as genuine
  cross-provider re-encodes. A same-band overlap between "different work" and
  "re-encoded same work" is exactly why a metric may only propose and review
  must conclude.
- **Cross-provider mirroring is real**: identical bytes across providers occur
  (2 of 8 cross-provider pairs), so exact-hash equality remains the strongest
  cheap signal, with perceptual distance covering the re-encoded remainder.

## Limitations

- Small sample: 83 positive and 50 negative pairs from one collection and a
  curated handful of example works; margins are evidence, not guarantees.
- `same_artist_near_negative` is empty — the deterministic sample contained no
  two works by the same author, so visually-similar-same-artist false positives
  are not yet measured; that class is the most important one to grow next.
- Group-3 candidate labels are unconfirmed; the distance structure is reported
  as measured.
- All hashes in this spike were computed fresh from fixture bytes; the catalog's
  stored `assets.phash` mixes managed (`imagehash.phash-v1`) and legacy x-likes
  values — nominally the same DCT phash@8 lineage, but a managed-vs-legacy
  sanity comparison should accompany the first real-catalog use of
  `catalog assets similar`.
- One curated example could not be resolved (deleted/restricted at the
  provider), reducing cross-provider coverage.

## Consequences

- These bands are *proposal* evidence for any future, generic matching design
  — nothing here ships as a product surface. Distance ≤ 10 measured as
  same-image-transformed; distance 0 with unequal SHA-256 measured as
  visually-identical-different-bytes; exact hash equality verifies same-bytes.
  A single metric is not reliable enough to build on: the measured classes are
  small, partly mechanical (one provider's own re-encode pipeline), and lack
  same-artist false-positive probes.
- A future similarity mechanism should be generic (multiple metrics, taken
  from established libraries, compared against evidence like this), not a
  hardcoded threshold in a catalog surface.
- The empty `same_artist_near_negative` class is the most important
  measurement gap: visually-similar-same-artist false positives are unmeasured.
- Thumbnails measured visually identical to originals at phash@8, so any
  variant-family view must exclude them by variant role and dimensions, never
  by hash distance.
- The kernel Phase D schema half (Bead `data-processing-t08`) remains the
  consumer of this evidence when relationship types and review-gated
  conclusions are designed.
