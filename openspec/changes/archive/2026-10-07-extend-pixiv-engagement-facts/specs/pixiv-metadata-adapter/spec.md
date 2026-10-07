## MODIFIED Requirements

### Requirement: Pixiv artwork metadata is retained without media acquisition
The adapter SHALL retain artwork title, caption, creation and update times when supplied, type,
page count, dimensions, tags, restriction and visibility state, canonical URL, user relationship,
engagement totals that map onto the neutral observation vocabulary (bookmark count and comment
count as post metadata observations; `total_view` and classification fields remain raw-retained
until persistence homes exist), and raw provider response without downloading artwork files.

#### Scenario: Fetch one illustration
- **WHEN** an available artwork detail is fetched by stable artwork ID
- **THEN** the post, publishing Pixiv account, author-role participation, raw response, tags, and
  metadata-only media occurrences are persisted together

#### Scenario: Artwork is unavailable
- **WHEN** Pixiv reports an artwork as deleted, private, restricted, or unavailable
- **THEN** the typed availability observation is retained without fabricating media URLs

#### Scenario: Engagement totals are observed
- **WHEN** an artwork detail supplies bookmark and comment totals
- **THEN** they persist as post metadata observations under the shared vocabulary with raw
  provenance, and repeat observations update them without duplicating rows
