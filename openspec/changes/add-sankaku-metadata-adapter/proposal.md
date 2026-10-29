# Proposal

## Why

Sankaku (chan.sankakucomplex.com) is the largest remaining anime-illustration corpus in the
reference-derived candidate set (gallery-dl `sankaku` extractor, Grabber "Sankaku" site), and it
runs its own capi-v2 JSON API — a genuinely new provider family, not a gelbooru/danbooru engine.
The family patterns were just proven twice over (danbooru instances, gelbooru family), so the
marginal cost of a new family is the API client itself; the marginal value is a corpus none of
the current platforms cover.

## What Changes

- New `adapters/sankaku` package: `SankakuInstance` (canonical capi-v2 base, platform key
  `sankaku`, schema version `sankaku-capi-v2-v1`, credentials-required policy), and
  `SankakuAdapter` implementing the provider-neutral adapter protocol for the first slice:
  - `fetch_post` via `/v2/posts?tags=id_range:<id>` (single-post bounded run);
  - `list_account_posts`-style tag-enumerated listing via `/v2/posts/keyset` with `next`-cursor
    continuation under the shared bounded-run contract.
- Credential model: `SankakuCredentials` (external `SANKAKU_LOGIN`/`SANKAKU_PASSWORD` env
  references) exchanged once per process at the API boundary for a Bearer access token
  (`POST /auth/token`); the token lives only in HTTP headers, never in any durable store,
  identity, observation, log, or diagnostic. Token refresh on the provider's invalid-token
  signal; no persistent token cache.
- Kernel admission: `SOURCE_OPERATIONS` gains `sankaku`; migration `0021` seeds its platform row
  (the FamilyReviewer lesson: registry + platform row + captured fixture, or nothing ships).
- Contract verification by credentialed live capture only (r4y rule): the fixture suite carries
  real captured bytes for the post fetch and one keyset listing page before any surface is
  treated as verified. No synthetic shapes.
- CLI: `sankaku-post` and `sankaku-list` metadata commands with the family credential guidance.

### Non-goals (this change)

- Typed tag categories (`/posts/{id}/tags`, one request per post — needs its own budget decision
  and captured fixture; posts initially land tags with unknown category), notes
  (`/posts/{id}/notes`), pools/pool series, the Idol instance (idolcomplex), reverse lookup,
  and media acquisition. Rate-limit policy beyond the family floor (2 s) and honest 429
  handling land with the captured evidence of actual behavior.

## Capabilities

### New Capabilities

- `sankaku-metadata-adapter`: the Sankaku capi-v2 metadata adapter — instance identity,
  credential/token policy, bounded post and keyset-listing operations, normalization of only
  evidenced facts, and capture-verified response contracts.

### Modified Capabilities

- none
