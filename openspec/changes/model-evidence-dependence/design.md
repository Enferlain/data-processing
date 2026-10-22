## Context

Phase D landed the typed relationship model: a closed 15-kind vocabulary with symmetric/
directional orientation, epistemic status from the kernel vocabulary, review state, and
evidence through the shared ledger. Cross-source reposts and byte-identical content are
already expressed there (`reposted_from` from declared source URLs, `same_bytes` from
verified content deduplication). What is missing is the step from those edges to the
question gh#9 asks: when several sources repeat one claim, how many *independent*
corroborations exist?

## Goals / Non-Goals

Goals:

- Decide, and record, whether dependence needs new storage (a lineage/group/correlation
  reference) or derives from the relationship graph.
- Name the dependence semantics of every relationship kind.
- Provide the derivation primitive future corroboration surfaces call — not the confidence
  surfaces themselves.

Non-Goals:

- No confidence scoring, agreement weighting, or provider reliability — those surfaces do
  not exist yet; this change only guarantees they cannot silently over-count.
- No storage change: no migration, no new columns, no lineage stamps.
- No CLI/export surface: `lineage_components` is a library primitive consumed by tests and
  future projections.
- No as-of reconstruction over relationships yet (tracked on 2ai follow-ons); derivation
  reads current relationship state.

## Decisions

### D1: Dependence derives from the relationship graph; rows carry no lineage stamps

Dependence between two sources is itself a claim about the world — it may be observed (a
provider declares its source), verified (byte equality), derived, inferred (a matcher
proposes a repost), or reviewed. That is exactly what a relationship row already is: typed,
epistemic, evidence-backed, review-gated, append-only. A lineage/group identifier on
evidence or observation rows would instead be:

- **Immutable-but-derived**: group membership changes as descent edges arrive; an
  immutable row cannot be updated, so stamps would go stale or need a second mutable table.
- **A parallel mechanism**: the kernel requires new capabilities to reuse the relationship
  and evidence ledgers rather than build beside them.
- **Uncertainty-free**: a group id cannot say *how well established* the dependence is; an
  edge with epistemic status can.

Consequences: evidence rows stay single-finding facts (stance, detector, explanation, and
detector payload — the sha256 inside a `same_bytes` evidence row is detector output, not a
lineage identity); lineage is recomputed at read time under a stated policy and is always
consistent with the current retained graph.

### D2: The vocabulary classifies into descent, equivalence, and structural

- **Descent (directional, derivative on the subject side):** `reposted_from`,
  `derived_from`, `variant_of`, `reencoded_from`, `resized_from`, `cropped_from`,
  `censored_variant_of`, `edited_from`, `transcoded_from`, `extracted_from`,
  `thumbnail_of`. The subject's version of the content — and transitively its claims about
  the content — likely descends from the target's.
- **Equivalence (symmetric, common origin without direction):** `same_bytes`, `same_work`.
  They prove dependence without claiming who copied whom; that asymmetry can be established
  later by a descent edge or chronology without changing the grouping.
- **Structural (anchor, not claim-descent):** `page_of`, `parent_of`. A page belongs to its
  work and a reply to its parent thread without the parent's metadata claims being the
  source of the child's — a quote is new authorship, not a copy of the parent's claims.
  These never merge lineages.

Structural **anchoring** (distinct from structural relationship kinds) is intrinsic and
always applies: a post, its media occurrences, and its work anchor are one node for lineage
purposes (`media_occurrences.post_id`, `works.origin_post_id`, `work_representations`).

### D3: The default dependence policy is conclusion-grade and non-rejected

`lineage_components` counts an edge as dependence when its kind is in the default set
(descent ∪ equivalence), its epistemic status is conclusion-grade (`observed`, `verified`,
`derived`, `reviewed`), and its review state is not `rejected`. Rationale:

- Deterministic seeds land as `verified`/`observed` with review state `pending` (they
  bypass *required* review, they are not auto-confirmed) — filtering on review state
  `confirmed` would wrongly exclude every seeded edge.
- An `inferred` edge is a pending proposal; merging lineages on it would let a proposal
  drive a conclusion. Confirming it promotes the status to `reviewed` and merges.
- A `rejected` edge has been overturned by review; the sides stand independent again while
  the edge and its evidence remain retained.

The policy parameters (kind set, status set, rejected handling) are arguments; a surface
that wants stricter or looser dependence states its own — that is the opt-in independence
rule made mechanical.

### D4: Corroboration counting is a projection concern; the kernel supplies grouping only

`lineage_components` returns groups, never confidence. A future corroboration surface
states its dependence policy in its projection spec (a new policy slot would participate in
the spec digest like every other stated policy) and counts distinct lineages intersecting
its claim anchors. "N sources agree" is never assembled implicitly.

### D5: No global provider-reliability scores

Rejected alternative: a provider-confidence column that discounts mirrors globally.
Dependence is claim- and field-specific (a site may mirror uploads but originate tags), so
global scores would encode a wrong generalization and age badly. The graph records per-edge
dependence with evidence; any reliability heuristic would be a projection over that graph,
never a stored ranking.

### D6: Connected components in Python over SQL

The component computation is a union-find over three node kinds (post, media_occurrence,
work) with anchoring joins plus filtered relationship edges, done in Python. A recursive
CTE over polymorphic (kind, id) endpoints is expressible but gnarly, and catalog scale
(thousands of posts, tens of thousands of edges) makes in-memory traversal trivially cheap.
Determinism: components ordered by their smallest member label, members sorted, edges
sorted.

## Risks / Trade-offs

- [Dependence edges can be wrong; grouping inherits the error] → The policy is per-call and
  review can reject an edge, which un-merges the lineage on the next derivation; nothing
  stamped persists a wrong grouping.
- [Default policy choices (exclude `inferred`, exclude `rejected`) could surprise a surface
  wanting maximal merging] → Both are explicit arguments with the default stated here and
  in the doc; a surface must state what it counts.
- [Lineage answers change as edges arrive] → Inherent to read-time derivation; as-of
  reconstruction over relationships (2ai follow-on) will pin groupings under a cutoff once
  relationship conclusions gain as-of semantics.
- [`thumbnail_of` merges claim lineages within a post only] → It seeds between occurrences
  of the same post today; even cross-post it is honest dependence for content claims. No
  mitigation needed, recorded as a semantics note.

## Migration Plan

None: no storage change. Rollback is deleting the new module and tests.

## Open Questions

- Whether a corroboration surface should also traverse *asset*-endpoint relationships
  (`same_bytes` between assets) — today the vocabulary links occurrences; revisit if an
  asset-level kind lands.
- The policy-slot wording future corroboration projections will use; decided when the first
  such projection exists.
