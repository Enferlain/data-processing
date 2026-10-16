## Why

The 2026-10-16 audit of the real catalog found the provider-observed `parent_of` relation
actively written (danbooru `parent_id`/`has_children` normalization lands in
`post_relations`) while the deterministic seeder materializes only `same_bytes`,
`thumbnail_of`, and `reposted_from` — so the typed relationship model has a live gap: a
kind the decision table promises as `observed` (provider) that nothing produces. Pre-approved
by the maintainer as a small seeder extension alongside the audit.

## What Changes

- Extend `seed_relationships` to materialize `parent_of` relationships from retained
  `post_relations` rows whose relation type is `parent_of`: post↔post, `observed` status,
  evidence citing the provider parent declaration (detector `provider-parent-relation`,
  linked to the raw observation the relation came from).
- `quote` and `reply` relations stay in `post_relations` deliberately: they are
  provider/import discourse facts without Phase D kinds; the boundary is named here and left
  for a future vocabulary decision (tracked separately).
- Idempotent via the deterministic relationship key; self-links and relations without a
  recorded raw observation still materialize (the provider declaration is the evidence) but
  are reported with typed skip reasons where endpoints are unusable.

## Capabilities

### New Capabilities

### Modified Capabilities

- `work-relationships`: the deterministic-seeding requirement gains the `parent_of` kind.

## Impact

- `src/media_catalog/relationships/seed.py` (one additional seed pass); tests extend the
  existing seeding fixture with a `post_relations` row; guide and changelog updated. No
  schema changes.
