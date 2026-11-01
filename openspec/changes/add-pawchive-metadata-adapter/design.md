# Design

## Context

The repo's adapter precedents split between families (gelbooru instances, danbooru
variants) and single-instance adapters (sankaku, pixiv). Pawchive is a family of one
today — the maintainer's statement (2026-10-31) that kemono.su/coomer.su are dead or
stale is the deciding input — so the adapter is single-instance with a family-shaped
registry, sankaku-like, not a generalization exercise. The kemono-browser investigation
supplied the reference contract; every shipped fact was re-verified by our own anonymous
captures on 2026-11-01 (r4y rule: reference tools point, live bytes decide).

## Goals and Non-Goals

Goals: first-class metadata-only pawchive platform (account, posts, listing); live-captured
contract fixtures; bounded, anonymous, secret-free transport; catalog-standard operations.

Non-goals: the creators dump as a runtime surface, lookup strategies, sibling instances,
media bytes, archive extraction.

## Decisions

### D1: Targets are compound strings, no new vocabulary

Accounts are `service:user-id`, posts `service:user-id:post-id` (e.g.
`patreon:75232195:70439020`). The service dimension lives inside the target instead of
the platform key — one platform row, ten services, no `pawchive-patreon` platform sprawl.
`service` is retained as evidence on accounts, posts, and participants.

### D2: Offset continuation rides the durable request target

The API pages by `o=<offset>` with server-fixed 50-entry pages and no cursor token. The
adapter embeds the offset in the request target (`listing:{service}:{user}:{offset}`) so
normalization derives `next = offset + len(page)` without client state — the same pattern
gelbooru uses for `pid`. A short page (< 50) terminates the listing. Offline replay
rebuilds envelopes without request targets, so a replayed full page is treated as
terminal rather than failed (the gelbooru listing precedent); reprocess is a
re-normalization surface, never a re-pagination one. The 4 MiB response ceiling is
justified by the fixed page size: observed pages hit 1.5 MiB and the adapter cannot
request smaller ones.

### D3: Media identity is name+path; expiring URLs never persist

Live probes: stable-path originals (`file.pawchive.pw/data/<path>`) answer 404
anonymously; paywalled-preview entries carry `preview_only: true` plus an expiring signed
`temp_url` (`t1.pawchive.pw/f/<sig>/...`); thumbnails are reachable on a stable URL
(`img.pawchive.pw/thumbnail/data/<path>`, verified 200). Occurrences therefore carry
`file_name`, the content-addressed `path`, `preview_only`, a thumbnail variant, and
`remote_url: null` — the sankaku expiring-signature rule. If a durable original host
returns, `remote_url` earns its value from a capture.

### D4: The post detail envelope is flat, and ids are strings

Both differ from what kemono-browser's code implies (`{post, attachments}` envelope;
numeric-looking ids). Our captures show a flat body plus `next`/`prev` sibling ids, and
string ids across profile, listing, and detail. The adapter validates strings (bools
excluded) and ignores `next`/`prev` (reachable via our own targets).

### D5: Tags are a brace string or null

`"{Benefits,Douki-Chan,NSFW}"` on a large captured page (kept out of the fixture by the
size cap; the manifest records the evidence), `null` on the fixture's own posts. Parsed
to unknown-category tags — the API exposes no tag taxonomy.

## Risks / Trade-offs

- Pawchive is a community mirror of paywalled content; the adapter is metadata-only and
  anonymous, same stance as every other platform. No media bytes, ever.
- Single-instance coupling: if the site changes shape (it already diverged from
  kemono-browser's encoded contract), the fixture suite is the tripwire.
- 4 MiB pages are heavy but bounded; SyncLimits cap pages per run as everywhere else.

## Migration Plan

Single forward migration `0023` seeds the `pawchive` platform row (`INSERT OR IGNORE`,
the aibooru/safebooru/e926/rule34 precedent). No data migration: nothing referenced the
key before.

## Open Questions

- None blocking. Future: a `pawchive` lookup contract if a bounded strategy is ever
  evidenced, and revived siblings rejoining the registry behind their own captures.
