# qi7 image-hash study: czkawka method set (2026-11-05)

## Question

Can perceptual hashing connect "same image, slight variation" without
admitting same-artist lookalikes? Ground truth: the four-post d-rex corpus
(operator-confirmed 2026-11-04) — three distinct files (md5 `761b6db8…`
gelbooru 11165341 = e621 5486288 byte-identical; `6e1d0ba8…` gelbooru
11254040; `21780869…` gelbooru 11254042, the Discord pair), all 797×1200,
all the same artwork with slight variation. Negatives: five other d-rex
works from e621 (6818884, 6741871, 6660303, 6657520, 6657501) — same artist,
different drawings.

## Methods (czkawka / image_hasher set, pure PIL)

mean (aHash), gradient (dHash), vertgradient, doublegradient, blockhash,
median — at grid sizes 8/16/32 (64/128/256 bits). Distances are normalized
Hamming over all 36 pairwise combinations of 9 images. Caveat:
doublegradient is our two-half interpretation of image_hasher's variant,
not a port.

## Results (positives min/mean/max vs negatives min/mean/max)

| method | size 8 | size 16 | size 32 |
|---|---|---|---|
| mean | 0/0/0 vs 12.5/43.0/71.9 | 0/0/0 vs 15.6/45.5/59.0 | 0/0.2/0.4 vs 15.7/44.9/56.1 |
| median | 0/0/0 vs 15.6/42.7/71.9 | 0/0.2/0.4 vs 18.8/45.3/60.5 | 0/0.2/0.3 vs 21.8/45.8/57.2 |
| gradient | 0/0/0 vs 20.3/49.3/65.6 | 0/0.6/1.2 vs 26.2/49.0/56.6 | 0/1.1/1.7 vs 29.1/49.7/54.8 |
| vertgradient | 0/0/0 vs 29.7/47.8/59.4 | 0/0.2/0.4 vs 25.8/48.1/54.7 | 0/0.6/1.0 vs 25.7/49.0/51.6 |
| doublegradient | 0/0/0 vs 26.6/49.3/59.4 | 0/0/0 vs 24.2/49.2/54.7 | 0/0.3/0.5 vs 26.7/49.8/53.4 |
| blockhash | 0/2.1/3.1 vs 15.6/44.2/68.8 | 0/0.5/0.8 vs 19.5/44.9/60.9 | 0/0.2/0.4 vs 21.7/45.8/56.6 |

Every method×size separates cleanly; the worst positive (blockhash@8,
3.1%) is four points under the best negative (mean@8, 12.5%). Identical
bytes trivially distance 0; the *variant* pairs — the actual signal — stay
at or under 1.7% everywhere except blockhash@8.

## Verdict

- **All six czkawka methods pass on this corpus.** The "slight variation"
  the operator described (re-encode + small edits at identical resolution)
  is invisible to every hash; same-artist different-drawing is always far.
- **Recommended primary: gradient (dHash) at 16** — positives ≤1.2%,
  negatives ≥26.2%, 128 bits (16 bytes), one LANCZOS resize, robust to
  mean-shift. Threshold: **10%** normalized Hamming (midpoint of the gap,
  generous to real-world transforms).
- **Recommended prefilter: mean@8** (64-bit) if storage/compute ever matters;
  it separates at 6–8%.

## Honest limits

1. **Corpus size**: 9 images, 1 artist, 36 pairs. The negative floor needs
   a wider sweep (more artists, more styles) before any threshold is load
   bearing. This study validates the method family, not the final threshold.
2. **Transform hardness untested**: the variants here share resolution and
   composition. Crops, rotations, watermarks, and aspect changes are where
   these methods historically degrade — the corpus has none.
3. **Same-artist negatives**: five samples did not produce a single
   near-miss, which is encouraging but weak; the "same-artist negatives"
   risk in qi7's title needs a 100+ image sweep to characterize.

## Next steps (gated)

1. Widen the corpus (more d-rex + other artists; include crops/edits if the
   operator can supply known variants) and re-run the sweep — the script is
   a throwaway; the note is the artifact.
2. If separation holds: design fingerprint storage (computed at adoption
   and post-fetch verification; asset-level, method+size versioned) and a
   `perceptual_hash` match strategy as a new evidence kind — adapter-scale
   OpenSpec change.
3. Text-metadata similarity (artist names, tag lists) stays a separate
   text-native phase per the operator's scope decision.

## Operator data notes

- The artist is tagged **d-rex** on e621/danbooru/gelbooru (e621 artist id
  24584); `d_rex_too` is an X handle, confirmed as an alias on the d-rex
  attribution entity (fetched 2026-11-05 — the alias bridge is machine-proven).
  e621's artist record lists twitter `D_rex_art`; the posts' `d_rex_too`
  source account is a further identity question, not settled here.
- Gelbooru's CDN requires browser Referer/UA for originals (anonymous
  default-UA fetches return the post page HTML) — relevant to bead
  `data-processing-3xv` (gelbooru media policy).
- Attribution URL links did not materialize into `account_external_links`
  (0 rows) — the link pass recognized 3,193 links but artist-record URLs
  need an account to attach to; noted as an identity-flow gap.
