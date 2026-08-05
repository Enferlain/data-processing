# Cross-platform media catalog plan

Status: proposed
Last updated: 2026-08-05
Runtime: Python 3.13
Initial storage: SQLite plus a content-addressed media directory

## 1. Goal

Build a local-first catalog that starts with posts found in personal X likes and bookmarks, but
does not remain an X-specific archive. The catalog must be able to:

- retain accounts, posts, media, tags, links, and raw provider data from multiple platforms;
- distinguish a platform account from a possible real creator identity;
- distinguish the creator of a work from an uploader, reposter, or source-attributor;
- propose explainable matches between X, Pixiv, Danbooru-family boorus, and later platforms;
- match exact files and visually related variants without treating similarity as proof;
- discover other posts belonging to a confirmed or explicitly allowed account;
- fetch metadata without downloading media, then download selected media as a separate action;
- preserve why every record is present: liked, bookmarked, imported, matched, or crawled;
- remain resumable, rate-limited, reviewable, and safe to run against private exports.

The browser viewer is not a core component. X likes and bookmarks are seed sources and ingestion
adapters, not separate long-term databases.

### Primary workflow: bookmark to artist library

The primary product workflow is:

1. The user bookmarks an image post on X.
2. The X bookmark importer records the post, author account, media occurrences, bookmark event,
   entities, profile snapshot, and raw source data.
3. The catalog inspects the post text, cards, quoted/source posts, author bio, profile website, and
   redirected external links for stable platform references.
4. It extracts native account/post IDs from links to Pixiv, personal sites, portfolios, boorus,
   and other supported platforms. Different handles or display names do not prevent a match.
5. Danbooru-family artist URLs, post `source` URLs, `pixiv_id`, and other provider cross-references
   add independent evidence.
6. The X image is compared with known remote occurrences. Exact hashes are tried first, followed by
   compression/resizing-tolerant similarity when Twitter has changed the bytes.
7. The catalog proposes account, post, work, and attribution links with the complete evidence chain.
8. After confirmation or an explicit bounded override, it enumerates the artist account's other
   posts as metadata-only discoveries.
9. It finds upstream or better-quality occurrences, such as Pixiv originals, without discarding the
   X or booru copies and their provenance.
10. The user optionally downloads selected originals or variants. The catalog stores immutable
    bytes, hashes, metadata, relationships, and the reason each asset was selected.

The goal is not merely to answer “are these usernames equal?” It is to answer:

- Which platform accounts are plausibly controlled by the same creator?
- Which evidence supports that conclusion even when their names differ?
- Which posts and files represent the same work or a derivative?
- Which available occurrence is most likely the upstream or highest-quality useful copy?
- What other works can be discovered from confirmed accounts without confusing them with the
  user's liked/bookmarked set?

### Metadata required by this workflow

Artist/account metadata must include:

- platform and stable native account ID;
- current and historical handles/display names;
- bio, profile URL, website, and every extracted external profile link;
- link redirect chain and the stable native IDs parsed from destinations;
- avatar/banner occurrences and hashes when downloaded;
- verification/account state, location, counts, first/last seen, and snapshot time;
- candidate/confirmed/rejected identity links with evidence and review history;
- booru artist entries, artist tags, aliases, other names, and artist URLs kept distinct from
  platform accounts.

Post/work/image metadata must include:

- platform post ID, canonical/source URLs, author/uploader/artist roles, dates, text/caption, tags,
  rating, status, and raw provider data;
- Pixiv artwork/user/page IDs, booru `pixiv_id`, parent/child relations, page order, and source links;
- all remote media variants and their roles, dimensions, MIME type, file size, duration, alt text,
  and availability;
- provider-declared hashes separately from locally verified MD5/SHA-256;
- pHash and later crop/region evidence for compression or resize matches;
- exact, re-encoded, resized, cropped, translated, thumbnail, and derivative relationships;
- a reviewable quality/original assessment rather than one destructively selected “best image.”

## 2. Success criteria

The first useful end-to-end result is:

1. Import an existing `x-likes` SQLite database and an xarchive bookmark JSON file.
2. Represent likes and bookmarks as separate observations on platform-namespaced X posts.
3. Retain author/account metadata, source URLs, media variants, raw JSON, and unavailable records.
4. Import or query one Pixiv account and one Danbooru-family source without downloading files.
5. Propose cross-platform account and post matches with visible evidence.
6. Require review before confirming identity or creator attribution.
7. Download a bounded selection into content-addressed storage.
8. Match exact bytes and generate reviewable perceptual-match candidates.
9. Resume an interrupted crawl without duplicating records or losing provenance.

## 3. Explicit non-goals

- No automatic identity merges based only on matching handles, names, avatars, or image hashes.
- No assumption that a booru uploader is the artist.
- No assumption that an X or Pixiv poster created every image they posted.
- No unbounded whole-account crawl by default.
- No downloading during import, search, or matching unless explicitly requested.
- No modification, recompression, or replacement of archived source bytes.
- No vector database, face recognition, or style embeddings in the initial implementation.
- No bypassing provider access controls, authentication requirements, or rate limits.
- No dependence on scraper internals as the catalog's permanent data model.

## 4. Vocabulary and invariants

### Platform

A remote service or independently operated instance, such as X, Pixiv, Danbooru, AIBooru, or
e621. Native identifiers are unique only within a platform.

### Account

A platform-specific account. Handles and display names are mutable attributes, not identifiers.
The stable key is `(platform, native_account_id)`.

### Identity

An optional catalog concept representing a possible person, collective, studio, or organization.
An identity can be linked to multiple accounts, but only through explicit, reviewable evidence.

### Post

A platform-specific publication. The stable key is `(platform, native_post_id)`. A post can have
multiple participants with different roles.

### Work

An optional conceptual artwork or creative work that may have several platform posts and several
asset variants. Work grouping is never required for basic ingestion.

### Media occurrence

A media entry as it appeared in a specific post: its index, remote URL, preview, dimensions, alt
text, declared hash, and availability. It may exist before its bytes have been downloaded.

### Asset

Downloaded bytes stored by verified SHA-256. An asset is not the same thing as an occurrence or a
work. Re-encodes and crops have different exact assets even when they depict the same work.

### Observation

Why the catalog knows about a record, for example `liked`, `bookmarked`, `quoted`, `imported`,
`discovered`, or `crawled`. Observations are append-only provenance rather than flags overwritten
on the post.

### Evidence

An observation supporting or contradicting an account, identity, post, work, or asset match.
Evidence has a source, algorithm/version, strength, timestamp, and review state.

## 5. Current repository and migration boundary

The current `x_likes` schema is a useful source adapter but is not the long-term core:

- `accounts.author_id` is globally keyed as though X were the only platform;
- `posts.post_id` has the same assumption;
- `media` is directly keyed by `(post_id, media_index)`;
- image download paths are based on account handles;
- one account is treated as the author of one post;
- there is no event ledger, identity evidence, roleful attribution, crawl state, or work model.

Keep `x_likes` working as a compatibility tool. Add a new neutral package and database in parallel,
then import from the old database. Do not destructively rewrite the old database.

Suggested package boundary:

```text
src/media_catalog/
  cli.py
  database.py
  migrations/
  models.py
  ids.py
  observations.py
  matching/
  storage/
  jobs/
  adapters/
    base.py
    x_archive.py
    x_live.py
    pixiv.py
    danbooru.py
    gallery_dl.py
```

The exact name may change before implementation, but all source adapters should target one core
contract and one catalog database.

## 6. Research sources and limitations

### Local reference: `tag-workspace`

Path: `/mnt/d/Projects/tag-workspace/`

This is an uncommitted script workspace rather than a versioned library. It is useful for endpoint,
query, tag-category, and rate-limit examples, but should not be imported directly.

Relevant references:

- `download_images_from_aibooru.py:59-143` categorizes artist, character, copyright, general,
  meta, and model tags.
- `download_images_from_aibooru.py:213-276` queries AIBooru `/posts.json` with tags, pages,
  limits, optional credentials, and fixed request delays.
- `download_images_from_aibooru.py:278-396` selects full/large/preview URLs and downloads posts.
- `download_images_from_aibooru.py:526-615` expands an artist tag into a multi-post download.
- `get_artist_db_from_aibooru.py:8-126` queries AIBooru `/artists.json`.
- `get_artist_db_from_danbooru.py:8-89` queries Danbooru artist-category tags.
- `tag_database/danbooru_tag_downloader.py:29-147` demonstrates `page=b<ID>` keyset
  pagination and zero-post artist-tag handling.
- `booru_counter.py:21-123` demonstrates cheap count probes for Danbooru, e621, and Gelbooru.

Useful ideas:

- retain booru tag categories rather than flattening all tags;
- estimate query/account size before scheduling a full crawl;
- use keyset pagination for large tag synchronization;
- keep source-specific throttling and explicit user agents.

Behaviors not to copy:

- artist tags are treated too much like creator identities;
- tag deduplication can destroy order and source spelling;
- fixed sleeps and broad exception handling replace resumable job state;
- existing-file checks replace content verification;
- transparent images may be rewritten as JPEGs with black backgrounds;
- media is organized by artist/handle path rather than content hash;
- some scripts contain hardcoded API credentials.

The credentials must never be copied. If they are real, they should be rotated and moved to an
external secret store before reusing these scripts.

### Local reference: `gallery-dl`

Path: `/mnt/d/Projects/image-downloaders/gallery-dl/`
Inspected version: 1.32.2, commit `2e88d6ae29780dbed02e4a5172a1aa0a1b1c91b5`

Relevant references:

- `gallery_dl/extractor/twitter.py` handles X users, timelines, likes, bookmarks, tweet detail,
  cursors, tombstones, account metadata, and media variants.
- `gallery_dl/extractor/pixiv.py` handles user works, bookmarks, tags, original image URLs,
  profiles, OAuth refresh tokens, pagination, and Ugoira.
- `gallery_dl/extractor/danbooru.py` handles posts, tags, MD5, artist objects, uploader metadata,
  parent/child data, source URLs, and batch pagination.
- `gallery_dl/extractor/booru.py` provides a reusable pattern for Danbooru-like post records.
- `gallery_dl/extractor/common.py` implements request intervals, retries, 429 behavior, sessions,
  timeouts, and JSON requests.
- `gallery_dl/downloader/http.py` implements streamed downloads, partial files, retries, range
  resume, and response validation.
- `gallery_dl/job.py:1055-1161` implements the JSON-producing `DataJob` used by `-j`.
- `gallery_dl/archive.py` provides a download archive, but this is file-entry deduplication rather
  than catalog provenance or content identity.

Upstream documentation:

- [gallery-dl repository](https://github.com/mikf/gallery-dl)
- [gallery-dl configuration](https://github.com/mikf/gallery-dl/blob/master/docs/configuration.rst)
- [gallery-dl command-line options](https://github.com/mikf/gallery-dl/blob/master/docs/options.md)
- [Danbooru source repository](https://github.com/danbooru/danbooru)

The local gallery-dl checkout currently cannot run all extractors in the ambient Python
environment because its `requests` dependency is not installed there. Any bridge must run from a
pinned, isolated environment. The first bridge fixture should pin version `1.32.2`; changing the
version requires rerunning its contract fixtures before the pin is updated.

### Live fixture findings

Small read-only requests on 2026-08-04 confirmed that current Danbooru and AIBooru post responses
include fields such as post ID, MD5, source, Pixiv ID, uploader ID, media URLs, dimensions, rating,
status flags, categorized tag strings, and timestamps. e621 uses a different/nested file schema.

These fixtures prove only the observed responses. Before implementing or updating an adapter,
capture a fresh redacted fixture and contract-test the exact response, pagination, error, and
rate-limit shapes. Never finalize normalization from documentation or memory alone.

## 7. Source interaction strategy

### Native adapters for first-class sources

Implement native adapters for the sources central to this project:

1. X archive/xarchive ingestion.
2. Existing `x-likes` database migration.
3. X live enrichment where necessary.
4. Pixiv user and artwork metadata.
5. Danbooru-family post, artist-tag, and source metadata.

Native adapters give the catalog stable normalized contracts, raw-payload retention, precise
provenance, controlled request budgets, and tests against redacted fixtures.

### gallery-dl subprocess bridge

Use gallery-dl for unsupported platforms and as a fixture/oracle for native-adapter behavior.
Do not import its internal Python extractors and do not copy their implementations.

Reasons:

- extractor internals and `Message`/`Job` contracts are not a stable public API;
- direct coupling would make upgrades difficult;
- gallery-dl is GPL-2.0-only, so a subprocess boundary is cleaner than linking or deriving core
  catalog code from it;
- subprocess execution allows version pinning, timeouts, resource limits, isolated credentials,
  and captured stdout/stderr.

Metadata bridge shape:

```text
gallery-dl
  --config <isolated-config>
  --config-ignore
  --no-input
  -j
  -o output.jsonl=true
  -o output.private=true
  <bounded URL>
```

`-j` selects gallery-dl's `DataJob` and does not download files. It emits Directory, URL, and Queue
records with metadata. The `output.jsonl` and `output.private` settings were found in the inspected
checkout, but M0 must verify their exact behavior against the pinned executable before this command
is treated as a stable contract. The bridge must:

- record the gallery-dl version, command, config digest, source URL, exit status, and stderr;
- accept JSON array and JSONL modes;
- namespace records by extractor category/subcategory and native ID;
- preserve raw records before normalization;
- whitelist child extractor categories to prevent accidental traversal into unrelated sites;
- impose catalog-side maximum posts, maximum requests/time, and subprocess timeout;
- keep cookie files, refresh tokens, and API keys outside the catalog and logs.

For actual downloads, gallery-dl may download into a staging directory with metadata sidecars. The
catalog must then verify bytes, move them into content-addressed storage, and register provenance.
Its `--download-archive` may remain a secondary safety mechanism, never the source of truth.

## 8. Platform-specific initial methods

### X

Inputs:

- official X archive `like.js`;
- xarchive bookmark JSON;
- existing `x-likes` database;
- optional authenticated live enrichment.

Preserve:

- numeric post and account IDs as text;
- handle/name/bio/profile URLs and account snapshots;
- post text, timestamps, conversation/reply/quote relations, metrics, entities, and cards;
- original/variant media URLs, dimensions, alt text, video duration/bitrate;
- liked/bookmarked timestamps when available;
- tombstone/unavailable states and raw provider JSON.

gallery-dl demonstrates cursor-based GraphQL timelines, cookie authentication using `auth_token`
and `ct0`, tombstone handling, tweet/account normalization, and original-size media fallbacks. X
query IDs and internal response shapes are unstable, so the native adapter must be fixture-driven,
versioned, and independently health-checked.

### Pixiv

Initial scope:

- resolve a numeric user ID;
- fetch user profile metadata;
- list user artworks with resumable pagination;
- fetch one artwork's pages, tags, caption, rating, timestamps, and original URLs;
- retain multi-page order and Ugoira metadata;
- optionally import the authenticated user's bookmarks later.

Authentication:

- keep refresh tokens and `PHPSESSID` outside the database;
- use a named secret/config reference in crawl jobs, never the token value;
- treat private, My Pixiv, mature, and sanity-limited works as unavailable unless the configured
  account legitimately has access.

gallery-dl's `PixivAppAPI` uses refresh-token OAuth, `/v1/user/illusts`, `/v1/illust/detail`,
`next_url` pagination, and additional endpoints for profiles, bookmarks, following, and Ugoira.
These are internal/client APIs, so the research spike must capture fresh fixtures before native
implementation.

### Danbooru and AIBooru

Initial scope:

- query `/posts.json` by ID, source URL, MD5, Pixiv ID, or bounded tags;
- retain post status, parent/child relationships, uploader separately from artist tags;
- retain provider-declared MD5 without pretending it was locally verified;
- query artist objects and artist URLs where available;
- retain artist-tag aliases, other names, deprecation/deletion, and update timestamps;
- use keyset pagination for large syncs when supported;
- run count probes before scheduling large tag or artist crawls.

Important distinctions:

- a booru uploader is an account with the `uploader` role;
- an artist tag is community attribution, not proof of account ownership;
- a `source` URL is strong post/work evidence but may be missing, stale, or incorrect;
- a booru-provided MD5 is `declared_md5` until local bytes verify it.

### Other boorus

Do not assume one response shape. e621 nests file, preview, sample, source, relationship, score, and
tag data differently. Gelbooru-style DAPI endpoints differ again. Each instance gets a platform
record and adapter capability declaration.

## 9. Adapter contract

Every adapter should provide a subset of these operations:

```python
resolve_account(reference) -> AccountRecord
fetch_account(native_id) -> AccountSnapshot
iter_account_posts(native_id, cursor, scope) -> Page[PostRecord]
fetch_post(native_id) -> PostRecord
search_posts(query, cursor, scope) -> Page[PostRecord]
fetch_media_metadata(post) -> tuple[MediaOccurrenceRecord, ...]
```

Every returned page must include:

- normalized records;
- the raw provider response or a durable raw-response reference;
- the adapter and provider version;
- request timestamp and canonical request identity;
- continuation cursor;
- rate-limit/status metadata when available;
- typed unavailable, deleted, authentication, rate-limit, and parse errors.

Adapters do not write arbitrary SQL. A catalog service validates and persists normalized records,
raw observations, and checkpoints transactionally.

## 10. Database model

Use numbered SQL migrations and `PRAGMA user_version`; do not hide the initial schema behind an ORM.
Enable foreign keys and WAL. Probe FTS5 at runtime rather than assuming it exists.

### Source and provenance tables

`platforms`

- internal ID, stable key, display name, canonical base URL;
- adapter name/version and capability flags;
- default request/download policy.

`import_runs`

- kind, source path/reference, source digest, adapter/version;
- start/end/status, counts, warnings, and errors;
- raw-input retention policy.

`raw_observations`

- platform, object kind/native ID, request/import identity;
- observed time, status, raw JSON or compressed sidecar reference;
- payload digest and schema/version hints.

Raw observations are append-only. Normalized rows point to the observation that produced them.

### Account and identity tables

`accounts`

- internal ID;
- platform and native account ID with a unique constraint;
- canonical profile URL and current availability state;
- first/last seen timestamps.

`account_snapshots`

- account ID and observation time;
- handle, display name, bio, location, website, avatar/banner URLs;
- follower/following counts and verification fields;
- source observation ID.

`account_aliases`

- exact alias/handle, normalized comparison value, type, locale;
- first/last seen and source evidence;
- no global uniqueness assumption.

`identities`

- optional person, collective, studio, organization, or unknown entity;
- user-assigned label/notes and lifecycle status.

`account_identity_links`

- identity, account, relationship, confidence, and review state;
- states: `candidate`, `confirmed`, `rejected`, `superseded`;
- created/reviewed timestamps and reviewer note.

`link_evidence`

- subject link, evidence kind, direction, strength, and structured details;
- source URL/post/observation;
- matcher and algorithm version;
- created time and invalidation/supersession status.

### Post, attribution, and event tables

`posts`

- internal ID;
- platform and native post ID with a unique constraint;
- canonical URL, text/caption, language, created/updated/deleted times;
- availability/rating/status and source observation;
- conversation, reply, quote, parent/child relations through a relation table.

`post_participants`

- post plus account, identity, tag attribution, or free-text subject;
- role such as `author`, `uploader`, `artist`, `creator`, `reposter`, `commissioner`,
  `source_attributor`;
- confidence, review state, evidence, and source observation.

`post_relations`

- source post, target post, relationship (`quote`, `reply`, `repost`, `parent`, `child`,
  `source`, `derivative`, `same_work_candidate`);
- evidence and review state.

`user_events`

- post and event type (`liked`, `bookmarked`, `foldered`, `imported`, `discovered`, `crawled`);
- event/observation time, folder/collection, source import, and raw event data;
- unique event identity for idempotent re-import.

### Tag tables

`tags`

- platform, native tag ID where available, exact name, normalized comparison name;
- namespace/category, locale, deprecation/deletion, and current post count.

`tag_aliases`

- source tag, target tag, alias type, status, source, and observation time.

`artist_entries`

- one booru-native artist object, keyed by platform and native artist ID;
- canonical artist-tag link, exact/canonical name, group name, other names;
- deletion, ban, deprecation, created/updated times, and source observation;
- explicitly not an account or confirmed creator identity.

`artist_urls`

- artist entry, exact external URL, normalized URL, host and URL kind;
- first/last seen, active/deleted state, and source observation;
- parsed target platform/native account or post ID when safely identifiable;
- optional candidate account/identity link, never an automatic confirmation.

Artist URLs are a canonical source registry and feed `link_evidence`; the evidence ledger retains
how a particular URL influenced a match and which artist-entry observation supplied it.

`post_tags`

- post, tag, category as observed, observation ID, and order where available.

Do not collapse platform tags into global tags initially. Cross-platform tag equivalence is another
reviewable mapping.

### Search indexes

When SQLite provides FTS5, create external-content FTS indexes for selected post text, account
snapshots/aliases, tags, cards/links, and user notes. Keep the normalized tables authoritative and
rebuildable.

When FTS5 is unavailable, `catalog search` falls back to parameterized, escaped `LIKE` queries over
indexed normalized columns and clearly reports `search_backend=like`. The fallback may be slower
but search must remain available. Trigram or external search is deferred until measured need.

### Media and asset tables

`media_occurrences`

- post, media index, role/type, original/large/preview URLs;
- MIME hints, dimensions, duration, bitrate, alt text, availability;
- provider-declared MD5/SHA fields and source observation;
- nullable verified asset ID.

`asset_sources`

- occurrence/asset, remote URL, variant role, headers/referer requirements;
- first/last seen, expiry hint, ETag, Last-Modified, content length/type;
- download eligibility and last error.

`assets`

- verified SHA-256 unique key;
- verified MD5, size, MIME, extension, dimensions, animation/video metadata;
- optional pixel-normalized hash and pHash;
- content-addressed local path and verification time.

`asset_matches`

- two assets or occurrence candidates;
- relationship (`exact_bytes`, `exact_pixels`, `near_duplicate`, `crop`, `thumbnail`,
  `reencode`, `derivative`);
- metric/distance, matcher version, evidence, and review state.

`works` and `post_work_links`

- optional grouping for confirmed/candidate manifestations of one conceptual work;
- confidence, evidence, and review state;
- never required merely because two images are visually similar.

### Job tables

`crawl_jobs`

- platform/adapter, target type/native ID or query;
- metadata/media scope, since/until, maximum posts/pages/requests/bytes;
- credential reference, policy, priority, and requested-by reason.

`crawl_runs`

- job, start/end/status, adapter version, counts and rate-limit observations;
- last checkpoint, retry time, error class/message, and audit log reference.

`crawl_checkpoints`

- job/run, cursor kind/value, page/query state, last native ID and updated time;
- adapter-defined JSON preserved alongside normalized checkpoint fields.

## 11. Identity and account matching

Candidate generation and confirmation are separate steps.

Evidence strength, from strongest to weakest:

1. Explicit self-declared cross-platform profile link containing a stable native ID.
2. Shared verified/personal domain linking back to both accounts.
3. Provider-maintained stable cross-reference.
4. Booru artist URL/source URL pointing to a platform account or post.
5. Exact source post ID embedded in URL or provider metadata, such as `pixiv_id`.
6. Repeated exact-byte or near-image matches plus consistent chronology and profile evidence.
7. Matching bio links, aliases, watermarks, and stable names.
8. Same handle, display name, or avatar alone.

For the primary workflow, profile-link extraction must:

- preserve the original bio/profile URL and every redirect hop;
- normalize tracking parameters without destroying meaningful path IDs;
- recognize stable IDs in Pixiv, X, booru artist/post, portfolio, and supported link-hub URLs;
- distinguish a self-declared profile link from a link merely mentioned in a post;
- record shared domains as evidence without assuming every account on a domain has one owner;
- periodically re-resolve mutable short/link-hub URLs while retaining historical destinations.

Rules:

- levels 7-8 generate candidates only;
- exact image matches establish asset/post relationships, not account ownership by themselves;
- booru artist records are community-maintained evidence, not automatic identity confirmation;
- every score stores feature contributions and matcher version;
- confirmed and rejected decisions are reversible and never delete evidence;
- handle changes create snapshots/aliases rather than destructive updates.

Initial review CLI:

```text
catalog links propose
catalog links list --state candidate
catalog links show <candidate-id>
catalog links confirm <candidate-id> --note ...
catalog links reject <candidate-id> --note ...
```

## 12. Post, work, and asset matching

### Exact matching

- provider-declared MD5 may be queried without downloading;
- verified MD5 and SHA-256 require the bytes;
- SHA-256 identifies exact stored bytes;
- a normalized pixel hash can detect the same pixels across lossless container/metadata changes;
- source URLs and embedded platform post IDs can directly link occurrences.

Twitter/X commonly serves resized or recompressed derivatives. In that case, the X file and an
upstream Pixiv/booru file will have different MD5 and SHA-256 values even when they show the same
artwork. An exact-hash miss is therefore “not the same bytes,” not “not the same image.”

### Similarity matching

- image pHash is a candidate index, not a unique constraint;
- compare Hamming distance together with aspect ratio and dimensions;
- retain thumbnails/previews as variants but avoid matching them as originals without context;
- record suspected crop, resize, translation, watermark, and recompression relationships;
- multi-page works must preserve page number before similarity grouping;
- GIF/video initially receive exact hashes and technical metadata only;
- optional ffmpeg frame hashing is a later research item.

The initial lossy-image matcher should combine:

- pHash Hamming distance;
- aspect-ratio agreement;
- dimensions and likely resize scale;
- page/index compatibility for multi-image works;
- source/post/account links and chronology;
- optional color histogram or a second perceptual hash when pHash is ambiguous.

Crop-resistant local features or region hashes are a later fallback for substantial crops,
watermarks, borders, or translations. Embeddings remain deferred until a measured fixture set shows
that explicit links, source IDs, pHash, dimensions, and crop-aware methods are insufficient.

### Matching pipeline

```text
canonical source/post ID
  -> declared exact hash lookup
  -> verified SHA-256/MD5 lookup
  -> normalized pixel hash
  -> pHash plus geometry candidate search
  -> crop/region candidate search when enabled
  -> URL/profile/tag/context corroboration
  -> reviewable post/work/account proposals
```

### Choosing a better-quality occurrence

Quality selection is evidence-based and reversible. Prefer, in order of confidence:

1. A provider-designated original from an explicitly linked upstream post.
2. A source post referenced by Pixiv ID or canonical source URL.
3. A larger, less-compressed occurrence with compatible dimensions/aspect ratio and matching work
   evidence.
4. A booru copy only when its bytes/dimensions or source metadata make it preferable.

Larger dimensions alone do not prove better quality because an image may be upscaled. Keep all
occurrences and record the assessment signals instead of overwriting the lower-quality copy.

`asset_quality_assessments`

- work/post-match candidate and asset/occurrence;
- classification such as `upstream_original`, `original_candidate`, `best_available`, `derivative`,
  `upscaled`, or `unknown`;
- dimensions, file size, MIME, source role, generation-loss indicators, and scoring details;
- matcher/version, confidence, review state, reviewer note, and timestamps.

## 13. Media download and storage

Downloads are explicit jobs and must be safe to interrupt.

Required behavior:

- validate HTTPS and adapter-approved hosts/redirects;
- use provider-required cookies/referer without logging secrets;
- stream to a uniquely named temporary file;
- enforce content-length and streamed byte limits;
- validate response status, type, and decodability;
- compute SHA-256 and MD5 while streaming;
- inspect dimensions/MIME after completion;
- compute pHash for supported raster images;
- atomically move verified bytes into content-addressed storage;
- keep original bytes immutable;
- register every remote occurrence/source against the stored asset;
- persist retryable/permanent error state and response metadata;
- quarantine declared-hash mismatches instead of silently accepting them.

Suggested layout:

```text
media/
  sha256/
    ab/
      cd/
        abcdef...<extension>
  staging/
  quarantine/
```

The database is authoritative for filenames, accounts, posts, and provenance. Paths do not expose
handles or display names.

## 14. Discovery and crawl policy

Discovery is metadata-first and bounded.

A new crawl must specify:

- the seed and why it was selected;
- allowed platform/adapter and target;
- maximum posts, pages, requests, runtime, and optional bytes;
- earliest/latest date where appropriate;
- metadata-only or media policy;
- credential reference;
- resume/retry policy.

Default behavior:

- network disabled unless the command explicitly enables it;
- metadata-only unless downloads are explicitly enabled;
- dry-run prints estimated targets and request budget;
- count probes run before large booru queries;
- account expansion requires a confirmed link or an explicit one-off override;
- child/external URLs are recorded as discovery candidates, not automatically traversed;
- crawling additional posts creates `discovered`/`crawled` events and never labels them liked or
  bookmarked;
- 429 and provider cooldowns persist a future retry time instead of busy-waiting.

Example commands:

```text
catalog crawl account pixiv:12345 --network --metadata-only --limit 100 --dry-run
catalog crawl account pixiv:12345 --network --metadata-only --limit 100 --resume
catalog assets download --account pixiv:12345 --limit 25 --max-bytes 2G
```

## 15. CLI plan

```text
catalog init PATH

catalog ingest x-likes-db LIKES.sqlite --catalog PATH
catalog ingest xarchive BOOKMARKS.json --catalog PATH
catalog ingest gallery-dl-jsonl RECORDS.jsonl --catalog PATH

catalog stats
catalog search QUERY [filters]
catalog account show PLATFORM:NATIVE_ID
catalog post show PLATFORM:NATIVE_ID

catalog links propose [filters]
catalog links list --state candidate
catalog links confirm CANDIDATE_ID
catalog links reject CANDIDATE_ID

catalog crawl account PLATFORM:NATIVE_ID --metadata-only --limit N
catalog crawl query PLATFORM QUERY --metadata-only --limit N
catalog jobs list
catalog jobs resume JOB_ID

catalog assets download [filters] --limit N
catalog assets verify [filters]
catalog assets match [filters]

catalog export --format jsonl|csv
catalog doctor
catalog backup DESTINATION
```

All commands support structured JSON output. Logs redact credentials, cookie paths, private source
paths, and raw profile/post text by default.

## 16. Migration strategy

### Existing `x-likes` database

Import rather than modify:

- account rows become X accounts and account snapshots;
- post rows become X posts;
- the legacy import becomes an `import_run`;
- each imported liked post receives a `liked` event;
- media rows become occurrences and, when downloaded, verified assets;
- existing MD5/SHA-256/pHash/local paths remain preserved;
- legacy MD5/SHA-256/pHash values map to verified asset hashes because `x_likes` computed them from
  downloaded bytes; they never map to provider-declared hash fields;
- fetch/download errors and unavailable reasons become observations/job state;
- raw JSON remains attached to raw observations.

### xarchive bookmarks

- import every bookmark as an X post plus a `bookmarked` event;
- preserve folder assignments as event/collection metadata;
- import media variants, quotes, cards, entities, and metrics;
- retain unavailable records;
- absent account fields remain unknown instead of receiving synthetic handles;
- preserve the full raw bookmark object.

### Reconciliation

- reconcile by `(platform, native ID)`, never by URL text alone;
- repeated imports are idempotent;
- an import report compares source and target counts for accounts, posts, events, occurrences,
  downloaded assets, errors, and unavailable records;
- old files/databases remain read-only until the report passes and a backup exists.

## 17. Delivery phases

### M0: contracts and live-fixture research

Deliverables:

- approve this glossary and source policy;
- define namespaced ID formatting and adapter result/error types;
- create a redacted fixture matrix for X, Pixiv, Danbooru, AIBooru, and e621;
- capture small live responses, pagination, deleted/unavailable, 429, and auth failures;
- document provider terms, practical rate limits, and credential method;
- decide the catalog CLI/package name.

Exit criteria:

- every normalized field is backed by a current fixture or marked optional/unknown;
- no credential appears in source, fixtures, logs, or the catalog;
- unknown response fields round-trip through raw storage.

### M1: core schema and migrations

Deliverables:

- `media_catalog` package and CLI skeleton;
- `pyproject.toml` wheel packaging and a `catalog` console-script entry for the new package;
- numbered SQL migrations;
- source, account, snapshot, post, participant, observation, media occurrence, asset, raw
  observation, and import-run tables;
- deterministic platform/native ID handling;
- database integrity and summary commands;
- runtime FTS5 capability probe.

Exit criteria:

- fresh creation and upgrade tests pass on Python 3.13;
- foreign-key checks pass;
- two platforms can both store native ID `123` without collision;
- no X/Pixiv/booru-specific column leaks into the core tables.

### M2: legacy X ingestion

Deliverables:

- existing `x-likes` DB importer;
- xarchive bookmark importer;
- raw-input digest/provenance and idempotent import keys;
- reconciliation report;
- search/stats over liked versus bookmarked events.

Exit criteria:

- repeat imports produce no duplicate posts/events/media;
- source-to-target counts reconcile;
- unavailable/tombstone records and all raw JSON survive;
- current `x-likes` CLI and tests remain operational.

### M3: assets and safe downloading

Deliverables:

- metadata-only media occurrence ingestion;
- download jobs with budgets, retries, checkpoints, and atomic staging;
- content-addressed storage;
- verified SHA-256/MD5, dimensions, MIME, and image pHash;
- exact duplicate and perceptual candidate queries;
- verify/quarantine tooling.

Exit criteria:

- offline commands make zero HTTP requests;
- interrupted downloads resume or retry safely;
- identical bytes share one asset while retaining all occurrences;
- declared hash mismatches are visible and never silently accepted.

### M4: Pixiv and Danbooru-family adapters

Deliverables:

- Pixiv profile, user artworks, artwork pages, tags, source metadata, and cursors;
- Danbooru post/artist/tag/source/uploader metadata and pagination;
- one additional instance adapter, initially AIBooru or e621;
- external credential configuration;
- bounded live smoke tests disabled by default;
- gallery-dl JSON bridge prototype for comparison and unsupported sites.

Exit criteria:

- redacted fixture parity tests pass;
- each live command has request/post/time limits;
- booru uploader and artist attribution remain separate;
- Pixiv multi-page order and original URLs are preserved;
- provider MD5 is stored distinctly from verified MD5.

### M5: identity and matching

Deliverables:

- identity, account-link, and evidence tables;
- explicit profile/source URL candidate generation;
- account alias/history handling;
- asset/post matching pipeline;
- explainable scoring with algorithm versions;
- manual review CLI.

Exit criteria:

- no candidate is auto-confirmed from a handle or hash alone;
- creator/uploader roles remain visible in every proposal;
- confirmation/rejection is reversible and audited;
- tests include impersonation, repost, handle-reuse, and false-pHash examples.

### M6: discovery and bounded expansion

Deliverables:

- crawl job/run/checkpoint tables and runner;
- account and query discovery commands;
- count/estimate and dry-run behavior;
- metadata-first expansion from confirmed/allowed links;
- resumable cursors and per-host backoff;
- selected media download from discovered posts.

Exit criteria:

- no account crawl can run without an explicit limit/policy;
- kill-and-resume tests do not duplicate or skip committed pages;
- discovered posts never inherit liked/bookmarked state;
- rate-limit cooldown survives process restart.

### M7: operations and maintenance

Deliverables:

- JSONL/CSV export;
- backup, restore, integrity, and repair commands;
- retention/redaction policies for raw observations;
- schema and adapter version reporting;
- usage guides and troubleshooting;
- migration/deprecation path for direct writes by `x-likes`.

Exit criteria:

- backup/restore round-trip passes integrity and count checks;
- a provider schema change produces a bounded, diagnosable failure;
- private exports and catalog/media directories are ignored by version control.

## 18. Time-boxed research spikes

| Spike | Method | Required output | Exit condition |
| --- | --- | --- | --- |
| X author/bookmark response | Capture redacted current raw timeline and tweet-detail fixtures | Field/path map, cursors, tombstones, rate-limit errors | Parser contract tests pass |
| Pixiv auth and profiles | Use isolated gallery-dl/Pixiv credentials on one owned/accessible profile | Redacted user/artwork/page fixtures, token lifecycle, request counts | Profile plus 2-page artwork listing repeats reliably |
| Pixiv original/ugoira | Inspect one multi-page work and one Ugoira | Original URL, page ordering, frame/archive metadata | Lossless metadata round-trip fixture |
| Danbooru source matching | Query one post by ID, MD5, source, and Pixiv ID | Query syntax, response fields, not-found behavior | Same post reconciles across queries |
| Artist URL semantics | Inspect artist objects/URLs/aliases/deprecation | Evidence mapping and update cursor | No artist tag is modeled as confirmed identity |
| Booru pagination | Compare page numbers and keyset cursors | Checkpoint design and end conditions | Restart resumes without gaps/duplicates |
| gallery-dl bridge | Run pinned isolated `-j` JSONL for X/Pixiv/Danbooru fixtures | Record grammar, version/config capture, timeout/error behavior | Importer handles Directory/URL/Queue/error records |
| Declared hash verification | Download a small permitted sample with provider MD5 | Declared-versus-verified result and mismatch policy | Exact and mismatch tests pass |
| pHash thresholds | Curate originals, recompresses, crops, thumbnails, unrelated images | Distance distribution and candidate threshold | False-positive set is documented |
| Terms/rate policy | Review each provider's current access rules and observed headers | Per-platform policy record | Adapter cannot run without a policy |

## 19. Dependencies and tooling

Keep the core lean:

- standard library: `sqlite3`, `hashlib`, `json`, `pathlib`, `subprocess`;
- existing `httpx` for native HTTP adapters;
- existing Pillow and `imagehash` for image inspection and pHash;
- pytest and injected/mock HTTP transports for deterministic adapter tests;
- Ruff for linting;
- optional `ffmpeg`/`ffprobe` executable for Ugoira/video conversion or later frame analysis;
- optional pinned gallery-dl executable in an isolated environment.

Initial secret handling uses either environment variables or a user-owned configuration file
outside the repository with restrictive permissions. Jobs store only a credential-profile name.
The gallery-dl bridge receives a short-lived generated config in a private temporary directory and
deletes it after the subprocess exits. OS keyring support can be added later if this proves awkward.

Do not add initially:

- a heavyweight ORM;
- vector databases or embedding frameworks;
- a task queue/server when a resumable local job runner suffices;
- gallery-dl as an imported internal library.

Numbered SQL migrations, explicit dataclasses/protocols, fixture-driven parsers, and a single-process
job runner are sufficient for the first several phases.

## 20. Test strategy

Required automated coverage:

- fresh schema creation and every migration path;
- foreign-key and integrity checks;
- platform/native ID collision cases;
- idempotent x-likes and xarchive imports;
- missing/unknown fields and raw JSON round-trip;
- account snapshots and handle reuse;
- booru uploader versus artist-role preservation;
- unavailable/deleted/tombstone records;
- adapter pagination, cursor resume, 429, 5xx, timeout, and malformed JSON;
- explicit network-off guarantees;
- request/post/page/byte budget enforcement;
- safe URL/redirect/content-type/size handling;
- staging cleanup and atomic asset placement;
- declared versus verified hashes;
- exact, pixel-equivalent, pHash, crop, and false-positive samples;
- candidate evidence explanations and reversible reviews;
- gallery-dl JSON/JSONL and error-record parsing;
- CLI structured-output golden tests;
- backup/restore and reconciliation counts.

Live tests must be opt-in, tiny, read-only where possible, redacted, and separated from the default
test suite.

## 21. Security, privacy, and operational policy

- Keep archives, databases, downloaded media, cookies, tokens, and raw fixtures outside Git.
- Add narrow ignore rules before creating predictable local output directories.
- Never put API keys or tokens in URLs that are logged; prefer auth headers/basic auth where the
  provider supports it.
- Store secret references, not secret values, in jobs.
- Redact raw text, profile fields, paths, URLs with tokens, and headers from default logs.
- Restrict gallery-dl subprocess config, environment, working directory, timeout, and child
  extractor whitelist.
- Validate all remote hosts and redirects through the active adapter.
- Preserve deletions/tombstones as state while supporting user-requested local purge/redaction.
- Record adapter version, request identity, and raw payload digest for every live normalization.
- Review current provider terms and access rules before enabling each live adapter.

## 22. Principal risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Internal APIs change | Redacted fixtures, raw retention, adapter versioning, small health checks |
| Identity false positives | Evidence ledger, conservative candidates, manual confirmation |
| Uploader mistaken for artist | Roleful attribution and source-specific semantics |
| Re-encoded/cropped images do not exact-match | Layered hashes and reviewable similarity relationships |
| Provider MD5 is wrong or stale | Separate declared and verified hash fields |
| Signed media URLs expire | Preserve occurrence, refresh metadata before download |
| Unbounded crawl/account lockout | Explicit budgets, count probes, cursors, cooldown persistence |
| Handle changes break paths/identity | Stable native IDs, snapshots, content-addressed storage |
| Scraper dependency drifts | Native contracts plus pinned subprocess bridge |
| Private exports or credentials enter Git | Narrow ignores, redacted fixtures, secret scanning |
| Original bytes are accidentally transformed | Immutable CAS; derivatives stored as separate assets |

## 23. First implementation backlog

The first coding tranche should be limited to M0-M2:

1. Decide the `media_catalog`/`catalog` name and database location convention.
2. Add platform/native ID helpers and adapter record dataclasses.
3. Add migrations for platforms, imports, raw observations, accounts/snapshots, posts,
   participants, user events, media occurrences, and assets.
4. Implement fresh/create/upgrade/integrity database tests.
5. Implement the existing `x-likes` DB importer and reconciliation report.
6. Implement the xarchive bookmark importer without network access.
7. Add `catalog stats`, `catalog account show`, `catalog post show`, and event-filtered search.
8. Check in small synthetic/redacted fixtures only.
9. Add narrow ignores for catalog databases, raw exports, fixtures under investigation, staging,
   and downloaded media.
10. Review this foundation before adding any new live platform adapter.

This sequence creates a durable home for existing data before introducing additional network and
identity-matching complexity.
