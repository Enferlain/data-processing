## Why

The existing `x_likes` database is useful for X-specific archiving, but it cannot safely represent
accounts, posts, media, and provenance from several platforms or distinguish likes from bookmarks
as durable observations. A platform-neutral foundation is needed before adding Pixiv, booru,
identity-matching, and higher-quality media discovery workflows.

## What Changes

- Add a new `media_catalog` package and `catalog` CLI alongside the existing `x_likes` tool.
- Add a versioned SQLite catalog schema for platforms, accounts and snapshots, posts and
  participants, observations, media occurrences, assets, raw provider records, and import runs.
- Namespace all remote identifiers by platform and retain unknown provider fields in raw JSON.
- Add database initialization, migration, integrity-check, summary, search, and stats operations.
- Add idempotent importers for an existing `x-likes` SQLite database and xarchive bookmark JSON.
- Preserve likes and bookmarks as separate provenance observations and report reconciliation counts.
- Keep the existing `x-likes` CLI and database unchanged as a supported compatibility source.

## Capabilities

### New Capabilities

- `media-catalog-core`: Create and operate a platform-neutral, migration-managed local catalog with
  durable provenance, raw-record retention, integrity checks, and queryable account/post/media data.
- `x-seed-import`: Import existing X likes databases and xarchive bookmark exports idempotently,
  preserving their distinct observation types and reconciling source and catalog counts.

### Modified Capabilities

None.

## Impact

- Adds `src/media_catalog/`, SQL migrations, a `catalog` console entry point, and catalog-focused
  tests and documentation.
- Updates Python packaging in `pyproject.toml` while retaining the current `x-likes` entry point.
- Uses SQLite and existing project dependencies; no network access or media download is required for
  this change.
- Reads legacy `x_likes` databases and xarchive JSON as immutable inputs and writes only to a new
  catalog database selected by the user.
