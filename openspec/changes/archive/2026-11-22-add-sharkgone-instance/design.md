# Design

## Context

The family adapter serves instances from `DanbooruInstance` config
constants (DANBOORU, AIBOORU); consumers branch on literal sets or import
constants. Sibling families register per-instance constants + registries
(safebooru/rule34 in GELBOORU_INSTANCES, e926 in E621_INSTANCES). Platform
identity needs: config instance → adapter_factory → kernel
SOURCE_OPERATIONS + platforms row → capability-gated consumers → link
recognizer/resolution → doctor surface + per-instance tests. The bead
probed the instance read-only: standard danbooru posts.json shape, md5
lookup round-trips, artists endpoint empty, ~185 posts. Anonymous access
verified 2026-11-22; operator credentials exist for authenticated use but
live in env only.

## Goals / Non-Goals

**Goals:** every family seam registers sharkgone once; fixture-backed
contract; md5-lane participation; artist surfaces omitted and documented.

**Non-Goals:** failover/routing semantics toward danbooru, artist
strategies or enumeration (endpoint empty), media-request policies (out of
family scope), authenticated-only behavior changes.

## Decisions

### D1: Instance mirrors AIBOORU's post-strategy set, minus artist

`lookup_capabilities` = SOURCE_POST_URL, EXTERNAL_POST_ID, DECLARED_MD5,
VERIFIED_MD5 (all "post"/keyset); no enumeration_capabilities. When the
provider's artists endpoint gains content, artist strategies land as their
own change. Credentials: `SHARKGONE_LOGIN`/`SHARKGONE_API_KEY`; anonymous
requests already work, so absent envs never crash a lane
(`DanbooruCredentials.from_environment` returns None when both are unset).

### D2: Literal-set seams extended in place

No new registry dict (the family has none): adapter_factory's set becomes
`{"danbooru", "aibooru", "sharkgone"}` with instance selection; the same
for library.py and offline replay; PROVIDERS/LOOKUP_PROVIDERS/CLI choices
gain the key/instance; links host table gains `booru.sharkgone.com`;
`_POSTS_PATH_PLATFORMS` gains the key (artist/media routes stay closed);
link resolution adds the host to the danbooru-family resolver and
RESOLVED_PLATFORMS; maintenance's reprocess providers gain the key.

### D3: Migration 0040 + SOURCE_OPERATIONS follow the family precedent

Replay-safe `INSERT OR IGNORE INTO platforms` row
(`sharkgone`, `Sharkgone`, `https://booru.sharkgone.com`), and
`SOURCE_OPERATIONS["sharkgone"] = REMOTE_OPERATIONS` so the kernel admits
the platform's operations.

### D4: Doctor surface with the captured anonymous suite

`sharkgone.json` (listing + md5 hit + miss, captured anonymously 2026-11-22,
no credentials ever transmitted) backs a per-instance DoctorSurface using
the danbooru-family offline adapter and anonymous live probe, mirroring the
aibooru entry.

## Risks / Trade-offs

- [Provider drift on a personal booru] → The instance declares the captured
  contract only; contract violations surface as malformed responses, not
  crashes; doctor pinpoints drift.
- [Forgotten seam] → The mirrored per-instance test enumerates the
  registration surfaces (factory, crosscheck, discovery, links, resolution,
  reprocess, kernel operations) so a new family seam that misses sharkgone
  has a pattern to extend.

## Migration Plan

Single commit; migration 0040 is replay-safe; no data backfill. Rollback is
`git revert` (the platform row is inert without code referencing it).
