# Spec Delta

## MODIFIED Requirements

### Requirement: Parse typed platform references
The system SHALL use versioned recognizers to parse supported canonical URLs into a
platform, object kind, identifier kind, identifier, and canonical target URL without
treating a booru artist record, uploader account, post, or artwork as interchangeable
object kinds. The recognizer host table SHALL cover every platform the catalog
registers: the danbooru family (danbooru, aibooru), the e621 family (e621, e926),
the gelbooru query-grammar family (gelbooru, safebooru, rule34 — each resolving to
its own canonical host), sankaku (opaque post identifiers, both the canonical and
chan hosts), and pawchive (service-scoped creator post routes). Recognizer coverage
SHALL not lag the platform registry: a registered platform's stable post URL SHALL
recognize.

#### Scenario: Recognize a Pixiv user URL
- **WHEN** a canonical URL contains a supported Pixiv user path with a stable numeric identifier
- **THEN** discovery records a Pixiv account reference using that stable identifier

#### Scenario: Recognize a Pixiv artwork URL
- **WHEN** a canonical URL contains a supported Pixiv artwork path with a stable numeric identifier
- **THEN** discovery records a Pixiv post reference separately from any account reference

#### Scenario: Recognize a mutable X handle
- **WHEN** a canonical URL identifies an X account only by its handle
- **THEN** discovery records a handle-kind account reference that remains ineligible for identity
  matching or account materialization until a stable provider account ID is known

#### Scenario: Recognize a Danbooru-family object
- **WHEN** a canonical URL identifies a supported Danbooru-family post or artist record
- **THEN** discovery retains the specific instance, object kind, and stable identifier or artist name available in the URL

#### Scenario: Recognize legacy and query-style booru post routes
- **WHEN** a URL identifies a post through a supported `/post/show/<id>` route or a Gelbooru-style `page=post`, `s=view`, and `id=<id>` query
- **THEN** discovery records an instance-qualified post reference while retaining the original route and query

#### Scenario: Recognize a Mastodon-compatible status
- **WHEN** a URL contains a supported instance-qualified `/@account/<status-id>` route
- **THEN** discovery records a status/post reference for that instance without assuming the display handle is its stable account ID

#### Scenario: Recognize every registered platform's post URL
- **WHEN** a URL is the stable post URL of any registered platform (aibooru, e926,
  rule34, safebooru, sankaku, pawchive included)
- **THEN** the recognizer resolves the platform, a stable post identifier, and that
  platform's canonical target URL
