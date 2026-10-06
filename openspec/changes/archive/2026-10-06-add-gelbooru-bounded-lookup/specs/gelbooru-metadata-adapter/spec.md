## ADDED Requirements

### Requirement: Gelbooru bounded reverse lookup is exact, credentialed, and evidence-only
The DAPI adapter SHALL declare and implement bounded reverse lookup by canonical source URL
and by exact MD5 (declared or locally verified) using the credentialed DAPI transport, with
exact query tokens only, digest-based request identities, pid-based page continuation under
the shared limits, and retained raw responses. Undeclared strategies, wildcard or whitespace
source tokens, non-hex hash material, and missing credentials MUST be rejected before any
request. Lookup results SHALL reuse the post normalizer and remain evidence: they MUST NOT
establish post equivalence, account identity, or authorship, and the HTML transport MUST NOT
gain lookup.

#### Scenario: Look up by declared MD5
- **WHEN** a bounded run searches DAPI for an exact MD5 and the provider returns a post
- **THEN** the result retains the provider post identity, source, declared MD5, uploader, and
  availability as evidence and lands as pending review material, never as a conclusion

#### Scenario: Unsupported strategy is excluded without a request
- **WHEN** planning requests a strategy gelbooru does not declare (external post ID, artist
  name, alias, or free text)
- **THEN** the plan reports it as unsupported and no provider request is made

#### Scenario: Missing credentials fail before transport
- **WHEN** a lookup execution is attempted without DAPI credentials
- **THEN** the attempt fails closed with a credential diagnostic and no provider contact

#### Scenario: Full page continues under bounds
- **WHEN** a lookup page returns a full result set
- **THEN** the run may continue at the next pid boundary under its admitted limits and stops
  cleanly when a budget is reached

## MODIFIED Requirements

### Requirement: Normalization preserves only evidenced Gelbooru facts
The adapter SHALL retain stable post ID, observation time, availability, source, uploader role,
rating, score, declared MD5, dimensions, returned media representations, title, parent post
references as directional relations, tag spelling, and tag category evidence only when supplied
and validated by the selected transport's versioned fixture contract. DAPI detail requests
SHALL request typed tag info, and when the response supplies it, tags SHALL normalize under
the neutral categories (`tag`→general, `metadata`→meta, other documented type names
passthrough, anything else unknown). It MUST NOT derive absent media URLs, infer creator
identity from uploader or tags, or interpret undocumented native fields as reviewed
relationships.

#### Scenario: DAPI returns original and preview URLs
- **WHEN** a post response supplies validated original, sample, or preview locations
- **THEN** named metadata-only variants retain those returned locations while the original MD5 remains a provider declaration

#### Scenario: HTML exposes categorized tags
- **WHEN** a post page supplies fixture-proven artist, character, copyright, or general category markers
- **THEN** the normalized tag observations retain those native categories and their raw HTML provenance

#### Scenario: DAPI supplies uncategorized tag text
- **WHEN** a DAPI post supplies tag names without a proven category mapping
- **THEN** the tags remain recoverable with native category unknown rather than being guessed from undocumented numeric conventions

#### Scenario: DAPI detail supplies typed tag info
- **WHEN** a DAPI detail response carries `tag_info` entries with string types
- **THEN** each tag normalizes under its neutral category (`tag`→general, `metadata`→meta,
  undocumented type names stay unknown) while listings without tag info keep flat unknown tags

#### Scenario: Post references a parent
- **WHEN** a DAPI post record carries a parent post ID
- **THEN** the catalog retains one directional parent relation to that stable post reference
  without labeling their visual variation type

#### Scenario: Post carries a title
- **WHEN** a DAPI post record supplies a title string
- **THEN** the post projection retains it as metadata alongside its raw provenance
