# Changelog

<!-- markdownlint-disable MD024 -->

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Rules:

- Use proper sub titles "Added", "Changed", "Removed" and "Fixed"
- Keep proper track of days for where entries should go
- Be concise and mention all changes without necessarily detailing each one

## [2026-11-11]

### Added

<!-- artist-identifier entry moved below from 2026-11-10 during wrap-up -->

- **`artist_identifier`: offline artist resolution from the e621 artists export (Bead
  `data-processing-an1`, change `add-index-artist-identifier`)** — `catalog index import
  --provider e621 --export artists [--download]` builds a second lookup-v1 projection
  (target `e621-artists`, real 12-column export: name/other-names/active+inactive URLs)
  serving exactly `artist_identifier` via per-target `index_meta.capabilities`; posts
  projections exclude the method by capability, artists projections exclude the post
  methods. Probes are the seed's account identities — participating-account profile URLs
  and profiles derived from x/twitter status URLs (`https://x.com/<handle>`; the handle is
  the stable identity) — plus recorded source URLs; hits are artist entries recorded as
  session-scoped leads in `discovery_artist_leads` (migration `0033`; leads only, never
  facts, never a fetch bridge). Artists refreshes carry their own revision and never
  invalidate posts-index attempts. Also fixes export URL canonicalization for both
  importers: bare host/path tokens (`furaffinity.net/user/x`, case-preserved) are retried
  as `https://…` instead of stored unmatchable, and postgres arrays parse in both quoted
  and unquoted element styles (the artists export ships `{name,name}`). Includes all seven
  review fixes (teach never touches artists projections; numeric account ids synthesize
  nothing; explicit `--name` required to register non-post projections; duplicate artist
  ids replace child rows; lead names bounded at the lookup boundary; prune refuses
  `--apply` under broken registrations; sqlite failures contained to the step). Validated
  on real data: X seed resolves `greengird11e` → e621 artist `greengirdle` offline
  (256 probes, 129k entries, 75 MB projection, integrity ok).

- **X status-URL canonicalization: one form across catalog and indexes (Bead
  `data-processing-an1`)** — the handle in an x/twitter status URL is decoration:
  `canonicalize_url` now normalizes `x.com/<handle>/status/N` and
  `twitter.com/<handle>/status/N` to `https://x.com/i/status/N` (the form the catalog
  already synthesizes), and index URL probes fold legacy stored handle spellings.
  Previously catalog probes (`x.com/i/status/N`) could never match provider-stored
  handle spellings — the e621 index holds 2.26 M x/twitter status URLs. Real-catalog
  URL hits: 71 → 225 distinct seed source URLs. Benefits every future provider index
  (Danbooru/Gelbooru store the same spelling family); stored catalog keys keep their
  original form and never need rewriting.

### Fixed

- **Prune review fixes (Bead `data-processing-an1`)** — `catalog index prune --apply` now
  skips files modified within the last hour (an import registers its artifact only after
  the build finishes; previously a concurrent first-import's `.part` or freshly downloaded
  artifact could be deleted mid-flight) and refuses to run when a provider registration is
  broken or records no artifact path (a projection without its artifact reference could
  not protect its rebuild source). Reviewer found the checksum-compare and progress units
  clean; the spec gained the operator-checksum pin scenario.

- **www-variant URL probes match in index lookups (Bead `data-processing-dp8`)** —
  e621 exports list both `furaffinity.net/…` and `www.furaffinity.net/…` spellings of the
  same page while `links.py` deliberately keeps `www` for unknown hosts, so
  `source_post_url` and `artist_identifier` probes could silently miss the other spelling.
  The fold happens at the probe boundary in `lookup()` (each HTTPS URL probe tries its www
  and non-www twin): no stored-key changes, no re-import, canonicalization untouched.
  Tests pin both directions for both methods.

- **Three real-data correctness fixes from the acceptance/coverage pass (Bead
  `data-processing-an1`)** — (1) `discover --search-state` crashed with
  "'artist_identifier' is not a valid LookupStrategy" once an artists projection was
  registered: index-only methods now carry the index target version as their strategy
  version (`lookup-v1.<revision>.g<generation>`), which is what freshness compares anyway.
  (2) the CLI `--method` vocabulary rejected `artist_identifier`, making the method
  unselectable; it now derives from `INDEX_METHODS` too. (3) profile derivation treated
  the literal `/i/` in X's canonical status URLs (`x.com/i/status/N`) as a handle,
  producing false artist leads against junk export entries (`https://x.com/i`); the
  canonical path form is now excluded. Regression tests pin all three.


## [2026-11-10]

### Added

- **`catalog index import --download` (Bead `data-processing-an1`)** — the explicit network
  path for e621 index imports: one request to the public `/db_exports.json` listing, one
  streamed artifact download with the identifying e621 User-Agent, SHA-256 verified against
  the listing before the import reads it, retained under
  `<catalog-stem>-indexes/e621/downloads/`. A matching existing artifact is reused without a
  second download, so for e621 — daily full exports — re-running `import --download` is the
  refresh: a newer export is a new checksum and snapshot revision, replanning every subject's
  index searches. Mutually exclusive with `--artifact`; two mocked-transport tests cover the
  verify/reuse/mismatch paths.

- **`catalog index import --download --checksum`** — an operator-supplied checksum with
  `--download` is now explicitly compared against the provider listing before any transfer
  (pins the exact export revision; a listing that moved on refuses) instead of being
  silently replaced by the listing checksum.

- **`catalog index prune` (Bead `data-processing-an1`)** — retention hygiene for downloaded
  export artifacts: reports (and with `--apply`, deletes) files under
  `<catalog-stem>-indexes/<provider>/downloads/` that no registered projection references —
  stale `.part` temp files from killed downloads and superseded exports. Referenced
  artifacts are never pruned. e621's export filename is constant, so daily refreshes replace
  the artifact in place rather than accumulating.

- **Progress output for index download/import (Bead `data-processing-an1`)** —
  `catalog index import --download` now reports transfer progress every 64 MiB and import
  progress every 500k rows on stderr; stdout remains machine-readable for `--json`. The
  2 GB download and ~15 min full import previously printed nothing.

### Fixed

- **e621 export import vs. the real artifact (Bead `data-processing-an1`)** — validated
  against the real 2026-11-09 posts export (1.99 GB, 6,834,929 rows; fixture now pins the
  actual 32-column header): (1) legacy source-array elements that pack several URLs —
  newline-separated or concatenated with no separator (37% of source-bearing rows) — are
  split into one normalized lookup key per embedded URL; (2) absent optional export columns
  (the real export has no `tag_string_artist`; artist tags are not separable in this
  artifact) are reported in the import result instead of silently degrading — artist rows
  come from teach material until the artist exports land in a later slice.


## [2026-11-08]

### Added

- **Local search indexes: lookup-v1 projections as offline discovery targets (Bead
  `data-processing-an1`, stage 2 slice 1)** — `catalog index register/list/import` maintain
  per-provider disposable SQLite lookup databases (migration `0032`; default
  `<catalog-stem>-indexes/<provider>/lookup.sqlite`) built from raw provider artifacts: the
  e621 daily DB export importer verifies the published SHA-256, streams the gzipped CSV,
  records the snapshot identity, and swaps atomically; artifacts are retained untouched as
  the rebuild source. Registered indexes appear in `catalog discover` as ordinary `index`
  targets — same policy filters, freshness skips, and `--dry-run`/`--search-state`
  explanations — executing offline and ordered before providers, with snapshot-scoped
  strategy versions (`lookup-v1.<revision>`) so a refreshed snapshot replans every subject.
  Index hits are leads (`discovery_index_hits`) that bridge into the existing fetch
  follow-up generation; only the fetch pipeline writes catalog facts. Every persisted
  provider post — fetch, metadata sync, candidate lookup, discovery — teaches its
  provider's index at a shared post-commit boundary in the normalized-page writer
  (failure-contained; rolled-back transactions teach nothing; no-op without a
  registration). The version-pattern contract gained an optional dot-suffix for
  snapshot-stamped versions. Danbooru importer and refresh strategies are follow-ups.

- **`catalog backup` / `catalog restore --verify` (Bead `data-processing-dbq`, roadmap P0.5)** —
  online consistent catalog snapshots via SQLite `VACUUM INTO` (safe under active WAL writers
  such as the labeling server) into a timestamped file plus a self-describing manifest (schema
  version, row counts, managed-root registry, SHA-256). Restore is verify-first: digest check
  before any write, `--force` for existing targets, `--verify` integrity/foreign-key/row-count
  checks, and `--media-root` re-verifies media trees through the asset verifier. `--keep N`
  retention never prunes the newest verified backup, and `catalog doctor` now reports backup
  state — neutral when absent, failing when the latest backup's digest drifts. No schema change;
  backups are sidecar files.
- **Discovery search policy, freshness ledger, and run transparency (Bead `data-processing-19p`)** —
  `catalog discover` now obeys an explicit search policy and remembers what was searched.
  Executed searches land in a durable attempt ledger (migration `0031`) keyed by
  subject x target x method x strategy version x query evidence, so repeat runs skip fresh
  successes (naming the attempt) and retry only failed, deferred, or never-attempted work;
  zero-result searches record their scope and never assert nonexistence. New operator surface:
  `--recheck unsearched|stale|force` with `--stale-after`, `--include-source`/`--exclude-source`,
  `--method`, `--search-mode trails|active`, `--dry-run`, `--search-state` (offline inspection
  of per-target attempts and freshness), and repeatable subject inputs running sequentially
  under one shared budget with per-subject progress and aggregate counts. Budget-exhausted
  steps end `deferred` (resumable) instead of failed; sessions track `requests_used`. Bare-file
  discovery is idempotent by content, so freshness applies to file subjects too. Stage 2
  (index/optimization targets) and stage 3 (more providers) extend the same vocabulary.

### Fixed
- **Danbooru-family media policy sends the identifying User-Agent** — danbooru's CDN
  enforces the site bot policy: browser and library-default agents get 403, and only a
  descriptive custom agent with the site Referer is served (live matrix 2026-11-08:
  default-ua 403, browser-ua 403, catalog agent 200). The danbooru-family policies
  (danbooru/aibooru/gelbooru/rule34/safebooru) now carry the catalog's identifying
  agent alongside the Referer, fixing failed image loads in the labeling UI and the
  acquisition path for danbooru originals.
- **Selected downloads plan against committed WAL state (Bead `data-processing-818`)** —
  `catalog assets download` previously planned via the path-based read-only open, which
  refuses any WAL frames and made ordinary selected downloads fail while the labeling
  server was writing. The mutating download command now opens the catalog and plans
  through the supported snapshot, so committed concurrent writes are planned against;
  the explicitly read-only `download-plan` keeps its stricter no-WAL guarantee.
- **Relationship materialization no longer requires works-first ordering (Bead
  `data-processing-e2l`)** — `catalog relationships materialize` refused confirmed
  work-level candidates with `work_anchor_missing` whenever `catalog works materialize`
  had not run yet. Work anchors for posts with occurrences are now ensured lazily under
  the same deterministic rule (kind from occurrence count, representations linked), making
  the two commands order-independent and idempotent; only a target post with no
  representations to anchor keeps the refusal.

- **Search-index freshness correctness (Bead `data-processing-an1` review)** — two gaps in
  slice 1 where index searches could wrongly stay fresh. (1) Bounded `--max-records` imports
  shared the full import's revision: the snapshot revision now identifies the actual
  searchable scope (artifact digest + builder version + `full` when the artifact was consumed
  to EOF, else the bounded prefix), so expanding a bounded import replans prior zero-result
  searches. (2) Teach-on-result mutated projections invisibly to freshness: each teach batch
  is now one projection transaction (whole or rolled back — no partial rows on failure), bumps
  a teach overlay generation only when content actually changed (reconfirmations do not churn
  freshness), records a durable `teach_log` row for inspection, and the generation rides the
  target version (`lookup-v1.<revision>.g<n>`) so taught content invalidates prior attempts —
  including zero-result ones. Teach material now also covers provider source URLs
  (`source_url` external references) and artist tags, completing the spec contract; catalog
  success remains fully independent of index-teach success.

## [2026-11-07]

### Added

- **`catalog label` — interactive local labeling UI (Bead `data-processing-w7j`)** —
  a stdlib-only localhost server for calibrating match heuristics the way the
  operator described: brings up image pairs side by side (served from managed
  storage, remote URL fallback), shows the queueing signal and per-image
  metadata, and takes a verdict (same / variant / different / unsure,
  keyboard 1-4) plus a free-text relation description. Pairs are queued from
  NON-perceptual signals so the tool never needs the similarity judge it
  calibrates: identical md5 across platforms, shared source URLs,
  provider-recorded parent/child variant relations, shared external ids,
  same-artist tag overlap, and same-artist contrast pairs for the
  false-positive side. Labels persist to `pair_labels` (migration `0030`)
  with append-only decision history; labeled pairs drop from future queues,
  so the calibration corpus accumulates as the catalog grows.

### Fixed

- **Sankaku images in the label UI (Bead `data-processing-hjr`)** — route signed CDN media
  through native-client headers, renew expired links in memory, and retry a denied link once.
  Validate refreshed post/hash identity and use stable post links without changing catalog facts.
- **Expired Sankaku label link refreshed (Bead `data-processing-cud`)** — refreshed cached
  signed media for the reported post and verified the original with browser-compatible headers;
  automatic URL renewal is tracked in `data-processing-hjr`.
- **Provider-aware remote label media (Bead `data-processing-wae`)** — serve remote media
  through existing provider request policies, including required Referer headers and bounded
  video ranges, without requiring asset downloads. Admit the observed Aibooru CDN host
  (`data-processing-mqn`) while retaining exact-host validation.
- **Local originals for remote-blocked label images (Bead `data-processing-ax0`)** — acquired
  five remaining Gelbooru cross-check originals; verified local serving bypasses CDN requests
  that return HTML without a provider Referer. Aibooru CDN policy follow-up is tracked separately.
- **Automatic catalog credentials (Bead `data-processing-2f3`)** — load the private central
  credentials file and current directory `.env` without extra flags; explicit environment
  variables take precedence and local values override central defaults.
- **Reusable local provider credentials (Bead `data-processing-1fs`)** — documented the private
  central environment-file location and explicit loading through the ignored project `.env` link.
- **Label server startup and shutdown errors (Bead `data-processing-a59`)** —
  commands without `--json` report errors and shutdown normally; a failed server bind closes
  its catalog connection instead of leaking it or masking the port error with `AttributeError`.
- **Fresh descriptions for label revisits (Bead `data-processing-482`)** —
  previous notes remain visible as context; the editable description starts blank and clears
  after a successful save, so old notes are not silently resubmitted with a new verdict.
- **Incomplete pairs deferred during label revisits (Bead `data-processing-efw`)** —
  `--revisit-unsure` applies the same media and post availability checks as the normal queue,
  preserves deferred labels and notes, and reports them without claiming they were relabeled.
  Byte-verified originals use declared format hints when inspection only reports generic binary,
  allowing downloaded WebM files to render without overriding specific detected formats.
- **`catalog label` media resolution, format rendering, streaming, and save guarantees (Bead `data-processing-efw`)** —
  resolves post media respecting `st_dev:st_ino` managed root identity and local file
  existence; prioritizes local primary/original media over previews, handles multiple
  acquisition history records without arbitrary ordering, and applies neutral badges to
  unverified local copies; renders multi-format media (`<video>` with controls for WebM/MP4,
  native animated GIF, audio, preview badges, and missing/unavailable explanation boxes with
  source links); supports video Range streaming (HTTP 206 Partial Content including suffix
  ranges); improves save feedback with HTTP error statuses, transaction rollback on failure,
  flash banner across reloads, note preservation, Enter key prevention, and adds
  `--revisit-unsure` queue mode.
- **Legacy `/post/show/<id>` links resolve (danbooru-family + e621-family)** —
  the operator's test list uses danbooru's old route; the link recognizer
  already accepted both path shapes but the fetch resolver did not, so
  `catalog fetch` rejected them. Both families now normalize `/post/show/N`
  to the same identity as `/posts/N`, pinned by test.

### Changed

- **Cross-check originals acquired (Bead `data-processing-ee7`)** — downloaded and verified
  original images for the two newly cataloged focused matches into managed media storage.
- **Focused calibration cross-check (Bead `data-processing-jh3`)** — stopped the broad X
  bookmark sweep and verified coverage for reviewed/downloaded examples; retained results,
  unavailable-provider status, and exclusions in the operator run report.
- **qi7 study 2: tier calibration grounded in labeled truth** — the
  operator's three-group test list (including a with/without-text variation
  set) populates the middle band the two-threshold design needed:
  cross-platform identical files hash at 0%, text/variation pairs at
  1.6–12.5% (matching the operator's own structure note), different
  artworks never below 37.5%, same-artist negatives never below 29.7%.
  Certain ≲2% / uncertain 2–15% / no-match ≳25% now has labeled evidence
  behind it. Details in `docs/plans/qi7-image-hash-study.md`.

## [2026-11-05]

### Added

- **Attribution candidates complete the artist identity bridge (Bead
  `data-processing-s1j`)** — a recognized artist-record URL now becomes a
  reviewable `attribution_match_candidates` row (migration `0029`, mirroring
  the account candidate tables): subject is the attribution entity, target
  the recognized account reference, relation `same_identity`, evidence the
  provider's own listing. Live on d-rex: two pending candidates (`x:
  d_rex_art`, `x: d_rex_too`) reviewable through the generic
  `matches`/`match-show`/`match-review` surfaces via `attribution:ID` refs.

- **Attribution URLs feed the recognized link graph (Bead
  `data-processing-9er`)** — artist-record URLs persisted by attribution
  fetches were opaque strings in `attribution_urls`, never canonicalized or
  recognized, so a fetched artist's stable account links (the tag-to-handle
  identity bridge) stopped one table short. The link pass now observes them
  as `attribution`-subject link occurrences (migration `0027` widens
  `link_observations` with a third subject kind via the established rebuild
  pattern): the d-rex artist record's nine URLs now carry two recognized
  x-account references (`D_rex_art` and `d_rex_too`) with the rest honestly
  unresolved, queryable through `catalog links --subject-kind attribution`.
  Domain-shaped rows are skipped; candidate generation from
  attribution-subject links is the recorded follow-up.

- **Gelbooru-family media acquisition policies (Bead `data-processing-3xv`)** —
  gelbooru, rule34, and safebooru representations are acquirable, closing the
  Milestone B gap the live run exposed. Live-captured wire behavior
  (2026-11-05): gelbooru's CDN answers only with a `https://gelbooru.com/`
  Referer (a plain fetch gets a 302 to an HTML page — the existing
  danbooru-style Referer header covers it); rule34 serves images from
  `api-cdn.rule34.xxx` with no referer requirement though its DAPI needs
  credentials; safebooru serves media from its base host. Only observed
  hosts are allowed — `img1..3.gelbooru.com` remain rejected until a
  capture shows them. Proof: the gelbooru original of the Milestone B pair
  downloaded through the catalog and deduplicated onto the e621 original's
  CAS address (same sha256, one asset from two providers).

### Fixed

- **Corrective migration `0028` from the deferred 9er review** — 0027's
  rebuild had accidentally tightened `link_observations.occurrence_digest`
  to a global inline UNIQUE (0002 keys uniqueness on digest plus extractor
  version, so a future extractor bump could no longer record re-observations
  and would crash the store path) and silently relaxed `discovery_run_id` to
  nullable with an AUTOINCREMENT key; 0028 restores 0002's exact constraints
  while keeping the attribution subject widening. The external-link-discovery
  spec now covers attribution-subject extraction.

- **Milestone B live run found four defects, all fixed** — `relationships
  list`/`show` crashed on every call (an unbound LIMIT placeholder in the
  query); planning an e621 original was impossible because one unoffered
  variant role (`sample` with `url: null`) poisoned the whole variant map
  (null-URL roles are now skipped, malformed JSON and ambiguous roles still
  fail); `assets download-plan --variant` now works with `--select`
  selections so e621's explicit original/sample/preview roles are reachable
  without a library plan; and the sqlite snapshot pattern that deadlocked
  discovery (2026-11-04) existed as nine copy-pasted backup sites — all now
  route through one guarded `snapshot_connection` helper that commits any
  open transaction before `backup()` can block on it.

### Added

- **`catalog tombstone` operator command** — marks bad catalog data as
  errored without deleting evidence, productizing the 2026-11-04 lesson:
  `--post <id>… --reason <text>` marks posts unavailable with an
  error-tombstone status carrying the reason; `--lookup-run <id> --reason`
  marks a degenerate lookup run failed with the diagnostic while its inputs
  stay trigger-immutable. Idempotent, missing ids reported, reasons required.

- **Offline golden replay of bare-file discovery (session 32)** — the
  recorded wire payloads of the first fixed bare-file run (gelbooru md5 hit,
  two honest zero-results, one rate-limited refusal) now replay through the
  real discovery pipeline in CI: `tests/fixtures/golden_discover/` plus a
  test that pins the computed-hash query construction, generation-zero
  outcomes per provider, the single wave-A fetch of the provider-native
  post, and the persisted hit — drift in the bare-file path fails before a
  live run can be surprised.
- **Milestone B vertical slice proven live** — candidate confirm →
  `work:gelbooru:11165341 ⟷ work:e621:5486288` reviewed relationship →
  works materialized → policy-gated `download-plan` (e621-media) → the
  original downloaded into managed storage with its declared md5
  (`761b6db8…`) verified against the stored bytes.

## [2026-11-04]

### Fixed

- **Source-URL lookup material kept its query string** — the alias builder
  rebuilt every non-x source URL without the query, degrading gelbooru-family
  post URLs (id in the query) to a bare site root; a wave-B source lookup
  then matched fifty unrelated posts. Non-x hosts now preserve the query;
  x.com aliases stay path-canonical as before. Found live on a second
  Grabber validation batch (2026-11-04).

### Added

- **Bare-file discovery root and generational fan-out (Bead `data-processing-b8n`,
  change `add-local-file-discovery-root`, roadmap P0.1/Milestone A)** —
  `catalog discover --file <path>` now starts a session from an arbitrary local
  image with no known source: the file's verified md5/sha256, dimensions, MIME
  type, and size are recorded as a `discovery_file_seeds` row with file
  provenance — no stub post, no synthetic platform (migration `0026` widens the
  candidate-lookup-run seed rule to a third kind via the established CHECK
  rebuild). The verified hash drives the existing `verified_md5` strategy on
  every declaring provider, and a first hit fans out inside the same bounded
  session: the hit post is fetched and persisted, then its normalized
  references (source URLs, external ids, declared hashes) become one further
  generation of deduped reverse lookups and source fetches, hard-capped at a
  single follow-up wave under the existing request/time budgets. Session
  reports gain an additive `generations` breakdown and the file seed's
  intrinsic identity; operator paths stay out of reports.

### Fixed

- **Bare-file fan-out corrections from the deferred reviewer pass** — the
  first-hop fetch targeted the local surrogate `post_id` instead of the
  provider-native id (so a live wave-A fetch retrieved the wrong post and
  starved the follow-up wave; now the hit join reads `posts.native_post_id`,
  and hits from every generation-0 run of the session's seed fan out, not
  just the run recorded first on a step); `--url` + `--file` attachment
  worked again (the new input guard had rejected the pair the spec pins);
  interrupted sessions resume cleanly (planned fetch steps route through the
  follow-up executor instead of crashing the lookup-strategy parser); the
  follow-up post accumulator resets per execution; wave B plans one step per
  query material (digest-keyed) instead of duplicating a material's runs
  per value. Re-accepted live: e621 hash hit fetches true native post 5155635
  and its declared-md5 reference hits a further e621 post in the same
  session.
- **Lookup-snapshot deadlock** — discovery provider steps left their step-outcome
  writes uncommitted, and the lookup planner's catalog snapshot (`sqlite3
  backup`) blocks forever on an open write transaction; step outcomes now
  commit immediately (found live: sessions hung with zero CPU on the third
  provider).
- **Gelbooru response envelopes rejected cookies** — the envelope guard raised
  on any `set-cookie` response header, but Gelbooru's DAPI sets one on every
  response, making the whole surface unusable; the adapter now keeps only the
  public operational headers (content-type, retry-after, x-rate-limit),
  matching the danbooru/e621 convention.

## [2026-11-03]

### Added

- **Offline golden fetch scenarios from the 21-URL live batch (Bead
  `data-processing-h74`, roadmap P0.5)** — the recorded raw payloads of the
  2026-11-02 live validation batch (danbooru 6, e621 6, sankaku 6, pawchive 3)
  now live as per-scenario fixtures under `tests/fixtures/golden_fetch/`
  (secret-scanned, each under 20 KB), replayed by a parametrized test that
  runs the real fetch pipeline offline — resolver, shared factory, adapter,
  sync, persistence — over a mock transport that serves the recorded payload
  and refuses any request the live run did not make. Each scenario pins the
  persisted platform, native id, media-occurrence count, declared MD5 where
  present, and the e621 negative downvote counts; the sankaku replay sinks
  the credential exchange with a throwaway token. Wire-shape drift of the
  kinds the live batch caught (wrapped envelopes, clamped negatives, naive
  timestamps) now fails CI before it can surprise a live run.

### Fixed

- **`catalog fetch` now exits nonzero on a failed or paused sync (Bead
  `data-processing-uls`)** — the fetch command runs the same sync service as
  the metadata family but was absent from the exit-code policy, so a failed
  or paused fetch printed `status: failed` and still exited 0; it now exits 2
  exactly like `metadata`/`library`/`lookup`. `--resolve-only` is unaffected;
  a budget-paused run (progress persisted, resumable via `--resume-from`)
  exits 2, matching the metadata family's identical rule.

### Changed

- **CLI split into command-family modules (Bead `data-processing-c30`)** —
  `cli.py` shrank from 1,607 lines to a ~90-line entry (parsing, rendering,
  exit-code policy, family dispatch); parser fragments and handlers now live
  together in `media_catalog/cli_commands/` (admin, discovery, ingest, media,
  metadata, lookup, export, relationships, maintenance, library, plus a shared
  support module). The five near-identical metadata sync blocks collapsed into
  one factory helper. Pure structure change: every command, flag, default, and
  per-command output byte is unchanged (the only visible difference is the
  top-level help listing regrouping stats/search ahead of fetch/discover with
  their family), and a new drift-guard test pins that each family's declared
  command table matches the registered parser. Test monkeypatches repointed
  from `cli` to the family modules that now resolve those symbols.

## [2026-11-02]

### Added

- **CI workflow (Bead `data-processing-sd4`, roadmap P0.5 first leg)** —
  `.github/workflows/ci.yml` runs the repo's own gates on every push and PR to main:
  `ruff check`, `ruff format --check`, `ty check src`, the full pytest suite (migrations
  exercised via fresh test catalogs), `catalog adapter-doctor` offline (the 11-surface
  fixture replay — deliberately network-free), and a package build. Late formatting
  drift in three files caught by the new gate itself and fixed. Live golden scenarios
  stay out of CI by design (network flake); they remain a later offline-fixture unit.

### Changed

- **CLI adapter construction unified on the shared factory** — every live
  metadata/enrichment/lookup/library command block now builds its adapter through
  `media_catalog.adapter_factory.adapter_construction` (the same path link-driven fetch
  and discovery use), eliminating the last hand-rolled constructions that could drift on
  credentials, instances, or pacing floors; the gelbooru lookup path now resolves
  through the same factory fallthrough instead of its own construction. Offline replay and the adapter doctor keep
  their refuse-transport constructions by design, and pixiv keeps its context-manager
  lifecycle. CLI tests updated to patch the factory instead of constructors.

## [2026-11-01]

### Added

- **Pawchive metadata adapter (Bead `data-processing-629`, change
  `add-pawchive-metadata-adapter`)** — first-class anonymous metadata support for
  pawchive.pw, the kemono API family's only maintained instance (per the
  kemono-family investigation): `pawchive-profile`/`pawchive-post`/`pawchive-list` CLI
  surfaces, a single-instance family registry, migration `0023`, and
  `SOURCE_OPERATIONS` at ten keys. Contracts are live-captured (2026-11-01): flat post
  detail with string ids, bare-array listing pages with offset continuation embedded in
  the durable request target (replayed pages normalize terminally), name+path media
  occurrences with stable thumbnail URLs while expiring signed original URLs are never
  retained (the stable-path originals host 404s anonymously), and brace-string tags.
  A 4 MiB response ceiling absorbs the server-fixed 50-entry pages (observed at
  1.5 MiB). Reviewer pass caught and fixed an offline-replay failure mode for full
  listing pages.

- **Adapter doctor (Bead `data-processing-dm3`, change `add-adapter-doctor`)** — new
  `catalog adapter-doctor` command answering "do all adapters still work?": offline it
  replays every committed fixture suite under the current adapters (11 surfaces, 59
  cases — version agreement, expected outcomes including normalized deleted/unavailable
  states, post/account id membership, platform attribution), and with `--live` it probes
  each provider once through the real adapter (metadata-only, pacing-floored, creds from
  the established env files; credential-gated platforms skip with a named reason).
  Per-surface failure reporting with case names and reasons, `--json`, `--platform`
  filter, nonzero exit on any failure. Its first run caught a real fixture bug:
  `gelbooru_html.json`'s `html_not_found` recorded status 200 against its own expected
  `unavailable` outcome (the family test had been forcing 404 to mask it) — corrected to
  404. Reviewer pass fixed six doctor defects (phantom gelbooru-html probe case, vacuous
  pixiv probe, uncontained transport/normalizer exceptions, unused danbooru credentials,
  double-printed report, registration-failure semantics).

- **Catalog doctor surfaces adapter health (Bead `data-processing-lvc`, change
  `compose-doctor-adapter-summary`)** — `catalog doctor` now composes the adapter
  doctor's offline replay summary (overall ok, per-surface status, named failures)
  alongside storage integrity, so one command answers "is everything healthy"; full
  per-case detail and `--live` probing stay on `catalog adapter-doctor`. The report's
  top-level ok keeps its storage-only meaning (pinned by comment, spec, and test).

- **Link-driven ingest (Bead `data-processing-qz2`, change `add-link-driven-ingest`)** —
  `catalog fetch <catalog> <url>` closes the loop the maintainer asked for: paste a
  post URL from any of the ten platforms and its metadata syncs through the
  platform's real adapter path (credentials from the established environment,
  pacing floors, sync budgets, resume). A pure `link_resolution` module maps each
  platform's URL grammar — including pasted variants (`www.`/`en/`/`.json`,
  `rule34.xxx`/`www.`/`api.` hosts, `sankaku.app`/`chan.sankakucomplex.com`,
  pixiv's legacy `member_illust.php` form) — to platform+target offline, failing
  with actionable errors on unsupported links; `--resolve-only` resolves without
  touching the catalog. Gelbooru-family links use the DAPI transport and need that
  family's credentials (the HTML transport stays an explicit command). **Fixed:**
  live end-to-end fetch exposed that pawchive serializes zoneless timestamps the
  temporal layer must reject — the adapter now qualifies them as UTC (the gelbooru
  HTML adapter's shipped interpretation); verified live against the real catalog
  on e926 and pawchive. Reviewer pass hardened the variant test, tightened the
  pawchive service grammar, and pinned the DAPI-credential decision in design.

- **Development roadmap adopted (docs/plans/priority.md)** — maintainer-provided
  roadmap: project goal and target workflow, honest foundation inventory, P0/P1/P2
  backlog (discovery orchestration, external index search, targeted remote discovery,
  multi-method reconciliation, integration/CI; organization + acquisition; downstream
  projections, scaling, temporal knowledge, enrichment, expansion), delivery milestones
  A–D with required demonstrations, a persistent reference acceptance scenario, and
  architectural constraints (reuse the provenance kernel; discovery produces evidence,
  reconciliation produces conclusions; generalize only when justified). Milestone A
  (unified multi-source discovery) is the active priority; first unit bead opened
  (`v28`, P0.1 discovery orchestration). Existing beads reconciled against it:
  `2ai` → P2.3, `cyp` → P1, `qi7` deferral ratified by P0.4.

- **Discovery orchestration, first Milestone A unit (Bead `data-processing-v28`, change
  `add-discovery-orchestration`)** — `catalog discover` turns one input (a supported-site
  URL, or an existing post/account record) into a bounded discovery session inside the
  existing discovery package (`discovery/orchestration.py`): URL inputs materialize
  through the operator seed path (idempotent, same identity as manual seeding), the
  planner reports every (source, method) pair as planned / skipped-with-reason /
  excluded-with-why across the local catalog and the four lookup-capable providers, local
  steps execute offline always, and provider steps execute only under `--live` through
  the candidate-lookup machinery under session request + wall-clock budgets with
  per-step failure containment (missing gelbooru credentials become that step's typed
  outcome, not a crash). Sessions and steps persist and re-report by id. Supporting
  moves: the real adapter construction extracted to a shared `adapter_factory` (fetch and
  discovery delegate; metadata commands migrate incrementally), and the seed/link URL
  recognizer extended to every registered platform — aibooru, e926, rule34, safebooru
  (query grammar), sankaku, and pawchive URLs were unrecognized, a registry drift the
  external-link-discovery spec now forbids. Reviewer pass caught offline outcomes being
  rolled back on close (now committed and pinned by a reopen test), silent planner drops
  of undeclared-and-unmaterial pairs, mutating re-reports, missing deadline exactness,
  and unbounded CLI budget flags.

- **Live link-fetch validation batch (21 URLs across 4 platforms)** — all landed in the
  real catalog: danbooru 6/6 (images + animated, anonymous), e621 6/6 (after fixes),
  pawchive 3/3 (first fanbox-service URLs), sankaku 6/6 (images + animated, credentialed).
  The batch caught three live-wire defects, all fixed and pinned: locale-prefixed post
  URLs (`/en/posts/…`) now resolve and recognize (sankaku + danbooru family); e621's
  current wire reports negative downvote counts, rejected by both the adapter validator
  and the migration-0009 `CHECK (score_down >= 0)` — validator and record layer fixed,
  migration `0025` rebuilds the table with the check relaxed, and a live-captured
  fixture case (post 6577789: wrapped envelope, negative down) pins the contract.

## [2026-10-31]

### Added

- **KohakuGBC evaluated on the local stack (Bead `data-processing-dhb`)** —
  `docs/plans/kohakugbc-evaluation.md`: 12 maintainer-selected images through the GBC program
  with the VLM on llama-swap (`llama.cpp` flavour) and detectors on the RTX 3090 — OWLv2 pass
  25.5 s/image (median 16/24/36 vertices/captions/edges), SAM 3.1 pass 41.5 s/image (median
  28/51/49; the scene layer and object sub-structure OWLv2 misses), both 12/12 graphs with
  zero retries once inflight was throttled (the unthrottled first attempt wedged the server
  with fault-swallowed empty graphs). Gated models (EmbeddingGemma-300m, sam3.1) load from
  local snapshots under `eval-input/models/`; maintainer quality review of the graphs
  pending. Evaluation only — no product surface changes.
- **KohakuGBC maintainer review recorded, bead closed (Bead `data-processing-dhb`)** —
  graphs judged mostly okay with two findings: the served VLM mostly ignores NSFW content
  (coverage limitation for this corpus), and `ComfyUI_03874_.png` is confirmed
  full-scene confabulation — a single-character image consistently described as a
  two-character interaction across the run and two independent probes, so the same model
  cannot self-verify. Verdict: usable on this stack with throttled inflight and
  cross-model/human verification; SAM 3.1's structural advantage confirmed by review.

- **Batch A instance adapters: e926 and rule34 (Bead `data-processing-2e5`, change
  `add-e926-rule34-instances`)** — the e621 engine gains its SFW sibling through a new
  `E621_INSTANCES` registry (e926.net, `e926-json-v1`, anonymous, lookup deliberately
  undeclared until captured fixtures exist), and the gelbooru 0.2 family gains rule34.xxx
  as a credentials-required instance on `api.rule34.xxx` (`rule34-json-v1`; the www host
  serves a CAPTCHA wall). Both land with live-captured fixtures (post 6823045; post
  19210742 + notes XML 11899541 — rule34's dapi notes serve XML too, matching the r4y
  finding). Platform rows are migration-seeded (`0022`), `SOURCE_OPERATIONS` grows to nine
  keys, and CLI surfaces select instances explicitly. **Fixed:** live verification against
  both e621.net and e926.net proved the singular post endpoint now wraps payloads in
  `{"post": ...}` — the e621 adapter normalizes both the wrapped wire and the archived
  bare-post fixture shape.
- **Kemono-family investigation recorded (pointer: Anzhc/kemono-browser)** —
  `docs/plans/kemono-family-investigation.md`: the Electron app itself is not adopted
  (interactive media downloader, single hardcoded pawchive instance), but it is recorded
  as a third reference implementation of the Kemono `/api/v1` contract alongside gallery-dl
  and Grabber — including the post-detail `server`-backfill quirk, the file/img CDN split,
  and the `Accept: text/css` spoof. Live probe: `pawchive.pw` serves `/api/v1/creators`
  anonymously (200, 15.8 MB) and `.st` 301s to `.pw`. Assessed as a viable future adapter
  family (maintainer note: only pawchive itself is currently maintained — kemono.su and
  coomer.su are dead or stale by months to a year, so a future adapter ships pawchive
  alone); nothing built.

## [2026-10-30]

### Added

- **Togeari architectural investigation recorded (Bead `data-processing-164`)** —
  `docs/plans/togeari-investigation.md`: the out-of-order KIR machine mapped (lanes, engine
  contract B1–B7, dual Python/Rust cores, replay conformance), the bead's engineering-idea
  attribution corrected (paged KV / CUDA graphs / Triton kernels live in KohakuvLLM and
  kohakugbc_models, not Togeari), and the verdict: no adoption now — it fits a future
  in-repo branching multi-model enrichment lane, not the bounded single-request metadata sync
  the catalog runs today; the kernel bookkeeping boundary stands. Revisit trigger: the
  KohakuGBC evaluation (`dhb`) revealing a concrete pipeline need.

## [2026-10-29]

### Added

- **Sankaku metadata adapter (Bead `data-processing-4ly`, change
  `add-sankaku-metadata-adapter`)** — new provider family speaking Sankaku's API v2
  (live-verified host `sankakuapi.com`; the historical `capi-v2` host refuses this client):
  `sankaku-post` via the `/v2/posts` id-range query and `sankaku-list` via `/v2/posts/keyset`
  with `next`-cursor continuation, both under the bounded-run contract. Credentials
  (`SANKAKU_LOGIN`/`SANKAKU_PASSWORD`) are exchanged once per process for a bearer token that
  exists only in HTTP headers — one re-exchange on an invalid-token signal, no persistent token
  cache, and token/credential absence from all durable material is test-enforced with sentinels.
  Migration `0021` seeds the platform row and `SOURCE_OPERATIONS` admits `sankaku`. Contract is
  capture-verified only: the fixture suite carries live credentialed captures (post
  `wvaemE6YDaz` — opaque base62 string ids, ruby-Time `created_at`, embedded typed tags
  (kernel categories land typed; studio/genre/medium stay unknown), signed expiring media URLs —
  plus a `rating:g` keyset page), scanned for login/password/token before commit. Typed
  per-post tag fetching, notes, pools, and the Idol instance remain deferred.

## [2026-10-28]

### Fixed

- **Gelbooru dapi note contract verified live: XML, not JSON (Bead `data-processing-r4y`)** —
  a credentialed capture of the dapi note index (`s=note`) shows the endpoint serves XML
  regardless of `json=1`, disproving the synthetic JSON-wrapper fixture; post 953320 carries no
  notes, so the fixture subject is post 15172350 (two active notes, captured bytes retained in
  `gelbooru_notes_15172350.xml`). The enrichment parser now reads the XML notes document with
  strict attribute typing (any violation still classifies the whole response
  `malformed_response`); the synthetic fixture and the spec's provisional clause are gone; the
  capture utility gained `capture_gelbooru_dapi_notes`.

### Added

- **Crop-matching next-experiment direction recorded (Bead `data-processing-qi7`)** —
  maintainer guidance appended to `docs/plans/matching-crop-resistant-evaluation.md`: SIFT +
  RANSAC first (ORB deprioritized; learned features only if SIFT struggles; custom tiled
  matching last), a per-pair metric set (RANSAC inliers/ratio, spatial coverage, scale/rotation,
  reprojection error, crop-rectangle containment, symmetric test) instead of raw match counts,
  and the Lowe-ratio + homography pipeline shape. Nothing implemented; the opencv dependency
  decision stays open.
- **Gelbooru-engine adapter family: safebooru.org as the first family instance (Bead
  `data-processing-x5w`, change `extend-gelbooru-family-instances`)** — `GelbooruInstance`
  generalizes to a registered multi-instance family (`GELBOORU_INSTANCES`) with per-instance
  platform key, canonical base URL, credential envs, dapi schema version, and credential
  policy. `SAFEBOORU` (anonymous dapi, `safebooru-json-v1`) ships with a live-captured fixture
  suite: post 7272295 proves the bare-array gelbooru 0.2 generation (no wrapper, no created_at,
  `hash` instead of `md5`, null score) — pinned as contract facts, never synthetic. The dapi
  normalizer lands `created_at` only when the instance supplies it; `SOURCE_OPERATIONS` admits
  `safebooru`; gelbooru dapi CLI commands gain `--instance` (default `gelbooru`); reprocess
  accepts `safebooru`; the capture utility honors per-instance credential policy. rule34.xxx
  stays deferred until credentials allow a live capture.

### Added

- **Replay-stamp repair (Bead `data-processing-3qq`)** — `scripts/repair_replay_stamps.py`
  (dry-run by default) repairs the damage the 2026-10-08 pre-fix reprocess runs left: fact rows
  whose timestamp equals a reprocess run's `started_at` with an identical-facts earlier twin are
  deleted via trigger surgery (6 metadata, 1 snapshot, 172 post-tag observations on the audited
  catalog — every replay row had a twin, zero orphans), occurrence timestamps are restored from
  their retained raw observations, and current-projection fields (3 posts, 55 tags, 87 post_tags,
  2 accounts) are recomputed from the surviving history. Verified end to end on a copy of the
  real catalog: zero replay-stamped rows remain anywhere, foreign keys clean, originals restored.

## [2026-10-26]

### Added

- **Source-scoped anchorless identity + repair path (Bead `data-processing-7o0`; OpenSpec change
  `source-scoped-anchorless-identity`)** — migration 0019 replaces 0018's anchorless partial
  unique indexes with platform-scoped ones: byte-identical payloads from the same source share one
  observation (blessed by decision at the candidate-lookup and library-probe call sites), while
  different sources never fold — 0018's key conflated danbooru/aibooru lookups returning
  identical bodies (two real-catalog collisions verified). Anchorless retention now requires a
  declared source platform. `scripts/repair_anchorless_observations.py` (dry-run by default)
  performs the 0018-comment trigger surgery under the strict definition — keep the earliest row,
  dynamically re-point referencing rows, delete unreferenced members, recreate triggers verbatim,
  verify foreign keys and zero remaining groups — reporting same-platform and cross-platform
  folds separately; proven against a copy of the real catalog (5 folds: 3 same-platform, 2
  cross-platform), which then migrates through 0019 cleanly. A kernel requirement now names the
  identity rule (anchor-scoped or source-scoped content addressing).

## [2026-10-25]

### Added

- **Endpoint-kind generalization decided: conscious deferral (Bead `data-processing-9h6`,
  non-media-consumer spike F3)** — `ENDPOINT_KINDS` stays media-closed until a non-media
  family needs typed linking; when it does, the vocabulary extends by addition, never via a
  generic `object` endpoint. Policy recorded at the declaration in
  `src/media_catalog/records/relationships.py`.
- **Seeding boundary decisions recorded (Bead `data-processing-2mq`)** — quote/reply stay
  provider import discourse facts in `post_relations` (join the typed relationship vocabulary by
  addition only when a consumer needs typed discourse linking), and danbooru variant-level
  thumbnail linking defers to Phase D occurrence-variant objects rather than flattening
  `variants_json` roles into occurrence relations. Policies recorded at `RELATIONSHIP_KINDS` and
  in the thumbnail seeder.

### Changed

- **Per-source remote-run operation registry (Bead `data-processing-6y1`,
  non-media-consumer spike F2)** — `RemoteRunRecord` now validates its operation against
  `SOURCE_OPERATIONS`, a per-platform registry: shipped media platform keys map to the shared
  media set (behavior unchanged for media runs), unregistered platform keys are refused, and a
  platform cannot declare another family's operations. `validate_remote_operation` (requests and
  checkpoints, which carry no platform) validates against the registry union. A non-media family
  registers its own operation names when it lands, widening the SQL CHECK constraints by
  migration.
- **Repost seeding reports dropped source URLs (Bead `data-processing-2mq`)** — the
  `reposted_from` seeding pass now counts `source_url` references that have no resolvable
  platform reference instead of dropping them at the JOIN, reporting skip reasons typed as
  `source_url_unresolved` / `target_post_unresolved` / `self_reference` under `skipped_reasons`
  (`skipped` remains the total).
- **Anchorless raw observations dedup on re-intake (Bead `data-processing-40x`, spike F4)** —
  migration `0018` gives anchorless observations (no import run, no remote run/request) a
  content-addressed identity — object kind, native id when present, payload bytes — via two
  disjoint partial unique indexes. `store_raw` targets them with typed conflict clauses, so
  byte-identical re-intake resolves to the earliest observation instead of appending duplicates;
  anchored rows keep the pre-existing identity.

## [2026-10-24]

### Added

- **Crop-resistant hashing evaluated — negative result (Bead `data-processing-qi7`, remaining
  scope)** — the established library's segmentation-based `crop_resistant_hash` was added to the
  matching-spike harness and measured over the full fixture set: crops land inside the negative
  distribution under library defaults (crop p50 ≈ 4.5 vs negative p50 6–7; zero-FP threshold
  ≈ 1.1 rejects nearly every crop), and parameter sensitivity probing (segment threshold, minimum
  segment size, segmentation resolution — six configurations) rescues none of it. Two families are
  now eliminated for crop detection on this corpus: whole-image hashing and segmentation-based
  region matching. Feature-based (ORB/SIFT-class) methods remain the untested candidate and need
  an opencv-class dependency — a maintainer decision. Findings and probe table in
  `docs/plans/matching-crop-resistant-evaluation.md`; the spike evidence doc cross-links it.
- **Multi-size hash storage decision recorded (Bead `data-processing-yn1`)** — no schema change
  now: phash@16 stays a matching-research fact until a concrete metadata consumer needs finer
  fingerprints; when one does, it lands as a new fingerprint kind (never an `phash` algorithm
  version, which would blur the legacy @8 lineage). Recorded in
  `docs/plans/matching-spike-evidence.md`.
- **Mirror-vs-live strategy recorded (Bead `data-processing-6cu`)** — `docs/plans/mirror-vs-live.md`
  sizes the provider-metadata problem from live counts (danbooru 12,386,307 posts) and measured
  per-post footprint (1,669 B/post, raw payloads 62%), splits query classes into local-served
  (offline joins over the retained corpus) and live-served (bounded point lookups and
  enumeration), and records the decision: stay selective — local is the retained evidence layer,
  live is the bounded surfaces, no full-provider mirror (~21 GB + ~62 k-request refresh sweeps
  for danbooru alone) — with explicit revisit triggers (a provider-wide offline capability,
  retained fraction > ~10%, or a blessed bulk dataset).
- **Commentary and notes enrichment (Bead `data-processing-vus`; OpenSpec change
  `add-commentary-and-notes`)** — four opt-in metadata commands enrich one retained post at a
  time (`danbooru-commentary`, `aibooru-commentary`, `gelbooru-dapi-notes`, `e621-notes`) under
  the pool-fetch run contract: the run commits before the fetch, every response retains its raw
  report, provider faults end `failed`, and transport errors leave auditable runs. Commentary
  (original/translated title and description; provider-empty strings normalized to absence) and
  notes (body, position, e621 version) land as append-only, digest-deduplicated observations —
  unchanged re-observation is idempotent, any text/position/version change lands a new row — and
  nothing derives tags, attribution, or relationships from the text. Migration 0017 adds the two
  tables and rebuilds the remote-operation tables for `fetch_commentary`/`fetch_notes` (verified
  lossless on a copy of the real catalog). Real fixtures captured for danbooru and e621; the
  gelbooru dapi note fixture is synthetic per the documented shape pending a credentialed capture
  (follow-up bead). Default sync paths are untouched.

## [2026-10-23]

### Added

- **Danbooru-family pool collection (Bead `data-processing-cq0`; OpenSpec change
  `add-danbooru-pool-collection`)** — `mcat metadata danbooru-pool` (and `aibooru-pool`) fetches a
  single pool by id under the bounded run contract and records its provider-declared membership
  order as evidence: one digest-deduplicated pool observation (unchanged pools re-observe
  idempotently; any membership or order change lands as a new observation) with ordered member
  observations carrying every native id and position, post links only for already-retained posts,
  and post-view membership through the existing surface. `fetch_pool` joins the closed operation
  vocabularies (migration 0016 rebuilds the three remote-operation tables following the 0010
  idiom, preserving every row); nothing creates work-grouping conclusions. Real fixture captured
  from pool 17001 plus a reordered variant; storage-immutability enforced from the first migration.

- **Evidence dependence modeled as graph-derived lineages (Bead `data-processing-4ry`;
  OpenSpec change `model-evidence-dependence`; GitHub issue #9)** — observation count is
  now formally distinct from independent-corroboration count: the relationship vocabulary
  is classified into descent, equivalence, and structural kinds, and a new
  `lineage_components` derivation computes connected components over a stated dependence
  edge set (descent + equivalence kinds, conclusion-grade epistemic statuses, rejected
  edges excluded) joined through post/occurrence/work anchoring. Dependence is expressed
  only as typed relationships carrying epistemic status — no lineage stamps on evidence or
  observation rows — so a mirror chain keeps four observations but resolves to one lineage,
  and inferred proposals or rejected edges do not merge. Design decisions and a generated
  worked mirror-chain example live in `docs/plans/evidence-dependence.md`; kernel and
  work-relationship requirements bind corroboration to lineages and make independence
  assumptions opt-in.
- **Second non-media consumer spike executed (Bead `data-processing-vyc`; GitHub issue #4)** — a
  bounded PyPI package-metadata intake (`scripts/package-watchlist-spike/`: fetch → intake →
  project) exercised the kernel end to end outside media: source identity via `platforms`,
  append-only source reports, a mirrored bounded run with storage-immutable inputs, typed package
  records, evidence through the shared ledger, and a rebuildable as-of projection reusing the
  projection-spec machinery verbatim. Findings in `docs/plans/non-media-consumer-spike.md`: the
  run-operation vocabulary is media-closed while bending it is possible (`fetch_tag` on a pypi run
  validates), relationship endpoint kinds are media-closed, and anchorless `store_raw` re-intake
  duplicates observation rows under a NULL identity key. Follow-ups filed as beads
  `data-processing-6y1`, `data-processing-40x`, `data-processing-9h6`.

## [2026-10-21]

### Added

- **Temporal as-of semantics named and first surface landed (Bead `data-processing-2ai`;
  OpenSpec change `add-as-of-semantics`; GitHub issue #7)** — the five-timestamp vocabulary
  (source observation, provider-claimed, acquisition, interpretation, review) is mapped to
  its columns in a tracked design doc with fixed as-of reconstruction rules (filter by
  source observation time, re-resolve under the stated policy; review state from the latest
  decision at or before the cutoff; deleted/unavailable objects appear through observations,
  never by absence). A kernel requirement binds the distinction; every export manifest now
  records its evidence cutoff (`as_of`, participating in the spec digest); and
  `post-field-sources` accepts `--as-of` for cutoff-restricted, re-resolved field
  histories. No schema changes, no event-sourcing layer; follow-on surfaces (as-of on
  current-column kinds, change reports, timelines) tracked on the bead.

- **Per-field source export projection (Bead `data-processing-1oi`, final slice; OpenSpec
  change `per-field-source-export`; GitHub issue #6)** — the `post-field-sources` kind emits
  one row per post with retained metadata observations, carrying every observed field's
  complete value history (value, observation time, raw-observation evidence pointer) with
  the newest observation's value marked current under the stated
  newest-observation-wins-all-values-retained policy. Nulls assert nothing and never erase;
  posts without retained observations and limit overflow are excluded with counted reasons.
  Offline, read-only, manifest/digest contracts unchanged. This closes bead 1oi: framework,
  assets/posts/works/attribution-disagreements/post-field-sources kinds all delivered.

### Added

- **Attribution-disagreement export projection (Bead `data-processing-1oi`, second slice;
  OpenSpec change `attribution-disagreement-report`; GitHub issue #6)** — the
  `attribution-disagreements` kind emits one row per retained post-level relationship
  (`reposted_from`, `same_work`) whose ends both carry artist attribution (artist/author
  participants plus tag-implied attribution entities) with no cross-pair joined by a
  confirmed identity membership: the review worklist for attribution, not a verdict. Rows
  carry both ends' identities with review states, the linking relationship, and a
  `name_match` exact-casefolded hint marked as weak evidence; confirmed-join pairs,
  attribution-missing ends, rejected relationships, and limit overflow are excluded with
  counted reasons. Offline, read-only, report-only; rides the existing manifest and digest
  contracts unchanged.

## [2026-10-18]

### Added

- **Confirmed candidates materialize into relationships (Bead `data-processing-zaf`;
  OpenSpec change `add-reviewed-candidate-materialization`)** — `catalog relationships
  materialize` turns confirmed post match candidates into reviewed relationship rows under
  a fixed mapping (`sourced_from`/`repost_of` → `reposted_from` post↔post;
  `same_work`/`variant_of`/`derived_from` → work↔work through the posts' deterministic
  anchors), attaches the candidate's entire evidence bundle through the shared ledger, and
  records a review decision naming the candidate as source. Idempotent via the
  deterministic relationship key with evidence top-up on re-runs; pending/rejected
  candidates, `unresolved` kinds, reference-only targets, and missing work anchors are
  refused with typed reasons; the candidate ledger is never written; nothing ever
  materializes automatically from a score. Materializing onto an already-seeded
  (observed, pending) relationship upgrades it: the confirmation decision lands, the
  status moves to `reviewed` with the prior status retained in history, and an
  already-confirmed row gains only the new evidence.

## [2026-10-16]

### Added

- **`parent_of` joins the deterministic relationship seeder (Bead `data-processing-zaf`
  audit follow-up; OpenSpec change `seed-parent-of-relations`)** — `catalog relationships
  seed` now materializes `parent_of` (post↔post, `observed`) from retained
  provider-declared post parent relations, citing provider-declaration evidence and linked
  raw observations; idempotent via the deterministic relationship key. `quote`/`reply`
  stay in `post_relations` pending a vocabulary decision.

- **Work entities and the typed relationship model — kernel Phase D schema half (Bead
  `data-processing-t08`; OpenSpec change `add-work-relationship-model`; GitHub issues #2 and
  #3)** — migration 0015 adds works (minimal deterministic anchors, one per post with
  occurrences, no media vocabulary), work representation links, one uniform
  typed-relationship table (polymorphic endpoints, closed fifteen-kind vocabulary, epistemic
  status, canonical orientation with deterministic relationship keys), evidence attachment
  through the existing match-evidence ledger, append-only reversible review decisions, and
  append-only status-transition history — with trigger-enforced immutability tiers from day
  one (anchor identity and links immutable; relationship identity immutable with only state
  fields updatable; evidence links, decisions, and history fully immutable; nothing
  deletable). `catalog works materialize` and `catalog relationships seed|list|show|review`
  land the deterministic surfaces: same_bytes from SHA-256 content dedup (verified),
  thumbnail_of from provider-declared variant roles (observed), and reposted_from from
  provider-declared source URLs (observed) — all offline, idempotent, evidence-citing, and
  never establishing identity, authorship, or same-work. A `works` export projection kind
  groups variant families per work under a stated policy excluding thumbnail roles and
  preferring the upstream original then the largest verified area. The design carries the
  gh#2 semantic decision table and the gh#3 lifecycle model; the records/persistence surface
  contracts were consciously updated (47 record signatures, 60 writer methods).

### Changed

- **Kernel plan mapping updated after Phase D** — the provenance-kernel plan's mapping
  table now records the landed work/relationship surfaces (`works`, `relationships`,
  migration 0015) and names the remaining `post_relations` absorption decision, replacing
  the stale "not built" / "partial, scattered" rows.

## [2026-10-09]

### Added

- **Export projections: bounded, reproducible JSONL/CSV views over the evidence layer (Bead
  `data-processing-1oi`; OpenSpec change `add-export-projections`; GitHub issue #6)** —
  `catalog export plan|run` previews and writes projection kinds `assets` (one row per
  verified asset, exact byte-duplicates collapsed by content identity with representation
  counts) and `posts` (current facts with their evidence pointer, occurrence summary,
  participants with review states, optional platform filter) as JSONL and/or CSV plus a
  manifest sidecar. The manifest is the full recipe per gh#6: kind and projection schema
  version, six stated policies, source schema and tool versions, generation timestamp,
  per-file row counts and content digests, inclusion/exclusion counts with bounded reasons,
  stable evidence-layer identifiers, and deterministic `spec_digest`/`selection_digest` —
  re-runs on unchanged evidence reproduce digests and byte-identical files. Execution is
  offline and read-only (no-write snapshot open), output is deny-by-default allowlisted (no
  storage paths, credentials, signed URLs, or raw payloads; URLs emit origin and path only),
  and exports are bounded with `excluded_by_limit` reporting. Remaining on the bead:
  attribution-disagreement report, per-field source exports, variant-family grouping (Phase D).

## [2026-10-08]

### Fixed

- **Reprocess review fixes: source observation time and schema-drift planning (Bead
  `data-processing-qoa`; GitHub issue #8 review)** — replayed facts now land at the retained
  raw's original observation time instead of the replay wall-clock (which runs only on the
  reprocess run), so a replayed older raw can no longer outrank genuinely newer source
  observations in current-projection resolution (`posts.last_seen_at` guards, tag/attribute
  last-observed upserts, post metadata observation ordering); and `reprocess plan` treats
  schema-version drift (or a NULL schema version) as stale alongside adapter-version drift,
  matching the (payload, adapter version, schema version) normalization identity instead of
  relying solely on the adapter-version-bump discipline. Both are conformance restorations of
  the synced `remote-metadata-sync` reprocessing requirement; two regression tests reproduce
  each defect against the pre-fix code.

### Changed

- **README and user-facing terminology restructured around the three layers (Bead
  `data-processing-n7l`; GitHub issue #1)** — the top-level README now presents the
  provenance/data-gathering kernel, the media/social domain family, and the current
  `x-likes`/`catalog` workflows as distinct layers, with a terminology table naming what stays
  intentionally legacy or domain-local (no code or CLI renames) and a "what this can become"
  section framing future surfaces as evidence-layer projections that do not exist yet. The
  roadmap date/state coherence was restored for the 2026-10-05 through 2026-10-08 capability
  work (matching evidence, materialize-a-seed, e621 content facts, Pixiv engagement,
  reprocessing), and a duplicated changelog line in the 2026-10-07 entry was removed.

### Added

- **Retained raw now reprocesses offline under newer normalizers (Bead `data-processing-uru`,
  OpenSpec change `add-reprocessing-contract`; GitHub issue #8)** — `catalog reprocess
  plan|run` replays retained provider responses through the current adapter with zero
  provider requests: the reconstructed envelope normalizes and commits through the shared
  page writer under a `reprocess`-origin remote run (migration 0014 extends the origin-kind
  vocabulary), the retained payload is never modified, identical facts dedup by observation
  digest, replaying the same raw under the same versions is skipped, and malformed
  historical payloads fail as typed retentive outcomes. Establishing the contract surfaced a
  real gap: this week's normalizer changes had shipped without version bumps, so all four
  provider adapters now carry `-v2` versions (fixture manifests and pinned literals follow,
  with a guard test keeping them in lockstep). Verified live: the six retained danbooru
  post raws replayed complete offline, a re-run skipped, and six zero-request reprocess
  runs recorded. Retained lookup responses and import raws have no metadata-operation
  linkage and stay out of scope.

## [2026-10-07]

### Added

- **Pixiv engagement totals normalize (Bead `data-processing-cyp`, partial; OpenSpec change
  `extend-pixiv-engagement-facts`)** — artwork details emit bookmark and comment counts
  (from `total_bookmarks`/`total_comments`) that persist as post metadata observations
  through the shared page writer, reprocess-able from retained raw. The audit records the
  remaining scope precisely: `total_view` and the classification fields have no persistence
  homes; series membership has no representable object kind today (the same constraint that
  defers e621 sets — waits on the typed relationship model, bead `data-processing-t08`);
  and a related-works operation needs a new `AdapterOperation` value whose CHECK
  constraints on `remote_runs`/`remote_requests` require deliberate table rebuilds.

- **e621 post content facts normalize (Bead `data-processing-8jj`, OpenSpec change
  `extend-e621-post-content-facts`)** — description content lands as post text
  (`posts.text_content` — live-verified e621 descriptions embed the artist's original
  "From source:" caption, i.e. retained source content), the top-level seconds float
  lands as the occurrence's `duration_ms`, and URL-bearing `sample.alternates` enrich the
  variant metadata under `alternate:*` names with dimensions, extension/MIME, fps, and
  codec. Malformed shapes fail closed. Findings recorded in the audit: `locked_tags` and
  `change_seq` stay raw-retained (no persistence home), and the sets surface is verified —
  `/sets.json` does not exist; the real endpoint `/post_sets.json` returns 403 anonymously,
  so set membership needs the authenticated transport plus the typed grouping model
  (Bead `data-processing-t08`).

- **Materialize-a-seed gains the local-bytes phase (Bead `data-processing-8b2`, completed;
  OpenSpec change `add-materialize-seed` archived)** — `catalog seed create --file` ingests
  the file the operator holds: its content hash joins the bundle identity (changed bytes are
  a new seed), a declared MD5 is verified against the bytes before any write, and the file
  adopts through the existing managed-storage machinery into the designated `--media-root`,
  yielding verified SHA-256/MD5, detected dimensions, and a recorded perceptual hash linked
  to the stub's occurrence. The stub therefore seeds `external_post_id`, `declared_md5`, and
  `verified_md5` lookup planning exactly like a recorded post — requirement 1's non-recorded
  half now works end to end with innate image metadata preferred, per the decided design.

## [2026-10-06]

### Added

- **Non-recorded items gain a materialize-a-seed entry point (Bead `data-processing-8b2`,
  phase 1, OpenSpec change `add-materialize-seed`)** — the decided design's first half:
  `catalog seed create` ingests the operator's evidence bundle (one or more URLs where the
  item was found, optional note, optional declared MD5; all URLs must resolve to stable,
  pairwise-consistent post identities) and materializes a provenance-recorded stub post —
  the bundle retained as raw `operator_seed` import evidence, availability `unknown`, every
  URL as a `source_url` link and typed `provider_id` reference. The stub is an ordinary
  lookup seed (`external_post_id` planning accepts it exactly like a synced post),
  materialization is idempotent and decides nothing, and later real syncs enrich the stub
  in place. The local-bytes phase (hashing a held file into verified asset facts) remains
  open on the bead.

- **Gelbooru gains bounded reverse lookup and relationship normalization (Bead
  `data-processing-o6y`, OpenSpec change `add-gelbooru-bounded-lookup`)** — the last
  adapted provider with zero lookup capability now declares `source_post_url`,
  `declared_md5`, and `verified_md5` (rendered as exact credentialed DAPI `tags=` queries
  with digest-only request identities and pid page continuation under the shared limits;
  the HTML transport stays lookup-free), and the CLI accepts `--provider gelbooru` for
  plan/run/resume. Single-post DAPI fetches request `fields=tag_info`, so detail
  observations land typed tag categories (`tag`→general, `metadata`→meta, undocumented →
  unknown) instead of flat `unknown`; post `parent_id` normalizes as a directional
  `parent_of` relation and `title` lands on the post projection. The audit's
  favorites-dispute is resolved from references: gallery-dl's DAPI JSON `s=favorite&id=`
  works; Grabber's JSON path only refuses generic favorites syntax. Requirements 1 and 2
  are no longer blocked for gelbooru.

## [2026-10-05]

### Added

- **Danbooru-family post and artist fact normalization catches up (Bead
  `data-processing-unp`, OpenSpec change `extend-danbooru-post-artist-facts`)** — the
  adapter now emits fields the persistence layer already supported but no provider fed it:
  post score components (danbooru's negative `down_score` translated to the neutral
  downvote count), favorite count, and status flags as post metadata and flag
  observations; per-variant dimensions from `media_asset.variants` including the
  provider-native intermediate sizes (180x180/360x360/720x720) on the occurrence's
  variant metadata; and artist `group_name`/`is_banned`/created/updated on attribution
  snapshots. Malformed shapes for the new fields fail closed. Findings recorded in the
  metadata audit: danbooru post payloads carry no pool ids (pool grouping split out to a
  dedicated pools-surface bead), and `tag_count_*`/`has_children` are derivable from
  already-normalized tags and relations.

- **The identification-bridge hardening unit is completed (Bead `data-processing-zos`)** —
  e621's `external_post_id` now renders both known pixiv source URL spellings (bare and
  `/en/`) as separate bounded requests walked by the existing alias continuation, pinned by
  adapter tests and verified live through the mirrored control (danbooru post 12320097 →
  pixiv 150422897 → e621: two distinct requests, honest zero — not mirrored).
  `source_post_url` is demoted to weak evidence with the 0/10 probe result in the catalog
  guide's strategy-strength note, and the non-recorded-seed entry point is decided as a
  materialize-a-seed operation that ingests the full evidence bundle available at the time
  (innate image metadata first, supplied references at declared/asserted status) — recorded
  in the catalog plan §12 and the metadata audit.

- **Discovery-found references now seed stable-ID lookups (Bead `data-processing-zos`,
  partial)** — lookup planning read only sync-written `post_external_references`, so a
  pixiv URL discovered in a bookmark's text was invisible to the `external_post_id`
  strategy; the material query now unions the discovery chain
  (`link_observations` → `external_link_references` → `platform_references`), with a
  regression test. The live positive control then completed the first end-to-end
  identification hop: an X bookmark → discovery-found pixiv reference → Danbooru
  `pixiv_id:` metatag search → one result, landing as a pending review candidate.

### Fixed

- **The hosted-source metadata audit is delivered (Bead `data-processing-a3t`)** —
  [docs/plans/metadata-audit.md](docs/plans/metadata-audit.md) consolidates, per provider
  (danbooru/aibooru, gelbooru, e621, pixiv, X), what each source exposes (mined from
  gallery-dl and Grabber) against what the repo retains and normalizes, with every gap
  classified reprocess-able vs refetch. Headline findings: the strongest identification
  bridge (danbooru's first-class `pixiv_id` field and `pixiv_id:` metatag lookup) is
  already wired but never exercised; gelbooru has zero lookup capability despite
  server-side md5/source/id/parent search support; danbooru's adapter skips
  score/flag/pool fields the persistence layer already accepts; pixiv series and
  related-works are unnormalized relationship surfaces. Worklist filed as six beads.

### Fixed

- **e621 candidate lookups no longer reject the provider's response envelope (Bead
  `data-processing-7lt`)** — e621's `/posts.json` search wraps results in a `{"posts":
  [...]}` object while the lookup parser accepted only bare lists, so every e621 post lookup
  reported `malformed_response` regardless of results. The parser now unwraps the envelope
  (tag and alias endpoints keep their bare-list shape); fixture tests cover empty and
  populated envelopes, and the live probe seed that previously failed now returns a clean
  bounded page.

- **Link discovery no longer aborts on metadata-sync-attached links (Bead
  `data-processing-815`)** — discovery's end-of-run garbage collection deleted
  `external_links` that lacked discovery observations, but metadata sync legitimately
  attaches links through `post_external_references` and `account_external_links` without
  observations; after any provider metadata sync the whole `discover-links` run failed with
  a foreign-key violation. The collection now spares links referenced by any attach point,
  verified by a regression test and on the live catalog.

### Added

- **The supervised matching research spike is delivered (Bead `data-processing-8nj`)** —
  a bounded, manifest-driven research harness under `scripts/matching-spike/` (seeds,
  manifest builder, host-allowlisted fetcher, measurement runner) with private fixtures
  under `private-exports/matching-spike/`, and the redacted
  [matching spike evidence](docs/plans/matching-spike-evidence.md): 133 labeled pairs
  measured from real data — positives at phash@8 distance ≤ 10, negatives ≥ 22, two
  byte-identical cross-provider mirrors, thumbnails visually identical to originals at
  phash@8, and an empty same-artist false-positive class flagged as the key gap. Per the
  maintainer decision recorded in the evidence document, these measurements are research
  evidence only: catalog hashes remain identification metadata, and no similarity
  mechanism enters a product surface unless a generic, evidence-backed one is proven.

## [2026-10-04]

### Added

- **The audit-immutability sweep is completed (Bead `data-processing-5de`)** — migration 0013
  adds deletion guards for the pre-0012 update-only surfaces (expansion plans, probes,
  executions, and post associations; candidate-lookup requests; media-acquisition attempts),
  full immutability for acquisition verification records and source-report payloads (payloads
  previously protected only transitively; verifications previously unguarded), and primary-key guards on the recreated 0006/0007
  immutable-inputs triggers, matching 0012's stronger pattern. The mutation sweep again found
  zero delete statements on every guarded surface; the full suite passes under the triggers.

- **Kernel storage enforcement is closed (Bead `data-processing-ts5`)** — migration 0012 brings
  every audit surface the provenance-kernel spec names under storage-level enforcement: source
  reports, post-tag observations, provenance-event revisions, and review decisions are immutable
  and undeletable; provenance events, adoption attempts, candidates, evidence rows, and evidence
  links are never deleted but keep their legitimate current-field updates (event projection
  refresh, attempt re-recording, review state, rematerialized digests); remote requests are
  undeletable and immutable after insert except attaching — never swapping or detaching — their
  retained source report; and remote-run declared inputs (including transport identity) are
  immutable while state and counters advance. The change is archived as
  `close-kernel-storage-enforcement-gaps` with its requirement synced into the main
  provenance-kernel spec. A
  two-part writer audit (mutation statements and upserts) shaped the enforcement strengths so no
  audited write path breaks — the full suite passes under the triggers. Known consequence: a
  future purge/redaction feature must supersede or tombstone rows rather than delete history.

- **The export-projections milestone candidate is filed (Bead `data-processing-1oi`)** — bounded
  JSONL/CSV export projections over the evidence layer, an attribution-disagreement report, and
  per-field-source exports. A gap analysis against `docs/plans/raw_future_plan.md` found the
  catalog CLI has no export surface today and named this the highest-leverage non-Phase-D work
  toward the raw plan.

### Changed

- **The roadmap names the work and relationship model (kernel Phase D) as the leading next
  milestone**, with practical workflows free to take priority. A gap analysis against
  `docs/plans/raw_future_plan.md` split the milestone into independently landable halves: the
  schema half (artifact/work entities and the typed-relationship model, Bead
  `data-processing-t08`) and the supervised matching research spike, which gates only fuzzy
  matcher proposals and is rescoped to its own lower-priority bead (`data-processing-8nj`, P3).

## [2026-10-03]

### Added

- **The reviewed-target workflow lands (kernel Phase C)** — OpenSpec change
  `generalize-reviewed-target-workflow`: a new offline `catalog library capabilities` view reports
  the enumeration operations (or explicit unsupported markers) for any stable account or
  attribution target; target resolution now reports pending/rejected candidates as ineligible
  with their review state instead of silently filtering them; `catalog assets download-plan
  --library-plan` resolves acquisition selections from a committed expansion's associations
  offline under a fixed criteria set (variant, availability, eligibility, item limit), reporting
  `details_required` posts and `excluded_by_limit` counts, with the preview matching an equivalent
  explicit `--select` plan; and provider-path proof is complete for all four registered
  capabilities — new Danbooru and AIBooru checkpoint/resume coverage plus a per-provider
  pause/resume matrix test alongside the already-proven Pixiv and e621 paths. Upgrade note:
  resolution now emits `review_state_*` exclusions for unconfirmed candidates, which changes
  replan digests for seeds with such candidates — paused expansions created before the upgrade
  fail closed as stale on resume and must be re-planned and re-run.

- **The provenance-kernel direction is adopted** — a new `docs/plans/provenance-kernel.md` defines
  the domain-neutral vocabulary (source, source object, observation, provenance event, blob,
  representation,
  assertion, relationship, evidence, acquisition, run, review, projection) with uniform epistemic
  statuses (`observed`, `verified`, `derived`, `inferred`, `reviewed`), and maps every concept onto
  the existing catalog schema with status and action. The kernel is latent in today's tables, so
  this is a naming, spec, and boundary change — no data migration is planned. Milestone tracked as
  Bead `data-processing-u1d`.

- **The provenance-kernel capability spec is implemented** — OpenSpec change
  `add-provenance-kernel-spec` adds a standalone `provenance-kernel` capability with twelve
  requirements covering source identity, append-only source reports, provenance events,
  content-addressed blobs, declared/verified comparisons, typed relationships with epistemic
  status, the evidence ledger, append-only reversible review, the bounded run contract,
  storage-enforced audit immutability, projections, and kernel-invariant preservation. A
  schema-accuracy review corrected enforcement overstatements in the spec and the kernel plan's
  verified-mapping claims (immutability triggers cover only
  the listed tables; `remote_runs` inputs are immutable by convention today; acquisition runs use
  item/byte budgets with partial-based resume), added a precedence statement over domain-altitude
  capability specs, and neutralized media vocabulary in the provenance-event requirement;
  remaining storage-enforcement gaps are filed as Bead `data-processing-ts5`. The change is
  archived with the spec synced into the main specs, and the roadmap records the architectural
  pass complete.

### Changed

- **All adoption SQL now lives in StorageWrites** — the `adoption_items` read moved off the
  CatalogWriter facade into the persistence component (Bead `data-processing-v4i`); the facade
  method now delegates and no callers changed.

- **Single-family vocabularies and validators colocate with their record family modules** —
  acquisition, lookup, library (minus the cross-family origin-kind pair), and storage/adoption
  vocabulary-validator pairs moved from `records.common` into their family modules with the
  facade re-export surface unchanged (Bead `data-processing-ee0`); `records.common` now holds
  only cross-family primitives.

- **The roadmap's goal broadened** from a cross-platform media catalog to a source-aware gathering
  and provenance system with media as the first data family. The next milestone is the bounded
  provenance-kernel architectural pass (per-table mapping verification, an OpenSpec kernel
  capability spec, and cheap boundary re-homing absorbing the two ready persistence follow-ups);
  the reviewed-target workflow milestone follows it. Two principles were added: the durable
  database is the evidence layer with projections on top, and domain-neutral extraction requires a
  second consumer or a concrete workflow.
- **The media catalog plan is annotated** as the media-family domain plan under the kernel framing;
  its vocabulary remains authoritative for the media family.

## [2026-10-02]

### Added

- **The Gelbooru OpenSpec change is archived with specs synced** — the 10 delta requirements were
  merged into the main specs (new `gelbooru-metadata-adapter` capability spec with its seven
  requirements, one persistence-neutrality requirement into `media-catalog-core`, and transport-
  identity plus ephemeral-query-credential requirements into `remote-metadata-sync`), strict spec
  validation passes for all 14 capabilities, and the change moved to
  `openspec/changes/archive/2026-10-02-add-gelbooru-metadata-adapter/`.

- **Gelbooru DAPI continuations are fully scope-validated (task 3.4)** — listing continuations now
  carry every enumeration dimension — operation, listing target, query scope (unfiltered only, so a
  continuation claiming a tag query fails closed), sort (`id-desc`, the only pid-stable DAPI order),
  transport, direction (`forward`), page boundary (`pid`, `last_pid`, `limit`, and the last-seen
  post id for drift audit), and continuation/adapter/schema versions — and resume validates all of
  them before any network access. The continuation version bumped `gelbooru-pid-v1` → `gelbooru-pid-v2`
  so legacy unscoped checkpoints fail closed with a clear version error, the listing request
  identity/target embed the scope (`listing:<target>:id-desc:forward:<pid>:<limit>`), and boundary
  consistency requires `pid == last_pid + 1`. Thirteen new tests pin each dimension's rejection plus
  fail-safe handling of legacy request-target material; `gallery-dl`'s Gelbooru extractor (pid
  stepping and `sort:id`/`id:<N` ordering evidence) was used as the interaction reference.
- **The Gelbooru DAPI JSON adapter is implemented** — `GelbooruAdapter` renders explicit authenticated
  requests for single-post fetch (`id=`), tag metadata (`name=`), and bounded post listings (`pid`/`limit`),
  normalizes fixture-proven response shapes (list, dict, bare-array, missing-key empty, three error
  envelope forms) into provider-neutral `NormalizedItem` pages covering posts, accounts, uploader
  participants, unknown-category tags, media occurrences with original/sample/preview variants,
  and source references; `_gelbooru_timestamp` handles both ctime-like and `YYYY-MM-DD HH:MM:SS`
  timestamp formats observed in live captures.
- **Gelbooru DAPI adapter tests verify request shapes, typed outcomes, and normalization** — 27
  injected-transport tests pin exact rendered request parameters, the 100-entry page ceiling, status
  code-to-outcome mapping (401/403/404/429/5xx/error-envelope/malformed), response-first raw
  retention, continuation validation, listing continuation with pid increment, idempotent
  normalization against fixture data, zero media-host requests, and all three DAPI response shapes.
- **The Gelbooru anonymous HTML adapter is implemented** — `GelbooruHtmlAdapter` performs exactly one
  unauthenticated GET to the canonical post page with no login, cookies, or media requests;
  fail-closed parsing requires `<title>` and `<img id="image">` markers, detects challenge pages
  via missing tag-list and statistics, and normalizes fixture-proven fields (title, source, uploader,
  rating, score, declared hash, dimensions, tag-category classes, original/sample/preview references).
- **Gelbooru HTML adapter tests verify bounded parsing and typed outcomes** — 22 tests cover
  single-request behavior, canonical request identity, marker extraction, category preservation,
  no secondary requests, no media access, no credentials or cookies, and fail-closed handling of
  missing title, missing image, challenge pages, 404, 403, empty payloads, and non-UTF8 responses.
- **Gelbooru metadata flows through the shared remote-sync stack** — both adapters now expose the
  provider pacing floor for the bounded executor and emit score facts in the mapping form the page
  writer persists; HTML tag categories map onto the neutral vocabulary (`metadata` → `meta`), and
  a six-test synchronization suite drives real catalog persistence over injected transports to
  prove raw-first retention before normalization, atomic page commits with checkpoint/resume for
  `pid` listings, DAPI/HTML observations coexisting as separate transport-identified raw records
  under one reconciled post identity, challenge denial without normalized writes, and rollback
  that keeps the retained raw attempt when a page commit fails midway.
- **Gelbooru tag-category and attribution policy is proven in persistence** — four more
  synchronization tests pin uncategorized DAPI tags keeping their native spelling under neutral
  `unknown`, HTML categories carrying only the fixture-proven neutral values, the uploader
  participant staying distinct from artist/creator attribution (no attribution entities are
  invented), and metadata runs writing zero liked/bookmarked activity observations; the shared
  page writer's fallback for a post tag without a category changed from `general` to `unknown` so
  a provider that stays silent is never recorded as claiming the tag is general.
- **The Gelbooru current-projection and metadata-only policies are pinned** — a later HTML
  observation never erases DAPI-proven facts (original URL, declared MD5, dimensions, post
  status all survive omission), a later DAPI observation fills the gaps an HTML-only view
  lacked, a disagreeing rating resolves to the newer observation while both raw payloads keep
  the audit trail, and returned media URLs stay browseable metadata-only variants with declared
  MD5 as a provider assertion and zero asset or acquisition rows after synchronization.
- **The Gelbooru acceptance matrix reconciles all five real posts across transports** — five
  parametrized tests verify each captured post ID (12370900, 11605534, 10720246, 10791439,
  10791440) synchronizes through both DAPI and HTML, produces stable post reconciliation under
  a shared numeric identity, and retains independent observation histories; the three variation
  records each maintain distinct/pair semantics with two transport-identified raw observations
  per post.
- **Gelbooru privacy and network-isolation tests cover result objects and endpoint contact** —
  sync result objects, run metadata, and database rows are scanned for credential sentinels and
  contain no authenticated URLs; adapter-level tests prove only gelbooru.com is contacted with
  exactly one request per transport and no secondary media-host requests.
- **Gelbooru budget, resilience, and transport-mismatch tests use real catalog persistence** —
  budget exhaustion halts at the record boundary with raw retention but no committed page;
  database reopen and resume produces no duplicate posts; re-observation is idempotent while
  growing raw history; malformed DAPI responses produce typed `malformed_response` outcomes;
  transport mismatch is rejected before any network access.
- **Provider regression suites for Pixiv, Danbooru, AIBooru, and e621 pass** — existing
  adapter and metadata-sync test suites for all four providers confirm Gelbooru integration
  does not declare or trigger unrelated capabilities.
- **Disabled-by-default live smoke tests require explicit operator authorization** — one DAPI
  post and one HTML post smoke test are guarded by `GELBOORU_LIVE_SMOKE=acknowledged` and
  external credential environment variables, with hard request/body/record/time limits and
  assertions that no media host is contacted.

### Changed

- **Gelbooru schema audit timestamp corrected** — live captures use ctime-like format with timezone
  offset (`Wed Jul 30 10:16:34 -0500 2025`); the adapter normalizes to UTC ISO, and schema audit
  and adapter test expectations now match the actual normalized timestamps.

### Fixed

- **Scoped-continuation review: validation errors are never transient provider faults** — the
  shared request gate no longer wraps adapter `ValueError`s as `transient_provider`; local
  request-contract failures (incompatible continuation version or scope, malformed target, absent
  credentials) now propagate so the sync service records the run failed with the root cause in its
  diagnostic instead of masking it as a retryable provider fault. A stale pre-bump `gelbooru-pid-v1`
  checkpoint resume is pinned by a service-level test: permanent failure, truthful message, no
  transient classification. The DAPI post parser also now filters non-dict entries from wrapped
  `post` lists (matching the bare-array shape) so a garbage trailing entry can never crash
  continuation production with an untyped `AttributeError`. Two formerly untested scope branches
  (in-value continuation and adapter version material) gained rejection tests.
- **Gelbooru adapters harden typed failures after a three-angle review** — DAPI post records with
  missing or unparseable `created_at` now raise `malformed_response` instead of crashing with
  `KeyError`/`ValueError`; malformed listing continuation payloads are rejected with a clear
  `ValueError` before network access; oversized response bodies raise the new
  `response_too_large` outcome (matching the pinned fixture contract) in both DAPI and HTML
  transports; httpx transport exceptions are re-raised as `transient_provider` with credential
  values scrubbed from the message; the HTML challenge check now runs before the identity-marker
  checks so well-formed challenge pages yield `authorization_denied` instead of
  `malformed_response` while truncated markup without a title still fails as malformed; and HTML
  post items carry an explicit null `status` for shape consistency with DAPI observations. Nine
  new injected-transport tests pin these behaviors. Two review findings were verified as false
  alarms (the Source regex is bounded by the opening tag; the malformed fixture is valid JSON),
  and one — sample-versus-original dimensions — was already handled by preferring the `Size:`
  statistic.

## [2026-10-01]

### Added

- **The Gelbooru schema audit proves the neutral schema needs no migration** — a fixture-driven
  round-trip suite persists every proven Gelbooru fact (platform seed, posts with ratings and
  declared hashes, uploader participants, unknown-category tags with native numeric codes,
  transport-identified raw observations and remote runs) while exercising foreign-key,
  origin-immutability and vocabulary triggers, idempotent re-upserts with stable IDs, rollback
  cleanliness, and doctor checks; tag ambiguity stays recoverable through retained raw payloads.
- **The reviewed Gelbooru fixture contract is documented** — a provider contract record now covers
  observed request and response shapes, post/tag field types, envelope variants, page-number
  pagination semantics, tag-category evidence, media variants, status-to-outcome mapping, pacing
  and redaction decisions, and every unresolved provider assumption, split by provenance
  (observed, reference-corroborated, synthetic, deferred).
- **Gelbooru error and tag fixtures pin typed outcomes** — observed shapes (numeric-type tag
  records, count-zero not-found envelopes, anonymous 401 with empty body) plus
  documentation-derived synthetic 403/5xx/oversized/malformed envelopes cover every typed DAPI
  and HTML failure mode except rate limiting, which stays deferred until actually observed; the
  rate-limit gap is recorded in the fixture manifest.
- **Reviewed Gelbooru fixtures pin the documented post examples** — live credentialed DAPI and
  anonymous HTML captures of the five planned posts (including the text/clean variation pair and
  the distinct third image) are committed as redacted contract fixtures with derived expected
  summaries, stripped inline scripts and session token values, marker-region HTML reduction, and
  tests asserting the variation relationships from the example plan.
- **Gelbooru credential material is scrubbed by a shared redaction boundary** — DAPI credentials
  now join query parameters only through a single final-boundary helper, and a reusable scrubber
  removes credential values and credential-bearing URLs from transport exceptions and any durable
  record, diagnostic, or output surface, pinned by sentinel-based tests.
- **Focused compatibility tests pin catalog writer idempotency and errors** — repeat upserts across
  account, post, media, observation, link-observation, and asset writes now assert the
  inserted/existing/updated outcomes with stable row identifiers, and the exact texts of platform,
  discovery, observation, raw-observation, and remote-run validation errors are asserted through
  the facade.

### Changed

- **The roadmap tracks the active Gelbooru milestone** — the completed e621 verification handoff
  milestone is retired with e621 capabilities marked complete, and the current milestone now names
  the bounded Gelbooru metadata adapter together with its explicit live-capture authorization
  gate.
- **Discovery and core-catalog writes moved behind internal persistence components** — the three
  discovery run/link-observation methods and the seven account, post, participant, observation,
  relation, media-occurrence, and asset-link methods now live in
  `media_catalog.persistence.discovery.DiscoveryWrites` and `...catalog.CatalogWrites`, with
  `CatalogWriter` delegating identically on the caller's shared transaction.
- **Tag, attribution, and external-reference writes moved behind an internal persistence
  component** — tag, tag-alias, post metadata/pool/flag, attribution, and external reference/link
  write methods now live in `media_catalog.persistence.metadata.MetadataWrites` together with the
  attribution-name and reference-URL helpers only they use, delegated identically by
  `CatalogWriter`.
- **Remote synchronization writes moved behind an internal persistence component** — raw
  observation storage and the remote run, request, and checkpoint write methods now live in
  `media_catalog.persistence.remote.RemoteWrites`, delegated identically by `CatalogWriter` with
  transport-identity checks preserved.
- **Candidate-lookup and library-expansion writes moved behind internal persistence components** —
  the five lookup run/request/checkpoint/result methods and four library plan/probe/execution/post
  methods now live in `media_catalog.persistence.lookup.LookupWrites` and
  `...library.LibraryWrites`, with identical public signatures delegated by `CatalogWriter`; the
  platform-identity lookup became a shared support helper the facade and components both use.
- **Acquisition writes moved behind an internal persistence component** — the nine acquisition
  plan, run, run-item, attempt, partial, verification, and quarantine write methods now live in
  `media_catalog.persistence.acquisition.AcquisitionWrites` with identical public signatures
  delegated by `CatalogWriter` on the caller's shared transaction.
- **Managed-storage and adoption writes moved behind an internal persistence component** — the
  eight root, asset-location, occurrence-source, fingerprint, and adoption write methods now live
  in `media_catalog.persistence.storage.StorageWrites`, with `CatalogWriter` keeping identical
  public signatures as explicit delegations on the caller's shared transaction; the root-upsert
  compatibility alias is preserved.

## [2026-09-30]

### Added

- **Catalog persistence gains an internal shared-support package** — `media_catalog.persistence`
  now provides the connection, timestamp, inserted-id, and write-result helpers that extracted
  writer components will share; `writer.py` imports them while keeping its public surface
  unchanged, and a guard test forbids any component from committing, executing scripts, or
  opening its own connection.

### Changed

- **Catalog record types are organized into domain modules behind the existing import surface** —
  `media_catalog.records` is now a package with discovery, core catalog, remote-sync, metadata,
  storage/adoption, acquisition, candidate-lookup, and library-expansion families re-exported
  compatibly, so existing imports, constructors, validation, and public names are unchanged.
- **The persistence compatibility suite pins the record surface more completely** — characterization
  coverage now also locks record fields and defaults, frozen/slots behavior, annotation resolution,
  per-family validation, and defining module paths, alongside the existing constructor, name, and
  writer-signature digests and the cross-domain rollback test.
- **Agent instruction files corrected** — quality-gate examples in CLAUDE.md and AGENTS.md now
  reference the `media_catalog/records` package instead of the removed single-module path.

## [2026-08-13]

### Added

- **e621 metadata can be synchronized through the catalog** — added a native adapter for bounded
  post, artist, tag, alias, and artist-tag listing requests with descriptive identification,
  optional external Basic-auth credentials, conservative pacing, typed failures, raw-response
  provenance, and resumable ID-keyset pagination without requesting media bytes.
- **e621 provider facts have neutral queryable persistence** — added versioned storage for native
  tag identities and categories, aliases, attribution details, post scores and counts, flags, and
  pool observations while preserving uploader roles, artist attribution, and locally verified
  asset facts as distinct concepts.
- **The metadata CLI supports explicit e621 workflows** — added post, artist, tag, alias, and
  bounded listing commands with finite budgets, stable human and JSON output, checkpoint resume,
  credential privacy, and no implicit media acquisition.
- **e621 evidence can feed bounded lookup and library expansion** — added source-URL, external-ID,
  declared/verified-MD5, exact-name, and approved-alias strategies; stable artist-tag expansion
  with retained-count estimates, opaque `b<ID>` resume, target-scoped browsing, and no fuzzy search
  or automatic identity/authorship conclusions.
- **Selected e621 variants can enter verified acquisition** — added explicit original/sample/preview
  handoff from browse selectors, a bounded `static1`–`static9` host and redirect policy, original-only
  claim comparison, derivative claim separation, quarantine, and CAS reuse without metadata-triggered
  downloads.
- **The catalog guide documents e621 operations and boundaries** — added external credential and
  pacing guidance, dynamic category and alias provenance, privacy/troubleshooting notes, and the
  disabled-by-default live-smoke limitation; Gelbooru and cross-database alias mapping remain future
  work.

### Changed

- **Remote synchronization admits continuation pages before requesting them** — request, page,
  record, and time boundaries now stop unadmitted work before the next provider call, including
  tag and alias pages, while retaining committed checkpoints for safe restart.

## [2026-08-12]

### Added

- **Reviewed or explicitly selected artists can seed bounded library expansion** — added offline
  target resolution, ambiguity handling, Pixiv count probing, Pixiv and Danbooru-family metadata
  enumeration, durable resume lineage, and explicit expansion-to-post provenance without inferring
  identity from handles, names, tags, aliases, or uploaders.
- **Expansion results feed the existing media and acquisition workflow** — added redacted
  list/show inspection, incomplete-detail reporting, target-scoped occurrence browsing, and stable
  variant selectors while keeping metadata enumeration separate from detail hydration and media
  download.
- **The repository now has an evolving project roadmap** — documented the overall goal, working
  pipeline, completed capabilities, current state, next artist-library milestone, future provider
  and operations work, and later supervised similarity research without duplicating Beads tasks or
  the detailed architecture plan.
- **The catalog can perform bounded cross-platform candidate lookups** — added explicit plan, run, resume, list, and show workflows for provenance-rich Danbooru and AIBooru source-URL, platform-ID, hash, artist-name, and alias searches without treating results as identity or authorship proof.
- **Candidate lookups are durable, finite, and review-oriented** — added immutable limits, sanitized request attempts, retained raw observations, checkpoints, typed provider outcomes, result associations, and evidence integration with the existing manual match-review ledger.

### Changed

- **Python quality tooling now has a blocking type-check gate** — added ty as a development
  dependency with Python 3.13 and vendored-code boundaries, resolved the first-party diagnostic
  baseline, expanded Ruff with explicit formatting, comprehension, and absolute-import policy, and
  documented the applicable test, lint, format, and type-check commands for agents.
- **Managed asset code now has a cohesive package layout** — moved content-addressed storage mechanics, local-file adoption, integrity verification, and read-only inspection into `media_catalog.storage` while keeping remote downloads under the separate acquisition boundary.
- **Remote page execution now has a reusable bounded loop** — metadata synchronization and candidate lookup share request, retention, normalization, commit, continuation, and budget semantics without coupling provider adapters to catalog persistence.

## [2026-08-11]

### Added

- **Selected remote media can be acquired into verified managed storage** — added explicit planning and execution, provider-aware request policy, resumable bounded transfers, exact hashing, inspection, quarantine, CAS publication, occurrence linking, and durable run and attempt history.
- **Catalog media occurrences can be browsed without direct SQL** — added bounded read-only list and detail queries with platform, author, post, availability, and asset-link filters plus stable occurrence and variant selections for download planning.

### Changed

- **Declared provider metadata remains distinct from locally verified facts** — acquisition preserves both claims and their provenance, and media browsing reports eligibility and linked assets without exposing remote URLs, credentials, raw payloads, or private paths.

## [2026-08-10]

### Added

- **Existing local media can be adopted into a content-addressed store** — added safe offline planning and execution, descriptor-relative path handling, SHA-256 and MD5 verification, raster inspection, versioned perceptual hashes, atomic publication, exact deduplication, reconciliation, and durable per-file outcomes.
- **Pixiv and Danbooru-family metadata adapters provide bounded synchronization** — added Pixiv profile, artwork, listing, multi-page, tag, and Ugoira normalization together with Danbooru and AIBooru post, artist, uploader, tag, relation, source, hash, and pagination metadata.
- **Remote metadata runs preserve auditability without downloading images** — added strict request, page, post, and time budgets; resumable checkpoints; raw response provenance; typed failures; redacted fixtures; and disabled-by-default live smoke tests.

### Changed

- **Legacy X media paths are occurrence-level provenance rather than managed storage** — imported paths remain non-owning source references until their bytes pass the catalog-owned adoption and verification workflow.

## [2026-08-09]

### Added

- **Offline cross-platform discovery turns retained links into reviewable evidence** — added extraction and canonicalization for profile and post URLs, typed platform references, unresolved-link retention, account and post candidates, deterministic evidence scores, and append-only review history.
- **Confirmed matches have explicit conservative semantics** — added reversible identity membership and post relations while keeping account identity, post equivalence, authorship, work grouping, and image variation as separate claims.

### Changed

- **Discovery responsibilities are split behind the stable service facade** — scanning, candidate generation, queries, review, identity rebuilding, and manual post matching live in focused collaborators without changing CLI or result contracts.

### Fixed

- **URL aliases no longer replace semantic platform-reference associations** — normalized links and references use many-to-many persistence, identifier kinds distinguish stable IDs from handles, slugs, hashes, and opaque values, and mutable X handles cannot materialize identities by themselves.

## [2026-08-05]

### Added

- **A platform-neutral media catalog now complements the X-specific tool** — added a migration-managed SQLite model for platforms, accounts and snapshots, posts, observations, media occurrences, assets, raw records, and import provenance together with initialization, integrity, statistics, and search commands.
- **Existing X likes and xarchive bookmarks can be imported idempotently** — added immutable-source importers that preserve likes and bookmarks as distinct observations, retain unknown provider data, reconcile overlapping exports, and report inserted, updated, existing, skipped, and failed counts.
- **The customized xarchive utility is maintained in-tree** — incorporated the locally extended bookmark parser as repository-owned code for stable bookmark JSON production and integration.

## [2026-08-04]

### Added

- **Each repository tool has a dedicated usage guide** — added the documentation index and a detailed `x-likes` guide covering setup, archive import, enrichment, optional media downloads, hashing, output, and operational caveats.

## [2026-08-03]

### Changed

- **X enrichment retains more accurate saved account and post information** — expanded provider normalization and database updates while preserving unavailable records and improving repeated enrichment behavior.

## [2026-08-02]

### Added

- **The first local-first tool imports and enriches X likes** — added archive parsing, SQLite persistence, provider enrichment, optional image downloading, MD5, SHA-256 and perceptual hashing, CLI commands, and focused tests under `x_likes`.
