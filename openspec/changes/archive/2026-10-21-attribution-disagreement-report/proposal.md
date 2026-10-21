## Why

The export-projection layer (Bead `data-processing-1oi`) still owes its second named
deliverable: the attribution-disagreement report — cases where two providers disagree on
artist attribution, drawn from retained evidence without overriding review decisions. The
Phase D relationship model (migration 0015) and the seeded/materialized `reposted_from` and
`same_work` links now supply the post linkage this report needed: a disagreement case is
precisely a linked post pair whose artist attributions no confirmed identity joins, i.e. the
human review worklist for attribution, not a verdict.

## What Changes

- Add an `attribution-disagreements` export projection kind to the existing framework: one
  row per linked post pair (retained post-level relationships: `reposted_from`,
  `same_work`, plus `variant_of`/`derived_from` post links if later materialized) where both
  ends carry artist-role attribution (account participants with artist/author roles, and
  provider attribution entities implied by the post's tags) and no cross-pair is joined by
  a confirmed identity membership.
- Each row lists both ends' attribution identities (platform, native identifier, primary
  name, review state, evidence pointer), the linking relationship (kind, epistemic status),
  and a `name_match` weak-evidence hint (exact casefolded primary-name equality) that is
  clearly evidence, never a conclusion. Rows carrying a confirmed identity join anywhere
  across the pair are excluded and counted with a reason.
- The report is offline, read-only, bounded with `excluded_by_limit` reporting, and rides
  the full manifest recipe (policies, digests, counts) unchanged. It never writes review
  decisions, candidates, or relationships.
- Per-field source exports (the other remaining 1oi slice) stay out and remain tracked.

## Capabilities

### New Capabilities

### Modified Capabilities

- `export-projections`: adds the `attribution-disagreements` projection kind and its
  selection/exclusion policies.

## Impact

- New `src/media_catalog/projections/attribution.py` kind module; registry and CLI choices
  gain the kind; no schema changes.
- Tests: disagreement detection over a seeded `reposted_from` link with unjoined
  attributions; exclusion when a confirmed identity joins the pair; `name_match` hinting;
  bounded limit reporting; digest reproduction; privacy allowlist conformance.
- Docs: guide export section gains the kind; changelog entry; bead 1oi notes updated.
