## ADDED REQUIREMENTS

### Requirement: Opt-in note collection with positions and versions
The e621 adapter SHALL support fetching the notes of one post by native identifier via the
provider's notes endpoint under the bounded run contract, as an explicit operator action separate
from default post sync. Each note observation SHALL retain the provider note identifier, body
text, position, and note version, deduplicated by a digest over those facts so unchanged
re-observation is idempotent and an edited or moved note lands as a new observation. The operation
SHALL require an already-retained post and SHALL retain the raw source report with provenance. A
post with no notes SHALL end the run successfully with zero observations.

#### Scenario: Notes land with position and version
- **WHEN** an operator enriches a retained post with overlay notes
- **THEN** one observation per note is retained carrying body, position, provider note id, and
  version, anchored to the raw report

#### Scenario: A note edit bumps the version and lands as a new observation
- **WHEN** a later fetch reports the same note id with a higher version or changed body or
  position
- **THEN** a new observation is retained for that note and the earlier one remains queryable
