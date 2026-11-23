# Proposal

## What

Bead `data-processing-h6d`: parse Grabber sidecar tag files during folder
ingest instead of only counting them.

- New `imports/sidecar.py`: `parse_sidecar` turns Grabber's comma-separated
  danbooru-style tag lines (with `category:` prefixes) into categorized
  tags; `pool:` metatags are counted apart; unknown prefixes map to the
  kernel's `unknown` category.
- `SidecarStore` retains each parsed sidecar as a raw observation
  (`object_kind='sidecar_tags'`) attached to its file seed, under one
  idempotent `folder_sidecar` import run per folder — the sidecar text as
  operator-supplied declared material from the original download.
- `ingest_folder` wires it: a media file's `<name>.txt` twin is read and
  attached after the seed materializes; orphan sidecars (no media twin) are
  counted, never opened; the result payload reports `sidecar_parsed`,
  `sidecar_orphan`, and `sidecar_pool_tags`.

## Why

For files that match nowhere (~1% of the 24k grabber collection), the
sidecar may be the only provenance — provider tags recovered without
network. For matched files the live lookup stays authoritative (operator
reframe 2026-11-15); sidecar facts are evidence, never tag-table writes.
The ingest walk already touches every file, so parsing costs nothing extra;
the mount-wide glob the operator's notes ruled out is never attempted.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `local-file-discovery`: new requirement covering sidecar parsing and
  evidence retention during folder ingest.

## Impact

- Code: `src/media_catalog/imports/sidecar.py` (new), `imports/folder.py`
  (wiring + counters), `tests/test_folder_ingest.py` (retention,
  idempotency, pool metatags, orphans).
- No schema changes: `raw_observations.object_kind` is free text,
  `import_runs.source_kind` is free text, tags stay out of the post-scoped
  tag tables.
- No posts, no platform identities, no adoption — unchanged ingest posture.
