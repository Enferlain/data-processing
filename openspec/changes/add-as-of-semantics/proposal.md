## Why

The evidence layer retains everything temporal questions need — append-only source reports
with `observed_at`, provider-reported timestamps, acquisition facts, reprocessing runs,
and append-only review decisions — but the capability is unnamed and undesigned, and
current projections quietly assume "latest" is the only state that matters (gh#7). The
reprocess work (8c95810) already forced one distinction into code: facts carry source
observation time while runs carry reprocessing time. This change names the full vocabulary,
fixes the as-of reconstruction semantics, and delivers the first concrete surfaces.

## What Changes

- Name the five timestamp kinds in a tracked design doc and map each to its existing
  columns: **source observation time** (`raw_observations.observed_at`, carried by every
  normalized fact), **provider-claimed time** (`posts.created_at`/`updated_at` and kin —
  what the provider says, not when we saw it), **acquisition time** (`assets.verified_at`,
  import/adoption run times — when bytes entered local custody), **interpretation time**
  (`remote_runs` including `reprocess`-origin runs — when a normalizer produced facts), and
  **review time** (decision ledgers' `decided_at`).
- Define **as-of reconstruction**: knowledge at cutoff `t` = every retained fact whose
  source observation time ≤ `t`, resolved under the same newer-observation-wins policy
  restricted to that set; review state at `t` = latest decision with `decided_at` ≤ `t`;
  relationship conclusions at `t` = rows created ≤ `t` under their latest recorded
  transition ≤ `t`. No history is rewritten; nothing is special-cased; deleted/unavailable
  objects appear through their availability observations, never by absence.
- Add a **kernel spec requirement** (`provenance-kernel` capability): temporal as-of
  reconstruction from retained history, with the timestamp vocabulary as the named
  distinction.
- **Export manifests record their evidence cutoff**: every projection manifest gains an
  `as_of` field (default: the generation timestamp's meaning made explicit — "all retained
  observations" — or an explicit operator cutoff), so a historical build can later be
  explained or rebuilt.
- First surface: **`--as-of` on the `post-field-sources` projection** — entries restricted
  to observations with `observed_at ≤ t`, current values re-resolved under the cutoff. The
  other kinds keep latest-only behavior with the manifest stating so; as-of support per
  kind arrives as each kind's semantics warrant it.
- Later surfaces (tracked on the bead, not here): as-of on current-column projections
  (needs full observation replay rather than current columns), change reports between two
  cutoffs, historical disagreement reports, provenance timelines.

## Capabilities

### New Capabilities

### Modified Capabilities

- `provenance-kernel`: adds the temporal as-of reconstruction requirement.
- `export-projections`: manifests record the evidence cutoff; `post-field-sources` gains
  the as-of parameter.

## Impact

- `src/media_catalog/projections/` (spec object gains `as_of`; `field_sources.build`
  filters by cutoff; service/CLI parameter plumbing) — no schema changes, no new tables.
- New `docs/plans/temporal-semantics.md` design doc (the timestamp vocabulary table and
  reconstruction rules).
- Tests: manifest carries `as_of` for all kinds; field-sources as-of resolves current
  values under the cutoff; cutoff later than all observations equals the uncutoff run's
  values; cutoff before all observations yields empty histories.
