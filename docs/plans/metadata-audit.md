# Hosted-source metadata audit

Status: complete (2026-10-05) · Bead: `data-processing-a3t`

Purpose: establish, per hosted source, **everything the source exposes** versus what this
repo retains and normalizes today, ordered by what each field unlocks for the
[raw capability requirements](raw_requirements.md): cross-database item matching (recorded
and non-recorded), hash-based matching, item relationships, and eventually tested
similarity. Sources of external knowledge: gallery-dl and Grabber under
`D:\Projects\Projects\image-downloaders` (mined 2026-10-05; distilled below).

Key structural fact: because raw responses are retained append-only and normalization is a
pure function of (payload, adapter/schema/transport versions), **every gap below is
reprocess-able from retained raw for already-synced data** — extending a normalizer never
requires refetching what a run already captured. The worklist is therefore mostly
normalizer catch-up, not re-crawl.

## External knowledge sources (distilled)

### Grabber (imgbrd-grabber)

Site models under `src/sites/`; canonical parsed fields (`IImage`): id, md5, author/
author_id, status, parent_id, has_children/has_notes/has_comments, source/sources, rating,
tags + per-category, ext, created_at, score, file/sample/preview urls + dimensions,
file_size.

- **Danbooru 2.0** (model covers clones incl. AIBooru): full JSON map incl.
  `tag_string_{general,artist,character,copyright,meta}`, `media_asset.variants`,
  `parent_id`, `uploader_name`, `status`, `change`. fav_count only via HTML. Server-side
  search operators confirmed: `source:`, `md5:`, `id:`, `parent:`, `parent:none`,
  `status:any|deleted|active|flagged|pending`, `rating:`, `user:`, `fav:`, `score:`,
  `date:`, `approver:`, order:* — OR via `~`. Page numbers ≤ 1000 then id-cursors
  `a{max}`/`b{min}`. Auth `login`/`api_key` or basic.
- **e621**: `v2=true` nested (`files.{original,sample,preview,meta}`,
  `relationships.parent_id`, `stats`, `flags`, `sources`); parser accepts legacy flat array
  too; hidden posts need auth; descriptive UA required.
- **Gelbooru 0.2**: dapi XML+JSON, fields verbatim (`owner` = uploader); no `status:`
  operator; favorites unsearchable via its XML path (gallery-dl disagrees for JSON
  `s=favorite` — verify); `order:` must be `sort:` server-side; 0-based `pid`; details
  `fields=tag_info` returns typed tags; auth `user_id`+`api_key`.
- Cross-cutting: default throttle 1 s/request, 60 s retry; site-delegated search tokens vs
  client-side post-filters are distinct layers.

### gallery-dl

Extractors under `gallery_dl/extractor/`; danbooru.py covers danbooru+aibooru+atfbooru as
one code path, e621.py subclasses it.

- **Danbooru/AIBooru** post fields: `approver_id, bit_flags, created_at, down_score,
  fav_count, file_ext, file_size, file_url, has_active_children, has_children, has_large,
  has_visible_children, id, image_height, image_width, is_banned, is_deleted, is_flagged,
  is_pending, large_file_url, last_comment_bumped_at, last_commented_at, last_noted_at,
  md5, media_asset, parent_id, pixiv_id, preview_file_url, rating, score, source,
  tag_count* (6), tag_string* (6), up_score, updated_at, uploader_id` + optional includes
  `artist_commentary, children, notes, parent, uploader`; ugoira frames via
  `?only=media_metadata`; pools/favgroups with `post_ids` ordering; artists with
  `other_names, group_name, is_banned, is_deleted`. **`pixiv_id` is a first-class field and
  `pixiv_id:` a search metatag** — the stable-ID bridge to pixiv. Deleted posts remain
  searchable (file_url absent). Page cap 1000 then id cursors.
- **e621** nested v2: `file{}`, `preview{}`, `sample{alt,alternates,has,...}`,
  `relationships{children, has_active_children, has_children, parent_id}`,
  `score{down,total,up}`, `sources` list, `tags` dict per category (artist, character,
  contributor, copyright, invalid, lore, meta, species), `approver_id, change_seq,
  comment_count, created_at, description, duration, fav_count, has_notes, is_favorited,
  locked_tags, pools, updated_at, uploader_id, uploader_name`; optional `notes` (with
  coordinates/version) and full `pools`. **Artists expose `urls[{url, normalized_url}]`
  and `domains`.** `/posts/{id}.json` wraps in `{"post": ...}`.
- **Gelbooru (0.2)** dapi passes through verbatim; typed tags only via `fields=tag_info`
  or HTML scrape (`tags_metadata` spelling); id-cursor pagination for deep searches;
  favorites via dapi `s=favorite`; 0.1.x instances HTML-only.
- **Pixiv** dual API (App + AJAX); works: `id, title, type, create_date, page_count,
  width, height, sanity_level, total_view/comments/bookmarks, restrict, x_restrict,
  illust_ai_type, illust_book_style, is_bookmarked, visible, series, tools, tags[{name,
  translated_name}], user{...}, page urls`; profile/workspace via option; unlisted works
  keep slug in `id_unlisted`; CDN URL encodes upload datetime; R-18 placeholders; refresh
  token OAuth; offset cap 5000 walked by date windows.
- **X/Twitter** full GraphQL surface incl. **Bookmarks endpoint**; tweet fields incl.
  `conversation_id, view_count, bookmark_count, source (client), sensitive_flags,
  birdwatch, article, date_bookmarked`; media fields incl. **`source_id`/`source_user`
  (media originally from another tweet — built-in repost signal)**, `media_key`, size
  fallback chain orig→4096→large→…; auth_token cookie or guest; rate-limit headers;
  GraphQL operation hashes rotate.

## Per-provider gap matrix

Legend: ✓ normalized · R retained-raw (reprocess-able) · ✗ not retained (needs new fetch
or adapter work) · n/a not exposed.

### Danbooru (+ AIBooru)

| Field group | Exposed | Today | Requirement unlocked |
| --- | --- | --- | --- |
| identity, created/updated, rating, status(deleted), availability | ✓ | ✓ | foundation |
| declared md5, file/preview/sample URLs, dims, size | ✓ | ✓ | hash matching (req 2) |
| `pixiv_id` typed reference | ✓ | ✓ (+ `pixiv_id:` lookup wired) | **stable-ID bridge (req 1)** |
| `source` URL | ✓ | ✓ (evidence-only ref) | weak URL bridge |
| parent_id + children | ✓ | ✓ (`parent_of`) | relationships (req 3) |
| tags × 5 categories | ✓ | ✓ | ordering/identity evidence |
| uploader (id, name via include) | ✓ | ✓ id only | — |
| **score / fav_count / up/down** | ✓ | ✓ (2026-10-05, bead `unp`) | ordering, quality signals |
| **is_flagged / is_pending (+bit_flags)** | ✓ | ✓ flags as observations (bit_flags stays raw) | revisit/freshness workflows |
| **pools / favgroups (post_ids)** | ✓ | ✗ from post payloads — verified absent on live payloads 2026-10-05; needs the `/pools/{id}.json` collection surface | **work-grouping relationships (req 3)** |
| **tag_count_\*** | ✓ | derivable (post-tag observations per category) | cheap ordering |
| **has_children / has_active/visible** | ✓ | derivable (parent/child relations) | traversal hints |
| **description / artist_commentary / notes** (includes) | opt-in | ✗ (never requested) | provenance/context |
| **ugoira frames** (`media_metadata`) | opt-in | ✗ | animation support |
| **media_asset (variants w/ dims, pixel_hash, duration, file_key)** | ✓ | ✓ variant dims per provider-native size (pixel_hash/duration/file_key stay raw) | variant fidelity |
| artist `group_name`, `is_banned`, canonical_url, created/updated | ✓ | ✓ group_name/is_banned/created/updated (canonical_url not exposed by the artist payload) alongside name/other_names/urls/active/deprecated/replacement | artist identity evidence |

The persistence layer already writes `PostMetadataObservation`, `PostFlagObservation`, and
`PostPoolObservation` for e621 — the danbooru adapter simply does not emit those keys, so
catch-up is cheap and reprocess-able.

### Gelbooru

| Field group | Exposed | Today | Unlocks |
| --- | --- | --- | --- |
| identity, created_at, rating, status, availability, source, score{total} | ✓ | ✓ | foundation |
| declared md5, file/preview/sample URLs, dims | ✓ | ✓ | hash matching |
| uploader (creator_id + owner) | ✓ | ✓ | — |
| tags (flat; typed via `fields=tag_info` or HTML) | ✓ | ✓ flat; **typed = R/adapter work** | ordering |
| **`parent_id` / `has_children`** | ✓ | **R** — not normalized | **relationships (req 3)** |
| **`title`** | ✓ | **R** | context |
| **lookup capabilities (md5:, source:, id:, parent:)** | ✓ server-side | **✗ — adapter declares none** | **req 1 + 2 entirely blocked for gelbooru** |
| favorites (`s=favorite`) | ✓ (JSON) | ✗ | discovery surface |
| updated_at, file size | ✗/n/a | — | — |

### e621

The most complete adapter. Gaps only:

| Field group | Exposed | Today | Unlocks |
| --- | --- | --- | --- |
| everything above for danbooru incl. per-variant dims, flags→observations, pools→observations, uploader id+name, rich artist records (urls, domains, group, linked_user_id), tag + alias records, sources[] refs, parent/children | ✓ | ✓ | — |
| **description content** | ✓ | only `description_present` bool (**R**) | **provenance: e621 descriptions embed the artist's original post text ("From source:" + full caption/credits, verified on live pages 2026-10-05) — normalize as retained source content** |
| **sets** (grouping type distinct from pools) | ✓ ("Sets with this post" on live pages) | **✗ — missed by the first audit pass; API surface to verify (`/sets.json`)** | work-grouping relationships (req 3) |
| **notes (coordinates, versions)** | opt-in | ✗ | overlay metadata |
| **duration, locked_tags, sample.alternates, change_seq, is_favorited** | ✓ | **R** | fidelity |
| external pixiv id | via sources[] only | ✓ when URL-recognized | bridge (URL-spelling sensitive) |

### Pixiv

| Field group | Exposed | Today | Unlocks |
| --- | --- | --- | --- |
| account incl. stable id, external_links (webpage/twitter/...), profile facts | ✓ | ✓ rich | account matching (req 1) |
| artwork identity/title/caption/type/dates/pages/dims/rating, tags w/ translations, per-page occurrences + variants, ugoira frames | ✓ | ✓ | foundation |
| **series (manga series membership)** | ✓ | **R** | **work relationships (req 3)** |
| **related works** (`/v2/illust/related`) | ✓ | ✗ (never requested) | **work relationships (req 3)** |
| **total_view / total_bookmarks / total_comments** | ✓ | **R** | ordering/quality |
| **tools, illust_ai_type, illust_book_style, sanity_level** | ✓ | **R** | evidence |
| unlisted works (`id_unlisted`) | ✓ | ✗ | coverage |
| lookup strategies | search is fuzzy | none (by design) | pixiv stays a reference target |

### X

| Field group | Source | Today | Unlocks |
| --- | --- | --- | --- |
| bookmark export fields (post, author, media incl. variants verbatim, folders, quotes/replies) | xarchive | ✓ all retained | foundation |
| media `source_id`/`source_user` (repost signal) | GraphQL only | ✗ (export lacks it — verify per export version) | repost relationships |
| X fetch adapter (Bookmarks/UserTweets GraphQL) | exists upstream | ✗ (no X adapter by design) | freshness (separate decision) |

## Identification bridge findings

Answering the probe question ("which lookup strategy actually identifies items?"), in
order of reliability:

1. **Stable-ID metatag (danbooru/aibooru `pixiv_id:`)** — the strongest bridge: a
   first-class provider field, no URL strings, already normalized as a typed reference and
   already wired as the `external_post_id` strategy on danbooru/aibooru. The 2026-10-05
   probe never exercised it (it used `source_post_url`).
2. **Hash matching (`md5:`)** — declared-MD5 lookups wired on danbooru/aibooru/e621;
   needs local verified bytes (or cross-provider declared-MD5 equality after sync).
   Gelbooru blocked only by its missing lookup capability.
3. **e621 `external_post_id`** — rendered as constructed pixiv source URLs (no pixiv_id
   field on e621); URL-spelling sensitive, so both known spellings
   (`pixiv.net/artworks/{id}`, `/en/`) are tried as separate bounded requests
   (2026-10-05, verified live: two distinct requests, clean zero for the control pair).
4. **`source_post_url`** — weakest: exact string match against uploader-entered URLs;
   handle volatility and spelling variance make it evidence-grade only. Keep, but demote
   in ordering/docs. (0/10 bookmarks matched on danbooru, 2026-10-05.)
5. **Artist-record URLs → account matching** — danbooru/e621 artist records carry curated
   twitter/pixiv URLs (e621 also `normalized_url`); linking a bookmark author to an artist
   record via these is the reviewed-target path that makes library expansion the real
   X→booru bridge (already supported by discovery + review).
6. **Non-recorded items have no entry point** — lookup seeds must be catalog entities.
   Decided 2026-10-05: a materialize-a-seed operation that ingests the full evidence bundle
   available at the time (innate image metadata first, supplied-alongside references second at
   declared/asserted status) — see the catalog plan §12 "Non-recorded item entry".

## Ordered normalization worklist

Filed as beads, in requirement-impact order:

1. **Danbooru-family normalization catch-up** — *(Done 2026-10-05, bead
   `data-processing-unp`)* emit score/fav/up/down ✓, flag observations ✓, media_asset
   variant dims ✓, artist group_name/is_banned/created/updated ✓; per-post pool ids
   verified absent (pool grouping needs the pools collection surface, still open);
   tag counts and has_children are derivable from already-normalized data.
2. **Gelbooru lookup + relations** — declare bounded lookup capabilities (md5:, source:,
   id:, parent:) with the dapi transport (verify favorites dispute), normalize
   parent_id/has_children/title, typed tags via `fields=tag_info`; unlocks req 1+2 for
   gelbooru.
3. **e621 description/duration/locked_tags normalization** — small reprocess-able
   catch-up.
4. **Pixiv engagement + series + related** — normalize totals, tools, ai_type, series
   membership; add `related` as an explicit bounded operation (work relationships).
5. **Bridge hardening + positive controls** — exercise `external_post_id`
   (pixiv_id metatag) end-to-end with a known pair; e621 multi-spelling pixiv source
   URLs; demote source_post_url in docs to weak evidence; decide the non-recorded-seed
   design. *(Done 2026-10-05 — bead `data-processing-zos`: positive control completed the
   first end-to-end hop; e621 now tries both pixiv source spellings; source_post_url
   demoted in the catalog guide; materialize-a-seed decided, catalog plan §12.)*
6. **Notes/commentary includes** (danbooru, e621) — promoted 2026-10-05: live pages show
   danbooru artist commentary is the artist's own cross-posted caption and e621
   descriptions embed the full source-post text ("From source:") — retained source
   content, not decoration. Gelbooru notes exist on post pages too.

Scale strategy (local mirror vs live API vs hybrid) remains Bead `data-processing-6cu` and
gates how aggressively the worklist's sync surfaces can be used at millions-of-rows scale.
