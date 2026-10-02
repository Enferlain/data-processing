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

This is a naming, specification, and boundary change, not a reimplementation. The mapping below is
concept-level as of 2026-10-03, drawn from the schema inventory and plan documents; the
architectural pass verifies it per table against the migrations.

| Kernel concept | Current home | Status | Action |
| --- | --- | --- | --- |
| Source | `platforms`; the source dimension of `import_runs` and `remote_runs` | Partial | Treat "source" as the kernel term; `platforms` stays the remote-provider specialization |
| Source object | `(platform, native_id)` keys on `accounts`, `posts`, `tags`, `attribution_entities` | Strong as a pattern | Keep per-kind tables; name the pattern in the kernel spec |
| Observation (source report) | `raw_observations`, `raw_payloads`, `observation_revisions` | Strong | Recognize as the kernel observation; no change |
| Observation (provenance event) | `observations` (`liked`, `bookmarked`, `imported`, `discovered`) | Strong | Recognize as assertions whose source is local user activity |
| Blob | `assets` (verified SHA-256 CAS) plus `asset_fingerprints` | Strong | `assets` is the kernel blob; image facts layered on it are domain |
| Representation | `media_occurrences`, named variants, `occurrence_assets` | Strong, media-named | Domain naming stays; the pattern is named in the kernel spec |
| Assertion | declared-vs-verified hash fields; adapter-run source pointers; the Gelbooru current-projection policy | Emergent | No universal assertion table; model field-level assertions only where sources disagree and it matters |
| Relationship | `post_relations`; account/post match candidates; `occurrence_assets` | Partial, scattered | One typed relationship model with epistemic status, designed with the work/version model |
| Evidence | `account_candidate_evidence`, `post_candidate_evidence`, `match_evidence` | Strong, candidate-scoped | Extend attachment scope as relationships generalize |
| Acquisition | `media_acquisition_plans`, `adoption_runs`, download `remote_runs` | Strong, media-named | Name the staging/quarantine/CAS-publication pattern in the kernel spec |
| Run | `import_runs`, `discovery_runs`, `remote_runs` + `remote_checkpoints`, `candidate_lookup_runs` + checkpoints, `adoption_runs` | Strong, five similar families | Unify the contract (spec and boundary); not necessarily the tables |
| Review | `account_candidate_decisions`, `post_candidate_decisions` | Strong | Recognize as the kernel review-ledger pattern |
| Artifact / work | not built | Greenfield | Design in kernel terms when the work/version model lands |
| Projection | Gelbooru current-projection policy; search and stats; planned exports | Nascent | Name the concept and its policy; exports become projections |

## 3. Kernel vocabulary

- **Source** — where an observation came from: a remote provider or instance, a local import, a
  file, an API response, a webpage. Remote providers are already stored as `platforms`; local
  imports are distinguished by run kind.
- **Source object** — a stable provider-native identity, `(platform, object kind, native id)`. Each
  object kind keeps its own typed table; the kernel defines the pattern, not a shared table.
- **Observation** — what a source reported about an object at a time, with the raw payload
  retained append-only and revisable through revisions. Observations never overwrite each other.
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
- **Phase B — architectural pass (next milestone, Bead `data-processing-u1d`):** verify the mapping
  per table; add an OpenSpec kernel capability spec; re-home or name boundaries where cheap,
  absorbing the two ready persistence follow-ups.
- **Phase C — reviewed-target workflow milestone:** the pipeline-gap workflow (carry a reviewed
  target through metadata sync, browsing, and acquisition without manual identifier translation)
  built against the named kernel.
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

- Per-table verification of the section 2 mapping against the actual migrations.
- Naming reconciliation for `observations` (provenance events) versus `raw_observations` (source
  reports) in kernel vocabulary.
- Whether local imports need a source-kind generalization of `platforms`, or a view suffices.
- The shape of the unified run contract: a protocol, a shared persistence component, or both.
- Where the kernel spec boundary lives in OpenSpec: a standalone capability spec or sections of
  `media-catalog-core`.
