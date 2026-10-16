## Context

Kernel Phase D (Bead `data-processing-t08`) is the leading schema milestone. The kernel spec
already fixes the epistemic vocabulary (`observed`/`verified`/`derived`/`inferred`/`reviewed`)
and the invariants (typed relationships, evidence ledger, append-only reversible review,
storage-enforced immutability tiers). The candidate machinery from migration 0002
(`post_match_candidates` with `relation_kind` ∈ sourced_from/same_work/repost_of/variant_of/
derived_from, generic `match_evidence`, append-only decisions) is the existing partial
expression. Deterministic seeds already exist in the data: SHA-256 content dedup
(`occurrence_assets` → one `assets` row per hash), provider-declared variant roles
(`media_occurrences.role` and `variants_json`), and provider-declared source URLs
(`post_external_references`, `reference_kind = 'source_url'`). gh#2 requires the semantic
boundaries settled before the first migration; gh#3 requires the lifecycle to be a durable
conclusion object, not a repackaged candidate.

## Goals / Non-Goals

**Goals:**

- Settle work-vs-representation semantics and the relationship taxonomy (gh#2 decision table
  below) and the evidence/review lifecycle (gh#3) before any migration.
- One migration with storage-level immutability tiers from day one.
- Deterministic, offline, idempotent seeding of the three already-provable kinds.
- A first variant-family projection riding the export framework.

**Non-Goals:**

- No fuzzy matcher, threshold, or similarity product surface (matching research is bead
  `data-processing-8nj`/`qi7`; matchers later arrive as `inferred` proposals through the
  existing candidates).
- No grouping objects for Pixiv series / Danbooru pools / e621 sets — membership primitives,
  not pairwise relationships (tracked on beads `cyp`/`vus`); the boundary is named below.
- No changes to existing tables, no data migration, no candidate-service rewiring (candidates
  confirm into relationships later via an explicit operator step, out of scope here).
- No per-kind derivation pipelines for `reencoded_from`/`cropped_from`/etc. — the vocabulary
  and storage accept them; measurement arrives with the research half.

## Decisions

### 1. Layering (gh#2 Q1): work / representation / blob, no extra revision layer

`work` = minimal deterministic anchor (one per post with occurrences). `media_occurrence` =
the kernel representation (already exists). `assets` = the kernel blob (already exists).
Edits, censorship, crops, re-encodes are **typed relationships between representations or
works**, not a third layer — a revision is not an object kind, it is a conclusion about two
objects. Works never merge: cross-platform human-level works are connected components over
reviewed `same_work` links, computed by projections; per-post anchor rows stay intact as
evidence. Multipage works are one work whose occurrences are page representations (page order
lives in `media_index`); a page posted separately is its own post/work linked `page_of`.

### 2. Semantic decision table (gh#2 deliverable)

| Variation (fixtures/providers) | One work? | Linked objects | Relationship | Symmetry | Default epistemic route |
| --- | --- | --- | --- | --- | --- |
| Exact mirror, identical SHA-256 | same | occurrence ↔ occurrence | `same_bytes` | symmetric | `verified` (local hash) |
| Lossy re-encode (same pixels, new bytes) | same | occurrence ↔ occurrence | `reencoded_from` | derivative → origin | `derived` (future measurement) or `observed` |
| Resize / provider sample | same | occurrence ↔ occurrence | `resized_from` | derivative → origin | `observed` (provider role) or `derived` |
| Thumbnail / preview | same | occurrence ↔ occurrence | `thumbnail_of` | derivative → origin | `observed` (provider role) — seeded now |
| Crop | same | occurrence ↔ occurrence | `cropped_from` | derivative → origin | `inferred` → review |
| Censored / uncensored | same work, distinct meaningful representations | occurrence ↔ occurrence | `censored_variant_of` | censored → uncensored | `inferred` → review |
| Text / no-text edit | same | occurrence ↔ occurrence | `edited_from` | derivative → origin | `inferred` → review |
| Multipage page order | one work already | — (index on representations) | `page_of` only for separately posted pages | page → parent | `observed` (provider) |
| Provider parent/child (danbooru `parent_id`) | separate works (one per post) | post ↔ post | `parent_of` | parent → child | `observed` (provider) |
| Repost with declared source URL | same human-level work | post ↔ post | `reposted_from` | repost → origin | `observed` (source URL) — seeded now |
| Cross-platform upload of one work | same human-level work | work ↔ work | `same_work` | symmetric | `inferred` (matcher) → `reviewed` |
| Pixiv series / Danbooru pool / e621 set | **not a relationship** | — | future membership primitive | — | `observed` |

Formats/dimensions/codecs are attributes (declared occurrence MIME vs verified detected MIME),
usable as relationship evidence, never the relationship itself.

### 3. Storage shape (gh#3 deliverable, part 1)

- `works (work_id, origin_post_id → posts, work_kind ∈ single|multi_page|unknown, created_at)`
  UNIQUE(origin_post_id). Immutable after insert.
- `work_representations (work_id, media_occurrence_id, added_at)` — insert-only.
- `relationships (relationship_id, relationship_key UNIQUE sha256, subject_kind ∈
  work|media_occurrence|post|asset, subject_id, relation_kind (closed CHECK list),
  target_kind, target_id, epistemic_status, review_state ∈ unreviewed|confirmed|rejected,
  created_at, updated_at)`. Identity fields (key, endpoints, kind) immutable after insert;
  only epistemic_status / review_state / updated_at may update; never deletable.
- `relationship_evidence (relationship_id, evidence_id → match_evidence, added_at)` — reuses
  the existing generic evidence ledger; insert-only, undeletable.
- `relationship_review_decisions (…, prior_state, decision, note, decided_at)` — fully
  immutable, mirroring the candidate decision ledgers.
- `relationship_status_history (…, prior_status, new_status, cause, at)` — fully immutable.

Polymorphic endpoint FKs are validated in code (same stance as `observations.subject_kind`);
kind-specific endpoint kinds (e.g. `same_bytes` is occurrence↔occurrence) are validated by the
records layer, not by SQL CHECKs, so the vocabulary can grow by value, not by migration.

### 4. Lifecycle (gh#3 deliverable, part 2)

```text
                evidence (match_evidence, immutable, stance ± )
                   │ supports
                   v
 seeder/matcher/operator ──> relationships row (conclusion object)
   observed/verified         epistemic_status ── append-only transitions ──> reviewed
   (deterministic bypass)         │
                                  v
                      relationship_review_decisions (append-only, reversible)
                                  │ latest decision
                                  v
                      review_state: unreviewed / confirmed / rejected
```

- Conclusion rows, not evolving candidates: a relationship row IS the durable conclusion;
  uncertain hypotheses remain candidates (existing machinery) until an operator materializes
  them (`inferred` → review) — nothing auto-materializes from a score.
- Deterministic bypass: seeded kinds land as `observed`/`verified` with evidence and no
  review required; humans may still review them (status → `reviewed` via history).
- Detector/version live on evidence rows only (`match_evidence.detector`/`detector_version`);
  relationship rows stay algorithm-agnostic — the "who proved it" chain reads through the
  evidence join.
- Multi-evidence bundles: any number of evidence rows per relationship, stances may disagree.
- Review reversal appends a decision (prior_state recorded); the row's review_state follows
  the latest decision; rejected rows are retained, never deleted.
- Canonical orientation: symmetric kinds store endpoints sorted by (kind, id) — the
  relationship_key hashes that canonical order; directional kinds fix derivative/child/page/
  thumbnail as subject, origin/parent/original as target.

### 5. Seeding and idempotency

`relationship_key = sha256(canonical kind + subject/target identity)` makes seeding
idempotent (INSERT OR IGNORE + evidence attach-if-absent). Evidence digest (existing
`match_evidence.evidence_digest` UNIQUE) dedups evidence rows across re-runs. Seeders emit
typed counts (materialized, existing, skipped with reason: unresolved source URL, missing
original, same-post self-link excluded).

### 6. Works projection

One export kind `works` over the framework: rows per work with representations (role,
verified sha256 when linked), preferred_representation under the stated policy (exclude
sample/preview/thumbnail roles; prefer role `original`, tie-break largest detected area,
then occurrence id), same_work link summary. Policies appear in the manifest
(`grouping: per_work`, `exclusion: thumbnail_roles_from_preference`, `preferred_representation:
upstream_original_role_first`).

## Risks / Trade-offs

- [Polymorphic endpoints cannot carry SQL FKs] → code validation + tests; the pattern is
  already established by `observations`.
- [One-work-per-post anchors feel redundant until same_work links exist] → deliberate:
  anchors are deterministic and non-destructive; grouping happens in projections, where it
  can be recomputed as reviewed evidence grows.
- [Seeded `thumbnail_of` trusts provider-declared roles] → the role is provider-declared
  evidence (`observed`), never a verified pixel fact; status vocabulary makes the trust level
  explicit.
- [Vocabulary growth by CHECK list needs migrations] → adding a kind is a one-line CHECK
  rebuild in a future migration; the closed list is the point (no free-text relationships).

## Migration Plan

Single additive migration; no existing table is touched. Rollback = drop the new tables
(they reference old ones, nothing references them).

## Open Questions

None blocking. The candidate-confirmation → relationship materialization operator step
(after this change) will reuse the review CLI shape introduced here.
