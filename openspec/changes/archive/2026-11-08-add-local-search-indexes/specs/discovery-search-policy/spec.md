# Spec Delta

## Purpose

Extend the stage-1 search-policy capability to the index target kind:
offline execution, snapshot-scoped freshness identity, and tier ordering.

## MODIFIED Requirements

### Requirement: search state identity

Retained search state SHALL be keyed by subject × search target (kind and
source) × method × strategy version × query-evidence digest. A completed
attempt against one target or method SHALL NOT imply anything about any other
target or method for the same subject. Query evidence SHALL be part of the
key: when a subject's applicable query material changes, the prior attempts
do not cover the new evidence and the step is planned again. The strategy
version SHALL be part of the key: attempts recorded under an older strategy
version are not fresh under a newer one — and for index targets the version
SHALL embed the index snapshot revision, so a refreshed snapshot is a new
version for every subject.

#### Scenario: one provider's success never satisfies another

- **WHEN** a subject's `danbooru / verified_md5` attempt succeeded and
  `aibooru / verified_md5` was never attempted
- **THEN** a later run still plans `aibooru / verified_md5`

#### Scenario: changed evidence replans

- **WHEN** a subject gains a newly verified hash after a successful search
  that did not include it
- **THEN** the search step keyed on the new evidence is planned again even
  under the default recheck mode

#### Scenario: index snapshot revision is part of identity

- **WHEN** an index is refreshed to a new snapshot revision and the same
  subject is searched again
- **THEN** the index steps execute again even though they succeeded under the
  previous revision

## ADDED Requirements

### Requirement: offline targets execute before network targets

Discovery execution SHALL order offline targets — the local catalog and
registered indexes — before provider targets, without requiring live
authorization and without consuming the request budget. A provider step whose
answer an offline target already supplied under the same evidence remains
independently keyed and is governed by its own policy; ordering is a cost
preference, not a substitute for per-target search state.

#### Scenario: index answers before the provider is queried

- **WHEN** a subject resolves through its md5 in a registered index during an
  offline-first discovery
- **THEN** the index step completes before any provider step executes, and
  the provider steps still follow the policy and their own freshness state
