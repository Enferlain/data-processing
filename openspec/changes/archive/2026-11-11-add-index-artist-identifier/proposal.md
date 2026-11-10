## Proposal

Add an offline, index-backed `artist_identifier` discovery method: import the e621
artists DB export (`artists.csv.gz`, ~7.7 MB daily) into a lookup projection registered
as its own index target (`e621-artists`), and resolve a subject's known source URLs to
e621 artist entries (name, other names, linked URLs, active flag) recorded as
session-scoped artist leads.

## Why

Artist search today is name-based (`artist_exact_name`/`alias`/`text`), which fails on
renames and aliases. Identifier-based resolution — the artist's stable account/page URL,
already present on most seeds as source material — is much stronger. The e621 artists
export makes identifier→artist-entry resolution a local, offline lookup (the design note's
`docs/plans/search-indexing-design.md` §3) with no provider API request and no
`LOOKUP_STRATEGY_VERSION` bump (that bump belongs to the later provider-side
`artist_identifier` strategy, explicitly out of scope here).

## What Changes

- `catalog index import --provider e621 --export artists [--download]` builds an
  artist-entry projection (default target name `e621-artists`, default path
  `<catalog-stem>-indexes/e621-artists/lookup.sqlite`); the raw export is retained under
  the provider's downloads directory like the posts export.
- lookup-v1 projections gain per-target capabilities: `index_meta` records which methods
  the projection serves (post projections keep the existing set; artist projections serve
  `artist_identifier`). The planner only offers a target's served methods.
- New offline index method `artist_identifier`: probe values are the seed's source-URL
  material (the same values `source_post_url` uses); hits are artist entries, recorded in
  a new `discovery_artist_leads` catalog table (migration 0033) with the snapshot
  revision — leads only, never facts, no fetch bridge (artist entries are not posts).
- Freshness, attempts, and policy behave exactly like the existing index methods
  (revision + overlay generation; zero-result searches invalidate on re-import).

## Out of Scope

- Provider-side `artist_identifier` strategy (danbooru/e621 `/artists.json?url=` live
  search; needs `LookupStrategy` + `LOOKUP_STRATEGY_VERSION` bump — deliberate follow-up).
- Deriving artist-tag post searches or fetch follow-ups from artist leads (policy
  question: auto-derived search terms; needs operator review).
- Account-seed identifier material (URLs held on accounts); slice 1 probes post/file
  seed source URLs only.
- Danbooru artist datasets (gated on an operator-supplied artifact, unchanged).
