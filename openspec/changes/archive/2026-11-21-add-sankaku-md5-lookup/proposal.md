# Proposal

## What

Bead `data-processing-hvs` phase 1: a Sankaku md5 lookup surface that rides
the existing candidate-lookup/crosscheck machinery. `catalog crosscheck` gains
a `sankaku` lane that searches `tags=md5:<hash>` for every subject's declared
and verified MD5, feeding exact-byte post candidates through the existing
interpreter — exactly like the danbooru/e621/gelbooru md5 lanes.

- `SankakuInstance` declares `lookup_capabilities` (`DECLARED_MD5`,
  `VERIFIED_MD5`, result kind `post`) and a `lookup_plan_context`.
- `SankakuAdapter` implements the `LookupAdapter` protocol
  (`fetch_lookup`/`normalize_lookup`): the md5 query reuses the existing
  authorized keyset listing path (`/v2/posts/keyset?tags=md5:<hash>`), its
  continuation wrapping, and the already-captured keyset response contract.
- `crosscheck.PROVIDERS` gains `"sankaku"`; per-item bounds, the 2.0s pacing
  floor, credential refusal, and rate-limit outcomes all come from existing
  machinery.
- A captured, redacted fixture of the md5-query response pins the surface per
  the sankaku fixture policy.

## Why

The 2026-11-19 operator direction keeps "md5 alone" as useful standalone
work: sankaku is an artist-anchored expansion source whose post payloads
carry declared MD5s, and the corpus's md5 material is already query-ready.
Phase 2 (artist sweep) shipped; this is the remaining cheap surface, with
credentials verified working on this machine.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `sankaku-metadata-adapter`: new requirement covering the md5 tag-query
  lookup surface (bounded, credentialed, keyset continuation, fixture-backed).
- `bounded-candidate-lookup`: new requirement admitting sankaku as an
  explicit lookup provider for the two md5 strategies only — exact-byte post
  candidates, no account/authorship inference, no artist strategies.

`catalog-cross-check` needs no delta: it is generic over "configured
supported providers" and its lanes/budgets/resume already cover a new
provider without requirement changes.

## Impact

- Code: `adapters/sankaku/{config,adapter}.py` (capability + protocol
  implementation), `crosscheck.py` (provider tuple), tests for the sankaku
  lookup surface and its crosscheck lane participation.
- No schema migrations (platform row `0021` exists; candidate-lookup tables
  are provider-generic).
- Out of scope: discovery's `LOOKUP_PROVIDERS` registry (standalone
  `catalog lookup` targeting sankaku — lands with artist strategies),
  sankaku artist lookup strategies, phase 3 similarity, phase 4 media
  harvest, any media-byte requests.
