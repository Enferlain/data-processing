## MODIFIED Requirements

### Requirement: Every export writes a complete manifest sidecar
Each export execution SHALL write a manifest alongside its data files. The manifest SHALL
carry the projection kind, the projection schema version, every projection policy in effect
(selection/filter, ordering, deduplication/variant, preferred-representation, field-source,
and URL-handling policies), the source database schema version, the tool version, the
generation timestamp, the evidence cutoff the selection resolved under (`as_of`; the
generation's "all retained observations" default when no explicit cutoff is given), the
output file names with per-file row counts and content digests, and inclusion and exclusion
counts with bounded reasons. Projection policies SHALL be stated, not implicit.

#### Scenario: Manifest answers the recipe question
- **WHEN** an export completes and the manifest is inspected
- **THEN** it names the projection kind and schema version, restates each policy in effect,
  records the source schema version, tool version, generation timestamp, and evidence
  cutoff, lists each output file with its row count and content digest, and reports
  inclusion and exclusion counts with a bounded reason for every exclusion category

## ADDED Requirements

### Requirement: Field-source histories reconstruct as of a cutoff
The `post-field-sources` projection SHALL accept an explicit as-of cutoff restricting every
field's history to observations whose source observation time is at or before the cutoff,
with current values re-resolved under the stated newest-observation-wins policy within the
restricted set. The cutoff SHALL participate in the projection specification digest, so two
runs with different cutoffs are different recipes.

#### Scenario: As-of resolves the earlier value
- **WHEN** the projection runs with a cutoff between two observations of a field
- **THEN** the field's history contains only the earlier observation and its value is the
  current value

#### Scenario: The cutoff changes the recipe digest
- **WHEN** the same projection runs with two different as-of cutoffs
- **THEN** the manifests report different specification digests and the data files differ
  only in cutoff-restricted content
