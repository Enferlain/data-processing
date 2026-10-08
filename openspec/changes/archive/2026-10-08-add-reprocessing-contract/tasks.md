# Tasks

## 1. Version discipline

- [x] 1.1 All four provider adapters bump ADAPTER_VERSION (normalization changed this week);
       fixture manifests and any pinned literals follow
- [x] 1.2 A guard test pins that fixture manifests always match the live constants

## 2. Reprocess service

- [x] 2.1 Read-only plan: retained raws with remote runs, stale adapter version vs the replay
       adapter, original operation/target/platform, already-reprocessed skips, bounded output
- [x] 2.2 Execute: envelope reconstruction from the retained row, offline normalize through
       the current adapter, commit via the shared page writer as a reprocess-origin run with
       zero requests
- [x] 2.3 Idempotency: same (raw, adapter version, schema version) replays are skipped;
       original raw payload bytes are never modified; malformed retained payloads fail as
       typed retentive outcomes

## 3. CLI and demo

- [x] 3.1 `catalog reprocess plan|run` with provider selection and bounds; offline proof in
       tests
- [x] 3.2 Live acceptance: replay the retained danbooru fetch_post raws captured before the
       engagement normalization; scores/flags/variant dims materialize without network

## 4. Spec, docs, gates

- [x] 4.1 Delta spec (ADDED requirement) validates strictly; audit updated; CHANGELOG
- [x] 4.2 Full pytest/ruff/ty/openspec gates green; archive
