## 1. Shared occurrence interpretation

- [x] 1.1 Extract or expose a pure validated occurrence-variant resolver shared by acquisition planning and media browsing, preserving existing plan identities, eligibility, malformed-input handling, and selected-URL secrecy.
- [x] 1.2 Add characterization tests proving browsing and `plan_acquisition` report identical variant keys, policy identities, eligibility, exclusion reasons, and satisfied asset IDs for primary, preview, original, Pixiv multi-page/Ugoira, booru, unsupported, malformed, and ambiguous cases.

## 2. Read-only media queries

- [x] 2.1 Implement bounded keyset-paginated occurrence listing with stable ordering and validated platform, author, post, availability, and linked/unlinked filters.
- [x] 2.2 Implement occurrence detail with stable post/account participation, named acquisition variants, distinct declared facts, linked verified asset facts, and bounded source-provenance classifications.
- [x] 2.3 Add a public `MediaQueryService` facade and path/open-database entry points that use the current-schema read-only boundary and never migrate, create layout, or issue network requests.
- [x] 2.4 Add query tests for pagination without overlap, every filter and filter combination, multi-author/multi-asset/source cardinality, missing records, unavailable/unlinked records, malformed variants, deterministic related ordering, and bounded collection truncation.
- [x] 2.5 Add adversarial output tests proving signed media URLs, URL hosts, raw payloads, request data, managed roots, relative/absolute legacy paths, credentials, and staging/quarantine names never appear in list, detail, exceptions, or serialized output.

## 3. CLI and documentation

- [x] 3.1 Add `catalog media list` and `catalog media show` parsers and execution paths with validated filters, positive capped limits, continuation input, stable JSON, bounded errors, and successful inspection of unavailable or unlinked occurrences.
- [x] 3.2 Add CLI tests with networking disabled and catalog/filesystem snapshots proving browsing is read-only, redacted, deterministic, and emits selections accepted unchanged by `catalog assets download-plan`.
- [x] 3.3 Extend the catalog usage guide with metadata-to-media browsing examples, filter/reference syntax, pagination, declared-versus-verified interpretation, redaction boundaries, and the explicit handoff to acquisition planning.

## 4. Verification

- [x] 4.1 Run focused query/planning/CLI tests, the full offline suite, Ruff, `git diff --check`, and strict OpenSpec validation; request review-mcp, address actionable findings, and rerun affected gates.
