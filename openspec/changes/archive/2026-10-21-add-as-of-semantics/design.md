## Context

Every ingredient exists in the schema: `raw_observations.observed_at` (source observation
time, carried into normalized facts), provider-claimed `created_at`/`updated_at` columns,
`assets.verified_at` and adoption runs (acquisition), `remote_runs` with
`reprocess`-origin runs (interpretation — the 8c95810 fix made facts carry source time
while runs carry interpretation time), and decision ledgers (`review time`). gh#7 asks for
the vocabulary to be named and the semantics made explicit before projections harden around
latest-only assumptions. The guardrail is explicit: exploit retained history; do not build
an event-sourcing framework.

## Goals / Non-Goals

**Goals:** name the vocabulary; fix reconstruction rules; kernel requirement; manifest
evidence cutoffs everywhere; one real as-of surface (`post-field-sources`).

**Non-Goals:** no event-sourcing rebuild layer, no snapshot tables, no as-of on
current-column kinds (posts/assets/works read current columns; their as-of needs full
observation replay — tracked on the bead), no change reports or timelines (follow-on
surfaces), no schema changes.

## Decisions

### 1. Five timestamp kinds, mapped, not invented

| Kind | Meaning | Home columns |
| --- | --- | --- |
| source observation time | when the source report was observed | `raw_observations.observed_at`; every normalized fact written by a run carries it |
| provider-claimed time | what the provider asserts about the content | `posts.created_at`/`updated_at`, `attribution_snapshots` availability fields, declared `created_at` on captures |
| acquisition time | when bytes entered local custody | `assets.verified_at`, `adoption_runs`, `media_acquisition_runs` |
| interpretation time | when a normalizer produced facts | `remote_runs.started_at`/`finished_at` (reprocess-origin runs are pure interpretation) |
| review time | when a human decided | `*_candidate_decisions.decided_at`, `relationship_review_decisions.decided_at` |

The design doc carries this table plus the reconstruction rules; the kernel requirement
binds the distinction normatively.

### 2. As-of = filter by source observation time, re-resolve under the same policy

Reconstruction is not a new resolver: it is the existing newer-observation-wins policy
applied to the subset of facts with `observed_at <= cutoff`. Review state: latest decision
with `decided_at <= cutoff` (absence of any decision ≤ cutoff ⇒ the pre-decision state).
Relationship conclusions: row `created_at <= cutoff` with the latest status transition
`at <= cutoff` (birth status before any transition). Unavailable/deleted objects appear
through their availability observations (`availability` fields on observations), never by
absence — omission-never-erases already guarantees this; as-of reads it consistently.

### 3. Manifests gain `as_of`; cutoffs participate in the spec digest

`ProjectionSpec` gains an `as_of: str` field — `"all_retained"` default, or the explicit
cutoff timestamp. It participates in `spec_digest` (different cutoff ⇒ different recipe ⇒
different digest), which the export spec already promises. The manifest's generation
timestamp stays separate: generation is when the projection ran; `as_of` is what it
resolved against.

### 4. `--as-of` on post-field-sources only, stated for the others

`field_sources.build` gains the cutoff parameter and filters observations before history
construction. The other kinds ignore `--as-of` — the CLI refuses the combination for kinds
without as-of semantics rather than silently accepting an ignored flag; their manifests
state `as_of: all_retained` (which is accurate: current-column kinds resolve against all
retained observations by construction of the current-projection policy).

## Risks / Trade-offs

- [String timestamp comparison] — stored timestamps mix whole-second and fractional
  precision, and lexicographic text comparison misplaces fractional seconds inside a
  whole-second cutoff (`.` sorts before `Z`); as-of comparisons therefore parse both sides
  (julianday over `Z`-stripped values) and cutoff inputs are calendar-validated on parse
  (review finding, folded in pre-commit).
- [As-of on current-column kinds would mislead if silently accepted] — refusing the flag
  per kind keeps the manifest honest.
- [Reconstruction depends on facts carrying source time] — true since 8c95810; the known
  pre-fix reprocess rows (quantified in the 2026-10-16 audit) are retained history of what
  the replay did and are excluded from no reconstruction — as-of reads them as the
  observations they claim to be, with their interpretation runs naming the replay.

## Migration Plan

None.

## Open Questions

None blocking.
