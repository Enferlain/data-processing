## MODIFIED Requirements

### Requirement: Acquisition is explicit and selection-scoped
The system SHALL acquire remote bytes only through an explicit acquisition operation over selected
catalog media occurrences or their named variants. Selection SHALL be either an explicit list of
occurrence and variant references, or an expansion-plan-scoped selection that resolves occurrences
offline from a committed library expansion plan's associations under a fixed criteria set —
variant, availability, eligibility, and item limit. Metadata synchronization, discovery, import,
and read-only query operations MUST NOT trigger media downloads.

#### Scenario: Plan selected occurrences without network activity
- **WHEN** a user plans acquisition for a bounded set of occurrence identifiers
- **THEN** the system reports the eligible variants, exclusions, estimated known sizes, and
  applicable limits without issuing media requests or changing managed storage

#### Scenario: Plan from a committed expansion without identifier translation
- **WHEN** a user plans acquisition scoped to a committed library expansion plan using the fixed
  criteria (variant and availability)
- **THEN** the system resolves the eligible occurrences and variants from the expansion's
  committed associations offline, reports inclusions, exclusions with reasons, and limits, and
  issues no media request

#### Scenario: Expansion-scoped selection stays bounded
- **WHEN** an expansion-scoped selection would exceed the configured item limit
- **THEN** planning applies the documented limit and reports which eligible occurrences were
  excluded by it

#### Scenario: Metadata synchronization remains metadata-only
- **WHEN** remote metadata synchronization creates or updates an occurrence with downloadable URLs
- **THEN** the system persists the metadata without fetching those URLs or creating an acquisition
  run
