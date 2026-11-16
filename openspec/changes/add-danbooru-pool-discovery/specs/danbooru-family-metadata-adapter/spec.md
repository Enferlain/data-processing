# danbooru-family-metadata-adapter Delta

## ADDED requirements

### Requirement: bounded pool search by name records full membership

The danbooru family SHALL support a `SEARCH_POOLS` operation rendering
`GET /pools.json?search[name_matches]=<name>` with the instance page size,
and a bounded runner that records, under the standard run contract (run
committed before the request, raw report retained, typed outcome), one pool
observation per matching pool with its complete provider-declared ordered
membership — anchored to the search response's raw observation. Re-running a
name SHALL be skippable when a complete prior `search_pools` run exists for
that target; unchanged pool memberships SHALL stay digest-deduplicated.

#### Scenario: one search records every matching pool

- **WHEN** `catalog metadata danbooru-pool-search <catalog> <name>` runs and
  the provider returns N matching pools with ordered `post_ids`
- **THEN** one complete remote run records N pool observations (ordered
  members, retained posts linked) anchored to one retained raw report

#### Scenario: discovery drives artist names under a budget

- **WHEN** `--discover` runs with name and request budgets
- **THEN** only artist names with at least three held posts are searched,
  names with complete prior runs are skipped, and the pass stops at the
  request budget with per-name results reported
