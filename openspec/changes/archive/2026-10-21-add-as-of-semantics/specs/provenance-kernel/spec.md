## ADDED Requirements

### Requirement: Temporal as-of reconstruction from retained history
The system SHALL be able to reconstruct what was known as of a cutoff time from retained
history alone, without rewriting or special-casing historical rows. Timestamps SHALL keep
their distinct meanings: source observation time (when a source report was observed),
provider-claimed time (what the provider asserts about the content), acquisition time (when
bytes entered local custody), interpretation time (when a normalizer produced facts,
including reprocessing), and review time (when a human decided). Reconstructed current
values SHALL resolve under the stated projection policy restricted to facts observed at or
before the cutoff; review state SHALL be the latest decision at or before the cutoff.
Deleted, unavailable, moved, or later-corrected objects SHALL appear in reconstructions
through their retained observations, never by absence.

#### Scenario: A field's value as of a cutoff
- **WHEN** a field was observed with value A in January and value B in March, and the
  system reconstructs as of a February cutoff
- **THEN** the reconstructed current value is A, both observations remain retained, and no
  historical row is modified

#### Scenario: Review state as of a cutoff
- **WHEN** a candidate or relationship was confirmed in January and reversed in March
- **THEN** reconstructing as of February yields the confirmed state from the January
  decision, and both decisions remain retained

#### Scenario: Projections state their evidence cutoff
- **WHEN** a projection or export is generated
- **THEN** it records the cutoff its selection resolved under, so the build can later be
  explained or replayed against retained history
