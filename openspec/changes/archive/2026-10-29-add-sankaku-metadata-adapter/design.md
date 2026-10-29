# Design

## Context

The repo has landed two multi-instance families (danbooru: instances; gelbooru: engine family
with per-instance credential policy) and the kernel admission pattern is settled:
`SOURCE_OPERATIONS` registration + migration-seeded platform row + captured fixtures (the
FamilyReviewer blocker lesson). Sankaku is a new provider family with its own capi-v2 API. Two
reference implementations exist locally: gallery-dl `sankaku.py` (API client: `/auth/token`
exchange, `/v2/posts?tags=id_range:<id>`, `/v2/posts/keyset` `{data, meta.next}` cursor,
per-post `/posts/{id}/tags` and `/notes` endpoints) and Grabber's Sankaku model (same endpoints;
token host evidence spans `capi-v2.sankakucomplex.com` and `sankakuapi.com`). Post records carry
`created_at: {s: unix}`, `tag_names`, `md5`, `file_url`/`sample_url`/`preview_url`, `status`,
`parent_id`, `rating`, `score`. Provider rate-limit behavior includes 429 with
`X-RateLimit-Reset`.

## Goals / Non-Goals

**Goals:** one honest first slice — `fetch_post` + keyset listing — fully admitted (registry,
platform row, CLI) with captured contracts and an ephemeral bearer-token credential model.

**Non-Goals:** typed tag categories (extra per-post request; deferred with its own budget
decision), notes, pools, the Idol instance, reverse lookup, media acquisition, and any
persistent token caching.

## Decisions

### D1: One request shape per surface, verified by capture before parsing code lands
The API client is written against the reference implementations, but every parsed shape is
blessed only by the captured fixture (r4y rule). Capture happens with the maintainer's
credentials before the normalizer is finalized; if Sankaku's live responses differ from the
references (token host, field drift), the capture wins.

### D2: Credentials are external; the token is process-ephemeral
`SankakuCredentials.from_environment` resolves `SANKAKU_LOGIN`/`SANKAKU_PASSWORD` (per-instance
env names on `SankakuInstance`). The adapter exchanges them once per process at its token
endpoint, holds the bearer token only in its HTTP client headers, and re-exchanges once on the
provider's invalid-token signal before typing the run `authentication_required`. No token or
credential value ever reaches durable stores, identities, observations, logs, fixtures, or
diagnostics — the same secret-free discipline the gelbooru family enforces, extended to the
token itself. Alternative — a persisted token cache (gallery-dl caches ~365 days) — rejected:
durability of credential material contradicts the kernel's provenance rules for marginal gain.

### D3: Post fetch rides the id-range query; listing rides the keyset cursor
`fetch_post` uses the provider's documented single-post resolution (`/v2/posts` with
`id_range:<id>`, limit 1) rather than a guessed `/posts/{id}` route — the shape both references
actually exercise. Listing maps the kernel's enumeration contract onto `/v2/posts/keyset` with
the `next` cursor as the continuation payload (digest-checked like gelbooru's continuation).
429 responses end or pause the run typed `rate_limited`, retaining `X-RateLimit-Reset` when
present; no speculative retries.

### D4: Tags land typed from the embedded objects (revised by capture)
Post records embed typed tag objects (`tagName` + numeric `type`), so categories land typed
via the capture-corroborated type map, restricted to kernel categories (studio/genre/medium
stay `unknown` rather than approximated); the original deferral of typed categories — and the
per-post `/posts/{id}/tags` fetch it assumed — is unnecessary for this slice. `created_at` is
a unix-seconds object (`{s}`) and lands as the provider fact it is; `parent_id` lands as the
directional `parent_of` relation.

Live-verified host correction (2026-10-29): the token AND data host is `sankakuapi.com` — the
historical `capi-v2.sankakucomplex.com` host returns nginx 403 to this client — so the
instance's canonical base is `sankakuapi.com` and the schema version is `sankaku-api-v2-v1`.

### D5: Admission is complete or absent
`SOURCE_OPERATIONS` gains `sankaku`; migration `0021` seeds the platform row; the CLI commands
(`sankaku-post`, `sankaku-list`) ship in the same change as the fixtures. No surface ships
unverified — the FamilyReviewer blocker (registry without platform row) cannot recur because
the tasks make the three admission pieces explicit and the reviewer checks them together.

## Risks / Trade-offs

- **Provider hostility:** Sankaku aggressively rate-limits and has a history of banning
  non-browser clients. Mitigation: the family floor (2 s interval), bounded runs only, a
  descriptive non-browser user agent (the repo's existing policy), metadata-only scope, and
  honest 429 handling. Capture stays at a handful of requests.
- **Token/endpoint drift:** the two references disagree on the token host; D1's capture decides
  and the instance's base URLs make the choice explicit and versioned.
- **Field drift vs references:** same mitigation as the gelbooru family — per-instance schema
  version, fixture-decided normalization.
