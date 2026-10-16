## Why

Phase D landed relationship rows as durable conclusion objects and left the candidate
machinery unchanged: a human can confirm a post candidate (`sourced_from`, `same_work`,
`repost_of`, `variant_of`, `derived_from`) in the match-review ledger, but that reviewed
conclusion never becomes a queryable relationship — the operator has nowhere to carry it
across. The `add-work-relationship-model` design named this operator step as the deliberate
follow-up (Bead `data-processing-zaf`), and it is the missing link between the existing
candidate/review workflow and the relationship model.

## What Changes

- Add `catalog relationships materialize`: an explicit, offline, idempotent operator command
  that turns **confirmed** post candidates into relationship rows with `reviewed` epistemic
  status, citing the candidate's entire evidence bundle through `relationship_evidence`.
- Map candidate relation kinds onto the Phase D vocabulary with a stated, fixed mapping:
  post-level kinds materialize post↔post relationships (`sourced_from` and `repost_of` →
  `reposted_from`, subject = the post declaring the other as source), work-level kinds
  materialize work↔work relationships through the posts' deterministic work anchors
  (`same_work` → `same_work`, `variant_of` → `variant_of`, `derived_from` → `derived_from`).
- Refuse with typed reasons, never silently skip: candidates not confirmed, `unresolved`
  relation kind, target reference not resolved to a catalog post, or (for work-level kinds) a
  post without a materialized work anchor.
- Record provenance: each materialized relationship carries a review decision row naming the
  candidate it came from; re-materialization attaches missing evidence but never duplicates
  the relationship (deterministic relationship key).
- Nothing materializes automatically: unconfirmed candidates, matcher scores, and lookups
  never create relationships on their own.

## Capabilities

### New Capabilities

### Modified Capabilities

- `work-relationships`: adds the requirement that reviewed candidates materialize into
  relationships — the operator bridge from the candidate/review ledger into the relationship
  model, with kind mapping, refusal reasons, and evidence carry-over.

## Impact

- New service module in `src/media_catalog/relationships/` (candidate materialization) and a
  `materialize` subcommand on `catalog relationships`; no schema changes — migration 0015
  already carries every table this needs.
- Tests: confirmed candidate → exactly one `reviewed` relationship with the candidate's
  evidence attached and a decision row citing the candidate; idempotent re-run; pending,
  rejected, unresolved-kind, unresolved-target, and missing-anchor refusals with reasons;
  account candidates are out of scope and never touched.
