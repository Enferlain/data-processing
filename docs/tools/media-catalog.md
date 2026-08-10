# `catalog` usage guide

`catalog` builds an offline, platform-neutral SQLite catalog from local data sources. The first
supported sources are databases created by `x-likes` and bookmark JSON exported by xarchive.
Importing never contacts X or downloads media.

## Setup

Use Python 3.13 and `uv` from the repository root:

```bash
uv sync
uv run catalog --help
```

Keep source exports and catalog databases private. The repository ignores `catalog-output/` and
`private-exports/`; custom paths inside the repository are not automatically ignored.

## Create and inspect a catalog

```bash
uv run catalog init catalog-output/catalog.sqlite3
uv run catalog schema catalog-output/catalog.sqlite3
uv run catalog doctor catalog-output/catalog.sqlite3
```

`doctor` runs SQLite integrity and foreign-key checks. Stop catalog commands before copying the
database for backup so its WAL sidecar is fully checkpointed.

## Import existing likes

First create a legacy database with `x-likes`, then import it without modifying the source:

```bash
uv run catalog ingest x-likes-db /private/x-likes/likes.sqlite3 \
  --catalog catalog-output/catalog.sqlite3
```

Accounts, profile metadata, posts, unavailable/tombstone state, liked observations, media URLs,
raw JSON, and existing locally calculated MD5/SHA-256/pHash values are retained. Existing media
paths are non-owning references; files are not copied. Missing referenced files produce warnings.

## Import xarchive bookmarks

```bash
uv run catalog ingest xarchive /private/bookmarks.json \
  --catalog catalog-output/catalog.sqlite3
```

The importer retains raw bookmark objects and normalizes posts, real account fields, folders,
ordered media, video variants, replies, and quotes. Missing account fields remain null; it does not
invent `User <id>` names or `user_<id>` handles.

Every exact source file is identified by SHA-256. Repeating the same import is a reported no-op.
Overlapping newer exports reconcile by platform/native ID and report inserted, updated, existing,
skipped, and failed counts without duplicating liked/bookmarked events.

## Search and statistics

```bash
uv run catalog stats catalog-output/catalog.sqlite3
uv run catalog stats catalog-output/catalog.sqlite3 --event bookmarked
uv run catalog search catalog-output/catalog.sqlite3 "artist name"
uv run catalog search catalog-output/catalog.sqlite3 "watercolor" --event liked
```

Search covers post text and the latest author handle, display name, and bio. It uses SQLite FTS5
when available and otherwise reports `search_backend: like` while retaining the same result shape.

Add `--json` to any command for structured output:

```bash
uv run catalog stats catalog-output/catalog.sqlite3 --event bookmarked --json
```

Default output and errors show source/catalog basenames rather than absolute private paths. Raw
profile and post content is not printed by inspection or import summaries.

## Discover external links offline

Back up the catalog, then derive links already present in normalized profiles/posts and retained
X/xarchive JSON:

```bash
uv run catalog discover-links catalog-output/catalog.sqlite3
uv run catalog links catalog-output/catalog.sqlite3 --platform pixiv
uv run catalog links catalog-output/catalog.sqlite3 --subject-kind account --object-kind account
uv run catalog links catalog-output/catalog.sqlite3 --subject-kind post --subject-id 42
uv run catalog links catalog-output/catalog.sqlite3 --state unresolved --json
```

Discovery never follows redirects or contacts a site. It keeps the original URL, conservative
canonical URL, source field/JSON path, algorithm versions, and recognized instance-qualified ID.
Shorteners, link hubs, personal sites, malformed URLs, and unsupported routes remain visible with a
bounded resolution state instead of being guessed. Repeating discovery is safe: observations,
references, candidates, and evidence use stable identities, while each run retains its own counts.
Distinct URL aliases remain attached to the same semantic reference instead of replacing one
another. Link output includes `identifier_kind`: `stable_id` values may support matching, while
mutable `handle` or `slug` values and `hash`/`opaque` identifiers remain typed reference evidence.

## Inspect and review matches

Profile links can produce account candidates; links from posts to artworks/posts can produce post
source candidates. They are separate claims—post-source evidence does not establish artist identity.

```bash
uv run catalog matches catalog-output/catalog.sqlite3 --state pending
uv run catalog matches catalog-output/catalog.sqlite3 --kind post --json
uv run catalog match-show catalog-output/catalog.sqlite3 post:1
uv run catalog match-review catalog-output/catalog.sqlite3 post:1 \
  --decision confirm --note "checked source metadata" --expected-revision 0
uv run catalog match-review catalog-output/catalog.sqlite3 account:1 \
  --decision reject --note "different artist"
```

Scores are deterministic review-order hints, never confirmations. Decisions are append-only;
reconsidering a candidate adds history. Use the `review_revision` shown by `match-show` as
`--expected-revision` to reject a concurrent stale decision. Reversing an account confirmation
rebuilds active identity memberships from the remaining confirmed pair decisions. Confirming a
supported `stable_id` account reference may create a metadata-empty local account and identity
membership, but never invents a handle, display name,
bio, or transitive pair confirmation. Conflicting existing identity groups are reported for review.

Current discovery records manually supplied broad relation/variation facts but does not fetch media,
calculate MD5/pHash, compare pixels, choose originals, crawl accounts, or pull additional works.
Those are boundaries for future network adapters and image/work matching. Booru hashes and source
URLs are evidence, not proof of authorship. Keep private exports and catalog backups out of version
control, and run `catalog doctor` after restoring or migrating a catalog.

## Synchronize Pixiv and booru metadata

Metadata synchronization is explicit, finite, and separate from media acquisition. Each command
records an auditable run, sanitized request attempts, retained JSON responses, normalized records,
and (for listings) an opaque committed checkpoint. It never requests an image URL or creates an
asset. Back up the catalog before its first migration to this feature.

```bash
uv run catalog metadata pixiv-profile catalog-output/catalog.sqlite3 1001 --json
uv run catalog metadata pixiv-artwork catalog-output/catalog.sqlite3 2001 --json
uv run catalog metadata pixiv-account-artworks catalog-output/catalog.sqlite3 1001 \
  --max-requests 3 --max-pages 2 --max-records 500 --max-seconds 60

uv run catalog metadata danbooru-post catalog-output/catalog.sqlite3 3001
uv run catalog metadata danbooru-artist catalog-output/catalog.sqlite3 4001
uv run catalog metadata danbooru-list catalog-output/catalog.sqlite3 artist_a \
  --max-requests 3 --max-pages 2 --max-records 500
```

The corresponding `aibooru-post`, `aibooru-artist`, and `aibooru-list` commands use an independent
platform identity. All defaults are finite and can be lowered. A listing stopped at a budget
boundary reports `status: paused`; continue only from its committed checkpoint:

```bash
uv run catalog metadata pixiv-account-artworks catalog-output/catalog.sqlite3 1001 \
  --resume-from 12 --max-requests 3 --max-pages 2 --max-records 500
```

Pixiv refresh authentication reads `PIXIV_REFRESH_TOKEN`, `PIXIV_CLIENT_ID`, and
`PIXIV_CLIENT_SECRET`; client values are deliberately not embedded here. Booru credentials are
optional for public records and use `DANBOORU_LOGIN` plus `DANBOORU_API_KEY`, or the corresponding
`AIBOORU_LOGIN` and `AIBOORU_API_KEY`. Credentials are resolved at request time and excluded from
request identities, database diagnostics, structured output, and retained provider payloads.
Pixiv uses an unofficial app API and may need adapter updates when its contract changes. Provider
permissions, deletions, and rate limits remain typed outcomes rather than guessed records.

Inspect past runs without network access or credentials:

```bash
uv run catalog metadata runs catalog-output/catalog.sqlite3 --json
uv run catalog metadata run-show catalog-output/catalog.sqlite3 12 --json
```

Pixiv accounts and artworks use stable numeric IDs; names remain temporal metadata. Artwork page
order, original/translated tags, URL variants, and Ugoira archive/frame timing are metadata only.
Danbooru-family uploader IDs create uploader accounts, while artist records remain neutral
attribution entities with names and URLs. A booru `source` or `pixiv_id` is evidence, not an
automatic creator, account, post-equivalence, or work match. Provider MD5 remains a declared
occurrence assertion until the separate asset workflow verifies bytes.

Adapter fixtures live under `tests/fixtures/metadata_adapters/`. Regenerate only minimal responses,
replace personal names and URLs, remove credentials/cookies, retain no media bytes, and update the
manifest capture date plus adapter/schema version. Expected mappings were reviewed against
gallery-dl 1.32.2 commit `2e88d6ae29780dbed02e4a5172a1aa0a1b1c91b5` as a comparison oracle;
gallery-dl is not imported or executed by normal tests.

## Adopt existing local media

Asset adoption copies files already referenced by the catalog into immutable, SHA-256-addressed
managed storage. It is offline: it never downloads a remote-only occurrence. Before the first
adoption, stop catalog commands and make a backup of the catalog and its source database. The
source tree is read-only to the adopter and remains your recovery input.

Use separate, non-overlapping source and media roots. Start with a read-only plan:

```bash
uv run catalog assets plan catalog-output/catalog.sqlite3 \
  --source-root /private/x-likes --media-root /private/catalog-media
uv run catalog assets adopt catalog-output/catalog.sqlite3 \
  --source-root /private/x-likes --media-root /private/catalog-media \
  --max-files 100 --max-bytes 134217728 --max-pixels 100000000 --max-frames 100
```

Planning opens the catalog without migration and creates no database sidecar or media-root layout.
It reports the number and known total size of eligible references so you can allow for the temporary
disk cost of copying source bytes. If the schema is old, first back it up and run a normal mutating
command such as `catalog schema` to apply migrations, then plan again. Plan and verify also fail
closed when the catalog still has uncheckpointed WAL frames: stop mutating catalog processes,
complete the normal checkpoint/backup workflow, and retry instead of deleting SQLite sidecars.

Adoption verifies SHA-256 and MD5 before decoding, applies hard byte/pixel/frame limits, and stores
supported raster dimensions and a versioned pHash. Other valid content is retained as exact-only.
Managed files have paths derived only from SHA-256; duplicate bytes share one file while distinct
occurrence/source paths remain recorded. An imported exact-hash disagreement is a failure and does
not silently replace the imported assertion.

Inspect results and managed storage with:

```bash
uv run catalog assets list catalog-output/catalog.sqlite3
uv run catalog assets show catalog-output/catalog.sqlite3 1 --json
uv run catalog assets duplicates catalog-output/catalog.sqlite3
uv run catalog assets runs catalog-output/catalog.sqlite3
uv run catalog assets failures catalog-output/catalog.sqlite3
uv run catalog assets verify catalog-output/catalog.sqlite3 \
  --media-root /private/catalog-media --json
```

Rerunning adoption is safe: completed bytes, locations, occurrence links, and provenance are reused.
Each item commits independently, so a stopped run can leave valid completed files and may leave a
staging entry. Verification is strictly read-only and reports valid, missing, corrupt, orphaned,
unsafe, and stale-staging entries; it never repairs or deletes them. Preserve reported staging and
orphan files until you have inspected the interrupted run and restored or backed up the catalog.
The current fail-closed cleanup policy can retain a verified staging hard-link even after success,
because pathname unlink cannot atomically prove inode ownership under substitution. If this run
created the CAS target, the residue shares its inode and costs only another directory entry. If the
target already existed, or failure happened before publication, residue can retain a full staged
copy, so reserve suitable disk headroom. Removal belongs to a future explicit repair workflow.
Absolute roots are redacted from normal human and JSON output.
Legacy asset-level paths from older catalogs are never printed by asset list/show; only their
ambiguous/unassociated classification and bounded counts are exposed.

## Recovery and reconciliation

- A malformed import rolls back normalized records, records a failed import run, and retains a
  bounded diagnostic and failure counts.
- Source databases and JSON exports remain unchanged; keep them as recovery inputs.
- Run `catalog doctor` after importing or restoring a backup.
- Likes and bookmarks are separate observations. A post present in both sources remains one X post
  with independently queryable `liked` and `bookmarked` provenance.

The existing online `x-likes` workflow remains documented in [its guide](x-likes.md). Media
downloads, perceptual similarity decisions, and image/work matching remain later catalog changes,
not hidden behavior of metadata commands.
