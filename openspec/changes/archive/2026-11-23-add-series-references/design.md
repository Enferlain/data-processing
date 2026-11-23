# Design

## Context

`platform_references` (0002, rebuilt 0003) keys identity on (platform,
instance_host, object_kind, identifier_kind, native_identifier,
recognizer_version) with `object_kind CHECK IN (account, post, artist,
media_asset)` and account/post-only resolution guards. Six dependent tables
FK into it; candidate guard triggers reject non-account/post targets.
Code mirrors the CHECK in `records/common.py OBJECT_KINDS`. The pixiv
adapter retains nothing from the artwork `series` key today (fixture carries
`"series": null` twice; the key is in the suite's documented vocabulary).
Danbooru's `pixiv_id` bridge (adapter.py:745-760) is the writer shape to
mirror. Rebuild precedent: 0003 (this very table) and 0038 (freshest
CHECK-widening); the migration engine disables FKs and gates on
`PRAGMA foreign_key_check`.

## Goals / Non-Goals

**Goals:** widened kind with zero behavior change for existing kinds;
evidence-only series semantics decided and enforced by existing guards;
pixiv membership retained; recognition for series URLs.

**Non-Goals:** series fetch/enumeration operations (no AdapterOperation
addition), link resolution for series URLs, e621 sets parity, series as
relationship endpoints (the typed `relationships` model stays untouched),
seed promotion.

## Decisions

### D1: Evidence-only, guards do the enforcing

A series reference resolves nothing (`resolved_account_id`/`resolved_post_id`
stay NULL — their guards bind account/post only and are left untouched),
cannot be a candidate target (the 0002/0029 guard triggers already abort
non-account/post targets), and is not seed material (candidate-lookup
planning queries post references only). Promotion to any active role is a
future change that would have to argue for it — this change records the
decision, not just the default.

### D2: Migration 0041 mirrors the 0003 rebuild on this very table

`CREATE TABLE platform_references_rebuilt` with the widened CHECK (series
appended), explicit-column `INSERT ... SELECT` preserving
`platform_reference_id`, drop index, drop old table, rename, recreate
`platform_references_lookup_idx`. Dependent FKs re-validate through the
engine's disabled-FK window + `foreign_key_check` gate — the same contract
0016/0017/0038 relied on. No trigger changes: the candidate guards query
values, not schema.

### D3: Recognition before generic artwork grammar

`links.py` gains an explicit `pixiv-series` recognizer branch for
`/artworks/series/<id>` placed before the artwork branch (the id is a
distinct namespace; the artwork regex cannot match it, but an explicit
branch documents intent). `link_resolution` stays unextended: resolving a
series URL to an operation would require a fetch op we deliberately did not
add; unresolved series URLs fail exactly as today.

### D4: Pixiv writer rides the external-reference item path

`_normalize_post` reads `series` (dict with `id`); when present it emits one
`external_reference` NormalizedItem whose target is the pixiv `series`
stable id — `remote_sync/persistence.py:300-318` and
`persistence/metadata.py add_post_external_reference` already persist
whatever validated `target_object_kind` the record layer admits, so the
widened `OBJECT_KINDS` is the only enabling change. Canonical value:
`https://www.pixiv.net/artworks/series/<id>`.

### D5: Fixture extension follows the suite's own precedent

The pixiv suite already documents a reference-corroborated field addition
(the `series` key itself, 2026-10-07). One new case clones an existing
artwork detail case with a non-null `series` object, and the manifest notes
the addition the same way. No captured bytes are edited.

## Risks / Trade-offs

- [Rebuild on a hot table] → 1.1 GB catalog backup exists (2026-11-22
  checkpoint); engine gates on foreign_key_check; explicit column list
  prevents drift.
- [Series ids confused with artwork ids] → distinct object_kind rows in the
  unique key; recognizer branch names the grammar; tests pin both.

## Migration Plan

One commit; replay-safe migration; no data backfill (existing pixiv raws
gain series references only when reprocessed or refetched — an operator-run
choice, consistent with the reprocess tooling). Rollback is `git revert`
plus schema restore from backup if needed.
