## Context

See `proposal.md` for motivation and the two capability specs for observable behavior. The existing
`x_likes` package has one SQLite schema whose `author_id` and `post_id` primary keys assume X, whose
media rows combine remote occurrences with downloaded-file state, and whose CLI creates
`likes.sqlite3` directly. It must remain operational while a new catalog is introduced beside it.

The first supported bookmark input is xarchive JSON with top-level `bookmarks`, `folders`, and
`export_metadata` members. Bookmark records can contain an author, media, folders, entities, cards,
quoted posts, metrics, status, and reply/conversation identifiers, but account fields are optional.
Both source formats are private, local inputs. This change is offline and targets Python 3.13.

## Goals / Non-Goals

**Goals:**

- Establish stable storage boundaries that later Pixiv and booru adapters can use unchanged.
- Make normalized artist/account and post/media metadata immediately queryable while preserving the
  complete raw source record.
- Give imports deterministic identity, transactional behavior, and machine-readable reconciliation.
- Keep migrations explicit and testable without introducing an ORM.
- Preserve downloaded-file metadata from `x_likes` without copying or rewriting media bytes.

**Non-Goals:**

- Network enrichment, account crawling, media downloading, identity matching, work grouping, or
  perceptual candidate generation.
- Treating an author/uploader relationship as proof of creative ownership.
- Moving legacy media into content-addressed storage during import.
- Replacing or directly migrating the existing `x_likes` database in place.

## Decisions

### 1. Add a parallel package and CLI

Create `src/media_catalog/` with a `catalog` console entry point while leaving `src/x_likes/` and
`x-likes` intact. The catalog CLI uses subcommands:

```text
catalog init CATALOG
catalog schema CATALOG [--json]
catalog doctor CATALOG [--json]
catalog stats CATALOG [--event liked|bookmarked] [--json]
catalog search CATALOG QUERY [--event liked|bookmarked] [--json]
catalog ingest x-likes-db SOURCE --catalog CATALOG [--json]
catalog ingest xarchive SOURCE --catalog CATALOG [--json]
```

`--json` writes one stable JSON document to stdout; diagnostics go to stderr. Private source paths
are reduced to a basename in normal output, while the catalog retains a user-configurable source
reference plus its digest.

Alternative considered: extend the existing CLI and database. Rejected because it would entrench
X-specific identifiers and make compatibility and rollback harder.

### 2. Use explicit numbered SQL migrations

Package migrations as `src/media_catalog/migrations/NNNN_description.sql`. A small migration runner
uses `PRAGMA user_version`, enables foreign keys on every connection, and applies each migration in
an exclusive transaction. Opening a newer schema is a hard error. WAL is enabled for writable local
catalog connections, with a bounded busy timeout.

The initial schema remains plain SQLite. Constraints, foreign keys, and partial/covering indexes are
declared in SQL and exercised by migration tests. FTS5 is probed at runtime. If available, rebuildable
virtual indexes are created and refreshed by catalog writes; otherwise parameterized escaped `LIKE`
queries use normalized indexed columns.

Alternative considered: an ORM migration framework. Rejected because the project is local-first,
SQLite-specific, and benefits from reviewable SQL and a small dependency surface.

### 3. Separate stable objects, observations, snapshots, and raw payloads

The initial migration contains these groups:

- Registry: `platforms` with a stable key (`x` initially), display metadata, and optional adapter
  metadata.
- Import audit: `import_runs`, `import_run_counts`, and bounded `import_diagnostics`.
- Raw retention: content-deduplicated `raw_payloads` keyed by SHA-256 plus `raw_observations` that
  associate a payload with an import run, object kind/native identifier, observation time, source
  schema hint, and status.
- Accounts: `accounts` unique on `(platform_id, native_account_id)` and append-only
  `account_snapshots` referencing the raw observation that produced each snapshot.
- Posts: `posts` unique on `(platform_id, native_post_id)`, `post_participants` with an explicit role,
  and `post_relations` for quote/reply/repost relationships present in imported data.
- Provenance: `observations` with subject kind/id, event type, stable source event key, import run,
  event time, collection/folder metadata, and raw observation. A uniqueness constraint on source kind
  plus source event key makes repeat imports idempotent without collapsing liked and bookmarked.
  Append-only `observation_revisions` retain later source/folder metadata without changing the stable
  user event or losing its earlier provenance.
- Media: `media_occurrences` unique on `(post_id, source_key)` with source order, type, remote URL,
  dimensions, alt text, availability, declared hashes, and raw observation.
- Assets: `assets` unique on verified SHA-256 with verified MD5/pHash, size and media metadata;
  `occurrence_assets` links occurrences to assets with a relationship and verification provenance.
  An imported legacy path is marked `storage_kind=legacy_reference`; no bytes are moved.

All provider-native identifiers are stored as text. Internal integer keys are implementation details;
external structured output renders stable references as `platform:native_id`. Core tables contain no
X-only columns. Source-specific fields that are not yet normalized remain in raw payloads.

Alternative considered: store provider objects only as JSON. Rejected because account history,
liked/bookmarked filters, post/media joins, and later cross-platform evidence must be queryable.

### 4. Persist through a narrow catalog writer contract

Import parsers produce immutable normalized records plus their raw payload and provenance. A catalog
writer owns SQL upserts and validates platform keys, native identifiers, roles, event types, media
order, timestamps, and hash formats. Importers do not execute ad hoc writes.

Upserts update current stable-object state but never replace snapshots, observations, import audit,
or raw-observation history. Snapshot deduplication uses an account ID plus a digest of the normalized
snapshot and observation identity, so identical data in a later source can retain its provenance
without multiplying indistinguishable snapshot rows.

Alternative considered: let each adapter write SQL. Rejected because source-specific write paths
would drift and make future schema migration unsafe.

### 5. Treat a source file as one auditable import unit

Before parsing records, stream SHA-256 over the source and create an `import_runs` row in `running`
state. Parse and normalized-data writes occur in a transaction. On success, commit records and mark
the run complete with per-entity source/inserted/updated/existing/skipped/failed counts. On failure,
roll back normalized changes, then mark the run failed in a separate transaction with a bounded,
redacted diagnostic. This gives atomic behavior for the expected export sizes while leaving room for
explicit checkpointed batches in a later large-import change.

The source digest identifies an exact import file; record-level source keys allow an updated export
to overlap an earlier one safely. A repeat of an already completed digest still creates or returns an
auditable no-op result, but it cannot duplicate observations or normalized objects.

Alternative considered: commit each record independently. Rejected for the foundation because it
weakens reconciliation and makes malformed mid-file imports surprising.

### 6. Map legacy x-likes data without reinterpreting it

Open the legacy SQLite database read-only and verify its required tables/columns before import.
Mapping rules are:

- `accounts` -> X account plus a timestamped snapshot; nullable values remain null.
- `posts` -> X post; author fields create an `author` participant only when a stable account ID is
  present; fetch/unavailable state is retained in normalized status and raw observation metadata.
- every source post -> a `liked` observation tied to the import run.
- `media` -> media occurrence; downloaded rows with a verified SHA-256 create/link an asset whose
  MD5/SHA-256/pHash are labeled as legacy locally verified hashes, never provider declarations.
- `local_path` -> a non-owning legacy reference. A missing file is reported but does not erase the
  row or cause an implicit download.
- account/post raw JSON -> deduplicated raw payloads connected through raw observations.

The importer never writes to, attaches for writing, or migrates the source database.

### 7. Map xarchive bookmarks conservatively

Validate the root shape and require a stable tweet ID for each normalized post. Map `tweet_id` to an
X post, `author.user_id` to an X account, real `screen_name`/`name` fields to an account snapshot,
and each media array entry to an ordered occurrence. Never synthesize a name or handle from a user
ID. Map folders to observation collection metadata, each bookmark to a `bookmarked` observation, and
quoted/reply identifiers to post relations when stable IDs exist.

Preserve the complete bookmark object as a raw payload. Metrics, cards, entities, export metadata,
and currently unnormalized author fields remain available there until later migrations promote them.
An invalid individual record aborts the initial atomic import with its array index and field-level
diagnostic; an optional tolerant mode is deferred until its partial-commit semantics are specified.

### 8. Make reconciliation and offline behavior testable

Each importer performs source counts before writes and target counts scoped to its stable source keys
after writes. Reports distinguish normalized objects from provenance events so an overlapping liked
and bookmarked post reports one post but two events. JSON output includes the import run ID, source
kind/digest, status, schema version, counts, warnings, and active search backend.

The package contains no HTTP client calls in this change. Tests patch socket connection creation to
fail during init, inspection, search, and both import paths. Fixture data is synthetic or redacted;
the user's private archive is never copied into tests or committed.

## Risks / Trade-offs

- [The initial table set is broad] -> Keep service APIs narrow, create only the indexes needed by
  foundation queries, and evolve fields through numbered migrations.
- [Whole-file transactions can be long for very large exports] -> Expected initial files are modest;
  measure import time and specify checkpointed batches separately if needed.
- [Legacy hashes may refer to files that have moved] -> Preserve the claimed verified hashes and path
  provenance, report missing paths, and defer byte re-verification to the asset-verification change.
- [xarchive shapes can evolve] -> Validate supported root/record shapes, retain raw payloads, and fail
  with a bounded schema diagnostic instead of silently dropping fields.
- [FTS behavior varies by Python/SQLite build] -> Probe capability at runtime and test both FTS5 and
  `LIKE` modes against the same result contract.
- [Raw payloads can contain private data] -> Ignore catalog/output paths in Git, avoid payloads in
  logs, and expose only summaries unless the user explicitly requests raw output.

## Migration Plan

1. Add the new package, CLI entry point, migration runner, and initial schema without changing
   `x_likes`.
2. Verify fresh creation, upgrade, future-version rejection, foreign keys, integrity, and both search
   backends on Python 3.13.
3. Add the read-only `x_likes` importer and synthetic legacy fixtures; verify idempotency and count
   reconciliation.
4. Add the xarchive importer and redacted/synthetic fixtures covering missing author fields, multiple
   media, folders, quotes, and unavailable records.
5. Run both importers against user-selected copies/paths, review reconciliation, and keep the source
   databases/exports unchanged.

Rollback is to stop using the new catalog and remove or archive its separate database. No rollback
touches the original `x_likes` database, xarchive JSON, or media files.
