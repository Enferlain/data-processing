## ADDED requirements

### Requirement: Sharkgone registers as a Danbooru-family instance with artist surfaces omitted

The adapter SHALL serve the registered `sharkgone` instance (canonical
HTTPS base `booru.sharkgone.com`, schema `sharkgone-json-v1`, external
credential references only) through the shared Danbooru-family adapter,
declaring the non-artist post lookup strategies and omitting artist
strategies and attribution enumeration while the provider's artists endpoint
is empty. The instance SHALL participate in the family's cross-search
surfaces as an independent source — never as routing or failover for
danbooru — with its own pacing floor and replay-seeded platform row.

#### Scenario: md5 cross-search targets sharkgone

- **WHEN** `catalog crosscheck --provider sharkgone` runs over md5-bearing
  subjects
- **THEN** a sharkgone lane issues bounded `tags=md5:<hash>` queries under
  the shared family adapter and records item outcomes like every provider

#### Scenario: artist strategies are excluded

- **WHEN** a lookup plan requests an artist strategy against sharkgone
- **THEN** planning excludes it with a stable reason and no request is made

#### Scenario: sharkgone links and seeds recognize

- **WHEN** a `booru.sharkgone.com/posts/<id>` URL is recognized in material
- **THEN** it yields a stable sharkgone post reference usable as a lookup
  seed
