## Why

Offline discovery can recognize cross-platform references that already occur in imported profiles and posts, but many X artists do not publish a usable Pixiv or booru link. The catalog needs an explicit, bounded way to search supported providers for reviewable candidates without treating names, artist tags, hashes, or search results as identity proof.

## What Changes

- Add a network-explicit candidate-lookup workflow that plans and executes finite provider queries from an existing account or post seed.
- Support deterministic Danbooru-family reverse lookups by canonical source-post URL, embedded platform IDs, and exact declared or verified hashes where the provider supports them.
- Support bounded artist-name, alias, and artist-record lookup as weak evidence, while preserving the distinction between booru artist attribution, uploader accounts, and platform accounts.
- Persist sanitized lookup runs, attempts, raw observations, result provenance, budgets, checkpoints, and typed unavailable/rate/auth/parse outcomes.
- Feed lookup results into the existing account/post candidate and evidence ledger so review decisions remain manual, append-only, reversible, and idempotent.
- Provide dry-run/plan, execute, resume, list, and show commands with stable redacted JSON and human output.
- Hand confirmed stable targets to existing metadata synchronization explicitly; do not automatically enumerate accounts, download media, or traverse newly discovered links.
- Exclude visual similarity, perceptual thresholds, automatic identity or authorship decisions, arbitrary web search, X timeline crawling, recursive expansion, and automatic quality selection.

## Capabilities

### New Capabilities

- `bounded-candidate-lookup`: Plans, executes, persists, resumes, and inspects finite provider lookups that produce provenance-rich cross-platform account and post candidates.

### Modified Capabilities

- `cross-platform-match-review`: Accepts typed evidence from bounded provider lookups without changing conservative scoring, review, or identity-confirmation semantics.
- `danbooru-family-metadata-adapter`: Adds bounded post/source/hash and artist-name/alias lookup operations while retaining uploader-versus-artist separation and instance-specific capabilities.

## Impact

- Extends the catalog schema with durable lookup runs, attempts, result associations, immutable limits, and checkpoints; existing discovery and match tables remain authoritative for candidates and decisions.
- Extends Danbooru-family adapter and request-policy contracts, metadata persistence, CLI commands, and offline query surfaces.
- Reuses injected `httpx` transports, raw-observation retention, stable platform/native identifiers, existing provider pacing, and the current match-review facade.
- Adds no required dependency and makes no network request from import, offline discovery, browsing, planning, or review commands.
