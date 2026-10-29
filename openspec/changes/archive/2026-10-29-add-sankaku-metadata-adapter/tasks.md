# Tasks

## 1. Instance and credential machinery

- [x] 1.1 `adapters/sankaku/config.py`: `SankakuInstance` (platform key `sankaku`, canonical `sankakuapi.com` base (live-verified; capi-v2 refuses this client), `sankaku-api-v2-v1` schema version, credentials-required policy, login/password env names, family limits) and the instance registry entry
- [x] 1.2 `adapters/sankaku/credentials.py`: `SankakuCredentials.from_environment` with the same secret-free repr/redaction discipline as the other families
- [x] 1.3 Token exchange in the adapter: one `POST /auth/token` per process, bearer token only in HTTP headers, single re-exchange on the provider's invalid-token signal, `authentication_required` typing on failure; token/credentials provably absent from identities, observations, logs, and diagnostics (tests with sentinel values)

- [x] 2.1 `SankakuAdapter.fetch/normalize` for `fetch_post` via `/v2/posts` id-range query: request rendering, strict envelope validation, run-contract identity (`sankaku:api_v2:post:<id>`)
- [x] 2.2 Keyset listing: `/v2/posts/keyset` with `next`-cursor continuation (scope-checked: adapter, version, query, shape, length), shared budget enforcement, `rate_limited` outcome honoring `X-RateLimit-Reset`
- [x] 2.3 Normalization from the captured contract only: post facts, typed tags from the embedded objects plus unknown-category tags from the fuller `tag_names` array, media representations as metadata, source URL, `parent_of` relation, absence-tolerant fields per capture; malformed classification for shape violations

- [x] 3.1 Migration `0021` seeds the `sankaku` platform row; `SOURCE_OPERATIONS` gains `sankaku`; adapter-contracts registry test pins the eight-key set
- [x] 3.2 Credentialed live capture with the maintainer's credentials: one post fetch and one keyset listing page; redacted fixture suite (`sankaku.json`) with manifest provenance and a token/credential secret scan before commit
- [x] 3.3 CLI `sankaku-post` and `sankaku-list` commands with credential guidance; tests: wire requests (MockTransport), normalization vs fixtures, policy refusals, CLI routing, and a real-service persistence integration test on a migrated catalog

## 4. Verification and close-out

- [x] 4.1 Full gates: `ruff check`, `ruff format` on changed files, `ty check src`, full `pytest`
- [x] 4.2 Reviewer subagent pass on the complete diff; address findings
- [x] 4.3 CHANGELOG entry under the current date
- [x] 4.4 Sync spec delta into `openspec/specs/sankaku-metadata-adapter`, archive the change, close Bead `data-processing-4ly`
