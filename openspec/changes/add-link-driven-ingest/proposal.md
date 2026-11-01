# Proposal

## Why

The repo could fetch metadata by internal id and download bytes for cataloged
occurrences, but had no link-driven entry: pasting a post URL did nothing. The
maintainer asked for the missing wiring — "fetch content from any of the supported
sites via links" — and greenlit it as the current topic (2026-11-01). Every URL
grammar needed is already proven: each normalizer emits its platform's canonical
URL, so reading those URLs back is pure composition over captured contracts.

## What Changes

- New `media_catalog.link_resolution` module: a pure, network-free resolver mapping
  each platform's URL grammar to `(platform, operation, target)` — post URLs for all
  ten platforms, including the variant spellings people actually paste
  (`www.`/`en/`/`.json` prefixes and suffixes, `rule34.xxx` vs `www.` vs `api.`,
  `sankaku.app` vs `chan.sankakucomplex.com`, pixiv's legacy `member_illust.php`
  query form). Unsupported hosts, non-HTTPS, and malformed ids fail with
  actionable errors before any network access.
- New `catalog fetch <catalog> <url>` command: resolves the link, then syncs its
  metadata through the platform's real adapter construction path (credentials from
  the established environment, pacing floors, `SyncLimits`, resume support).
  `--resolve-only` prints the resolution without touching the catalog. Media bytes
  stay on the managed-asset pipeline, which the synced occurrences feed.
- **Fixed (exposed end-to-end by the new surface):** pawchive serializes zoneless
  ISO timestamps; the temporal layer requires offsets, so live persistence failed.
  The adapter now qualifies naive stamps as UTC — the repo's established
  interpretation for zoneless provider stamps (the gelbooru HTML adapter qualifies
  its `Posted:` stamps identically). Offset-bearing stamps pass through normalized.

### Non-goals

- Media-byte fetching on this command (compose with the existing `assets`
  pipeline), account/pool URL grammars, HTML-scrape fallbacks for URL shapes the
  APIs cannot serve, and lookup-by-source-URL (already a separate capability).

## Capabilities

### New Capabilities

- `link-resolution`: supported-site URLs resolve, offline and unambiguously, to
  the platform operation and target that fetches them.

### Modified Capabilities

- `pawchive-metadata-adapter`: normalization qualifies the provider's zoneless
  timestamps as UTC (documented interpretation, gelbooru precedent) so temporal
  facts persist.
