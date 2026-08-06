## Why

The catalog retains profile and post links, but most are available only as single normalized fields
or inside raw provider JSON and therefore cannot drive the bookmark-to-artist workflow. The next
step is to turn existing local links into queryable cross-platform references and reviewable account
and post match candidates without making unverified identity, authorship, or same-work claims.

## What Changes

- Extract external URLs from normalized account/post fields and retained raw X/xarchive records,
  preserving the original value, source context, observation, and extraction version.
- Canonicalize supported URLs and parse stable platform references such as Pixiv user/artwork IDs,
  X account/post IDs, and Danbooru-family post or artist references without network access.
- Store unresolved links rather than discarding or guessing at shortened, link-hub, personal-site,
  or unsupported URLs.
- Create distinct account-to-account and post-to-post candidates backed by independently stored,
  explainable evidence and deterministic candidate scoring.
- Support pending, confirmed, and rejected review decisions with append-only decision history; only
  explicit confirmation may create durable identity membership or confirmed post relationships.
- Provide idempotent discovery plus human-readable and JSON commands for listing links, candidates,
  evidence, and review history.
- Define relation families that can later accommodate same-work, source, derivative, progression,
  and technical media-variation evidence without implementing downloads, perceptual matching, work
  versions, or an exhaustive image-transformation taxonomy in this change.

## Capabilities

### New Capabilities

- `external-link-discovery`: Extract, normalize, retain, resolve, and query offline external-link
  observations and stable platform references from existing catalog data.
- `cross-platform-match-review`: Generate and review typed account and post match candidates with
  explainable evidence, explicit confirmation semantics, and future-compatible relation families.

### Modified Capabilities

None.

## Impact

- Adds a numbered catalog migration for links, resolved references, identities, typed candidates,
  evidence, decisions, and confirmed relationships.
- Extends normalized record/writer/query services and the `catalog` CLI while preserving existing
  imports, searches, observations, raw payloads, and legacy `x-likes` behavior.
- Adds deterministic URL recognizers and offline reprocessing of existing catalogs; this change adds
  no HTTP client, redirect following, account crawling, media download, or image-similarity runtime.
- Adds synthetic/redacted fixtures and tests for URL provenance, platform parsing, idempotency,
  candidate separation, evidence scoring, review history, and non-inference safeguards.
