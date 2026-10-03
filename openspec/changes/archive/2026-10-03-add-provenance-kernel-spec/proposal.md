## Why

The provenance-kernel direction adopted on 2026-10-03 (see `docs/plans/provenance-kernel.md`,
mapping verified against migrations 0001-0011) broadened the project from a cross-platform media
catalog to a source-aware gathering and provenance system with media as the first data family. The
domain-neutral core that the schema already implements — source identity, append-only source
reports, provenance events, content-addressed blobs, the shared bounded-run contract, evidence and
review ledgers, trigger-enforced audit immutability — has no spec. Without one, every future
milestone risks re-inventing or silently eroding those invariants, and the latent kernel stays
unnamed in code, docs, and specs.

## What Changes

- Adds a standalone `provenance-kernel` capability spec that formalizes the domain-neutral core as
  requirements: source and source-object identity, source-report observation retention, provenance
  events, blobs and representations, the declared/verified/comparison assertion pattern, typed
  relationships with uniform epistemic status (`observed`, `verified`, `derived`, `inferred`,
  `reviewed`), evidence and review ledgers, the run/checkpoint contract shared by the six run
  families, storage-enforced audit immutability, and projections with stated policies.
- Adopts the kernel vocabulary as authoritative naming for cross-cutting concepts, resolving the
  `observations` (provenance events) versus `raw_observations` (source reports) collision: the
  unqualified kernel word "observation" means the source report.
- Re-homes cheap module boundaries so kernel concepts have a named home in code, absorbing the two
  ready persistence follow-ups (Beads `data-processing-v4i` and `data-processing-ee0`). Internal
  structure only — no CLI, API, schema, or adapter behavior changes.
- Explicitly out of scope: table renames, data migration, new tables, adapter changes, and any
  generic entity/attribute/value storage.

## Capabilities

### New Capabilities

- `provenance-kernel`: the domain-neutral provenance core — identity, observation retention,
  provenance events, blobs, representations, assertion comparison, typed relationships with
  epistemic status, evidence and review ledgers, the bounded run contract, audit immutability, and
  projections. Requirements codify what the catalog already implements so future capabilities
  build on, and cannot silently erode, these invariants.

### Modified Capabilities

- None. `media-catalog-core` and the adapter capability specs keep their requirements unchanged;
  the kernel spec is additive and sits underneath them at a domain-neutral altitude.

## Impact

- New main spec after sync: `openspec/specs/provenance-kernel/spec.md`.
- Code (structure only): `media_catalog.persistence` gains the `adoption_items` read in
  StorageWrites (from the CatalogWriter facade); single-family vocabularies and validators colocate
  with their record family modules in `media_catalog.records`.
- Documentation: `docs/plans/provenance-kernel.md` already reflects the verified mapping and the
  decisions this change implements; `ROADMAP.md` names this pass as the active milestone.
- Issue tracking: Beads `data-processing-v4i` and `data-processing-ee0` are absorbed;
  `data-processing-u1d` tracks the overall pass.
