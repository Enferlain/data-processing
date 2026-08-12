## Why

The catalog can already review cross-platform leads, synchronize provider metadata, browse media,
and acquire selected files, but using those capabilities as one artist-library workflow still
requires manually translating internal IDs and provider targets between commands. The next
milestone should connect those existing parts with an explicit, bounded, provenance-preserving
handoff rather than introducing another crawler or downloader.

## What Changes

- Add typed expansion targets for stable provider accounts and provider attribution records without
  conflating a booru artist/tag with an owned platform account.
- Add an offline expansion planner that resolves a confirmed or explicitly selected catalog seed,
  reports supported operations and exclusions, uses retained estimates when available, and records
  unknown estimates honestly.
- Add explicit execution and resume workflows that delegate metadata-only enumeration to the
  existing adapter, request-budget, raw-retention, persistence, and checkpoint machinery.
- Durably associate each expansion with its seed, selection or review provenance, resolved target,
  immutable limits, and underlying metadata run.
- Return stable browse filters and occurrence selections that feed the existing media browser and
  acquisition planner after enumeration.
- Keep count probes, enumeration, and acquisition as separate explicit operations; never recurse
  through discovered links or accounts, implicitly download media, or assign discovered posts a
  liked/bookmarked event.

## Capabilities

### New Capabilities

- `artist-library-expansion`: Resolve, plan, execute, resume, and inspect bounded metadata-first
  expansion from a reviewed or explicitly selected target, with typed attribution boundaries and
  handoffs to existing browsing and acquisition workflows.

### Modified Capabilities

None.

## Impact

- Adds a focused artist-library orchestration/query package and `catalog library` CLI surface.
- Adds versioned persistence for expansion plans/runs and their references to existing catalog,
  review, and remote metadata records.
- Reuses the current Pixiv and Danbooru-family adapters, `MetadataSyncService`, media browser, and
  acquisition planner without changing their standalone contracts.
- Adds offline planning/query tests, injected-network execution/resume tests, migration coverage,
  CLI documentation, roadmap status, and changelog entries.
- Adds no provider, similarity algorithm, recursive traversal, automatic review decision, media
  downloader, or managed-storage implementation.
