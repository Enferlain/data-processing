# labeling Specification

## Purpose

The operator pair-labeling queue: which provider-declared signal families may
enqueue candidate pairs for review, under the rule that a signal proposes
pairs but never decides a relationship. Label semantics and decision history
live in the operator-labels capability.

## Requirements

### Requirement: pool co-membership enqueues as a labeling family

Posts sharing a provider-declared pool membership (recorded in
`post_pool_observations`) SHALL enqueue as `pool_member` pairs in the
labeling queue when both posts are available and the pair is not already
labeled. The pair join SHALL be scoped to one platform namespace: the same
pool id on two different platforms SHALL NOT pair. Co-membership SHALL NOT
decide or materialize any relationship; the content verdict remains the
operator's.

#### Scenario: co-membership pair reaches the queue

- **WHEN** two available catalog posts on one platform carry observations
  for the same pool and the pair is unlabeled
- **THEN** the queue offers the pair under the `pool_member` signal with a
  detail stating the provider declared the shared pool

#### Scenario: same pool id across platforms never pairs

- **WHEN** two posts on different platforms carry the same numeric pool id
- **THEN** no `pool_member` pair is offered for them

#### Scenario: pool membership alone never decides

- **WHEN** any number of pool observations exist
- **THEN** no pair label, relationship, or candidate is created without
  either the operator's verdict or another family's earned automation

### Requirement: queue assembly interleaves signal families

The labeling queue SHALL assemble the per-session candidate list by
round-robin across signal families — one pair per family per rotation, in
the families' established order, preserving each family's internal pair
order — so no single family can monopolize a session. Interleaving SHALL
NOT change which pairs are eligible or skipped, pair attribution to the
first claiming family, or any pair's signal detail.

#### Scenario: dominant family no longer fills the session

- **WHEN** one family holds thousands of unlabeled pairs and every other
  family holds at least one
- **THEN** the session queue alternates families and each contributing
  family's pairs appear before the dominant family's second rotation

#### Scenario: family with nothing to offer is skipped in rotation

- **WHEN** a family has no eligible unlabeled pairs
- **THEN** rotation continues across the remaining families without gaps in
  the assembled queue
