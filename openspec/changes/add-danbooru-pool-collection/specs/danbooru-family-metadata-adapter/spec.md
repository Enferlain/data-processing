## ADDED REQUIREMENTS

### Requirement: Pool collection is bounded, ordered, and evidence-only
The danbooru-family adapter SHALL support fetching a single pool by native identifier via the
provider's pool endpoint under the bounded run contract — declared budgets, a recorded remote
request, retained raw source report with provenance, and a typed outcome. Pool observations SHALL
retain the provider-declared membership order as an ordered list of member observations carrying
each member's native post identifier and position, with catalog post links only for posts already
retained. Re-observation of an unchanged pool (same membership, same order) SHALL be idempotent
through the observation digest; a changed membership or order SHALL land as a new retained
observation, never a rewrite. Pool observations SHALL NOT create works, relationships, or any
work-grouping conclusion — ordering is evidence for review-gated Phase D conclusions only.

#### Scenario: A pool fetch observes ordered membership
- **WHEN** an operator fetches pool 42 and the provider reports post_ids `[100, 7, 900]`
- **THEN** one pool observation is retained with three member observations at positions 1, 2, 3 in
  that order, each carrying its native post identifier, and the raw report anchors the observation

#### Scenario: Unretained members stay by native identifier
- **WHEN** a pool member's post is not yet retained in the catalog
- **THEN** the member observation retains its position and native identifier with no post link,
  and a later post sync may resolve it without rewriting the pool observation

#### Scenario: Unchanged pools re-observe idempotently
- **WHEN** the same pool is fetched again and membership plus order are unchanged
- **THEN** no new pool observation row is created while the fetch's raw report and run are still
  retained

#### Scenario: Reordered membership is a new observation
- **WHEN** a later fetch reports the same members in a different order
- **THEN** a new pool observation is retained and the earlier one remains queryable

#### Scenario: Pools claim no grouping conclusion
- **WHEN** pool observations are recorded
- **THEN** no work, relationship, or work-grouping conclusion is created automatically

#### Scenario: The single-pool endpoint does not paginate
- **WHEN** a pool fetch completes
- **THEN** it terminates after one request; resumable semantics apply only where a provider
  endpoint paginates, which this one does not
