## ADDED requirements

### Requirement: Sankaku md5 lookup rides the bounded keyset listing path

The adapter SHALL accept `DECLARED_MD5` and `VERIFIED_MD5` lookup requests and
execute them as the provider's `tags=md5:<32-hex>` query on the authorized
keyset post-listing path under the shared bounded-run contract, retaining the
keyset continuation when the provider supplies one. Lookup responses SHALL
normalize through the same captured post contract as other Sankaku post
surfaces, and request identities SHALL carry no credential or token
material.

#### Scenario: md5 lookup hits

- **WHEN** a lookup request carries a declared or verified MD5 and the
  provider returns a matching post
- **THEN** the response is retained as a raw observation and normalized to
  one post result carrying the provider's declared MD5 and source evidence

#### Scenario: md5 lookup misses

- **WHEN** the provider returns an empty page for the md5 query
- **THEN** the lookup completes with zero results and no error outcome

#### Scenario: md5 material is validated before any request

- **WHEN** a lookup query material reaches the adapter
- **THEN** its value is exactly 32 lowercase hexadecimal characters per the
  shared query-material contract, and unsupported strategies are refused
  without contacting the provider

#### Scenario: Credentials are absent

- **WHEN** either Sankaku credential is unresolved at lookup time
- **THEN** the lookup fails before network access with bounded configuration
  guidance and no secret value
