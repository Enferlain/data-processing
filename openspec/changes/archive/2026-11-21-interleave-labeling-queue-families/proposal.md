# Proposal

## What

`build_queue` currently concatenates signal families in fixed order
(A1 identical_md5 → … → pool_member → … → same_artist_contrast) and takes the
head of that list as the session queue. When one family dominates — today
`pool_member` holds 7,762 unlabeled pairs, 87% from three large pools — the
operator faces a long single-signal run. Change assembly to round-robin:
one pair per family per rotation, families in their existing priority order
and original pair order within a family, until the session limit.

## Why

Operator report and decision (2026-11-21, beads `data-processing-763` /
`data-processing-xm9`): back-to-back pairs from one 90-member pool make the
labeling session monotonous and waste attention on the weakest prior at the
head of the queue. Interleaving keeps full enumeration but mixes signal
families within every session, so stronger families' pairs surface
immediately instead of after thousands of pool pairs.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `labeling`: new requirement covering family-interleaved queue assembly.

## Impact

- `src/media_catalog/labeling/queue.py` (`build_queue` normal mode; the
  shared `add()` helper gains per-family buckets; final assembly
  round-robins buckets).
- Unchanged: cross-family pair dedup (first family claims a pair),
  media-usable filtering, `skipped_count`, `revisit_unsure` mode, per-family
  pair order, family priority order, the `pair_labels` exclusion.
- Tests: pin interleaved assembly; existing family/detail tests keep passing
  (they assert membership and details, not block ordering).
