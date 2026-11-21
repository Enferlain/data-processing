# Design

## Context

Sankaku phase 2 shipped the adapter's metadata surface: token auth
(`_exchange_token`, one re-exchange retry), `FETCH_POST` (`/v2/posts` with
`tags=id_range:<id>`), keyset listings (`/v2/posts/keyset` with arbitrary
1–200 char tag queries + `next` cursor), normalization with `declared_md5`,
and a 2.0s pacing floor. The crosscheck coordinator drives any adapter whose
instance declares `lookup_capabilities` through the `LookupAdapter` protocol
(`fetch_lookup`/`normalize_lookup`, `adapters/contracts.py:1005-1023`);
`LookupRequest.operation` already maps both md5 strategies to
`AdapterOperation.FETCH_POST`. Danbooru is the reference md5 lane
(`adapters/danbooru/adapter.py:278-514`). Credentials resolve on this
machine (verified 2026-11-21 via `SankakuCredentials.from_environment`).

## Goals / Non-Goals

**Goals:**

- Sankaku md5 lookups behave indistinguishably from the other md5 lanes:
  same materials, budgets, pacing, outcomes, candidate semantics.
- Zero new transport code paths — the md5 query reuses the authorized keyset
  listing request and its continuation machinery.

**Non-Goals:**

- Artist/URL/external-id strategies for Sankaku (later phases).
- Registration in discovery's `LOOKUP_PROVIDERS` (standalone `catalog
  lookup` targeting); lands when there is a strategy beyond md5 worth
  running standalone.
- Media bytes, similarity, harvesting.

## Decisions

### D1: The md5 query rides the keyset listing path, not `/v2/posts`

`fetch_lookup` renders the md5 strategies through the existing
`_listing_request` (`/v2/posts/keyset?tags=md5:<hash>&limit=<n>&lang=en`).
Alternative: `/v2/posts` with a tags param (danbooru's shape). Rejected: the
keyset path already has continuation wrapping (`Continuation("sankaku",
"sankaku-keyset-v1", …)`), cursor validation, request-target identity
(`listing:md5:<hash>:<cursor|start>`), and a captured response contract —
`/v2/posts` would add a second posts-endpoint parse for no gain. An md5 is
provider-unique, so a hit page has at most one post and continuation is
normally absent; if the provider ever supplies `next`, the bounded run
contract already handles it.

### D2: Capabilities are minimal and honest

`SankakuInstance` declares exactly `LookupCapability(DECLARED_MD5, "post",
"keyset")` and `LookupCapability(VERIFIED_MD5, "post", "keyset")` with
`max_page_size` at the instance page size (100), plus a
`lookup_plan_context` property mirroring `DanbooruInstance`
(`config.py:54-64`). `fetch_lookup` refuses any other strategy with the
standard unsupported-operation failure before network access; planning
already excludes unsupported strategies per-provider, so the refusal is
defense in depth.

### D3: `normalize_lookup` reuses `_post_items` for result payloads

Mirror danbooru's `_lookup_post_result`: each returned post becomes
`NormalizedLookupResult("post", <id>, data, rank, items)` where `items`
carries the full `NormalizedItem` tuple from the existing
`_post_items` normalizer (post facts, tags, media occurrence with
`declared_md5`, source reference) — the interpreter then applies the same
exact-hash evidence semantics it applies to danbooru/e621/gelbooru results.
Shape violations raise `AdapterFailure(MALFORMED_RESPONSE, …)` per the
captured contract.

### D4: Crosscheck registration is a one-line provider addition

`crosscheck.PROVIDERS` gains `"sankaku"`; CLI choices derive from the tuple.
Lane construction, per-item `LookupLimits`, budget checkpoints, rate-limit
handling, and `_reusable_run` skip logic are provider-generic and need no
changes. The 2.0s sankaku floor flows through
`adapter_construction` → `CandidateLookupService` → `RequestGate`
automatically.

### D5: Fixture from a live capture, per the sankaku fixture policy

The keyset posts shape is already fixture-backed; the md5 surface adds two
captured fixtures (hit + miss) of actual `tags=md5:<hash>` responses in a
new `sankaku_lookup.json` suite — mirroring the danbooru/aibooru
`*_lookup.json` convention and keeping `sankaku.json` under the fixture
size budget — trimmed to parsed fields with all retained values verbatim, so
the parsed contract for this query kind is verifiable. Default
tests use injected transports only; any live check stays opt-in and bounded.

### D6: Credential absence defers to a typed per-item failure (gelbooru pattern)

Implementation finding: the sankaku adapter required credentials at
construction, so a crosscheck lane without `SANKAKU_*` env would crash the
whole batch — violating catalog-cross-check's item-level missing-credentials
reason. Sankaku gains `optional_from_environment` (both unset → `None`,
exactly one set → refuse) mirroring `GelbooruCredentials
.optional_from_environment`; the adapter accepts `credentials=None` and
`_exchange_token` raises the typed `AUTHENTICATION_REQUIRED` failure with
bounded "configure both" guidance at the first bounded request, so items
record `failed` with that reason while sibling lanes continue. The strict
`from_environment` path used by the metadata sync and artist sweep is
unchanged.

## Risks / Trade-offs

- [Provider rejects md5: queries on the keyset endpoint differently than
  gallery-dl/Grabber's search path] → Live smoke during apply with one
  known-md5 query before wiring the lane; if the keyset endpoint refuses,
  fall back to `/v2/posts` with the same tags param (D1 alternative) — one
  request-builder change, contract unchanged.
- [Sankaku auth token exchange adds latency per lane] → The lane builds one
  adapter per batch run like every provider; token exchange happens once per
  lane process, not per item.
- [Interpreter assumes booru-shaped result data] → Result data mirrors the
  danbooru md5 lane's fields (declared md5, canonical URL, source), which
  the interpreter already consumes for three providers.

## Migration Plan

No schema changes. Implement capabilities + protocol methods + provider
registration in one commit; add fixture + tests; run the standard gates; a
live opt-in smoke run (`catalog crosscheck --provider sankaku --max-requests
2`) verifies end-to-end. Rollback is `git revert`.
