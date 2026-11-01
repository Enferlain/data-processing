# Data Processing — Development Roadmap

**Project:** [Enferlain/data-processing](https://github.com/Enferlain/data-processing)  
**Baseline:** `main` — `8a0915c` (2026-11-01)  
**Status:** Proposed development priorities  
**Scope:** Core capabilities, integration, reliability, and future expansion

---

## 1. Project Goal

Build a **local-first, source-aware data discovery, reconciliation, and processing system** capable of gathering, identifying, cross-referencing, verifying, organizing, and acquiring data from heterogeneous sources while preserving provenance, uncertainty, and historical information.

The system should accept different types of input, discover where the underlying content or information exists, identify exact matches and related variants using multiple methods, reconcile the results, and retain the complete evidence and relationship history.

Media is the initial domain, but the architecture should remain applicable to other data families where concrete workflows justify expansion.

### Target Workflow

```text
INPUT
  Local file / directory
  URL / source identifier
  Hash / fingerprint
  Metadata / known references
  Existing catalog record
          |
          v
INPUT ANALYSIS
  Extract identifiers
  Calculate fingerprints
  Inspect metadata
  Resolve existing records
          |
          v
MULTI-SOURCE DISCOVERY
  Existing local catalog
  Local files and managed storage
  Imported / maintained external databases
  Targeted provider API searches
  Source references and related objects
  Similarity / transformation matching
          |
          v
CANDIDATE RECONCILIATION
  Exact matches
  Equivalent representations
  Re-encodes / resizes / crops
  Edited and censored variants
  Related works and collections
  Conflicting or uncertain claims
          |
          v
EVIDENCE + RELATIONSHIPS
  Source attribution
  Verified and declared facts
  Matching evidence
  Epistemic status
  Review history
  Relationship and variant graph
          |
          v
ORGANIZATION + ACQUISITION
  Group related objects
  Preserve page / series / pool order
  Select preferred representations
  Identify available downloads
  Acquire and verify selected content
  Retain alternatives and history
          |
          v
PERSISTENT KNOWLEDGE + OUTPUTS
  Searchable evidence database
  Verified content-addressed storage
  Rebuildable views and datasets
  Auditable exports
  Future enrichment and processing
```

### Fundamental Requirements

1. **Flexible entry points:** Accept recorded and previously unknown objects, including local content without a known original source.
2. **Multiple discovery methods:** Search local records, maintained indexes, external databases, and live providers using whichever methods are supported and justified.
3. **Comprehensive reconciliation:** Preserve exact duplicates, alternative representations, related versions, and genuinely distinct works without incorrectly merging them.
4. **Evidence-based conclusions:** Distinguish observed facts, locally verified properties, algorithmic inferences, and reviewed decisions.
5. **Non-destructive information retention:** Keep source-specific metadata, original observations, competing claims, and historical decisions.
6. **Source-aware acquisition:** Identify and acquire preferred representations without discarding alternatives or assuming that larger files are inherently better.
7. **Ordering and structure:** Preserve original page order, series and pool membership, revision sequences, and other source-declared relationships.
8. **Reproducibility:** Make discovery, reconciliation, acquisition, and projection decisions inspectable, explainable, and repeatable under stated policies.

---

## 2. Existing Foundation

The repository already implements substantial portions of the underlying infrastructure:

- Versioned SQLite schema, content-addressed asset storage, raw observations, and provenance records.
- Source-specific metadata adapters, bounded remote operations, checkpointing, and resumable workflows.
- X archive imports and operator-held seed materialization.
- Source URL, identifier, hash, and selected artist-based provider lookups.
- Candidate evidence, review, typed relationships, and work anchors.
- Local asset verification and explicit acquisition planning.
- Reprocessing retained raw observations.
- Initial JSONL/CSV projections with reproducibility manifests.
- Adapter fixtures, offline health checks, and extensive automated tests.

**The primary missing capability is not another foundational database abstraction. It is a coherent discovery and reconciliation workflow connecting these components, especially across locally maintained and externally sourced indexes.**

Existing subsystems should be reused and extended unless a demonstrated requirement proves they are insufficient.

---

## 3. Prioritized Development Backlog

### P0 — Core Functional Priorities

These establish the central workflow and should form the next active development milestone.

#### P0.1 — Unified Input and Discovery Orchestration

**Objective:** Allow one input to initiate a coherent, bounded discovery operation across appropriate search methods and sources.

**Implementation:**

- Normalize supported input types into a common discovery request while preserving their original identity and provenance.
- Extract available query material: stable IDs, URLs, hashes, fingerprints, metadata, and operator-supplied references.
- Reuse existing seed materialization rather than creating a parallel candidate identity system.
- Introduce a discovery planner that selects applicable search capabilities from registered sources.
- Execute local and remote discovery operations under explicit budgets and authorization policies.
- Retain search attempts, strategy versions, source/index identities, results, failures, and continuations.
- Permit bounded follow-up discovery from newly identified references without unrestricted recursive crawling.
- Deduplicate equivalent queries while retaining the provenance of every discovery path.

**Acceptance criteria:**

- A local image, URL, or existing catalog object can initiate the same discovery workflow.
- The planner reports which methods are available, unavailable, or excluded and why.
- Local inspection and planning remain offline by default.
- Discovery can resume without losing completed results or repeating unnecessary work.
- A search returning no results records its scope; it does not assert global nonexistence.

#### P0.2 — Local and External Database Discovery

**Objective:** Make existing local knowledge and independently maintained metadata databases first-class discovery sources.

**Implementation:**

- Provide indexed lookups across the existing catalog, managed assets, and imported content.
- Support read-only or explicitly imported external databases such as SQLite, JSONL, and CSV.
- Introduce source/index adapters declaring supported identifiers, query methods, schema mappings, and limitations.
- Support exact identifiers, declared hashes, verified hashes, source URLs, and applicable metadata fields.
- Retain index revision, snapshot identity, acquisition/source information, and observation timestamps.
- Distinguish indexed records from live-verified source observations.
- Allow indexed results to initiate targeted live verification or further discovery.
- Avoid copying large external datasets into the primary catalog unless needed.

**Acceptance criteria:**

- A locally held file can match a record in an external metadata index.
- Results can be reconciled with catalog records without creating duplicate identities.
- Imported indexes remain distinguishable from authoritative live provider responses.
- Reindexing is incremental where practical, idempotent, and inspectable.

#### P0.3 — Unified Targeted Remote Discovery

**Objective:** Search supported online sources using the strongest available evidence and suitable provider-specific query methods.

**Implementation:**

- Extend existing bounded candidate lookup capabilities.
- Support stable IDs, external references, source URLs, declared/verified hashes, and provider-specific search operators.
- Use supported metadata and contextual searches where exact methods are insufficient.
- Prefer narrow, high-confidence queries before weaker or more expensive strategies.
- Combine local-index and remote-provider results into one discovery session.
- Track source capability, query cost, freshness, outcomes, and rate-limit boundaries.
- Preserve authentication, host allowlisting, pagination, retry, and redaction policies.

**Acceptance criteria:**

- One discovery request can search multiple supported providers.
- Each provider receives only valid, explicitly permitted query operations.
- Results identify how they were discovered.
- Partial failures and unsupported search capabilities remain visible.
- Discovery never implicitly triggers unrelated bulk enumeration or media downloads.

#### P0.4 — Multi-Method Matching and Reconciliation

**Objective:** Turn discovery results into evidence-backed candidate identities and relationships.

**Implementation:**

- Combine canonical references, stable identifiers, verified SHA-256/MD5, provider-declared hashes, and measured visual fingerprints.
- Compare perceptual hashes, dimensions, aspect ratios, and contextual source information.
- Introduce geometric crop/partial-region matching only after research validates its usefulness.
- Distinguish exact-byte equivalence, visual equivalence, technical transformations, creative edits, and broader related-work relationships.
- Reuse candidate evidence and reversible review machinery.
- Preserve contradictory evidence and uncertain results.
- Materialize sufficiently supported relationships through the existing typed relationship model.
- Make scoring methods, feature contributions, and detector versions inspectable.

**Acceptance criteria:**

- Identical bytes across sources are linked without duplicating content.
- Re-encoded or visually equivalent representations can be proposed as related despite different hashes.
- Unrelated images with stylistic similarities are not automatically grouped.
- Cropped and edited variants remain separate representations with appropriate relationship evidence.
- Repeated reconciliation is idempotent.
- Similarity alone never establishes authorship, source direction, or work identity.

---

### P1 — Completion of the Core Workflow

These turn discovery results into a useful organized collection with verifiable acquisition decisions.

#### P1.1 — Work, Variant, and Collection Organization

**Objective:** Represent discovered content as connected works, representations, versions, and ordered collections.

**Implementation:**

- Extend current per-post work anchors with cross-provider grouping projections.
- Preserve original source occurrences and representations independently.
- Distinguish technical derivatives from meaningful edits, separate works, and broader collections.
- Support multipage works, animations, media sets, pools, series, and other grouping structures.
- Preserve source-declared ordering, membership, page indices, and revisions.
- Support multiple simultaneous orderings rather than imposing one canonical order.
- Retain relationship provenance and review history.
- Allow grouping and selection policies to vary by downstream use.

**Acceptance criteria:**

- A work can be inspected across all known sources and representations.
- A multipage work retains its original page order.
- Provider collection membership and order are preserved even when incomplete or conflicting.
- Distinct creative versions are not silently merged into one asset.
- The system can reconstruct why an object belongs to a group.

#### P1.2 — Source-Aware Acquisition and Representation Selection

**Objective:** Identify available representations, choose preferred acquisition candidates, and retain verified downloads.

**Implementation:**

- Aggregate acquisition availability across discovered occurrences.
- Detect content already held locally before scheduling another download.
- Prefer upstream originals where provenance supports that classification.
- Evaluate dimensions, format, source role, verified properties, and possible quality degradation.
- Avoid treating upscales or larger files as automatically superior.
- Handle unavailable, deleted, expired, and inaccessible source URLs.
- Reuse existing bounded transfer, staging, verification, quarantine, and CAS publication machinery.
- Preserve source associations, attempts, outcomes, and alternative acquisition paths.

**Acceptance criteria:**

- Given several discovered representations, the system can explain its preferred acquisition choice.
- Already-held exact content is not downloaded unnecessarily.
- An inaccessible preferred source can produce a documented fallback.
- Failed downloads do not erase metadata or discovery results.
- Every acquired asset retains its originating source and verification evidence.

#### P1.3 — Efficient Review and Inspection

**Objective:** Make reconciliation practical for collections containing many candidates.

**Implementation:**

- Provide bounded views of discovery results, relationships, conflicts, and acquisition alternatives.
- Display source evidence, visual comparisons, dimensions, declared hashes, verified hashes, and matching signals.
- Support explicit confirmation, rejection, and reversal of uncertain conclusions.
- Provide batch-review operations with safeguards.
- Begin with CLI/report-based workflows; introduce a GUI only when justified.

**Acceptance criteria:**

- Candidates can be reviewed without manually reconstructing their supporting evidence.
- Review decisions survive later discovery and metadata refresh.
- Batch operations preserve individual candidate histories.
- Confirmed, rejected, and unresolved relationships remain distinguishable.

---

### P0 — Continuous Engineering Requirements

These should be developed alongside the functional work rather than postponed until the end.

#### P0.5 — Integration Tests, Recovery, and Reproducibility

**Objective:** Prove that complete workflows are correct, safe, recoverable, and repeatable.

**Implementation:**

- Create representative end-to-end golden scenarios spanning local and remote discovery.
- Add CI for pytest, Ruff, ty, migrations, packaging, and offline adapter checks.
- Test partial failures, interruption, retry, resume, duplicate input, and conflicting source observations.
- Implement or formalize consistent backup/restore with integrity verification.
- Test provider capability and adapter-version drift.
- Pin relevant source snapshots and implementation versions for reproducibility.
- Measure discovery completeness within explicitly defined searchable scopes.

**Acceptance criteria:**

- Core workflows run entirely offline against deterministic fixtures.
- Repeated execution cannot silently duplicate conclusions or corrupt existing data.
- Recovery preserves already committed evidence.
- Database backup/restore is tested.
- Every change is checked automatically against the established quality gates.

---

### P2 — Downstream Capabilities and Expansion

These are important but should be driven by working discovery and reconciliation use cases.

#### P2.1 — Reproducible Dataset and Custom Projection Output

- Generate consumer-specific schemas from the retained evidence database.
- Select, filter, deduplicate, and group works and representations under stated policies.
- Prevent related variants from leaking across training/validation/test splits.
- Preserve field-level provenance and disagreement information.
- Support JSONL, CSV, and additional formats such as Parquet where justified.
- Record code revision, input snapshot, policies, identifiers, exclusions, and output digests.

**Acceptance criteria:** A training or research dataset can be regenerated with traceable decisions about included objects and selected representations.

#### P2.2 — Scalability and Index Maintenance

- Replace or extend read-only snapshot handling where the current in-memory size limit becomes restrictive.
- Support consistent snapshots alongside active database writes.
- Use indexed/keyset queries and streaming output for large datasets.
- Benchmark local index discovery, matching, grouping, and export workloads.
- Bound memory, processing time, disk usage, and unnecessary repeated work.
- Add maintenance and repair workflows for indexes and derived data.

**Acceptance criteria:** Large catalogs and metadata indexes remain queryable and exportable without requiring full in-memory copies or unbounded operations.

#### P2.3 — Temporal Knowledge, Refresh, and Evidence Evolution

- Complete as-of reconstruction for relationships, reviews, and source-specific metadata.
- Preserve what was known at a historical cutoff.
- Support changes in availability, aliases, source references, and provider assertions.
- Plan bounded refresh operations based on age, availability, or changed evidence.
- Reprocess retained raw payloads under newer normalizers without unnecessary refetching.
- Distinguish observation history from derived lineage and confidence policies.

**Acceptance criteria:** The system can explain what changed between two knowledge snapshots and why a current conclusion or projection differs.

#### P2.4 — Derived Metadata and Enrichment Pipelines

- Define provenance-preserving processing contracts for local analysis and enrichment.
- Support image/video/audio inspection, metadata extraction, captioning, embeddings, detection, and segmentation where justified.
- Track processor/model identity, version, parameters, inputs, outputs, and failures.
- Store machine-generated assertions separately from verified properties and human-reviewed conclusions.
- Reuse existing run, evidence, blob, and projection mechanisms.
- Keep optional computational backends separate from the core kernel.

**Acceptance criteria:** A derived processing result can be retained, compared, challenged, reprocessed, and exported without overwriting source evidence.

#### P2.5 — Additional Sources and Data Families

- Add providers when they unlock concrete discovery or acquisition capabilities.
- Extend local/external index adapters independently of live provider adapters.
- Introduce non-media data families through demonstrated workflows.
- Generalize kernel interfaces only where additional consumers expose actual shared requirements.
- Avoid duplicating mature acquisition, provenance, or candidate subsystems.

**Acceptance criteria:** Adding a source or domain family requires domain-specific integration rather than reimplementing the core discovery and evidence lifecycle.

---

## 4. Delivery Milestones

### Milestone A — Unified Multi-Source Discovery and Reconciliation

**Highest immediate priority.**

Includes:

- P0.1 Unified input and discovery orchestration
- P0.2 Local/external database search
- P0.3 Targeted remote discovery
- P0.4 Multi-method matching and reconciliation
- P0.5 Integration tests and recovery
- Minimal grouping and acquisition-plan integration from P1

**Required demonstration:**

Starting with an arbitrary local image, the system finds known local content, searches a maintained metadata index, performs appropriate targeted provider queries, reconciles candidates, and outputs linked occurrences, evidence, and available acquisition choices.

Deliver one working vertical slice first, then broaden coverage and matching methods.

### Milestone B — Work/Variant Organization and Acquisition

Includes P1.1–P1.3.

**Required demonstration:**

A discovered work with multiple representations, sources, and ordered pages can be inspected as a coherent related collection, reviewed, and acquired according to explicit selection policies.

### Milestone C — Reproducible Downstream Outputs

Includes P2.1 and the necessary supporting scalability and temporal capabilities.

**Required demonstration:**

Build an auditable dataset from the reconciled catalog with configurable selection rules, grouped variant handling, original-source preferences, metadata provenance, and reproducible outputs.

### Milestone D — Generalized Processing and Domain Expansion

Includes P2.4–P2.5, plus scaling and maintenance improvements justified by real workloads.

**Required demonstration:**

A new enrichment pipeline or non-media consumer uses the established provenance and execution contracts without requiring a parallel implementation of the kernel.

---

## 5. Reference Acceptance Scenario

Use a representative real-world case throughout development.

**Input:** A JPEG obtained from X, with no reliably known original source.

**Expected behavior:**

1. Inspect the input, verify bytes, extract metadata, and calculate relevant hashes/fingerprints.
2. Search the managed local catalog and known file/index locations.
3. Search a separately maintained booru metadata database by appropriate identifiers.
4. Use discovered references or hashes for targeted live provider queries.
5. Identify an upstream Pixiv PNG, an exact-byte Danbooru mirror, a resized Gelbooru sample, and a potentially cropped repost where available.
6. Distinguish exact matches from proposed transformations and unrelated similar artworks.
7. Preserve every occurrence, its source-specific metadata, and all discovery evidence.
8. Connect the records using typed relationships, retaining uncertainty and review decisions.
9. Preserve page/collection ordering and any known version relationships.
10. Generate an acquisition plan favoring the best justified representation while retaining alternatives.
11. Download authorized selections, verify them, and attach resulting assets to the evidence graph.
12. Expose the final collection through reproducible queries and exports.

**Additional required cases:**

- A local file with no known external match.
- An input represented in multiple imported databases but not currently available online.
- A deleted source whose prior metadata is still retained.
- Several visually similar but genuinely different works.
- A multipage work with different provider ordering or incomplete membership.
- Conflicting artist attribution across providers.
- A later discovery run that contributes new evidence without destroying historical conclusions.

These scenarios should remain persistent regression fixtures as implementation advances.

---

## 6. Architectural Constraints

All milestones must respect the following rules:

- **Reuse the existing provenance kernel.** Do not introduce parallel stores for the same facts, evidence, relationships, or acquisitions.
- **Do not conflate search hits with verified identities.** Discovery produces evidence; reconciliation produces justified conclusions.
- **Preserve source-specific records.** Deduplication of identical bytes must not erase occurrences, metadata, or provenance.
- **Keep typed domain schemas.** Do not replace meaningful domain structure with an unrestricted entity-attribute-value system.
- **Separate source truth from system interpretation.** Raw observations and historical decisions remain available for reinterpretation.
- **Keep network interaction explicit and bounded.** Local planning and inspection must not silently fetch remote content.
- **Prefer established matching and processing methods.** Introduce custom algorithms only when comparative evaluation establishes a need.
- **Do not invent source or version ordering.** Preserve original orderings and represent uncertain chronology explicitly.
- **Maintain reproducible policies.** Every derived grouping, candidate decision, preference, and projection should identify the method and evidence used.
- **Generalize only when justified.** New abstractions should serve a demonstrated consumer or remove observed duplication, not exist solely for architectural uniformity.

---

## 7. Implementation and Tracking Policy

Use Beads as the authoritative implementation task tracker, with OpenSpec for substantial new behavior or schema contracts.

Each implementation unit should identify:

- The concrete user-facing or downstream capability it unlocks.
- Existing components that will be reused.
- The smallest necessary interface, schema, or behavior changes.
- Dependencies and compatibility requirements.
- Deterministic tests and acceptance cases.
- Failure, cancellation, recovery, privacy, and resource-boundary behavior.
- Documentation and changelog updates.

Keep the project roadmap focused on milestones and capability status rather than duplicating every implementation task.

Reconcile previously completed or partially implemented work before creating replacement issues.

---

## 8. Definition of Success

The project's central capability is complete when a user can supply an object or piece of information and reliably ask:

> **Find where this exists, what other versions or related objects exist, what the available sources know about it, which relationships are supported by evidence, what can be downloaded, and how the results are organized.**

The system should be able to answer with:

- All discovered occurrences within the explicitly searched scope.
- Exact and probable matches, with understandable evidence.
- Related versions, representations, and their ordering.
- Source-specific metadata and provenance.
- Contradictions, unknowns, and review history.
- Available and verified local content.
- Explicit acquisition and preference decisions.
- Rebuildable, consumer-specific outputs.

A successful system does not need to know everything. It must reliably distinguish **what was found, what was searched, what is verified, what is inferred, and what remains unknown**.

**Development principle:** Prioritize concrete discovery and reconciliation capabilities. Expand the underlying infrastructure only where those capabilities expose real requirements, limitations, or measurable bottlenecks.
