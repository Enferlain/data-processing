## 1. Spec validation

- [x] 1.1 Run `openspec validate add-provenance-kernel-spec --strict` and fix any findings so
  every requirement parses with its scenarios and the Purpose section is present
- [x] 1.2 Cross-check each of the twelve requirements against the verified mapping in
  `docs/plans/provenance-kernel.md` section 2; correct the mapping (docs only) if any requirement
  and mapping row disagree, and record the check result in Bead `data-processing-u1d` notes

## 2. Persistence boundary move (Bead `data-processing-v4i`)

- [x] 2.1 Move the `adoption_items` read from the CatalogWriter facade into the StorageWrites
  persistence component, preserving caller behavior and transaction ownership, and verify
  `uv run pytest tests/test_catalog_writer.py tests/test_asset_adoption.py tests/test_asset_storage.py`
  passes
- [x] 2.2 Update facade re-exports and callers for the moved read and verify
  `uv run ty check src` and `uv run ruff check .` pass unchanged

## 3. Records vocabulary colocation (Bead `data-processing-ee0`)

- [x] 3.1 Colocate single-family vocabularies and validators with their record family modules in
  `media_catalog.records` (acquisition, library minus the cross-family origin pair, lookup, and
  storage/adoption), keeping the facade re-export surface identical — verified by the full gate
  suite in 3.2, since no records-named test modules exist
- [x] 3.2 Run the full gates — `uv run pytest`, `uv run ruff check .`, `uv run ty check src` —
  and confirm they pass with no new exclusions

## 4. Close-out

- [ ] 4.1 Add a `CHANGELOG.md` entry under the current date covering the new capability spec and
  the two boundary moves, following the file's concision rules
- [x] 4.2 Close Beads `data-processing-v4i` and `data-processing-ee0`, and update
  `data-processing-u1d` notes to record the spec change implemented
- [x] 4.3 Sync the delta spec into the main specs and archive this change via the OpenSpec
  archive workflow after review, verifying `openspec list` shows no active change afterwards
