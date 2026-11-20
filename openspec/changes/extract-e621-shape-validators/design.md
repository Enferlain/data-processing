# Design

## Context

`adapters/e621/adapter.py` held the `E621Adapter` class (lines 109–1395) plus
fourteen module-level validators/renderers after it (1398–1606) and their two
length constants. Nothing outside the module referenced the helpers (verified
by grep across `src/` and `tests/` before the move).

## Decision

One new sibling module, `shapes.py`, mirroring the gelbooru package layout.
Pure move with an explicit re-import in `adapter.py`; no re-export from
`adapters/e621/__init__.py` because nothing external used the helpers (adding a
public surface for moved private names would be new API, not a refactor).

Constants `_MAX_TARGET_LENGTH` / `_MAX_LOOKUP_TEXT` move with the only code
that reads them; both remain module-private to `shapes.py`. `adapter.py` drops
the imports that only the moved code used (`mimetypes`, `recognize_url`,
`LookupQueryMaterial`).

## Risks

None beyond mechanical: identical bodies, unchanged call sites, existing e621
suites (lookup + adapter) exercise every validator through real adapter paths.
