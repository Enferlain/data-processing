## Context

See `proposal.md` for motivation. `media_catalog.records` is a widely imported public module, and
`CatalogWriter` is constructed throughout services and tests. Both now cover discovery, remote
metadata, core catalog data, storage, acquisition, candidate lookup, and library expansion. Their
database writes intentionally share the caller's `CatalogDatabase.connection` and transaction
boundaries.

The repository already organizes feature behavior into subpackages such as `acquisition`,
`candidate_lookup`, `discovery`, `library`, `remote_sync`, and `storage`. Persistence should follow
the same domain vocabulary without requiring every caller to change at once.

## Goals / Non-Goals

**Goals:**

- Give record definitions and SQL writes clear domain ownership.
- Preserve `from media_catalog.records import ...` and
  `from media_catalog.writer import CatalogWriter` compatibility.
- Preserve constructor and method signatures, return values, validation, SQL ordering, error text,
  row identity, idempotency, and transaction behavior.
- Keep shared validators and low-level SQL helpers small and explicit.
- Make each extraction independently reviewable and reversible.

**Non-Goals:**

- Changing the database schema or migrations.
- Redesigning service APIs or forcing callers onto domain-specific writer objects.
- Combining this refactor with Gelbooru or another provider implementation.
- Changing current projection, conflict-resolution, or provenance policies.
- Optimizing SQL without separate evidence and tests.

## Decisions

### Preserve compatibility facades

Convert `media_catalog.records` into a package whose `__init__.py` explicitly re-exports every
existing public record, vocabulary, and validator. Keep `media_catalog.writer.CatalogWriter` as the
public writer. This avoids a repository-wide migration and protects downstream imports.

Alternative considered: change all callers to domain-specific imports and writers immediately.
That produces unnecessary churn and makes behavioral regressions harder to isolate.

### Use domain modules rather than filename prefixes

Record modules will use the existing feature vocabulary: `common`, `discovery`, `catalog`,
`remote`, `metadata`, `storage`, `acquisition`, `lookup`, and `library`. Writer implementations will
live under `media_catalog.persistence` with corresponding domain names. This avoids adding another
flat set of `writer_*` or `records_*` files.

### Use composition behind CatalogWriter

Internal persistence components receive the existing `CatalogDatabase` and use its connection.
`CatalogWriter` delegates explicitly to them. Components do not own transactions and never call
`commit` or open replacement connections.

Alternative considered: multiple-inheritance mixins. Mixins would reduce delegation lines but hide
dependencies and method ownership, recreating a large implicit class across several files.

### Extract low-coupling domains first

Start with compatibility characterization, then move acquisition, candidate lookup, library
expansion, and adoption/storage persistence. Move remote metadata and core catalog projection last
because they share more provenance and conflict-resolution behavior.

### Separate movement from cleanup

Initial extraction copies behavior without rewriting SQL or validation. Deduplication and API
improvements are deferred until the reorganized boundaries are green. Mechanical moves and
behavioral changes must not share a review slice.

## Risks / Trade-offs

- **Import or re-export omission** → Snapshot the public `media_catalog.records` namespace and add
  focused import compatibility tests before moving definitions.
- **Transaction ownership drifts into components** → Pass the existing database object, forbid
  component commits, and test rollback across calls from different components.
- **Circular imports between record families** → Put only high-fan-in primitive validators and
  closed vocabularies in `records.common`; domain modules may depend on common but not one another
  unless the dependency represents a real type relationship.
- **Dataclass module paths change** → Preserve source import compatibility and explicitly check
  repository serialization usage. No repository pickle contract is currently known; if an external
  serialization requirement is discovered, retain compatibility aliases or defer that record move.
- **Large mechanical diff obscures regressions** → Extract one domain per slice, run focused and
  full gates, and request bounded review per completed section.
- **Facade delegation adds boilerplate** → Accept explicit delegation as the cost of a stable API
  and visible ownership; remove it only in a future breaking change.

## Migration Plan

1. Characterize the existing record export surface, writer signatures, and cross-domain rollback.
2. Create the `records` package and move one cohesive record family at a time, retaining explicit
   re-exports.
3. Create internal persistence components and delegate low-coupling writer domains one at a time.
4. Extract shared metadata and core catalog persistence after their regression suites are pinned.
5. Run full compatibility gates and remove only helpers proven unused after all moves.

Rollback is file-level: each domain extraction can be reverted independently because there is no
schema or stored-data migration.

## Compatibility Audit

Repository-wide source and test searches found no pickle, `__module__`, dataclass-field reflection,
or signature-reflection consumers before extraction. All 45 dataclasses now live in the family
modules under `media_catalog.records` and are re-exported from the package, so imports remain
compatible while their defining (reflection-visible) module path is the family module rather than
`media_catalog.records`. Shared validators are defined in `media_catalog.records.common` while
remaining importable from `media_catalog.records`; reflection on a validator's defining module will
therefore report the internal common module. The compatibility suite pins these decisions plus the
public name, constructor, and field surfaces after record-family extraction.
