# Crop-resistant hashing evaluation: negative result (research note)

Status: measured 2026-10-24 (Bead `data-processing-qi7` remaining scope)
Related: [matching spike evidence](matching-spike-evidence.md) — this note extends its crop-blindness
consequence with the named next candidate.

The 2026-10-21 extension established that whole-image signals (phash@8/@16, ahash@8, dhash@8) are
crop-blind on this corpus: crop variants land inside (or at the edge of) the negative
distribution — ahash@8 reaches two of sixteen crops only via non-crop false-positive overlap. The named next
candidate was region/feature-based methods, starting with the established library's own
`imagehash.crop_resistant_hash` (segmentation + per-segment dhash@8; imagehash 4.3.2). This note
records the measurement.

## Measurement

Same harness, same fixtures (239 files, 212 pairs): the sweep gained a
`crop_resistant_distance` column — the symmetric ImageMultiHash region-matching distance
(0 = same; bounded by segment counts, which are small on this corpus: median 4–5 segments for
single-illustration posts, 8 for multi-region gelbooru posts). Parameter sensitivity was probed over six configurations
over `segment_threshold` (128/64/32), `min_segment_size` (500/100), and
`segmentation_image_size` (300/800), compared as crop-max vs negative-min separation (an ad-hoc parameterized run of the
library, not a committed harness mode; the configurations and metric are recorded for
reproduction).

## Result: no separation, at any probed parameterization

- **Crops sit inside the negatives under library defaults**: crop classes distance 1.1–9.0
  (p50 ≈ 4.5) against cross-artist negatives 2–11 (p50 6) and same-artist negatives 3–13
  (p50 7). The zero-false-positive threshold is 1.094 — it rejects 15 of 16 crop pairs.
- Parameterization does not rescue it — every probed configuration leaves crop maxima at or
  above negative minima (crop classes vs cross-artist + same-artist negatives, distance ranges):

  | Configuration | Crops | Negatives | Verdict |
  | --- | --- | --- | --- |
  | defaults | 1.09–9.0 | 2.0–13.0 | overlap |
  | segment_threshold=64 | 1.0–8.0 | 1.0–10.0 | overlap |
  | segment_threshold=32 | 1.0–8.0 | 1.0–9.0 | overlap |
  | min_segment_size=100 | 2.0–19.1 | 2.0–23.0 | overlap |
  | segmentation_image_size=800 | 3.0–24.1 | 3.0–38.0 | overlap |
  | threshold=32 + size=800 | 1.0–16.3 | 1.0–30.0 | overlap |
- The easy classes stay easy and cheap (transcodes 0.0–1.0, previews/samples 0.0–1.0,
  x-variants p50 0.01) — region matching confirms what exact and whole-image hashes already
  prove, at higher compute cost; it adds nothing where it was needed.

**Why it fails here:** region matching depends on meaningful segmentation. Illustration-style
images yield few, coarse, composition-scale segments; a crop re-frames the composition, so the
segments themselves change. The method's design cases (photos with many small regions) are not
this corpus.

## Consequence

Two families are now eliminated on this corpus for crop detection: whole-image hashing and
established-library region matching (segmentation-based). The remaining named candidates are
feature-based methods (SIFT/ORB-class keypoints), which require a dependency the research
environment does not carry (opencv-class) — a dependency decision for the maintainer — or a
custom tile-subset method, which the bead's standing rule defers until established options are
exhausted (they now are, within the current dependency set). Crop proposals therefore remain
**not available** to any product surface; the evidence stays research-only per the standing
constraint.
