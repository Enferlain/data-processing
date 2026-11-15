# operator-labels Specification

## Purpose

Free-form operator-defined labels on catalog subjects: local facts and
groupings ("ai-generated", "needs-review", batch names) that never touch
provider-observed tag tables, with append-only history and identical-content
semantics across platforms.

## Requirements

### Requirement: operator labels are free-form local facts with lifecycle

The catalog SHALL support operator-defined labels (unique name, optional
description) that can be created and retired at any time without losing
history, and SHALL record label applications as append-only assertions with
state `applied`/`revoked`, an operator attribution, a timestamp, and an
optional note. The current label state of a subject SHALL be the latest
assertion per (subject, label); assertions SHALL never be edited or deleted
in place. Labels and assertions SHALL NOT touch provider tag tables.

#### Scenario: apply, revoke, re-apply keeps full history

- **WHEN** a label is applied to a subject, revoked, then applied again
- **THEN** three assertion rows exist in order, and the subject currently
  carries the label, with every prior assertion still queryable

#### Scenario: retiring a label keeps past assertions readable

- **WHEN** an operator retires a label that has assertions
- **THEN** the label is marked retired (no new applications accepted) and all
  historical assertions remain

### Requirement: label search expands to identical content across platforms

Searching by label SHALL return every subject that carries the label directly
plus every subject with identical content: file seeds sharing the same
verified md5/sha256 pair, and posts linked by an identical md5 (file-seed
verified md5 to occurrence declared md5, or shared declared md5 between
posts). Near-duplicates (variants) SHALL NOT inherit labels.

#### Scenario: label on a file seed covers its identical provider posts

- **WHEN** a label is applied to a bare-file seed and a catalog post carries
  the same md5
- **THEN** searching the label lists both the seed and the post, each marked
  direct or identical-content

#### Scenario: variants do not inherit

- **WHEN** two posts are related as variant/crop but their md5s differ
- **THEN** a label on one does not surface the other
