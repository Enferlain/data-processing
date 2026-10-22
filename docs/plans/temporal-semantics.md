# Temporal semantics: what was known when

Status: accepted direction (2026-10-21; OpenSpec change `add-as-of-semantics`)
Related: [provenance kernel plan](provenance-kernel.md), [matching spike evidence](matching-spike-evidence.md),
the [reprocessing contract](../../openspec/specs/remote-metadata-sync/spec.md), GitHub issue #7.

The evidence layer retains append-only source reports, provenance-event revisions, immutable
run inputs, and append-only review decisions — everything temporal questions need. This
document names the timestamp vocabulary, fixes the as-of reconstruction rules, and lists the
surfaces. Guardrail (gh#7): exploit retained history; do not turn the core into an
event-sourcing framework for its own sake.

## The five timestamp kinds

| Kind | Meaning | Home columns |
| --- | --- | --- |
| **Source observation time** | when a source report was observed — the anchor for as-of reconstruction | `raw_observations.observed_at`; every normalized fact written by a run carries it (replayed facts keep the original observation time; interpretation time lives on the run) |
| **Provider-claimed time** | what the provider asserts about the content, independent of when we saw it | `posts.created_at` / `posts.updated_at`, declared `created_at` on retained captures, availability fields inside source reports |
| **Acquisition time** | when bytes entered local custody | `assets.verified_at`, `adoption_runs`, `media_acquisition_runs` |
| **Interpretation time** | when a normalizer produced facts from a source report | `remote_runs.started_at` / `finished_at`; `reprocess`-origin runs are pure interpretation |
| **Review time** | when a human decided | `*_candidate_decisions.decided_at`, `relationship_review_decisions.decided_at` |

The rule behind the table: **facts are dated by their source observation; processes are
dated by their run; decisions are dated by their ledger entry.** The 2026-10-16 reprocessing
fix (8c95810) made this exact in code — a replayed fact carries the original observation
time while the reprocess run records when the interpretation happened.

## As-of reconstruction

Knowledge at cutoff `t` is reconstructed from retained history alone:

- **Field values**: every retained fact with source observation time ≤ `t`, resolved under
  the stated projection policy (newer observation wins a mutable field) restricted to that
  set. No historical row is read differently, rewritten, or special-cased.
- **Review state**: the latest decision with `decided_at` ≤ `t`; no decision ≤ `t` means
  the pre-decision state. Both sides of a reversed decision remain retained.
- **Relationship conclusions**: rows created ≤ `t`, at their latest recorded status
  transition ≤ `t` (the birth status before any transition).
- **Deleted, unavailable, moved, renamed, or later-corrected objects** appear through
  their retained availability/name observations, never by absence — the
  omission-never-erases policy already guarantees the history is there; as-of reads it
  consistently. A timeline shows an object becoming unavailable, not disappearing.

## Surfaces

Landed with this change:

- Every export manifest records its **evidence cutoff** (`as_of`): the explicit operator
  cutoff, or `all_retained` when none was given. The cutoff participates in the projection
  specification digest — different cutoffs are different recipes.
- The `post-field-sources` projection accepts **`--as-of`**: histories restricted to
  observations ≤ `t`, current values re-resolved within the restricted set.

Follow-on surfaces (tracked on Bead `data-processing-2ai`):

- as-of on current-column projections (posts/assets/works read current columns; their
  as-of needs full observation replay, not column reads);
- review-state and relationship-conclusion reconstruction as of a cutoff (the kernel
  requirement states it; decision ledgers and status history are latest-only today);
- change reports between two evidence cutoffs;
- historical disagreement reports (the attribution worklist as it looked at `t`);
- provenance timelines for debugging why a current projection changed.

## Caveats

- Reconstruction trusts facts' claimed observation times. The known pre-fix reprocess rows
  (quantified in the 2026-10-16 audit, bd memory `reprocess-replay-stamp-damage-2026-10-08`)
  carry replay wall-clock times; as-of reads them as the observations they claim to be,
  while their interpretation runs name the replay. Rows are immutable history either way.
- Timestamp comparisons in as-of surfaces parse both sides rather than comparing text:
  stored timestamps mix whole-second and fractional-second precision, and lexicographic
  comparison would misplace a fractional second inside a whole-second cutoff (`.` sorts
  before `Z`). Cutoff inputs are calendar-validated on parse.
