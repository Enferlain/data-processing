# Proposal

## Why

Roadmap `docs/plans/priority.md` Milestone A names unified discovery orchestration
(P0.1) as the highest immediate priority, and its diagnosis matches the repo's lived
pattern: every component exists — seed materialization into stub posts, per-provider
bounded candidate lookup with full run/request/result persistence, typed relationship
and review machinery — but no one input can initiate a coherent discovery session
across them. `fetch` (link-driven ingest) wired one inch of this; this change wires
the whole first slice.

## What Changes

- New `media_catalog.discovery.orchestration` module inside the existing discovery
  package: a **discovery session** model
  (`DiscoverySession`, `DiscoveryStep`) plus three components:
  - **Input normalization** — a URL (optionally with a held file and declared MD5)
    materializes an operator seed into a stub post exactly as `seed create` does
    today (idempotent by bundle digest); an existing record is accepted as
    `POST:<id>`/`ACCOUNT:<id>`. Every input preserves its original identity and
    provenance — no parallel candidate identity system.
  - **Planner** — resolves the seed's query material offline (reusing the
    `plan_candidate_lookup` material resolution) and produces one step per
    (source, method): local-catalog searches (verified/declared MD5 against
    `asset_fingerprints`/assets, source-URL references, platform identity) and one
    bounded lookup plan per provider that declares the strategy. Steps the source
    cannot serve are reported as excluded with the reason — the planner never
    silently omits.
  - **Runner** — executes local steps inline (pure SQL, offline by construction);
    remote steps only under explicit `--live`, each through the existing
    `CandidateLookupService` with its own budgets and a session-level budget across
    them; without `--live`, remote steps stay `planned`. Every step retains status,
    outcome, counts, and the linked `candidate_lookup_run_id`; failures are
    contained per step.
- New `catalog discover` command: `--url` (+`--file`/`--media-root`/`--declared-md5`)
  or `--post`/`--account`, `--live`, `--json`, budget flags, and `--session <id>` to
  re-report a prior session.
- Persistence: migration `0024` adds `discovery_sessions` and `discovery_steps`
  (session identity and input bundle digest; step source/method/status/outcome and
  run linkage). Existing candidate, evidence, and run tables are reused untouched —
  the session binds them, it does not duplicate them.

### Non-goals

- External metadata indexes (P0.2 — the next unit; the planner's source registry is
  shaped so index sources are additive rows), fingerprint-based visual matching
  (P0.4/qi7 deferral), follow-up discovery hops beyond the first (the step model
  records the material for them), file-only inputs with no URL (needs a URL-less
  seed shape; deferred with the stub-post model documented), and media downloads
  (existing assets pipeline).

## Capabilities

### New Capabilities

- `unified-discovery`: one input initiates a coherent, bounded, evidence-retaining
  discovery session across the local catalog and registered remote providers.

### Modified Capabilities

- `external-link-discovery`: the URL recognizer's host table now covers every
  registered platform (aibooru, e926, rule34, safebooru, sankaku, pawchive were
  unrecognized; safebooru post URLs also missed the gelbooru query grammar) —
  coverage must not lag the platform registry.
