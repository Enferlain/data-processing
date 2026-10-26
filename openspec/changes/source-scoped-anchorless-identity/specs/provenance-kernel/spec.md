## ADDED REQUIREMENTS

### Requirement: Source-report observation identity is anchor-scoped or source-scoped content addressing
Each raw observation SHALL have exactly one identity: rows anchored to an import run are keyed by
their anchor, object kind, native identifier, and payload; rows anchored to a remote request are
keyed by that request; anchorless rows SHALL be content-addressed **per source** — platform,
object kind, native identifier when present, and payload bytes — enforced by the storage layer.
Anchorless retention SHALL require a declared source platform. Byte-identical anchorless payloads
from the same source SHALL resolve to one observation shareable by any number of requesting rows
(each keeping its own outcome and timestamps); byte-identical payloads from different sources
SHALL remain distinct observations with their own source attribution.

#### Scenario: A retry shares the observation
- **WHEN** the same source is asked again and returns byte-identical bytes for the same object
- **THEN** the requesting row references the existing content-addressed observation and no new
  observation row is created

#### Scenario: Different sources never fold
- **WHEN** two different sources return byte-identical bodies for the same object identity
- **THEN** two observations are retained, each carrying its own source attribution

#### Scenario: Anchored rows keep their anchor identity
- **WHEN** an observation is anchored to an import run or a remote request
- **THEN** the anchor key governs its identity and the anchorless indexes do not apply

#### Scenario: Anchorless retention names its source
- **WHEN** a source report is retained without a run or request anchor
- **THEN** the retention declares the reporting platform, and the observation's identity includes
  it
