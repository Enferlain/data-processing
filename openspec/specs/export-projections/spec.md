# export-projections Specification

## Purpose
Bounded, reproducible, auditable exports over the retained evidence layer: JSONL/CSV
projections with a complete recipe manifest, deterministic digests, privacy-safe output, and
offline read-only execution, so downstream datasets can be rebuilt and audited rather than
merely regenerated.

## Requirements

### Requirement: Every export writes a complete manifest sidecar
Each export execution SHALL write a manifest alongside its data files. The manifest SHALL
carry the projection kind, the projection schema version, every projection policy in effect
(selection/filter, ordering, deduplication/variant, preferred-representation, field-source,
and URL-handling policies), the source database schema version, the tool version, the
generation timestamp, the output file names with per-file row counts and content digests, and
inclusion and exclusion counts with bounded reasons. Projection policies SHALL be stated, not
implicit.

#### Scenario: Manifest answers the recipe question
- **WHEN** an export completes and the manifest is inspected
- **THEN** it names the projection kind and schema version, restates each policy in effect,
  records the source schema version, tool version, and generation timestamp, lists each output
  file with its row count and content digest, and reports inclusion and exclusion counts with
  a bounded reason for every exclusion category

### Requirement: Projections are deterministic and rebuildable
The projection specification SHALL have a deterministic digest that is stable across re-runs
with identical policy and tool/schema versions. The exported selection SHALL have a
deterministic digest computed over the ordered stable identifiers of included rows; re-running
the same projection against unchanged evidence SHALL produce identical specification and
selection digests and logically equivalent output rows in the stated order. A change to the
evidence or to any policy input SHALL change the corresponding digest.

#### Scenario: Re-run on unchanged evidence reproduces the projection
- **WHEN** the same projection runs twice against an unchanged catalog with the same policy
  inputs
- **THEN** both runs report the same specification digest and selection digest, and the data
  files contain logically equivalent rows in the same order, differing at most by generation
  timestamp recorded in the manifest

#### Scenario: Evidence change moves the selection digest
- **WHEN** the catalog gains or loses rows in the projection's selection after an earlier run
- **THEN** the next run reports a different selection digest

### Requirement: Output is privacy-safe by default
Every projection kind SHALL define a deny-by-default field allowlist. Export output and
manifests SHALL NOT contain private storage paths, credentials, cookies, signed URLs, or raw
payload content. Remote URLs SHALL be emitted as origin and path only, with any query string
removed.

#### Scenario: Private material stays out of exports
- **WHEN** the catalog contains managed-storage paths and occurrence URLs carrying query
  strings
- **THEN** no exported row or manifest field contains a storage path or a URL query string,
  and only fields on the projection kind's allowlist are emitted

### Requirement: Exports are offline, read-only, and bounded
Export planning and execution SHALL NOT contact any network service and SHALL NOT modify the
catalog database. Exports SHALL be bounded by an explicit row limit with a stated selection
policy, and a planning preview SHALL report would-be inclusion and exclusion counts and
reasons without writing any file.

#### Scenario: Plan writes nothing
- **WHEN** an operator runs the export planning preview
- **THEN** it reports the projection kind, policy inputs, would-be included and excluded counts
  with reasons, and writes no files

#### Scenario: Execution never mutates the catalog
- **WHEN** an export runs against a catalog
- **THEN** the catalog database file contents are unchanged apart from ordinary read access,
  and any network attempt fails the export

### Requirement: Rows carry stable evidence-layer identifiers
Every exported row SHALL carry identifiers that resolve back to evidence-layer records without
ambiguity, and the manifest SHALL state which identifiers each projection kind emits.

#### Scenario: A row can be traced to its evidence
- **WHEN** an exported row is inspected
- **THEN** it carries the stable identifiers the manifest declares for its projection kind,
  sufficient to locate the underlying catalog record

### Requirement: First projection kinds cover assets and posts
The system SHALL provide an `assets` projection — one row per verified asset with its
content-addressed identity, locally verified byte and image facts, representation-link count,
and bounded legacy-assertion classification, with exact byte-duplicates collapsed by content
identity and their representation counts retained — and a `posts` projection — one row per
post with its platform identity, current mutable facts and their evidence pointer, occurrence
summary, and participant summary with review states. Both SHALL state their selection,
ordering, deduplication, preferred-representation, and field-source policies in the manifest.

#### Scenario: Assets projection collapses exact duplicates by content
- **WHEN** two catalog representations reference identical verified bytes
- **THEN** the assets projection emits one row for that content identity and retains the
  representation-link count that records both references

#### Scenario: Posts projection reports participants with review state
- **WHEN** a post has participants whose attribution review states differ
- **THEN** the posts projection row summarizes each participant with its role and review state
  without overriding any review decision

### Requirement: Works projection groups variant families per work
The system SHALL provide a `works` export projection kind emitting one row per work: its
stable identifier and origin post identity, its representations with roles and verified-byte
links, a preferred-representation selection computed under a stated policy that excludes
thumbnail and preview roles and prefers the upstream original, and a summary of its
`same_work` relationships. The manifest SHALL state the grouping, exclusion, and preference
policies. Selection and exclusion counts with reasons SHALL follow the existing manifest
contract.

#### Scenario: Thumbnails never become the preferred representation
- **WHEN** a work's representations include sample or preview roles alongside an original
- **THEN** the works projection row lists them all but selects the preferred representation
  from the non-thumbnail roles, and the manifest states that policy

#### Scenario: Works rows stay auditable
- **WHEN** a works projection is exported
- **THEN** each row carries stable work and representation identifiers resolving back to the
  evidence layer, and re-running against unchanged evidence reproduces the digests

### Requirement: Attribution disagreements project over linked posts
The system SHALL provide an `attribution-disagreements` export projection kind emitting one
row per retained post-level relationship (`reposted_from`, `same_work`) whose ends disagree
on artist attribution: both ends carry attribution, and no cross-pair of attribution
identities is joined by a confirmed identity membership. The projection SHALL be offline and
read-only, SHALL follow the existing manifest recipe and digest contracts, and SHALL NOT
create, modify, or override any review decision, candidate, or relationship.

#### Scenario: Unjoined attributions surface as one disagreement row
- **WHEN** two posts are linked by a retained relationship and each end's artist attribution
  — account participants with artist or author roles, plus provider attribution entities
  implied by the post's tags — resolves to identities no confirmed identity membership joins
- **THEN** the export emits one row listing both ends' attribution identities (platform,
  native identifier, primary name, review state), the linking relationship's kind and
  epistemic status, stable evidence-layer identifiers, and a name-equality hint marked as
  weak evidence

#### Scenario: Confirmed identities exclude a pair
- **WHEN** any account identity on one end is joined to one on the other end by a confirmed
  identity membership
- **THEN** the pair is excluded from the rows and reported under the confirmed-join
  exclusion count

#### Scenario: Other exclusions are counted with reasons
- **WHEN** a linked pair lacks attribution on either end, the relationship's review state is
  rejected, or rows fall beyond the export limit
- **THEN** the pair or row is excluded and counted under the matching bounded reason

#### Scenario: The report never settles anything
- **WHEN** the attribution-disagreements projection runs
- **THEN** no review decision, candidate, relationship, or other evidence-layer row is
  written, and the manifest states the report-only policy
