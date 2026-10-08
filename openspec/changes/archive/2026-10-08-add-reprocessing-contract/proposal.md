## Why

A major architectural payoff of append-only raw retention is that normalizer improvements
should not require refetching provider responses that are already stored. Every recent
normalization catch-up (unp, o6y, 8jj, cyp) marked its gaps "reprocess-able from retained
raw" — but no reprocessing path exists, so the benefit remained an implementation detail
(GitHub issue #8). Worse, those normalizer changes shipped without adapter-version bumps,
so `(payload, adapter_version, schema_version)` cannot currently identify which normalizer
produced the retained facts — the kernel's "normalization is a pure function of payload and
versions" contract was unenforced by discipline.

## What Changes

- **Version discipline**: adapters whose normalization behavior changes bump their
  `ADAPTER_VERSION`. The four providers' versions bump now (danbooru-native-v2,
  e621-native-v2, gelbooru-native-v2, pixiv-adapter-v2), reflecting this week's
  normalization changes; fixture manifests and version-pinning tests follow.
- **Reprocess planning**: an offline, read-only plan lists retained raw observations whose
  recorded adapter version differs from the replay adapter's — with the original operation,
  target, platform, versions, and already-reprocessed skips — under explicit bounds.
- **Reprocess execution**: replaying one retained raw reconstructs its response envelope
  (payload, status, identity), runs the current adapter's normalizer offline, and commits
  through the shared page writer as a `reprocess`-origin remote run with zero provider
  requests. The original raw payload and prior normalized interpretation are never mutated;
  new facts land as observations per the existing current-projection policy; replaying the
  same raw under the same adapter/schema version is idempotent (skipped, not duplicated);
  malformed retained payloads fail retentively as typed outcomes.
- CLI: `catalog reprocess plan|run` (offline; socket-blocked in tests).

## Impact

- Capabilities: `remote-metadata-sync` (one ADDED requirement).
- Code: adapter config version constants; new `media_catalog/remote_sync/reprocess.py`;
  `cli.py` reprocess command; fixtures/manifests; tests in `tests/test_reprocess.py`.
- No schema migration: reprocess runs reuse `remote_runs` origins; raw observations and
  normalized tables are untouched in shape.
