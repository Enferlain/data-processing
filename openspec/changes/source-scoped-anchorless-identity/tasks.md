# Tasks: source-scoped-anchorless-identity

## 1. Identity and storage

- [ ] 1.1 Migration `0019_source_scoped_anchorless_identity.sql`: drop the two 0018 partial unique indexes; create platform-scoped replacements (same WHERE clauses), documenting the source-in-identity rationale
- [ ] 1.2 `store_raw` (`src/media_catalog/persistence/remote.py`): anchorless conflict targets and resolve-back SELECT include `platform_id`; anchorless retention without a declared platform raises
- [ ] 1.3 Policy comments blessing intra-source sharing at `candidate_lookup/service.py` `_retain_response` and `library/probes.py` `probe`

## 2. Repair script

- [ ] 2.1 `scripts/repair_anchorless_observations.py`: dry-run default; discover 0018-definition duplicate groups; keep earliest; dynamically discover referencing tables/columns; re-point referencing rows (update-trigger drop/recreate from stored SQL); delete unreferenced members (immutability-trigger drop/recreate); one transaction on `--apply`; `foreign_key_check` + zero-group verification; report same-platform vs cross-platform folds separately

## 3. Tests and validation

- [ ] 3.1 `tests/test_catalog_writer.py`: two platforms with identical bytes → two observations with own attribution; same-platform re-intake → one shared row; anchorless without platform refused
- [ ] 3.2 `tests/test_repair_anchorless.py`: fixture catalogs covering unreferenced fold, referenced fold (re-point), cross-platform group (untouched by 0019 identity, folded by repair under 0018 with separate reporting); plan mode touches nothing; apply leaves zero groups under both definitions and restores triggers
- [ ] 3.3 Prove the chain on a copy of the real catalog: repair (plan then apply) → migrate through 0019 → counts and FK check
- [ ] 3.4 Gates green; `openspec validate`; subagent review; CHANGELOG

## 4. Closeout

- [ ] 4.1 Archive the change, commit, push, close `data-processing-7o0` with the blessing + repair decision recorded
