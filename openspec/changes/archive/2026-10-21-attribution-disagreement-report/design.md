## Context

Attribution lives on two surfaces: account-side (`post_participants`, roles include
`artist`/`author`, with review states) and provider-side (a post's `post_tags` →
`attribution_tag_links` → `attribution_entities` with `attribution_names`). Confirmed
identity joins exist only between accounts (`identities`/`identity_accounts`); provider
attribution entities have no join machinery, so any cross-provider comparison is unjoined
until a human confirms — which is exactly the report's purpose. Post linkage comes from the
Phase D `relationships` table: `reposted_from` seeds today from provider source URLs;
`same_work` arrives through reviewed candidates (zaf pipeline).

## Goals / Non-Goals

**Goals:** one bounded, offline, report-only export kind over linked-post attribution
conflicts; ride the existing manifest/digest contract untouched.

**Non-Goals:** no per-field source exports (remaining 1oi slice), no new join machinery for
attribution entities, no candidate or relationship writes, no fuzzy name matching beyond
exact casefolded equality as a marked hint.

## Decisions

### 1. Disagreement = linked pair, both ends attributed, zero confirmed joins

For each post-level relationship row (`relation_kind IN ('reposted_from','same_work')`,
both ends `post` kind, not `rejected` review state): gather each end's attribution
identities — participants (`role IN ('artist','author')`) as `participant` identities
(platform, account native id, review state) and tag-implied attribution entities as
`attribution_entity` identities (platform, provider id, primary name). A pair is a
disagreement row iff both ends have ≥1 identity AND no account↔account cross-pair is joined
by a confirmed identity (attribution entities never join — they are inherently unjoined
sides). Exclusion reasons: `attribution_missing_on_end`, `confirmed_identity_join`,
`rejected_relationship`, `excluded_by_limit`.

### 2. One row per relationship, not per identity pair

A linked pair with three unjoined identities on one side and two on the other is ONE review
case, not six. The row nests both ends' identity lists; the reviewer opens the worklist, not
a cross-product.

### 3. `name_match` is a hint field, computed, stated

Exact casefolded equality between any primary names across the ends → `name_match: true`.
The manifest's field-source policy names it weak evidence that never establishes identity
(the kernel stance); it sorts nothing and concludes nothing.

### 4. Policies in the manifest

`selection: linked_post_pairs_with_attributed_ends`, `ordering: relationship_id ascending`,
`dedup: one_row_per_relationship`, `preferred_representation: not_applicable`,
`field_source: participants_and_tag_implied_attribution_with_name_hint`, `url_handling:
no_urls_emitted`. Same six slots, same digest layers — no framework changes.

## Risks / Trade-offs

- [Sparse data until the matcher pipeline fills same_work] → `reposted_from` seeding gives
  the report real cases today; the kind silently grows as reviews land.
- [Tag-implied attribution can misfire on generic tags] → only tags with
  `attribution_tag_links` rows count (provider-asserted artist tags), not any tag.
- [Row count grows with identity lists] → identity lists are bounded by what providers
  assert per post; the limit guards the row count, not list lengths (lists stay small in
  practice).

## Migration Plan

None.

## Open Questions

None blocking.
