## Why

`media_catalog.records` and `CatalogWriter` have accumulated unrelated discovery, metadata,
storage, acquisition, lookup, and library-expansion responsibilities in two oversized modules.
Their size now obscures ownership and makes otherwise bounded changes harder to review without
providing any useful integration boundary.

## What Changes

- Organize persistence record types into cohesive domain modules behind the existing
  `media_catalog.records` import surface.
- Extract cohesive SQL-writing responsibilities into internal persistence components behind the
  existing `CatalogWriter` facade.
- Centralize only genuinely shared validation and connection helpers.
- Preserve current record validation, writer method signatures, transaction ownership, SQL
  behavior, identifiers, errors, and public imports.
- Add compatibility and transaction-characterization coverage before moving implementations.
- Make no schema, CLI, network, or catalog behavior changes.

## Capabilities

This is a behavior-preserving implementation refactor. It introduces no new capability and changes
no existing capability requirement, so this change opts out of delta specs.

## Impact

The change affects `src/media_catalog/records.py`, `src/media_catalog/writer.py`, their importers,
and new internal record and persistence packages. Existing callers continue to import records from
`media_catalog.records` and construct and call `CatalogWriter` as before. Database migrations and
stored catalog formats are unaffected.
