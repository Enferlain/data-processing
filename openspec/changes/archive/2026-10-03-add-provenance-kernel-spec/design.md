## Context

The kernel already exists in the schema: migrations 0001-0011 implement every concept the new
spec formalizes, and `docs/plans/provenance-kernel.md` section 2 holds the verified
concept-to-table mapping. What is missing is a normative spec and a named boundary. This change
adds the spec and performs the two cheap code re-homings already queued as Beads
`data-processing-v4i` and `data-processing-ee0`; it changes no schema, data, CLI, or adapter
behavior. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**

- Make the domain-neutral invariants binding and reviewable as a standalone capability spec.
- Resolve kernel vocabulary (observation versus provenance event; epistemic statuses) in one
  authoritative place.
- Give kernel concepts a named home in code via the two queued boundary moves, and nothing more.

**Non-Goals:**

- No table renames, migrations, or data changes of any kind.
- No generic relationship/assertion tables — those land with the future work/version model, which
  is the first real consumer.
- No package or CLI renames (`media_catalog`, `catalog`, `x-likes` stay until a second data
  family lands).
- No unified run-table or run-protocol implementation; the spec states the contract the six
  existing families already satisfy.

## Decisions

### Standalone `provenance-kernel` spec rather than sections of `media-catalog-core`

The kernel is domain-neutral and must outlive media's primacy as the first data family; placing
its requirements inside a media capability would force every future family to reference a media
spec for cross-cutting invariants. The flat `specs/` layout takes a new sibling capability.
Alternative rejected: extending `media-catalog-core` (bakes media into the kernel's home;
capability deltas for future families would keep touching a media-named spec).

### Codify existing behavior, with named forward-looking elements

The requirements codify invariants the catalog already implements — some fully storage-enforced
(audit triggers; immutable run inputs for the lookup and acquisition families), some at concept
level where enforcement still rests on writer convention (append-only source reports, provenance
events, the review and evidence ledger) or on a partial vocabulary (today's candidate-proposal
and review states are the initial expression of the epistemic-status vocabulary; the full
five-status vocabulary is the target for relationship-bearing records, adopted when the
relationship model is built). Two clauses are explicitly forward-looking — "New capabilities
preserve kernel invariants" and storage enforcement for audit tables introduced after this
specification — and are enforced as review gates rather than automated tests. Alternative
rejected: also specifying new generic kernel tables now — no second consumer exists yet, which
the roadmap's own extraction guardrail forbids.

### Vocabulary resolves the `observations` collision documentarily

The unqualified kernel word "observation" means the source report (`raw_observations` +
`raw_payloads`); the `observations` table is named "provenance event" in kernel terms, with
`observation_revisions` as its revision log. Renaming tables was rejected outright (migration
churn, zero behavioral gain); the kernel plan's mapping table is the authoritative dictionary
between kernel terms and current table names.

### Epistemic statuses unify conceptually, not column-by-column

The closed vocabulary (`observed`, `verified`, `derived`, `inferred`, `reviewed`) is specified at
concept level. Today's partial enums — `post_participants.review_state`,
`asset_fingerprints.verification_status`, candidate `current_state` plus decisions — already
express pieces of it; unifying columns would be schema churn. Column-level adoption happens when
the relationship model is built (the first table designed under this spec).

### The two code re-homings are the whole implementation surface

`data-processing-v4i` moves the `adoption_items` read from the CatalogWriter facade into
StorageWrites, completing the persistence-component split from the modularization milestone.
`data-processing-ee0` colocates single-family vocabularies and validators with their record
family modules, so each family module is the named home of its vocabulary. Together they finish
naming the persistence and records boundaries; deliberately no further restructuring is attempted
in this change.

## Risks / Trade-offs

- [Spec/implementation drift: a future table violates a kernel invariant] → The kernel spec
  becomes the review checklist; new OpenSpec changes must reconcile against it, and archive-time
  validation keeps the main spec current.
- [Codification fossilizes incidental choices] → Requirements are written at concept altitude,
  never naming tables or columns; the mutable concept-to-table dictionary lives in the kernel
  plan, not the spec.
- [Overlap with capability specs (for example append-only provenance also in
  `media-catalog-core`)] → Accepted: capability specs keep domain-flavored requirements; the
  kernel spec is authoritative for the cross-cutting invariant.
- [The two refactors touch the writer facade and records facade used across callers] → Full
  quality gates (pytest, ruff, ty) plus focused tests on the moved read and re-exported
  vocabularies; both moves preserve public behavior.

## Migration Plan

None. No schema or data changes; the code moves are internal with tests. Rollback is reverting
the two refactors; the spec is documentation-grade and independently revertable.

## Open Questions

- Whether local imports need a source-kind generalization of the platform registry, or a view
  suffices — deferrable; affects no requirement in this change.
- The shape of a shared run contract implementation (protocol versus shared persistence
  component) — deferrable until a seventh run family or a non-media family forces the choice.
