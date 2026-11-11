# Investigate Danbooru/Gelbooru bootstrap indexes and incremental refresh

## Context

The Stage 2 search-index design currently treats Danbooru and Gelbooru as lacking the kind of official daily full-database export already used for e621. That is true in the narrow sense, but the stronger assumption that no usable post databases/datasets exist is incorrect.

There are several existing bulk metadata artifacts that could serve as **bootstrap sources** for local `lookup-v1` indexes. They should not necessarily be treated as long-term authoritative sources or assumed to remain current; the likely model is:

```text
bulk snapshot
    ↓
one-time/local bootstrap
    ↓
lookup-v1 base projection
    +
incremental provider API updates
    +
teach-on-result overlay
```

The goal of this investigation is to determine whether Danbooru and/or Gelbooru can become practical local index targets without requiring us to build a full crawler or depend indefinitely on third-party snapshot maintainers.

---

## Danbooru bulk-source candidates

Several full or near-full Danbooru metadata datasets currently exist.

Examples found:

- `nyanko-devs/danbooru2026`
  - includes a `posts-snapshot.parquet`
  - approximately 10.5M post rows
  - snapshot is not continuously current; roughly mid-2026

- `Jannchie/danbooru_metadata`
  - describes itself as metadata covering Danbooru posts
  - SQLite/downloadable dataset form
  - importantly, also includes an incremental/full Danbooru API update workflow (`update_danbooru.py`), demonstrating that snapshot + API synchronization is practical

- `trojblue/danbooru2025-metadata`
  - approximately 9M rows
  - useful as another schema/source candidate, but older

- `AngelBottomless/Booru-Parquets`
  - contains compact Danbooru Parquet variants
  - one interesting artifact is roughly a few hundred MB for ~9M posts
  - repository itself is older, so this should be treated as a bootstrap snapshot only

These mean Danbooru indexing is no longer blocked by the absence of a concrete artifact. The remaining questions are **which artifact has the right fields, provenance, license, completeness, and update semantics**.

Minimum fields we care about for a first projection:

```text
post id
md5
source URL(s)
updated_at
created_at
deletion/status state
artist/tag information if available
```

A compact artifact containing only the fields needed by `lookup-v1` may be preferable to a large rich metadata dump.

---

## Gelbooru bulk-source candidates

Gelbooru also has usable community metadata dumps.

Notable candidate:

- `AngelBottomless/Booru-Parquets`
  - `gelbooru.parquet`
  - approximately 3.6 GB
  - appears to contain post metadata rather than only tags
  - old enough that it must be considered a bootstrap source, not current truth

Other Gelbooru datasets exist, but some are unsuitable as canonical bootstrap sources:

- `nyanko-devs/gelbooru2026`
  - contains post metadata
  - intentionally curated/deduplicated against Danbooru
  - therefore not a complete Gelbooru mirror and unsuitable if the goal is faithful provider lookup coverage

There are also many Gelbooru **tag-only** datasets. Some datasets named like full databases or SQLite mirrors are actually tag tables only (`id`, `name`, `count`, `type`, etc.), so schema verification is required before treating anything as a post database.

---

## Freshness: snapshots are bootstrap material, not the refresh mechanism

Most third-party dumps are not sufficiently current to use as the sole local index source.

That is not necessarily a blocker.

An old but large snapshot still answers millions of historical:

```text
md5
source URL
provider post id
artist/tag
```

lookups locally.

Anything absent from the snapshot already falls through to existing live provider searches. A successful live lookup can then teach the local projection through the existing post-commit teach boundary.

The desired model is therefore:

```text
catalog
  ↓
local provider index
  ↓ miss
live exact provider lookup
  ↓ hit
normal catalog persistence
  ↓
teach local index
```

This is already compatible with the existing base-revision + overlay-generation model.

---

## Danbooru incremental refresh

Danbooru appears to be the cleaner provider for a maintained local index.

Its API exposes post timestamps including `updated_at`, stable post IDs, and cursor-style pagination.

A possible lifecycle:

```text
bootstrap snapshot

base:
  snapshot identity
  max post id
  updated_at watermark

periodic refresh:
  query posts updated since watermark - overlap
  deduplicate by post id
  upsert changed/new rows
  advance watermark only after successful completion
```

Use an overlap window rather than an exact boundary:

```text
stored watermark: 12:00

next refresh:
query >= 11:55
deduplicate
process all results
advance watermark
```

Reasons:

- multiple posts may share timestamps;
- page boundaries may split equal timestamps;
- an interrupted run must be replayable;
- clock and API ordering assumptions should not be trusted unnecessarily.

The refresh must catch not only newly created posts but existing posts whose source, tags, status, or other searchable metadata changed.

The existing `lookup-v1.<base-revision>.g<generation>` mechanism may be sufficient initially:

```text
bulk bootstrap
    ↓
base revision A, generation 0

API refresh changes rows
    ↓
generation 1

next refresh changes rows
    ↓
generation 2
```

Longer term, the mutable overlay can periodically be compacted into a new base projection if needed.

An alternative is to maintain explicit refresh state/watermarks separately from teach generation; this should be decided based on how large incremental refreshes become.

---

## Gelbooru incremental refresh

Gelbooru is less clean but still appears maintainable.

Relevant API concepts include:

- post IDs / paginated listings;
- `cid` change IDs;
- deletion listings / last IDs;
- ordinary exact lookup methods already supported by the catalog.

The public API documents `cid` as a change identifier / Unix timestamp, and multiple posts may share one value. Exact durable pagination semantics should therefore be verified against the live endpoint before designing a watermark around it.

Possible initial strategy:

```text
bootstrap old/full snapshot

new posts:
  walk forward/newest region past known max id

changed posts:
  use cid/change feed with overlap + dedup if live behavior proves reliable

deleted posts:
  consume deletion listing/feed

other old rows:
  refresh when encountered by normal live lookup
```

If `cid` proves awkward, a simpler first version is acceptable:

```text
new-post incremental sync
+
teach-on-result
+
periodic recent-window refresh
+
explicit deletion feed
```

We do not need a perfect Gelbooru mirror for discovery to benefit from millions of historical local lookup records.

---

## Interaction with existing teach-on-result behavior

The current Stage 2 design already has the useful distinction:

```text
base snapshot revision
+
mutable teach generation
```

This should be retained.

Provider API synchronization should not write directly into the primary catalog as mirrored truth. It should update the **disposable search projection**.

Search-index rows remain leads only. Normal provider fetch/reconciliation remains responsible for catalog facts and provenance.

Potential distinction to investigate:

```text
base snapshot
    imported bulk artifact

maintenance overlay
    provider incremental refresh

encountered overlay
    teach-on-result
```

These may be represented by one generation initially if that keeps the design simple, but the provenance/state should remain inspectable enough to answer:

- which bulk snapshot seeded this index?
- how current is the API-maintained portion?
- what refresh watermark was completed?
- which rows came only from encountered provider results?
- when was the index last successfully synchronized?

---

## Why Danbooru should probably be evaluated first

Danbooru currently looks like the stronger next candidate because:

1. multiple concrete bulk post-metadata artifacts already exist;
2. the API exposes a usable `updated_at` concept;
3. existing provider lookup/fetch support is already present;
4. incremental maintenance can likely be defined cleanly;
5. the recent real-catalog coverage analysis found MD5 misses from e621 that existing Danbooru live lookup may resolve;
6. a local Danbooru index would eliminate repeated live exact searches for those records over time.

Gelbooru remains useful, but its bulk sources are more community-dependent and its incremental-change semantics require more live verification.

---

## Investigation tasks

Before implementing either importer:

1. Inspect the current candidate Danbooru artifacts:
   - schema;
   - row count;
   - compressed/uncompressed size;
   - snapshot cutoff;
   - source provenance;
   - license;
   - presence/quality of `id`, `md5`, `source`, `updated_at`, deletion state, and artist/tag fields.

2. Determine whether a compact Danbooru artifact is sufficient for the existing post `lookup-v1` projection without importing unnecessary rich metadata.

3. Import/sample real rows into a temporary projection and test:
   - MD5 hit/miss;
   - source URL lookup;
   - post ID lookup;
   - URL normalization;
   - duplicate/source-array behavior;
   - deleted records;
   - lookup latency and projection size.

4. Verify Danbooru API incremental semantics on live data:
   - filtering/order by `updated_at`;
   - pagination behavior;
   - equal timestamps;
   - modification visibility;
   - safe overlap strategy.

5. Inspect the Gelbooru Parquet candidate independently:
   - confirm it really contains posts, not only tags;
   - determine snapshot age and completeness;
   - verify required lookup fields;
   - estimate projected SQLite size.

6. Verify Gelbooru live `cid`, deletion, and pagination semantics before defining a refresh watermark.

7. Compare expected disk and refresh cost with the already validated e621 projection:
   - e621 real validation: ~6.8M posts → ~4.2 GB `lookup-v1`;
   - use real candidate schemas to estimate whether normalized source indexes dominate size.

8. Keep third-party bulk snapshots clearly identified as bootstrap artifacts, not authoritative live provider observations.

---

## Expected outcome

The investigation should answer:

```text
Can Danbooru be bootstrapped from an existing snapshot?
Which snapshot should we trust as input?
How do we independently bring it current?
What refresh state/watermark is required?
Can the resulting projection use the existing lookup-v1 abstraction?

Can the same model be applied safely to Gelbooru?
If not, what smaller maintained-cache strategy is sufficient?
```

Do not build a generic bulk-dataset framework as part of this investigation.

The preferred outcome is a narrow provider-specific implementation using the existing search-index lifecycle:

```text
verified external snapshot
→ provider-specific importer
→ lookup-v1
→ bounded incremental refresh
→ teach-on-result
→ normal discovery/fetch pipeline
```

rather than making the primary catalog into a booru mirror.
