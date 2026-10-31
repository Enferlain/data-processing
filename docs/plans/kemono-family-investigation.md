# Kemono-family investigation: Anzhc/kemono-browser (research note)

Status: investigated 2026-10-31 at the maintainer's pointer; no product surface changes.
Verdict: **not adopted as a tool**, but recorded as a third reference implementation of
the Kemono `/api/v1` contract — a viable future adapter family (candidate after the
reference-derived booru families, which the maintainer has deprioritized).

## What it is

A 3-star single-file Electron app (654-line `main.js`) that browses and downloads from
**pawchive** — a Kemono-software mirror aimed at the furry community. It is hardcoded to
that one instance (`pawchive.st` → `pawchive.pw`), with favorites/read-post tracking,
gallery rendering, and zip/7z attachment extraction (image entries only). As a tool it
solves a different problem than this repo: interactive media downloading on Windows vs a
metadata-only catalog. Nothing to run or vendor.

## Why it was worth the look

It encodes the Kemono API family contract from the consumer side, with several quirks the
other two references (gallery-dl `kemono.py`, Grabber "Kemono") surface differently:

- Endpoints: `GET /api/v1/creators`; `/<service>/user/<id>/profile`;
  `/<service>/user/<id>/posts?o=<offset>&q=<query>&tag=<t>` (offset pagination);
  `/<service>/user/<id>/post/<postId>` (detail).
- Detail responses split as `{post, attachments, videos}`, and the post's own
  `file`/`attachments` entries can lack the `server` field — the app backfills it from the
  sibling top-level arrays (`server` + `path` → original media URL). Preview entries are
  thumbnail-only and explicitly not a source of truth for originals.
- Media hosts are split: originals on `file.<instance>` under `/data/<path>`, thumbnails on
  `img.<instance>/thumbnail/data/<path>`; site-relative `/data/` paths must be rewritten to
  the file host.
- Anti-bot quirks: API GETs spoof `Accept: text/css`; browser session cookies are forwarded
  (needed for media/CDN, not the API — see below); `Origin`/`Referer` pinned to the service
  host; the canonical `.st` domain 301s to `.pw`, whose asset hosts are the live ones.

## Live verification (2026-10-31, anonymous, metadata-only)

- `https://pawchive.pw/api/v1/creators` → **200**, 15.8 MB JSON array; entry shape
  `{id, name, public_id, service, indexed, updated, favorited, ever_imported}` with string
  ids and `service` values like `patreon`. Anonymous API access works; the app's cookie
  forwarding serves the media hosts, not the API.
- `https://pawchive.st/...` → 301 to `.pw`, confirming the domain dance.

## If a kemono-family adapter ever lands

- Instances would be a registry like the gelbooru family — but per the maintainer
  (2026-10-31), **only pawchive is currently maintained**: kemono.su and coomer.su are
  dead or stale by months to a year. A future adapter ships `pawchive.pw` alone; the
  other instances rejoin only if they demonstrably revive (fresh `indexed`/`updated`
  evidence). Credential story: anonymous for metadata, per the probe.
- The 15.8 MB creators dump is far outside our bounded-response floors — an adapter should
  target the per-creator endpoints (`profile`, `posts`, `post`) and treat `creators` as an
  out-of-band catalog seed, not a runtime call.
- Mapping: creator → account (keyed `service:id`), post → post with `attachments`/`file` →
  media occurrences (archive attachments stay URLs — the catalog does not extract zip/7z;
  that is the browser app's job, not ours); `favorited`/`indexed` are site-internal facts
  worth keeping as evidence, not truth.
- r4y applies in full: no normalizer ships until each instance is live-captured; the
  `server`-backfill quirk above is exactly the kind of surprise that rule exists for.
