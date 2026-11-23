## ADDED requirements

### Requirement: Pixiv artwork series membership is retained as an external series reference

The adapter SHALL read the artwork detail's `series` field and, when the
provider reports a non-null series, retain exactly one external reference
per artwork naming the pixiv series by its stable id — evidence on the post,
mirroring the source-URL reference path — without fetching series pages,
enumerating series members, or treating membership as a relationship
conclusion. A null or absent `series` key SHALL retain nothing.

#### Scenario: artwork in a series

- **WHEN** an artwork detail response carries `series` with an id
- **THEN** the persisted post gains a pixiv `series` external reference with
  that stable id and no other series-derived facts

#### Scenario: artwork outside any series

- **WHEN** the detail response carries `series: null`
- **THEN** no series reference is written and the post is otherwise
  unaffected
