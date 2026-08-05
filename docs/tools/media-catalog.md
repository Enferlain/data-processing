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

## Recovery and reconciliation

- A malformed import rolls back normalized records, records a failed import run, and retains a
  bounded diagnostic and failure counts.
- Source databases and JSON exports remain unchanged; keep them as recovery inputs.
- Run `catalog doctor` after importing or restoring a backup.
- Likes and bookmarks are separate observations. A post present in both sources remains one X post
  with independently queryable `liked` and `bookmarked` provenance.

The existing online `x-likes` workflow remains documented in [its guide](x-likes.md). Network
adapters, content-addressed downloads, Pixiv/booru matching, and identity review are later catalog
changes, not hidden behavior of these import commands.
