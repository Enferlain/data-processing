# Design

## Context

`ingest_folder` walks one directory, classifies `.txt` as count-only
sidecars, and materializes each media file as a `discovery_file_seeds` row
via `SeedMaterializationService.materialize_file` (verified hashes, no
post). Tags tables are post-scoped; pre-post evidence homes are
`raw_observations` (free `object_kind`) under free-text
`import_runs.source_kind` (precedent: `operator_seed`). The operator's
sample: one line, comma-separated, danbooru-style prefixes, unprefixed
artists; `pool:` presence unknown (count it).

## Goals / Non-Goals

**Goals:** parse + retain sidecars as seed evidence, idempotently; pool
metatag counts; orphan safety; bounded reads.

**Non-Goals:** writing provider tag tables (post-scoped; live lookup stays
authoritative for matched files), pool observations from `pool:` tags,
adoption, posts, any mount-wide scanning.

## Decisions

### D1: Evidence shape = raw observation on the seed

`object_kind='sidecar_tags'`, `native_id=str(seed_id)`, payload = canonical
JSON `{version, kind, source_file, tags[{name,category}], pool_ids,
unparseable_lines}` under `source_schema='grabber-sidecar-v1'`. Content
addressing + the `(import_run, object_kind, native_id, raw_payload_id)`
unique make re-attaches no-ops. This mirrors the `operator_seed` retention
pattern without reusing its source kind.

### D2: One import run per folder, reused when complete

`source_kind='folder_sidecar'`, digest = session digest + `:sidecars`.
First ingest creates and finishes it; a re-ingest reuses the completed run
(raw attach conflict-no-ops). Unlike `operator_seed`, completed-run reuse is
correct here because folder re-ingest is the normal idempotent rerun path.

### D3: Parser maps prefixes onto the kernel tag vocabulary

`general/artist/copyright/character/meta` pass through; `species/studio/
genre/medium` land as `unknown` (kernel has no approximation rule);
unprefixed entries are `general` (the queue treats raw tag text the same
way); `pool:<digits>` is counted apart, non-numeric `pool:` entries stay
general tags. Reads are bounded at 64 KiB per sidecar; oversized/missing
files count as failures without aborting the batch.

### D4: Orphans never open

Only `<media-name>.txt` twins are read; `.txt` files without a media twin
are counted (`sidecar_orphan`) and their content is never touched — the
operator's WSL-viability concern stays moot.

## Risks / Trade-offs

- [Sidecar format variants beyond the one-line sample] → Parser is
  line-tolerant (multiple lines all parse; non-tag lines land as general
  tags or `unparseable_lines` on NUL bytes); the raw payload retains the
  parsed form so a better parser can re-derive from evidence later.
- [Runaway sidecars] → 64 KiB read bound; oversized counted, not parsed.

## Migration Plan

Single commit; no schema changes; replay-safe by construction. Rollback is
`git revert` (retained sidecar raws are inert evidence rows).
