# Tasks

## 1. Service

- [x] 1.1 `SeedMaterializationService.materialize` validates the bundle (at least one URL,
      every URL a stable post identity, pairwise platform/id consistency, optional note and
      declared MD5) and fails closed with bounded diagnostics
- [x] 1.2 The bundle persists as an `operator_seed` import run with the bundle as its retained
      raw payload; the stub post lands with availability `unknown`, the primary canonical URL,
      and the raw observation attached
- [x] 1.3 Every URL attaches as a `source_url` and typed `provider_id` external reference
      under the seed's raw observation
- [x] 1.4 Re-running the same bundle reuses the import run and writes no duplicate rows

## 2. CLI

- [x] 2.1 `catalog seed create <catalog> --url ... [--note] [--declared-md5]` renders stable
      JSON/human output with identifiers and counts only (no note text, no URLs echoed)

## 3. Integration and boundaries

- [x] 3.1 A stub with a pixiv URL seeds `external_post_id` lookup planning like a synced post
- [x] 3.2 Materialization creates no candidates, relations, decisions, or identity claims

## 4. Spec, docs, gates

- [x] 4.1 Delta spec adds the seed-entry requirement; strict validation passes
- [x] 4.2 Catalog guide documents the workflow; audit §bridge findings updated; CHANGELOG
- [x] 4.3 Full pytest/ruff/ty/openspec gates green

## 5. Phase 2: local-bytes intake

- [x] 5.1 `--file` validation (exists, regular, within inspection byte ceiling) with the
      content hash folded into the bundle digest
- [x] 5.2 Media occurrence on the stub with declared MD5 and the file registered as a local
      source under an operator-seed source root
- [x] 5.3 `--media-root` adoption through the existing machinery: verified SHA-256/MD5,
      detected dimensions, versioned perceptual hash linked to the occurrence
- [x] 5.4 `verified_md5` (and declared) lookup planning accepts the stub; re-running the same
      bundle adopts nothing new
- [x] 5.5 Docs, CHANGELOG, gates, archive the change
