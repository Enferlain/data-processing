## ADDED Requirements

### Requirement: Danbooru-family adapters declare lookup capabilities
Each supported instance SHALL declare whether it can look up posts by canonical source URL, embedded external post ID, and MD5, and whether it can search artist records by exact name, alias, or bounded text query. The caller MUST be able to reject an unsupported operation before a request, and instance-specific response shapes MUST remain isolated behind normalized results.

#### Scenario: Instance supports source but not artist text search
- **WHEN** capability inspection is requested for that instance
- **THEN** source lookup is eligible and artist text search is excluded without probing an undocumented endpoint

### Requirement: Reverse post lookup retains provider facts
Post lookup results SHALL retain the provider post identity, source values, embedded external identifiers, declared MD5, uploader identity, artist-tag attribution, availability, raw observation, and request provenance without converting declared values into verified facts.

#### Scenario: Look up by canonical X source URL
- **WHEN** the provider returns a post for an allowlisted canonical X status URL
- **THEN** normalization preserves the queried source, returned source fields, provider post ID, uploader, artist tags, and declared media facts as distinct evidence

#### Scenario: Look up by MD5
- **WHEN** the provider returns a post for an exact MD5 query
- **THEN** the MD5 remains provider-declared unless catalog bytes independently verify it

### Requirement: Artist lookup preserves attribution boundaries
Artist lookup SHALL retain exact names, aliases, other names, deprecation or replacement state, and external URLs. It SHALL NOT normalize an artist record or tag as an account, and an uploader SHALL remain separate from artist attribution.

#### Scenario: Artist record links to Pixiv
- **WHEN** an artist lookup result contains a Pixiv user URL and an unrelated uploader account
- **THEN** normalization retains the artist URL as reference evidence and the uploader separately, without confirming either as the X seed's identity

#### Scenario: Similar artist names
- **WHEN** a bounded text query returns multiple similarly named artist records
- **THEN** all retained results remain ordered weak leads with provider identities and no automatic winner
