## ADDED REQUIREMENTS

### Requirement: Opt-in dapi note collection
The gelbooru dapi adapter SHALL support fetching the notes of one post by native identifier via
the dapi note endpoint under the bounded run contract, as an explicit operator action separate
from default post sync, using the adapter's credentialed transport. Each note observation SHALL
retain the provider note identifier, body text, and position, deduplicated by a digest over those
facts. The operation SHALL require an already-retained post and SHALL retain the raw source report
with provenance. Until a credentialed live capture replaces the current documented-shape fixture,
the response contract SHALL be treated as provisional.

#### Scenario: Notes land with position
- **WHEN** an operator enriches a retained post whose dapi note query returns note entries
- **THEN** one observation per note is retained carrying body, position, and provider note id,
  anchored to the raw report

#### Scenario: A note edit lands as a new observation
- **WHEN** a later fetch reports changed body or position for the same note id
- **THEN** a new observation is retained and the earlier one remains queryable
