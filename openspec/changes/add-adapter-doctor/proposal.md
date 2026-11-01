# Proposal

## Why

The adapter lane has landed ten platform keys, eleven adapter surfaces, and a
live-captured fixture suite behind nearly all of them — but the only ways to ask "does
everything still work?" are the full pytest run (offline, per-family, no reachability)
and two ad-hoc live-test conventions with different gates (`GELBOORU_LIVE_SMOKE=acknowledged`
for gelbooru, `MEDIA_CATALOG_LIVE_METADATA=1` plus per-platform env triples for e621).
The maintainer asked for one doctor: a single command that checks every adapter against
its captured contract and names what moved when something breaks.

## What Changes

- New `media doctor` CLI command over a new `media_catalog.doctor` module:
  - **Offline contract replay (default)**: every registered suite-format fixture case is
    replayed under the current adapters — manifest/adapter version agreement, expected
    outcome (success or typed failure), expected `post_ids`/`account_ids` membership, and
    per-item platform attribution. This is the schema-drift tripwire: a wire change that
    breaks a normalizer, or an adapter change that breaks a captured contract, is named
    per suite and case.
  - **Live probes (`--live`)**: one bounded, metadata-only request per platform against
    the suite's own captured target, using the real adapter, real pacing floors, and
    credentials resolved from the established external environment (never printed).
    Platforms whose credentials are absent are reported SKIPPED with the reason; the
    explicit `--live` flag is the operator authorization the live-smoke tests gate
    behind environment variables.
  - Per-platform report rows (suite case counts, failures with case names and reasons;
    live outcome, latency, response size), `--json` output, and a nonzero exit when
    anything fails.
- Registered surfaces: danbooru, aibooru, e621, e926, gelbooru (dapi), safebooru,
  rule34, gelbooru-html, pixiv, sankaku, pawchive. Lookup suites (danbooru/aibooru
  lookup) and the gallery-dl oracle are explicitly out: they exercise different runner
  contracts and stay covered by their family tests.

### Non-goals

- Replacing the per-family fixture tests (the doctor checks the common contract core;
  families still pin their exact facts), absorbing the ad-hoc live smoke tests (they
  stay; a later change may retire them once the doctor proves itself), media-byte
  verification, and continuous scheduling.

## Capabilities

### New Capabilities

- `adapter-doctor`: one policy-gated command that verifies every adapter offline
  against its captured contracts and, on explicit request, live against the providers.

### Modified Capabilities

- none
