# Matching spike evidence: perceptual-hash distance distributions

Status: extended (2026-10-21; first pass complete 2026-10-05)
Beads: `data-processing-8nj` (first pass), `data-processing-qi7` (extension; GitHub issue #5)

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

- 239 fixture files, 212 labeled pairs (first pass: 139 files, 133 pairs).
- Perceptual hashes computed with `imagehash` 4.3.2: `phash` at hash sizes 8
  (64-bit, the format `assets.phash` stores) and 16 (256-bit, computed fresh by
  the harness; not stored by the catalog), plus `average_hash` (`ahash@8`) and
  `dhash@8` from the same library (2026-10-21 extension). Distances are Hamming
  distances between hex digests via the harness's `signals` module.
- Exact hashes recomputed locally per fixture (SHA-256, MD5); declared provider
  MD5s verified the fetched originals at fetch time.
- Same-author negatives (2026-10-21): pairs are drawn deterministically from
  *all* archived X media grouped by author — the first pass sampled from a
  strided subset that contained no repeated author, which is why the class was
  empty.
- Synthetic transformation classes (2026-10-21): derived locally from fetched
  originals with ground truth by construction (a crop of X *is* a crop of X);
  no network, no labeling judgment. Transforms: center 60% crop, corner 40%
  crop, bottom-bar text overlay, contrast+brightness adjust, three black
  censor bars, JPEG q95 and WebP q80 re-encodes.

## Fixture classes

| Class | Pairs | Meaning |
| --- | --- | --- |
| `x_variant` | 62 | X `name=orig` vs `name=small` of one image — provider-labeled resize/re-encode |
| `gelbooru_sample` | 5 | booru post file vs its provider-generated sample (downscale) |
| `gelbooru_preview` | 5 | booru post file vs its provider-generated thumbnail |
| `cross_provider_same_work` | 8 | X original vs booru file of the same underlying work (per curated example groups) |
| `gelbooru_group3_candidate` | 3 | the curated three-variation group's inter-post pairs — measured candidates, labels unconfirmed |
| `cross_artist_negative` | 50 | random cross-author X originals — unrelated works |
| `same_artist_near_negative` | 23 | same-author, different-post X originals — visually related style/subject, assumed different works (provider-attributed author) |
| `synthetic_crop_center` | 8 | X original vs its center-60% crop (derived) |
| `synthetic_crop_corner` | 8 | X original vs its corner-40% crop (derived) |
| `synthetic_text_overlay` | 8 | X original vs a bottom-bar text overlay (derived) |
| `synthetic_color_adjust` | 8 | X original vs contrast 1.3 + brightness 1.15 (derived) |
| `synthetic_censor_bars` | 8 | X original vs three black censor bars (derived) |
| `synthetic_transcode_jpeg` | 8 | X original vs JPEG q95 re-encode (derived) |
| `synthetic_transcode_webp` | 8 | X original vs WebP q80 re-encode (derived) |

Positives for the sweep are the transformation and variant classes (group-3
candidates included with the caveat that their labels are unconfirmed);
negatives are the two negative classes. One curated example status could not be
resolved (provider 404), so its group contributes no X side; one sampled X
original from the same-author extension 404'd at fetch time, leaving 23 of 24
selected same-author pairs measurable.

## Distance distributions

Hamming distance min / median / max per class:

| Class | phash@8 (64-bit) | phash@16 (256-bit) | ahash@8 | dhash@8 | same bytes |
| --- | --- | --- | --- | --- | --- |
| `x_variant` | 0 / 0 / 2 | 0 / 0 / 4 | 0 / 0 / 2 | 0 / 0 / 3 | 0 |
| `gelbooru_sample` | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 |
| `gelbooru_preview` | 0 / 0 / 0 | 0 / 0 / 2 | 0 / 0 / 0 | 0 / 0 / 1 | 0 |
| `cross_provider_same_work` | 0 / 2 / 10 | 0 / 10 / 36 | 0 / 1 / 8 | 0 / 1 / 7 | 2 of 8 |
| `gelbooru_group3_candidate` | 4 / 10 / 10 | 20 / 32 / 36 | 2 / 6 / 8 | 2 / 4 / 6 | 0 |
| `synthetic_transcode_jpeg` | 0 / 0 / 0 | 0 / 0 / 2 | 0 / 0 / 0 | 0 / 0 / 0 | 0 |
| `synthetic_transcode_webp` | 0 / 0 / 2 | 0 / 0 / 2 | 0 / 0 / 1 | 0 / 0 / 1 | 0 |
| `synthetic_color_adjust` | 0 / 3 / 6 | 4 / 9 / 18 | 0 / 0 / 4 | 0 / 2 / 7 | 0 |
| `synthetic_text_overlay` | 4 / 6 / 10 | 8 / 30 / 36 | 2 / 13 / 19 | 0 / 2 / 5 | 0 |
| `synthetic_censor_bars` | 4 / 6 / 10 | 34 / 46 / 56 | 5 / 10 / 25 | 1 / 3 / 6 | 0 |
| `synthetic_crop_center` | 20 / 28 / 30 | 106 / 123 / 132 | 11 / 14 / 21 | 16 / 26 / 35 | 0 |
| `synthetic_crop_corner` | 24 / 29 / 36 | 112 / 126 / 142 | 9 / 29 / 37 | 24 / 28 / 31 | 0 |
| `same_artist_near_negative` | 20 / 32 / 42 | 86 / 128 / 150 | 16 / 30 / 47 | 20 / 30 / 40 | 0 |
| `cross_artist_negative` | 22 / 32 / 40 | 114 / 130 / 146 | 17 / 30 / 49 | 23 / 32 / 42 | 0 |

Same-bytes evidence: two cross-provider pairs (X original vs booru file of the
same work) had byte-identical SHA-256 — real provider mirrors exist and exact
hashes catch them at distance 0.

## Threshold sweep

phash@8 against the class labels. First pass (83 positives, 50 negatives):
thresholds 10–21 separated perfectly. With the 2026-10-21 extension (139
positives including 56 synthetic transformations, 73 negatives):

| Signal | zero-FP best threshold | TPR at zero FP | note |
| --- | --- | --- | --- |
| phash@8 | 10 | 123/139 (0.885) | the 16 misses are exactly the 16 crop pairs (min 20) |
| phash@16 | 56 | 123/139 (0.885) | the 16 misses are the crop pairs (min 106); negatives start at 86 |
| ahash@8 | 15 | 125/139 (0.899) | catches two crop pairs, but four non-crop positives (censor 21/25, overlay 16/19) exceed the negative minimum 16 |
| dhash@8 | 16 | 124/139 (0.892) | crop min 16 vs negative min 20; overlays excellent (≤ 5) |

Excluding the two crop classes, **phash@8, phash@16, and dhash@8 separate the
remaining 123 positives from all 73 negatives with zero false positives**
(phash@8: non-crop max 10 vs negatives ≥ 20; phash@16: non-crop max 56 vs
negatives ≥ 86; dhash@8: non-crop max 7 vs negatives ≥ 20). **ahash@8 does
not**: four non-crop positives reach 16–25 while same-artist negatives reach
down to 16 — ahash trades crop tolerance for same-artist false positives, the
wrong trade under this corpus. The crop classes sit inside or at the edge of
the negative distribution for every whole-image signal measured, so no
threshold on these signals can propose crop relationships without false
positives.

## Findings (2026-10-21 extension)

- **Same-artist negatives do not collapse the margin.** 23 same-author,
  different-work pairs measure 20/32/42 at phash@8 — statistically
  indistinguishable from cross-artist negatives (22/32/40). The worry that
  stylistically similar works by one artist would crowd the positive band is
  not borne out *on this sample*; the clean separation now has same-artist
  evidence behind it, not an assumption. (Caveat: 23 pairs is still a modest
  sample, and same-author here means provider-attributed author of X posts.)
- **Crops are invisible to whole-image perceptual hashes.** A 60% center crop
  of the *same image* measures like an unrelated work (phash@8 20–30 vs
  negatives ≥ 20; corner crops worse). No threshold on any measured signal can
  propose crop relationships without drowning in false positives. Consequence:
  crop detection requires region- or feature-based methods — the named next research step —
  and until then, crops are reachable only through provider labels and exact bytes.
  Update 2026-10-24: the established library's segmentation-based crop-resistant hash
  does **not** separate crops on this corpus at any probed parameterization — see the
  [crop-resistant evaluation](matching-crop-resistant-evaluation.md); feature-based
  (opencv-class) methods remain the untested candidate.
- **Overlays and censorship are mild for phash.** Text overlays and black
  censor bars land at 4–10 — inside the existing positive band. dhash@8 is
  even tighter there (≤ 6). Color adjustment is nearly free (0–6).
- **Transcodes are invisible, as expected.** JPEG q95 and WebP q80 re-encodes
  measure 0–2 — re-encode chains pose no perceptual-hash problem.
- **No single signal dominates.** phash@8, phash@16, and dhash@8 all separate
  every non-crop class with zero false positives, each with different margins;
  ahash@8 is the only signal that reaches into the crop classes (catching two
  of sixteen) but is also the only one with non-crop false-positive overlap
  (censor/overlay pairs at 16–25 vs same-artist negatives down to 16). A
  generic mechanism should carry multiple signals as independent evidence
  rows, per the kernel stance — and should not adopt ahash for overlay
  tolerance on the belief that it is false-positive-free there.

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

- Sample: 139 positive and 73 negative pairs from one collection, a curated
  handful of example works, and programmatic transformations; margins are
  evidence, not guarantees.
- `same_artist_near_negative` now has 23 pairs, but the sample remains modest
  and deterministic — a larger, artist-stratified sample would strengthen the
  no-collapse finding.
- The transformation classes are *programmatic* transforms of real originals:
  ground truth by construction, but real-world crops/edits (artist-cropped
  reposts, partial-screen reposts, real censor variants) may differ in kind;
  curated real-world pairs remain unfetched.
- Crop-resistant (segmentation-based) hashing is now evaluated — negatively; see the
  [crop-resistant evaluation](matching-crop-resistant-evaluation.md). Feature-based
  (ORB/keypoint) methods remain unevaluated: they need an opencv-class dependency the
  research environment does not carry — a maintainer dependency decision.
- No animated/video frame-derived class exists yet.
- Group-3 candidate labels are unconfirmed; the distance structure is reported
  as measured.
- measure.py now reports declared-vs-measured pair counts per class, so a
  class silently vanishing (the failure that hid the first pass's empty
  same-artist class) is visible in every future report.
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
  small and partly mechanical (one provider's own re-encode pipeline), and the
  crop classes are unreachable for every whole-image signal measured.
- A future similarity mechanism should be generic (multiple metrics, taken
  from established libraries, compared against evidence like this), not a
  hardcoded threshold in a catalog surface.
- The same-artist measurement gap is closed for this sample: same-author
  different-work pairs do not crowd the positive band.
- Crop-derived variants are the hard boundary for whole-image hashes: a
  matcher that cannot see crops must not pretend to — crop proposals need a
  different signal family, and until one is measured, `cropped_from`
  relationships come only from provider declarations, review, or construction.
- Thumbnails measured visually identical to originals at phash@8, so any
  variant-family view must exclude them by variant role and dimensions, never
  by hash distance.
- The kernel Phase D schema half (Bead `data-processing-t08`) remains the
  consumer of this evidence when relationship types and review-gated
  conclusions are designed.

## Standing decision on multi-size hash storage (Bead `data-processing-yn1`)

phash@16's wider margin (positives <= 36, negatives >= 114) is a *matching-research* fact, not a
storage requirement. Per the maintainer framing (2026-10-05): hashes are identification metadata,
and storing an additional fingerprint size is a metadata decision that stands only on a concrete
consumer's usefulness. **No schema change is made now.** When a concrete metadata consumer needs
finer fingerprints, phash@16 lands as a **new fingerprint kind** (`FINGERPRINT_KINDS` gains a
value plus a migration — `asset_fingerprints` rows are identification facts keyed by kind and
algorithm version, and a new kind keeps each size's lineage explicit), never as a new "algorithm
version" of `phash` (which would blur the @8 legacy values already stored in `assets.phash` — see
the managed-vs-legacy caveat above). The matching-quality side remains open on qi7
(crop-resistant/feature-based evaluation), which this decision deliberately does not prejudice.
