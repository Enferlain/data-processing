# local-file-discovery Specification

## Purpose
Start a bounded discovery session from an arbitrary local file with no known
source, using only the file's intrinsic verified identity, and let every new
reference exposed by a first provider hit participate in the same session.

## Requirements

### Requirement: bare-file discovery root

A discovery session MAY start from a local file path with no URL, catalog
post, or account. The system MUST validate the file and compute its identity
itself, and MUST NOT create a stub post row or invent a platform identity:
a remote post appears only when a provider returns one.

#### Scenario: standalone file seed

- **WHEN** `catalog discover <catalog> --file <path>` is run with no
  `--url`, `--post`, `--account`, or `--session`
- **THEN** a session starts with input kind `local_file`, and its offline
  report lists the local md5 search plus every supported provider hash lookup
  as planned steps
- **WHEN** the same command adds `--live`
- **THEN** the provider hash lookups execute within the session's request and
  time budgets

#### Scenario: file validation happens before any write

- **WHEN** the path does not exist, is not a regular file, or exceeds the
  seeding size ceiling
- **THEN** the command fails with a bounded diagnostic and no session, seed,
  or step row is written

#### Scenario: identity is computed, never trusted

- **WHEN** the seed is materialized
- **THEN** md5 and sha256 are computed from the file's bytes, with pixel
  dimensions, MIME type, and byte size recorded when derivable, and any
  caller-supplied or filename-derived hash is ignored
- **THEN** operator local paths are redacted from session reports like other
  private paths

#### Scenario: no synthetic identity

- **WHEN** a file seed is materialized
- **THEN** no `posts` row is created for the seed itself and no platform key
  is attributed to it

### Requirement: exact-hash provider fan-out

The file's verified md5 MUST drive the existing `verified_md5` lookup
strategy against providers whose captured wire contracts support exact-hash
queries. Providers without a captured hash-query contract MUST be reported as
excluded naming the missing capability, never probed speculatively. A hash
hit MUST persist the provider's post through the normal sync path before any
follow-up material is extracted from it.

#### Scenario: first hop executes under live authorization

- **WHEN** a live file-seeded session runs and a provider returns a post for
  the verified md5
- **THEN** the provider post is fetched and persisted as a catalog post with
  its normalized references, and the session records the hit
- **WHEN** no provider recognizes the hash
- **THEN** the session completes honestly with zero-hit outcomes and no
  error

### Requirement: bounded generational follow-up

After a provider hit is persisted, the session MUST treat the hit post's
normalized references as new query material and plan follow-up steps from
them within the same session, under hard bounds.

#### Scenario: references become follow-up steps

- **WHEN** a hit post exposes a canonical source URL, a foreign post id, or
  artist attribution
- **THEN** the session plans a direct fetch for a recognized source link,
  reverse `external_post_id` lookups on other providers, and artist candidate
  strategies in their established strength order
- **WHEN** two providers reveal the same reference
- **THEN** step-identity dedupe keeps a single step; the reference is
  fetched once

#### Scenario: one hit fans out

- **WHEN** a generation-one hash hit exposes a recognized source URL and a
  foreign post id
- **THEN** the session plans the source fetch and the reverse lookups as
  generation-two steps within the same budgets, and reports each planned,
  executed, skipped, or excluded step
- **WHEN** budgets are exhausted mid-fan-out
- **THEN** the session stops cleanly and reports which generation-two steps
  remained planned
- **WHEN** outcomes are reported
- **THEN** generation-scoped results are additive and existing report keys
  keep their shape

#### Scenario: depth is capped

- **WHEN** generation-two hits expose further references
- **THEN** no generation-three provider steps are planned; the new references
  are reported as material for a future session
