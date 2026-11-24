## ADDED requirements

### Requirement: Subject provenance timelines read retained history

The system SHALL provide a read-only timeline for one subject (a post or an
account): every retained event about it in parsed-time order — source
observations with their originating run, metadata observations, account
snapshots, pair labels and label decisions, match candidates and their
decisions, and relationships with their review decisions. The timeline
SHALL be bounded by an explicit event limit and SHALL modify nothing.

#### Scenario: post timeline spans providers and reviews

- **WHEN** a post has a provider observation from January, a label decision
  in February, and a candidate decision in March
- **THEN** the timeline lists the three events in that order with their
  kinds, timestamps, and originating sources

#### Scenario: account timeline shows snapshot history

- **WHEN** an account has snapshots from multiple dates
- **THEN** the timeline lists each snapshot with its observed time and the
  fields it carried

#### Scenario: unknown subject is rejected

- **WHEN** the requested post or account id does not exist
- **THEN** the command fails with a bounded diagnostic before any listing
