## ADDED Requirements

### Requirement: Post field sources project per-field provenance
The system SHALL provide a `post-field-sources` export projection kind emitting one row per
post with retained post metadata observations. Each row SHALL list, for every observed
field, the complete retained value history — value, observation time, raw-observation
evidence pointer, and source platform — and the field's current value selected under the
stated newest-observation-wins policy. Dissenting values SHALL be retained in the row, never
collapsed. The projection SHALL be offline and read-only, follow the existing manifest
recipe and digest contracts, exclude posts without retained metadata observations with a
counted reason, and carry no URLs or payload content.

#### Scenario: Dissenting values stay in the row
- **WHEN** a field has multiple retained observations with differing values
- **THEN** the row lists every observation with its value, time, evidence pointer, and
  platform, and marks the newest observation's value as current

#### Scenario: Posts without observations are excluded with a reason
- **WHEN** a post has no retained post metadata observations
- **THEN** it produces no row and is counted under the no-observations exclusion reason,
  alongside limit overflow when present
