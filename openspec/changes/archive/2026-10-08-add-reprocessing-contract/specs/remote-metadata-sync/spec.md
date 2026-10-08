## ADDED Requirements

### Requirement: Retained raw observations reprocess offline under newer normalizers
The system SHALL provide an explicit reprocessing operation that replays a retained raw
observation through the current adapter's normalizer without any provider contact. A
normalization attempt SHALL be identified by the source payload digest together with the
adapter and schema versions; adapters MUST bump their adapter version whenever normalization
behavior changes. Reprocessing MUST NOT modify the retained raw payload or erase prior
normalized interpretations — new facts land as observations under the existing
current-projection policy — and replaying the same raw under the same adapter/schema version
MUST be idempotent (skipped, not duplicated). Every reprocess execution SHALL be recorded as
a remote run with an explicit reprocess origin and zero provider requests, and malformed
retained payloads SHALL fail as typed outcomes that remain inspectable for a later retry.
Planning SHALL be read-only, bounded, and report which retained observations are stale under
the replay adapter before any commit.

#### Scenario: Plan reports stale retained raws without writing
- **WHEN** an operator plans reprocessing for a provider whose retained raws were normalized
  under an older adapter version
- **THEN** the plan lists them with operation, target, versions, and already-reprocessed
  skips, and writes nothing

#### Scenario: Replay materializes new facts offline
- **WHEN** a retained payload whose fields were previously raw-only is replayed under a newer
  normalizer
- **THEN** the additional typed facts materialize without network access, the original raw
  bytes are byte-identical, and the run records the reprocess origin with zero requests

#### Scenario: Repeat replay is idempotent
- **WHEN** the same raw is replayed again under the same adapter and schema version
- **THEN** the operation is skipped and no duplicate facts or runs are created

#### Scenario: Malformed retained payload stays inspectable
- **WHEN** a retained payload cannot be normalized under the current normalizer
- **THEN** the attempt records a typed malformed outcome without destroying the payload, and
  a later parser version may succeed on retry
