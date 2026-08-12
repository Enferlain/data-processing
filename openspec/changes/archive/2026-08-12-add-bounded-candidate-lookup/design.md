## Context

See `proposal.md` for motivation. The catalog already has two deliberately separate systems that this change must join without collapsing their boundaries:

- offline discovery recognizes URLs already present in retained data and owns typed account/post candidates, evidence, scoring, and review decisions;
- remote metadata sync owns provider requests, finite budgets, response-first raw retention, normalized persistence, and resumable checkpoints.

Danbooru-family adapters currently fetch posts and attribution records by stable ID and list posts by a supplied tag. They do not expose a capability contract or a typed reverse-lookup operation. Existing post candidates can express `sourced_from` and `same_work`, and can attach multiple characteristics such as `exact_bytes`; booru attribution entities and uploaders are already distinct.

The new workflow must search only supported provider endpoints, remain auditable when it finds nothing, and avoid turning a query result into identity, authorship, or similarity truth.

## Goals / Non-Goals

**Goals:**

- Add a read-only plan followed by explicit, finite, networked lookup execution.
- Reuse the existing request gate, budget accounting, raw-observation retention, provider pacing, and candidate review ledger.
- Make every lookup result explainable from a seed, strategy, provider request, raw observation, and algorithm version.
- Support source-URL, external post-ID, exact MD5, and provider artist-record lookups for configured Danbooru-family instances.
- Preserve useful weak artist-name/alias leads without manufacturing accounts or candidates.
- Provide durable pause/resume and redacted inspection contracts.

**Non-Goals:**

- Visual or perceptual similarity, distance thresholds, crop matching, or embeddings.
- Automatic review decisions, identity merging, creator inference, or choosing a preferred image.
- Arbitrary URL requests, general web search, redirect resolution, browser automation, or X network access.
- Recursive link traversal, account-post enumeration, media acquisition, or gallery-dl execution.
- Treating a booru artist tag or uploader as an account.

## Decisions

### 1. Add a lookup facade beside discovery and metadata sync

Introduce a public `CandidateLookupService` with plan, execute, resume, and query collaborators. The facade accepts catalog seed references, provider keys, named strategies, and limits. It delegates provider transport to adapters and candidate creation to the existing discovery components; it does not duplicate review logic.

The plan is produced through the current-schema read-only database boundary and performs no network or layout writes. Execution re-resolves the seed and compares a material plan digest before the first request so changed source facts make the plan stale rather than silently changing the query.

Keeping lookup separate from `DiscoveryService.discover()` preserves the offline guarantee of discovery. Keeping it separate from `MetadataSyncService.synchronize()` avoids making normal metadata fetches generate cross-platform claims as a hidden side effect.

Alternatives considered:

- Extending offline discovery with HTTP was rejected because existing commands and specs guarantee zero network access.
- Treating lookup as ordinary metadata sync was rejected because lookup has a subject seed, evidence direction, weak leads, and candidate side effects that ordinary fetch-by-ID does not.

### 2. Use closed lookup strategies and per-instance capability declarations

Add a versioned `LookupStrategy` vocabulary initially containing:

- `source_post_url`: query a provider by a catalog-derived canonical source-post URL;
- `external_post_id`: query a provider by an allowlisted embedded stable platform post ID;
- `declared_md5`: query a provider using a validated provider-declared MD5;
- `verified_md5`: query using an MD5 calculated from catalog-managed or otherwise verified bytes;
- `artist_exact_name`, `artist_alias`, and `artist_text`: query attribution records with explicitly selected seed text.

Each configured adapter instance publishes an immutable capability set describing supported strategies, pagination form, and result type. Planning intersects requested strategies with this set. Adapter code maps typed lookup requests to fixed HTTPS endpoints and parameter names; callers cannot supply an endpoint, host, or arbitrary parameter map.

Danbooru and AIBooru capabilities are independent even when they share normalization code. The initial implementation may support a smaller set on AIBooru when fixture-backed behavior differs. Unsupported capabilities fail during planning and are never probed speculatively.

### 3. Derive lookup material from catalog facts and store its provenance

Post strategies derive values only from stable catalog state:

- canonical X source URLs are rendered from the platform and native post ID, with known `x.com`/`twitter.com` aliases represented as a bounded provider query set under one strategy;
- external IDs come from typed stable platform references or provider metadata;
- declared MD5 retains its occurrence and raw-observation provenance;
- verified MD5 requires a linked asset and its verification source.

Weak artist lookup requires the user to choose a specific retained handle, display name, attribution name, or explicit term. The planner does not tokenize bios or automatically fan out every historical name. The persisted private query material is necessary for audit and resume, but normal output exposes only its kind and a stable digest.

Every plan item has a stable digest over seed identity and revision, provider/instance, strategy/version, normalized private query material, adapter policy/version, and limits. Execution refuses a stale digest.

### 4. Extend the remote execution substrate without sharing semantic writes

Refactor the request gate and response-retention loop into an internal reusable executor while keeping `MetadataSyncService` behavior and public results unchanged. Lookup supplies its own page consumer:

1. create the durable lookup run and request attempt;
2. perform the adapter request through the shared gate;
3. retain the response and typed outcome before normalization;
4. normalize the complete page;
5. in one transaction, persist normalized provider facts, lookup-result rows, evidence/candidate associations, counters, and the next continuation;
6. only then expose the continuation as committed.

One lookup run covers one seed, provider instance, and strategy. A multi-strategy CLI request is a bounded batch of independent runs. This keeps continuations and retry policies unambiguous and allows one failed strategy to be inspected or resumed without replaying successful strategies.

Existing `remote_runs` CHECK constraints encode metadata operations and will not be weakened to accept arbitrary text. A new migration adds dedicated `candidate_lookup_runs`, `candidate_lookup_requests`, `candidate_lookup_checkpoints`, and `candidate_lookup_results` tables with the same bounded outcome vocabulary and raw-observation associations. Shared Python execution primitives avoid copying request-safety logic while the separate tables preserve domain constraints.

`candidate_lookup_runs` stores exactly one subject endpoint (`seed_account_id` or `seed_post_id`), provider/instance, strategy and strategy version, plan/material digests, adapter/schema versions, immutable limits, predecessor run, state, counters, bounded diagnostic, and timestamps. Requests store only a sanitized request identity and outcome. Results use a stable digest and may reference a normalized post, attribution entity, platform reference, evidence row, and raw observation; nullable references are constrained by result kind.

### 5. Translate results into existing candidate semantics conservatively

Result interpretation is versioned and idempotent:

- A returned booru post whose normalized source names the seed X post creates or strengthens the directionally correct `sourced_from` post candidate. Direction follows the asserted source relationship, not which endpoint happened to seed the query.
- A declared provider MD5 matching a verified seed MD5 creates or strengthens a symmetric `same_work` candidate and adds the `exact_bytes` characteristic. It does not create an account candidate.
- A provider-declared MD5 matched only to another declared MD5 remains declared-hash evidence and is not labeled verified exact bytes.
- A returned artist record is persisted as an attribution entity. Its names and aliases remain weak lookup results.
- External URLs on an artist record enter the existing URL recognizer with provider-attribution provenance. Only a recognized stable account ID can create an account candidate, and ordinary review rules still apply.
- Uploaders remain account participants with uploader provenance and never substitute for artist attribution.

Evidence digests include subject and target identities, strategy and interpreter versions, observation identity, stance, direction, and evidence kind. Repeating a response does not duplicate candidate/evidence associations. Adding evidence advances evidence generation but never changes current review state or appends a decision.

### 6. Treat weak leads as query results, not match candidates

Name and alias search results are retained and inspectable with provider attribution IDs, normalized names, match mode, rank/order, observation, and bounded explanation. They do not enter `account_match_candidates` unless a separate stable account reference is recognized from retained provider URLs.

This avoids introducing a third ambiguous candidate endpoint type or fabricating local accounts for community-maintained artist tags. A later user can inspect the attribution record, supply a manual link, or run another explicit supported lookup.

### 7. Resume from committed pages under new authorization

Execution never mutates the immutable limits of a run. Budget exhaustion, a rate limit, or interruption leaves the run paused with its last committed continuation. Resume creates a new run linked to its predecessor, inherits the seed/provider/strategy/query material, and requires newly supplied positive limits. Adapter, schema, strategy, seed revision, and query-material compatibility are checked before reuse.

The next page is admitted as a unit. If its normalized top-level result count would exceed the remaining budget, no result, candidate, or checkpoint from that page commits. Replayed committed results are harmless because result, evidence, and candidate keys are stable.

### 8. Keep secrets and query material out of public surfaces

Adapters retain the existing external credential model. Lookup rows never store credentials, cookies, authorization headers, or generated request URLs. Request identities use provider, operation, and an opaque query digest. Raw responses remain in the catalog under the existing private-data policy but are absent from normal run/candidate output.

CLI output allowlists seed IDs, provider/instance, strategy, policy and adapter versions, limits, counts, state/outcome, retry time, result classifications, evidence IDs, and match references. It omits source-path text, raw query material, payloads, response headers other than already allowlisted rate metadata, and all URL query values.

### 9. Use a dedicated CLI namespace and explicit handoff

Add commands under `catalog lookup`:

- `plan` resolves a seed and strategies without network access;
- `run` executes an exact plan or equivalent explicit selection;
- `resume` creates a compatible successor run;
- `runs` and `show` inspect redacted history/results.

Results show existing match references when one was created and attribution/result references otherwise. Confirmation remains under the existing match-review commands. A confirmed Pixiv account can then be passed to the existing `catalog metadata pixiv-account-artworks` command; lookup does not invoke it.

## Risks / Trade-offs

- [Danbooru-family search syntax differs by instance and may change] → Declare capabilities per configured instance, use redacted fixtures, version strategies/adapters, and fail closed on unknown shapes.
- [Source URL aliases can cause false negatives] → Generate only a bounded canonical alias set, retain which form matched, and interpret absence as no result rather than disproof.
- [Twitter recompression makes exact hash lookup miss valid works] → Treat exact-hash misses as inconclusive and defer similarity to a separately reviewed future change.
- [Names produce many unrelated results] → Require explicit weak-search selection and result limits; retain them as leads without account candidates or automatic ranking conclusions.
- [A booru source or artist record can be wrong] → Preserve provider provenance and require existing manual review; never infer identity or authorship automatically.
- [Reusing request machinery could accidentally alter metadata-sync behavior] → Extract behavior behind characterization tests and keep separate facades, tables, consumers, and public result contracts.
- [Multiple strategies can spend more requests than expected] → Plan one independently budgeted run per strategy and show aggregate upper bounds before execution.
- [Raw provider responses may contain sensitive or surprising fields] → Keep the catalog private, bound response size through existing transport policy, redact all normal output, and retain raw data only under current provenance rules.

## Migration Plan

1. Add a numbered additive migration for lookup runs, requests, checkpoints, results, constraints, indexes, and raw-observation provenance; preserve all existing IDs and remote-sync tables.
2. Add records/writer/query contracts and migration tests for fresh creation, upgrade from the current schema, rollback on failure, idempotency, foreign keys, and future-version rejection.
3. Extract and characterize the reusable bounded request/retention executor without changing metadata-sync behavior.
4. Add typed lookup requests, capability declarations, Danbooru/AIBooru fixtures, adapter normalization, and policy tests.
5. Add planning, execution, result interpretation, candidate integration, resume, inspection, and CLI behavior.
6. Validate against synthetic versions of the existing cross-platform examples with networking mocked; keep optional live lookup smoke tests disabled by default and hard-bounded.

Rollback before lookup execution is a normal database backup restore. After migration, older binaries reject the newer schema; lookup adds records but does not rewrite existing imports, reviews, normalized posts, or managed assets.
