## ADDED Requirements

### Requirement: Candidate lookup supports bounded e621 evidence searches
Candidate lookup SHALL allow e621 as an explicit provider for supported source-post URL, embedded
external post ID, declared MD5, locally verified MD5, exact artist-name, and approved artist-alias
strategies. It SHALL preserve e621 result provenance and MUST NOT treat a tag, alias, uploader,
hash, similar name, or matching post as proof of account identity or authorship.

#### Scenario: e621 post cites the X seed
- **WHEN** a bounded source lookup returns an e621 post whose retained source identifies the seed post
- **THEN** the result may support a directed post-source candidate with the e621 observation attached as evidence

#### Scenario: Verified MD5 finds an e621 post
- **WHEN** an e621 post's declared original-file MD5 equals a locally verified seed occurrence MD5
- **THEN** the result may support an exact-byte post candidate while artist tags and uploader remain separate evidence

#### Scenario: Exact artist name or approved alias returns attribution
- **WHEN** a bounded exact-name or approved-alias lookup resolves an e621 artist-category tag or artist record
- **THEN** the result is retained as provider attribution evidence and creates no account candidate unless a separate stable account reference is recognized

#### Scenario: Unsupported text search is excluded
- **WHEN** the requested strategy would require arbitrary fuzzy or unrestricted tag search beyond the declared e621 capability
- **THEN** planning returns a stable exclusion and makes no provider request
