# Provenance kernel plan

Status: accepted direction, implementation pending
Last updated: 2026-10-03

Related: the [media catalog plan](cross-platform-media-catalog.md) is the media-family domain plan
under this framing; the [roadmap](../../ROADMAP.md) tracks milestone state; the discussion that
produced this direction is preserved in [raw_future_plan.md](raw_future_plan.md).

## 1. North star

Build a local-first system for gathering, retaining, cross-referencing, verifying, and organizing
data from heterogeneous sources while preserving provenance and uncertainty.

Media is the first data family, not the definition of the system. The important durable object is
not "an image in my collection" but the observation behind it:

> A piece of information or content was observed somewhere, at some time, through some source, with
> some metadata. Preserve that observation, connect it to other observations where justified, and
> never lose where any fact came from.

The durable database is the evidence layer. Consumer schemas — media-library views, training
datasets, research tables, exports — are projections over that layer with stated policies. Fifteen
sources may disagree; the system retains what each asserted, what local verification found, and
what the current projection currently chooses, without destroying anything to produce a usable
present view. Interpretation can improve later.

## 2. The kernel already exists latently

This is a naming, specification, and boundary change, not a reimplementation. The mapping below was
verified against migrations 0001-0011 on 2026-10-03.

| Kernel concept | Current home | Status | Action |
| --- | --- | --- | --- |
| Source | `platforms`; the source dimension of `import_runs` and `remote_runs` | Partial | Treat "source" as the kernel term; `platforms` stays the remote-provider specialization |
| Source object | `(platform, native_id)` keys on `accounts`, `posts`, `tags`, `attribution_entities` | Strong as a pattern | Keep per-kind tables; name the pattern in the kernel spec |
| Observation (source report) | `raw_observations`, `raw_payloads` | Strong | Recognize as the kernel observation; append-only, payload-deduplicated, anchored to an import run or a remote request, or — for lookups and probes — to the requesting row itself; never revised in place |
| Provenance event | `observations` plus `observation_revisions` (`liked`, `bookmarked`, `foldered`, `imported`, `discovered`, `crawled`) | Strong | Recognize as assertions whose source is local user activity; revisions attach here, not to source reports; `subject_kind` is post-only today |
| Blob | `assets` (verified SHA-256 CAS) plus `asset_fingerprints` | Strong | `assets` is the kernel blob; image facts layered on it are domain |
| Representation | `media_occurrences`, named variants, `occurrence_assets` | Strong, media-named | Domain naming stays; the pattern is named in the kernel spec |
| Assertion | declared-vs-verified columns; `media_acquisition_verifications` (claim kind, declared value, verified value, comparison result); the Gelbooru current-projection policy | Established in places | No universal assertion table; the declared/verified/comparison pattern is the template for contested fields |
| Relationship | `post_relations`; account/post match candidates with `relation_kind` and pending/confirmed/rejected state; `post_candidate_characteristics` (resized, reencoded, meaningful_edit, progression); `occurrence_assets` | Partial, scattered | One typed relationship model with epistemic status, designed with the work/version model |
| Evidence | `match_evidence` (stance supports/contradicts/neutral, direction, strength, detector and version) plus the two candidate join tables | Strong, candidate-scoped | Extend attachment scope as relationships generalize |
| Acquisition | `media_acquisition_plans` + immutable plan items, `adoption_runs`, `media_acquisition_runs` with attempts, partials, verifications, quarantine | Strong, media-named | Name the staging/quarantine/CAS-publication pattern in the kernel spec |
| Run | `import_runs`, `discovery_runs`, `adoption_runs`, `remote_runs` + `remote_checkpoints`/`remote_requests`, `candidate_lookup_runs` + checkpoints/requests, `media_acquisition_runs` | Strong, six similar families | Unify the contract (spec and boundary), not the tables; library expansion adds a plan-plus-lineage pattern over the shared `remote_runs` table instead of a seventh family |
| Review | `account_candidate_decisions`, `post_candidate_decisions` | Strong | Recognize as the kernel review-ledger pattern; append-only with prior state |
| Artifact / work | not built | Greenfield | Design in kernel terms when the work/version model lands |
| Projection | Gelbooru current-projection policy; search and stats; planned exports | Nascent | Name the concept and its policy; exports become projections |

Verification also confirmed three cross-cutting disciplines the kernel spec should name:

- Audit immutability is largely enforced at the storage layer: plans, probes, execution lineage,
  tag, tag-alias, and post metadata observations, terminal candidate-lookup requests, and
  terminal acquisition attempts are immutable or append-only via triggers. Where append-only
  still rests on writer convention — source reports (`raw_observations`), `remote_requests`,
  `adoption_attempts`, `post_tag_observations`, and the review/evidence ledger — bringing them
  under storage enforcement is tracked follow-up work.
- A shared typed-outcome vocabulary (`success`, `unavailable`, `deleted`,
  `authentication_required`, `authorization_denied`, `rate_limited`, `transient_provider`,
  `malformed_response`, `budget_exhausted`, `local_persistence`) fully covers remote and lookup
  runs and requests; probes omit `budget_exhausted` and add `unsupported`; acquisition runs and
  items use a family-specific subset plus extensions.
- The remote and candidate-lookup run families carry explicit request/page/record/time budgets, a
  budget-boundary marker, retry-after guidance, and resumable checkpoints with continuation
  versions. Acquisition runs instead declare item/byte/time budgets and resume through staged
  partials plus run lineage. Input immutability is trigger-enforced for lookup and acquisition
  runs; `remote_runs` enforces it only for its origin columns today.

Partial epistemic vocabulary is already in the schema: `post_participants.review_state` defaults
to `observed`; `asset_fingerprints.verification_status` spans
`legacy`/`calculated`/`verified`/`mismatch`/`unavailable`; `platform_references.identifier_kind`
separates stable ids from handles, slugs, hashes, and opaque identifiers.

## 3. Kernel vocabulary

- **Source** — where an observation came from: a remote provider or instance, a local import, a
  file, an API response, a webpage. Remote providers are already stored as `platforms`; local
  imports are distinguished by run kind.
- **Source object** — a stable provider-native identity, `(platform, object kind, native id)`. Each
  object kind keeps its own typed table; the kernel defines the pattern, not a shared table.
- **Observation (source report)** — what a source reported about an object at a time, with the
  raw payload retained append-only and deduplicated by content; stored as `raw_observations`. A
  source report is never revised in place — a later report is a new observation.
- **Provenance event** — why the catalog holds a record (`liked`, `bookmarked`, `foldered`,
  `imported`, `discovered`, `crawled`); stored as `observations`, with re-observations retained
  in `observation_revisions`. In kernel terms a provenance event is an assertion whose source is
  local user activity. This resolves the schema's `observations` versus `raw_observations`
  collision: the unqualified kernel word "observation" always means the source report.
- **Blob** — exact bytes: verified SHA-256, size, MIME. Content-addressed, immutable, deduplicated.
- **Representation** — one observed representation of an artifact at a source: remote URL, variant
  role, dimensions, availability. May exist before any bytes are acquired.
- **Artifact** — a conceptual content object (a work, a webpage, a dataset record) that several
  representations and blobs can manifest. Not yet built.
- **Assertion** — "source S says property P had value V at time T." Most assertions live as typed
  columns written by a run with a source-observation pointer; only genuinely contested fields need
  explicit assertion-level modeling.
- **Relationship** — a typed, provenance-bearing link between two objects: `same_bytes`,
  `reencoded_from`, `censored_variant_of`, `reposted_from`, `probably_same_work`,
  `confirmed_same_work`, and so on. Relationships carry epistemic status and evidence.
- **Evidence** — why a relationship or assertion is believed: kind, direction, strength, source,
  algorithm and version, review state.
- **Acquisition** — how bytes entered local storage: explicit plan, bounded execution, staged
  verification, quarantine on mismatch, atomic CAS publication.
- **Run** — one bounded import/fetch/crawl/lookup/analysis operation with limits, adapter version,
  counts, raw retention, and resumable checkpoints.
- **Review** — an append-only, reversible human decision over a candidate or proposed conclusion.
- **Projection** — a derived current view over retained observations with a stated policy (for
  example: newer observation wins a mutable field, omissions never erase).

### Epistemic status

Every relationship and assertion carries one of:

- `observed` — a source explicitly reports it;
- `verified` — a local deterministic check proves it (for example, matching SHA-256);
- `derived` — a deterministic algorithm establishes it;
- `inferred` — a matcher proposes it as plausible;
- `reviewed` — a human accepted or rejected it.

The current schema already distinguishes provider-declared from locally verified hashes and
candidate from confirmed decisions; this vocabulary makes the distinction uniform.

## 4. Layering

```text
projections        exports, views, training datasets, research tables
                     (stated policy, rebuildable)
domain families    media: occurrences, variants, image facts, acquisition policies
                     social: accounts, posts, participants, tags, attribution
kernel             source/object identity, observation retention, runs and
                     checkpoints, evidence and review, blobs, typed
                     relationships with epistemic status, projections
```

Domain families keep typed schemas layered over the kernel. The kernel never demands a generic
entity/attribute/value table for everything; that path ends in soup.

## 5. What stays domain-specific

- Provider adapters and their interaction policies (request shapes, pacing, hosts, credentials).
- Accounts, identities, posts, participants, tags, and attribution — social-source vocabulary, per
  the catalog plan, which remains authoritative for the media family.
- Image inspection, perceptual hashes, dimensions, variant roles, and quality signals.
- Anything with exactly one consumer: extract when a second family or a concrete workflow needs it.

## 6. Evolution path

- **Phase A — direction documents (done 2026-10-03):** this plan, the roadmap adjustment, and the
  catalog-plan annotation. No code or schema change.
- **Phase B — architectural pass (done 2026-10-03; archived change
  `2026-10-03-add-provenance-kernel-spec`, Bead `data-processing-u1d`):** mapping verified per
  table; kernel capability spec added and synced into the main specs; boundaries re-homed,
  absorbing the two persistence follow-ups. Storage-enforcement gaps filed as Bead
  `data-processing-ts5`.
- **Phase C — reviewed-target workflow milestone (current; started 2026-10-03, change
  `generalize-reviewed-target-workflow`):** the pipeline-gap workflow (carry a reviewed target
  through metadata sync, browsing, and acquisition without manual identifier translation) built
  against the named kernel.
- **Phase D — work/version and relationship model plus matching research:** greenfield, designed in
  kernel terms; new data families join when concrete workflows justify them.

## 7. Guardrails

- No data migration. Existing tables keep their names; today's schema is the media family's
  projection of the kernel, and new kernel concepts land as new migrations.
- No universal assertion or relationship-everywhere table. Field-level assertions and typed
  relationships are added only where sources disagree or a model needs them.
- Extract a kernel abstraction only when it has a second consumer or an imminent concrete workflow.
  The run/checkpoint families and evidence ledgers qualify now; adapters do not.
- Package and CLI names (`media_catalog`, `catalog`, `x-likes`) are unchanged until a second data
  family lands.
- New data families follow the same rule as new providers: a concrete workflow and a documented,
  bounded interaction policy.
- The roadmap's ongoing principles apply unchanged; they were already kernel-compatible.

## 8. Open questions for the architectural pass

Answered on 2026-10-03:

- The section 2 mapping is verified against migrations 0001-0011, including the correction that
  `observation_revisions` revises provenance events, not source reports.
- Kernel vocabulary resolves the `observations` versus `raw_observations` collision: the kernel
  word "observation" means the source report (`raw_observations`); the `observations` table is
  named "provenance event" in kernel terms.
- The kernel spec boundary is a standalone `provenance-kernel` capability spec in OpenSpec. The
  kernel is domain-neutral and cross-cutting; `media-catalog-core` remains the media capability
  and references the kernel rather than containing it.

Still open:

- Whether local imports need a source-kind generalization of `platforms`, or a view suffices.
- The shape of the unified run contract: a protocol, a shared persistence component, or both.
