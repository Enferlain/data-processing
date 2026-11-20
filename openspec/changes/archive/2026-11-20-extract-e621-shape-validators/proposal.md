# Extract e621 Shape Validators

## What

Move the fourteen module-level shape validators and query-render helpers out of
`src/media_catalog/adapters/e621/adapter.py` (they trailed ~200 lines after the
`E621Adapter` class) into a new sibling module
`src/media_catalog/adapters/e621/shapes.py`. Pure move: function bodies,
docstrings, comments, and the two lookup-bound constants (`_MAX_TARGET_LENGTH`,
`_MAX_LOOKUP_TEXT`) are byte-identical; `adapter.py` imports the names back so
every call site is unchanged.

## Why

The 2026-11-20 file-size survey flagged `adapter.py` (1,606 lines) as the
largest adapter with two clearly different concerns mixed in one file: the
adapter class (transport, pagination, normalization) and the wire-shape
validators it calls. The gelbooru package already establishes the multi-file
convention (`capture.py`, `credentials.py`, `html_adapter.py`, `redaction.py`).
Splitting follows the convention without changing behavior. Tracked as bead
`data-processing-zw3`.

## Scope

In:

- New `src/media_catalog/adapters/e621/shapes.py` with the moved validators.
- `adapter.py` imports them; now-unused imports removed.

Out:

- Any behavior, signature, or naming change (including renames to drop the
  underscore prefix — that would churn call sites for no gain).
- Test changes: the existing e621 suites cover the validators through adapter
  behavior; a pure move adds no new surface to pin.
