## 1. Compatibility Baseline

- [x] 1.1 Add characterization tests for the public `media_catalog.records` names, record constructor signatures, and `CatalogWriter` public method signatures.
- [x] 1.2 Add a transaction test proving writes delegated across persistence domains share the caller's connection and roll back atomically without component commits.
- [x] 1.3 Confirm repository serialization and reflection dependencies, documenting any module-path compatibility that must be preserved.

## 2. Record Organization

- [x] 2.1 Convert `media_catalog.records` to a package without changing its public imports, validation behavior, or exported names.
- [x] 2.2 Extract shared primitive validators and closed vocabularies into `records.common`, preserving exception types and messages.
- [x] 2.3 Extract discovery and core catalog record families into cohesive modules with explicit compatibility re-exports.
- [x] 2.4 Extract remote-sync and normalized metadata record families into cohesive modules with explicit compatibility re-exports.
- [x] 2.5 Extract managed-storage and adoption record families into cohesive modules with explicit compatibility re-exports.
- [x] 2.6 Extract acquisition, candidate-lookup, and library-expansion record families into cohesive modules with explicit compatibility re-exports.
- [x] 2.7 Verify import compatibility, annotations, dataclass fields, defaults, frozen behavior, and validation across every record family.

## 3. Writer Organization

- [x] 3.1 Add the internal `media_catalog.persistence` package and shared connection/result helpers without changing transaction ownership.
- [x] 3.2 Extract adoption and managed-storage SQL writes behind explicit `CatalogWriter` delegation.
- [x] 3.3 Extract acquisition SQL writes behind explicit `CatalogWriter` delegation.
- [x] 3.4 Extract candidate-lookup and library-expansion SQL writes behind explicit `CatalogWriter` delegation.
- [x] 3.5 Extract remote-run, request, checkpoint, and raw-observation SQL writes behind explicit `CatalogWriter` delegation.
- [x] 3.6 Extract tag, attribution, post-fact, and external-reference SQL writes behind explicit `CatalogWriter` delegation.
- [x] 3.7 Extract discovery, account, post, observation, relation, media, and asset-link SQL writes behind explicit `CatalogWriter` delegation.
- [x] 3.8 Remove only helpers proven unused after extraction and keep `writer.py` as the stable public facade.

## 4. Verification and Documentation

- [x] 4.1 Run focused domain tests after each extraction and verify SQLite rollback, idempotency, ID preservation, and error compatibility.
- [x] 4.2 Update architecture-facing documentation and the changelog with the new internal ownership boundaries and compatibility policy.
- [x] 4.3 Run changed-file formatting, repository Ruff, `ty`, full pytest, `git diff --check`, and strict OpenSpec validation.
- [x] 4.4 Request bounded review for the record split and each writer extraction section, address actionable findings, and confirm the final facade remains behavior-compatible.
