# Proposal

## Why

The kemono-family investigation (maintainer pointer Anzhc/kemono-browser; recorded in
`docs/plans/kemono-family-investigation.md`) left the catalog one reference tool short of
the kemono API family, and the maintainer confirmed only one instance of that family is
worth reaching: pawchive.pw (kemono.su and coomer.su are dead or stale by months to a
year, statement 2026-10-31). Live probes on 2026-11-01 proved the API serves anonymous
metadata, so the catalog can adopt it as a first-class platform with no credential story
at all — the simplest adapter surface the repo has.

## What Changes

- New `pawchive` adapter package (`src/media_catalog/adapters/pawchive/`): anonymous
  `GET /api/v1` transport with the captured `Accept: text/css` header, a single
  `PAWCHIVE` instance in a `PAWCHIVE_INSTANCES` registry (family-shaped for revived
  siblings), descriptive User-Agent, 1s pacing floor, and a 4 MiB response ceiling
  (observed 50-entry listing pages reach 1.5 MiB; the page size is server-fixed).
- Operations: `fetch_account` (`/{service}/user/{id}/profile`), `fetch_post`
  (`/{service}/user/{id}/post/{post}`; flat body — not the `{post, attachments}` envelope
  older consumers expect), `list_account_posts` (`/{service}/user/{id}/posts?o=<offset>`;
  offset continuation embedded in the durable request target, the gelbooru pid pattern).
- Normalization (live-captured contracts): string ids everywhere; creator → account with
  `service`/`public_id`/indexed/updated evidence; post → post + account + `creator`
  participant + occurrences; `file`+`attachments` → media occurrences carrying
  `name`+content-addressed `path` identity, `preview_only`, a stable thumbnail URL
  variant, and **no `remote_url`** (originals live behind expiring signed `temp_url`s
  that are never retained — the sankaku signature rule; the stable-path originals host
  404s anonymously); brace-string tags (`"{A,B,C}"` or null → unknown-category tags);
  empty `file: {}` entries stay absent rather than becoming empty occurrences.
- Platform key `pawchive` registers in `SOURCE_OPERATIONS`; platform row is
  migration-seeded (`0023`); CLI gains `pawchive-profile`, `pawchive-post`,
  `pawchive-list`; offline replay resolves the instance through the registry.
- Fixture suite `tests/fixtures/metadata_adapters/pawchive.json`: three live anonymous
  captures (profile, one-entry listing page, post detail with file + 5 attachments);
  the manifest records the contract facts observed on larger captures that the 20 KiB
  fixture cap keeps out (1.5 MiB full pages, brace tags, `preview_only`/`temp_url`).

### Non-goals

- The 15.8 MiB `/api/v1/creators` dump (out-of-band catalog seed at most, never a runtime
  call), reverse lookup (empty until each strategy earns a captured fixture), other
  kemono instances (dead or stale per the maintainer), media byte handling of any kind,
  and archive (zip/7z) attachment extraction (the browser app's job, not the catalog's).

## Capabilities

### New Capabilities

- `pawchive-metadata-adapter`: anonymous, bounded, fixture-verified metadata access to
  the pawchive instance of the kemono API family.

### Modified Capabilities

- none
