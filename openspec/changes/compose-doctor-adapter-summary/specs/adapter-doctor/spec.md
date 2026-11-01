# Spec Delta

## ADDED Requirements

### Requirement: The catalog doctor surfaces adapter contract health
The catalog-scoped doctor command SHALL include a compact summary of the adapter
doctor's offline replay in its report: overall ok, per-surface ok, named per-surface
failure reasons, and doctor-level errors. The composed summary SHALL NOT issue network
requests, and the catalog doctor's exit semantics SHALL remain report-only. The
report's top-level ok SHALL keep its storage-only meaning; adapter health is the
dedicated summary.

#### Scenario: Healthy catalog and adapters
- **WHEN** the catalog doctor runs with intact storage and green adapter replay
- **THEN** its report carries an adapters summary with ok true and every surface true

#### Scenario: Adapter contract drift
- **WHEN** a replayed adapter case fails
- **THEN** the catalog doctor's adapters summary names the surface and reason while the
  storage checks are reported independently
