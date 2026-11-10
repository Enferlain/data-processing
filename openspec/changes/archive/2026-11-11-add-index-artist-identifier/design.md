# Design: index-backed artist_identifier

## Context

`docs/plans/search-indexing-design.md` §3 (artist-identifier investigation) proposes
resolving a subject's stable account identity to provider artist entries. The e621
artists export (`artists.csv.gz`, verified real columns 2026-11-09:
`id, name, other_names{}, group_name, linked_user_id, is_active(t/f), is_locked,
creator_id, created_at, updated_at, active_urls, inactive_urls` — URL columns are
plain space-separated strings, not postgres arrays) makes this a local lookup.

## Decisions

### D1 — Separate projection and target name, not a merged projection

The posts projection's snapshot revision encodes the posts-artifact identity; merging
artist rows into it would either lie about freshness or force a posts re-import on every
artists refresh. Instead the artists import builds its own projection file registered as
its own target (`e621-artists`), with its own revision
(`<artists-digest-12>-e621-artists-export-v1-{scope}`). Attempts are recorded per target,
so refreshing artists never invalidates posts-index attempts and vice versa. Downloads
stay in the shared `e621/downloads/` directory; prune already keeps whatever any
registered projection references.

### D2 — Per-target capabilities instead of a format bump

The projection format stays `lookup-v1`: an artists projection is a lookup-v1 projection
whose post tables are empty and which adds `artist_entries`, `artist_names`, and
`artist_urls` tables plus an `index_meta.capabilities` key naming the methods it serves.
Existing post projections lack the key and resolve to the current method set, so nothing
re-imports and nothing invalidates. `lookup()` raises for methods outside the target's
capabilities exactly as it raises for unknown methods today.

### D3 — Index-method namespace, no LookupStrategy change

`artist_identifier` joins `INDEX_METHODS` as an index-only method string. The planner
sources its probe material from the existing `SOURCE_POST_URL` strategy values (post and
file seeds already resolve these; the seeds' source URLs are overwhelmingly artist
account pages on e621 posts). `LookupStrategy` and `LOOKUP_STRATEGY_VERSION` are
untouched — that bump is reserved for the provider-side strategy where it invalidates
provider attempts deliberately.

### D4 — Artist leads are a new table, not post hits

`discovery_index_hits` is post-shaped and feeds the fetch bridge; artist entries are not
posts. Hits from `artist_identifier` record into `discovery_artist_leads`
(session, provider, artist native id, name, other names, matched URL, active flag,
snapshot revision) — session-scoped leads, never facts, no fetch follow-up. Downstream
use (artist-tag post search from a lead) is a policy decision left to a later change.

### D5 — Both URL columns, canonicalized like source URLs

`active_urls` and `inactive_urls` split on whitespace; every token is canonicalized with
the same `canonicalize_url` used for post sources, so a subject's canonical probe URL
matches regardless of which side of the active/inactive split the artist entry lists it
under. The active flag rides the artist-entry row. Multi-URL jammed tokens cannot occur
here (whitespace-separated in the export), but tokens are still passed through the same
per-token URL extraction as the posts importer for consistency.

## Risks / trade-offs

- One more index target in every discovery plan (its unserved methods appear as excluded
  rows naming the capability reason; `artist_identifier` on post projections likewise
  excluded) — same decision-shape noise the artist rows already make on post indexes.
- Artists export has no artist→post mapping, so identifier→post resolution still needs a
  provider search later; this slice lands the identifier→artist-entry half.
