# Proposal

## Why

Milestone A's acceptance demonstration begins "starting with an arbitrary local
image", but a live test on 2026-11-03 proved the system cannot start there:
`discover` requires a URL, catalog post, or account (`--file` only attaches to
a URL seed), `seed create` validates that every URL resolves to a platform
post identity, lookup seeds require existing catalog entities, and adopted
occurrences are not seedable. A file with immediately available verified
identity (its own hashes) has no honest entry point.

The same test showed the second half of the gap: discovery plans steps exactly
once from the seed's material. When a provider hit reveals new references (a
source URL, a foreign post id, artist attribution), nothing reads that
material back, so a single hit is a dead end instead of a fan-out origin.

## What Changes

- Discovery gains a **local-file root**: `catalog discover --file <path>`
  standalone. The file's verified md5/sha256, dimensions, MIME type, and byte
  size become seed identity material with file provenance. No stub post and no
  synthetic platform row is created; a remote post appears only when a
  provider actually returns one.
- The planner accepts file-seed material: the catalog's local md5 search runs
  offline against the verified hash, and the existing `verified_md5` lookup
  strategy fans out to providers proven to support exact-hash queries
  (danbooru, e621, gelbooru DAPI). Sankaku and pawchive hash-query wire
  contracts are uncaptured; they are deferred until live-captured rather than
  assumed.
- Discovery sessions become **generational with a hard depth cap**: after a
  provider hit is persisted, its normalized references (canonical source URL,
  external ids, artist attribution) are extracted as new query material and
  planned as follow-up steps — a direct fetch for a recognized source link,
  reverse `external_post_id` lookups on other providers, and existing artist
  candidate machinery. At most two provider generations run per session; the
  existing request and wall-clock budgets and the (source, method) step
  identity dedupe unchanged hits.
- The session report gains an additive generation breakdown; existing report
  keys keep their shape.

## Capabilities

### New Capabilities

- `local-file-discovery`: seeding a discovery session from an arbitrary local
  file with no known source, using only the file's intrinsic verified
  identity; and the bounded generational fan-out that turns a first provider
  hit into further discovery within one session.

### Modified Capabilities

- `unified-discovery`: sessions may start from a local file root in addition
  to URL/post/account; session reports carry generation-scoped step outcomes.

## References

- Bead `data-processing-b8n`; live capability test 2026-11-03
  (`/mnt/e/Grabber/230bb8160ea5c6a90fc53e258cf8673e.jpg`, md5 matches
  filename).
- Roadmap P0.1/P0.3 (`docs/plans/priority.md`), Milestone A acceptance.
- Perceptual-hash matching is explicitly out of scope (bead `qi7` research).
