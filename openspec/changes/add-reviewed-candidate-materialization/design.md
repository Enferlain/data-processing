## Context

Migration 0015 and the `relationships` service (commit a5a5ffa) provide the conclusion
objects; migration 0002/0007 provide the candidate machinery (`post_match_candidates` with
`relation_kind` ∈ sourced_from/same_work/repost_of/variant_of/derived_from/unresolved,
`current_state` pending/confirmed/rejected, `post_candidate_evidence` joining generic
`match_evidence`). The gap is the operator bridge. Account candidates (`same_identity`,
`officialally_linked`) are identity-membership conclusions with their own resolved machinery
and stay out of scope.

## Goals / Non-Goals

**Goals:**

- One explicit offline command: `catalog relationships materialize <catalog> [--candidate
  post:<id>] [--json]` — a single candidate or all confirmed ones.
- Full evidence carry-over, decision-row provenance, idempotency via the deterministic
  relationship key.

**Non-Goals:**

- No schema change; no automatic materialization from any score, lookup, or sync; no
  account candidates; no deletion or rewriting of candidates or their decisions.

## Decisions

### 1. Fixed kind mapping, two endpoint altitudes

| Candidate kind | Relationship | Endpoints | Orientation |
| --- | --- | --- | --- |
| `sourced_from` | `reposted_from` | post ↔ post | subject = citing post, target = declared source |
| `repost_of` | `reposted_from` | post ↔ post | subject = repost, target = origin |
| `same_work` | `same_work` | work ↔ work | symmetric (canonical order via key) |
| `variant_of` | `variant_of` | work ↔ work | derivative → origin per candidate direction |
| `derived_from` | `derived_from` | work ↔ work | derivative → origin per candidate direction |
| `unresolved` | — | — | refused: `unresolved_relation_kind` |

`sourced_from` and `repost_of` both mean "the subject declares the target as where the
content came from", so both map to `reposted_from` — the single Phase D kind for that
semantic. Work-level kinds resolve each post's anchor through `works.origin_post_id`;
missing anchor → refusal `work_anchor_missing` (operator runs `works materialize` first —
materialization never creates anchors implicitly, keeping the command single-purpose).

Direction for `variant_of`/`derived_from` comes from the candidate's own subject/target
orientation (subject is the derivative). `same_work` relies on the record layer's canonical
symmetric ordering, so either input order yields the same key.

### 2. Target resolution rule

A candidate is materializable only when `target_post_id` is not NULL (the reference kind
with only `target_reference_id` describes a post the catalog has not recorded — a
relationship endpoint must be a catalog object; that bridge is future discovery work).
Refusal reason: `target_reference_unresolved`.

### 3. Provenance: decision row, not a new column

The materialized relationship is inserted with `epistemic_status = 'reviewed'`,
`review_state = 'pending'`, then immediately `record_relationship_review('confirmed', note
= "materialized from confirmed candidate post:<id>")` runs in the same transaction: the
decision ledger carries the source, review state becomes `confirmed`, and no status
transition is appended (birth status is already `reviewed`). This reuses the Phase D
lifecycle exactly as designed — no new columns, no candidate-side writes.

### 4. Idempotency and evidence top-up

The relationship key dedups the row. Re-materialization still walks the candidate's
evidence and attaches any link missing (evidence attach is conflict-ignored), but the
decision row is written only when the relationship insert was new — an existing
relationship means its provenance decision already exists. Counts distinguish
`materialized` / `existing` / refused-with-reason, mirroring the seeder's reporting shape.

## Risks / Trade-offs

- [A candidate confirmed long ago may have grown evidence since] → materialization
  re-runs attach the new evidence (top-up), and the relationship's identity is unchanged —
  evidence growth never requires a new conclusion row.
- [Two candidates asserting contradictory directions] → both materialize as separate
  directional rows; contradiction is visible in the relationship set and resolved by
  review, never by silent overwrite (consistent with the evidence-layer stance).
- [Work-level kinds depend on anchors existing] → refusal reason names the fix
  explicitly rather than cascading commands the operator did not ask for.

## Migration Plan

None; purely additive over migration 0015.

## Open Questions

None blocking.
