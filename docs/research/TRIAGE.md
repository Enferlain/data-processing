# Research triage: docs/research/ (2026-11-14)

Three research documents were triaged against the repo's current capabilities
(readers: one agent per document, November 2026 session). This file records
the consensus: what is already covered, what became actionable items (beads
filed, referenced below), and what was rejected.

## 2D Artwork Near-Duplicate Detection

Thesis: no single similarity representation survives recompression, resizing,
cropping, and overlays at catalog scale; deploy a staged funnel (exact →
256-bit hash → dense embeddings → human triage) with persistent relationship
state, never a single cutoff.

- **Already covered**: exact dedup (verified md5/sha256 in `asset_fingerprints`,
  `identical_md5` auto-same 59/59); URL canonicalization (www-fold, x-status
  normalization).
- **Actionable (filed)**: DINOv2-S (ViT-S/16 + registers, Apache-2.0) as the
  crop-resistant channel — ONNX, ~45 ms/image CPU, 384-d vector or 48-bit
  binarization in `asset_fingerprints`; measured 91% Recall@1 on 70%-side
  crops where PDQ scores 0% (photo benchmarks; needs our own calibration on
  the `same_artist_*` negatives). Border-trim canonicalization before hashing
  (uniform-margin auto-crop; Hydrus precedent; the doc quantifies
  border-collision false positives). The existing iqdb-v1 design note (§4)
  should prefer a 256-bit PDQ-style DCT hash over 64-bit (≈12 orders of
  magnitude more FP headroom) in a VP-tree — serves re-encodes only; crops
  belong to the embedding channel.
- **Rejected**: SSCD/RDCD copy descriptors (non-commercial licenses, reject
  WIP progressions); naive classical tile hashing (FP explosion at scale).

## Abstention-First Entity Resolution

Thesis: false merges cost more than missed matches; possible-match,
unlinkable, and explicit-exclusion are first-class outcomes; correlated
evidence must be compounded, not summed; thresholds need calibration, not
intuition.

- **Already covered**: append-only decision ledger (pair_labels); explicit
  verdicts (no Enter-to-unsure); leads never facts.
- **Actionable (filed)**: a random audit stream sampling pairs BELOW the
  enqueue thresholds (plus a slice of auto-confirmed pairs) — the only way to
  bound error for `autoconfirm_identical_md5_pairs` (59/59 ⇒ point precision
  1.0 but rule-of-three 95% upper bound ≈5% false-same); per-family
  calibrated priors (n<100 → empirical rate + CI, Platt-style; Beta at
  100–200+) folded into the versioned candidate-scoring policy, with
  `same_artist_*` as a NEGATIVE-weight feature (96–100% different — artist
  name agreement alone is evidence against same-work); reviewer blinding to
  aggregate scores at verdict time (keep facts, hide probabilities); richer
  disambiguating context per queue item (both source URLs, resolved artist
  entries/aliases from artist_identifier leads, parent chains, timestamps).
- **Rejected**: EM/posterior auto-merge gates (miscalibration risk); global
  1-to-1 constraints (our sources are dirty mirrors, not clean registries).

## Bitemporal Provenance Schemas in SQLite

Thesis: model evolving knowledge as an append-only observation log with
valid-time and system-time; omit `system_to` and derive current state by
reverse playback with early termination; keep "now" reads on a narrow
projection.

- **Already covered**: `observation_revisions` IS the append-only revision
  log; `posts.first_seen_at/last_seen_at` are system-time projections with a
  single serialized writer; the attempt ledger already records scoped
  negative knowledge.
- **Actionable (filed / folded into 2ai)**: as-of queries need NO schema
  change — reverse playback `ORDER BY observation_revision_id DESC LIMIT 1`
  with `import_run_id <= :R` bounds, backed by a covering index
  `(observation_id, observation_revision_id DESC)`; the as-of attempt query
  per ledger key answers "as of T, had we searched and found nothing?" for
  the unresolved-subject classes; append-only enforcement triggers
  (`BEFORE UPDATE/DELETE … RAISE(ABORT)`) on `raw_observations` and
  `observation_revisions` — insert-only tables, closing the
  convention-vs-enforced gap; index-planner hygiene (keep `IS NULL OR …`
  out of hot temporal predicates; verify with EXPLAIN QUERY PLAN).
- **Rejected**: full witness-group provenance semirings (complexity not
  justified at current scale); `current_claims` trigger projections (our
  projection volume is small and importer-serialized); R*Tree timestamp
  indexing (no spatial access pattern needs it).

## Filed beads

See `bd list` for current state; created from this triage:

- dinov2 embedding fingerprint channel (crop-resistant near-duplicate;
  consumes the `same_artist_*` negatives for calibration; serves the 26
  unresolved subjects)
- random audit stream below enqueue thresholds (calibration identifiability
  for auto-confirm and future thresholds)
- per-family calibrated priors + negative-weight artist feature in the
  versioned scoring policy
- label-UI reviewer blinding + disambiguation context bundling
- append-only enforcement triggers + as-of covering index (2ai
  implementation guidance)
