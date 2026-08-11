## Why

Remote metadata synchronization now creates posts, ordered media occurrences, named variants, and
downloadable source assertions, but the public catalog interface does not let users inspect those
records or obtain the occurrence IDs and variant keys required by explicit media acquisition.
Users should not need direct SQLite queries to move safely from synchronized metadata to a download
plan.

## What Changes

- Add read-only catalog queries for bounded, stably ordered media-occurrence listings with stable
  post identity and detailed occurrence inspection.
- Expose filters that make artist-library workflows practical, including platform, account, post,
  availability, and asset-link filters, while reporting acquisition eligibility per occurrence.
- Return stable occurrence IDs and named variant keys together with declared and verified metadata,
  source provenance, and linked asset identifiers while redacting remote URLs and private paths.
- Add `catalog media list` and `catalog media show` commands with stable JSON output and human-readable
  rendering suitable for feeding explicit `catalog assets download-plan` selections.
- Keep every browsing operation offline and read-only; add no migrations, provider requests,
  automatic downloads, account crawling, similarity conclusions, or best-quality selection.

## Capabilities

### New Capabilities

- `media-occurrence-browsing`: Read-only discovery and inspection of catalog posts, media
  occurrences, named variants, provenance, verified assets, and acquisition eligibility.

### Modified Capabilities

None.

## Impact

- Adds a focused query module and public query facade under `media_catalog`.
- Extends the `catalog` CLI with a nested, read-only `media` command group.
- Reuses the current-schema read-only database boundary and existing acquisition-policy evaluation;
  it does not change the schema or network behavior.
- Adds query, CLI, redaction, ordering, pagination, and zero-network tests plus usage documentation.
