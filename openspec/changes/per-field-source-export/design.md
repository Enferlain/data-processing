## Context

`post_metadata_observations` retains, per post and observation, the engagement/availability
field set (score up/down/total, favorite count, comment count, three flags) with
`observed_at` and `raw_observation_id`; identical facts dedup by digest. The
current-projection policy is established: newer observation wins a mutable field, omissions
never erase. gh#6's training-data question — "which source supplied each important field,
what alternatives existed" — is a direct projection of this table.

## Goals / Non-Goals

**Goals:** one bounded kind exposing complete per-field value history with the stated
winner; ride the existing contracts untouched.

**Non-Goals:** no tag/name/attribution field sources (future), no as-of temporal views
(bead `2ai`), no writes anywhere.

## Decisions

### 1. One row per post, nested per-field history

Row: `{post_id, platform, native_post_id, fields: [{field, entries: [{value, observed_at,
raw_observation_id}], current: {value, observed_at, raw_observation_id}}]}`. Entries ordered
by (observed_at, observation id); `current` is the last entry — newest-observation-wins,
stated in the manifest's field-source policy as
`newest_observation_wins_per_field_all_values_retained`. Null-valued fields within an
observation are omitted from that observation's entries (an observation asserts only its
non-null fields; omission-never-erases is preserved by not asserting at all).

### 2. Field vocabulary fixed to the observation table

`score_up`, `score_down`, `score_total`, `favorite_count`, `comment_count`, `flag_deleted`,
`flag_pending`, `flag_flagged`. Booleans serialize as `true/false/null` in JSONL and strings
in CSV via the existing nested-JSON cell rule.

### 3. Exclusions

`no_retained_observations` (posts with zero rows in the table) and `excluded_by_limit`.
Ordering: post_id ascending; selection keys `post_id:platform:native_post_id` matching the
posts kind, so cross-kind selection digests stay comparable.

## Risks / Trade-offs

- [History-heavy rows for long-observed posts] → bounded by reality: observations arrive one
  per sync per post; the row limit guards breadth, entries stay small.
- [Null-in-observation semantics could read as erasure] → entries only assert non-null
  fields, so a later null is simply absent, never a deletion — matches the retention policy.

## Migration Plan

None.

## Open Questions

None blocking.
