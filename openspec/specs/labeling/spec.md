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
