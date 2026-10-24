# Tasks: add-commentary-and-notes

## 1. Vocabulary and storage

- [ ] 1.1 Add `fetch_commentary` and `fetch_notes` to `AdapterOperation` and `REMOTE_OPERATIONS`
- [ ] 1.2 Migration `0017_commentary_notes.sql`: the two append-only observation tables with digest dedup and immutability triggers, plus the three remote-operation table rebuilds extending the vocabulary (0010/0016 idiom)
- [ ] 1.3 Records + persistence + writer facade: `PostCommentaryObservationRecord` and `PostNoteObservationRecord` with fact digests, `record_post_commentary` and `record_post_note` idempotent by digest

## 2. Adapter and enrichment surface

- [ ] 2.1 Adapter request paths: danbooru `FETCH_COMMENTARY` → `/artist_commentaries.json?search[post_id]=N`; e621 `FETCH_NOTES` → `/notes.json?search[post_id]=N`; gelbooru dapi `FETCH_NOTES` → `s=note&q=index&post_id=N&json=1`
- [ ] 2.2 `src/media_catalog/remote_sync/enrichment.py`: shared run-contract flow (run commits first, fetch outside the transaction, raw retained for every response, provider faults end failed, transport errors auditable) with `fetch_commentary` and `fetch_notes`, post resolution refusing unknown native ids
- [ ] 2.3 CLI: `danbooru-commentary` / `aibooru-commentary` / `gelbooru-dapi-notes` / `e621-notes` metadata commands

## 3. Fixtures, tests, docs

- [ ] 3.1 Fixtures: keep the captured danbooru (12436862) and e621 (6623509) documents; write the labeled synthetic gelbooru dapi note fixture
- [ ] 3.2 Tests (`tests/test_commentary_and_notes.py`): commentary lands with both text fields; notes land with position/version; empty results are successful zero-observation runs; unchanged refetch idempotent; text/version change lands new observations; unknown post refused; raw retained including malformed; run status/outcome semantics; immutability triggers; adapter endpoint paths
- [ ] 3.3 Update `tests/test_persistence_compatibility.py` digests, `tests/test_adapter_contracts.py` operation list, `CHANGELOG.md`, `docs/tools/media-catalog.md`

## 4. Validation

- [ ] 4.1 Gates: `uv run ruff check .`, `uv run ruff format --check`, `uv run ty check src`, `uv run pytest`; migration verified lossless against a copy of the real catalog
- [ ] 4.2 `openspec validate add-commentary-and-notes` and a subagent review before committing
