# Tasks

- [x] 1. e926 instance: `E926` constant + `E621_INSTANCES` registry in the e621 config;
      export from the adapter package.
- [x] 2. e926 fixture: redacted live capture of post 6823045 as
      `tests/fixtures/metadata_adapters/e926.json` (envelope format, `e926-json-v1`),
      loaded through `load_fixture_suite`.
- [x] 3. e926 tests: family registry/policy pins, captured-contract normalization under
      the e926 identity, anonymous wire request targeting `e926.net`.
- [x] 4. rule34 instance: `RULE34` constant in `GELBOORU_INSTANCES` (dapi base
      `api.rule34.xxx`, credentials required, `RULE34_USER_ID`/`RULE34_API_KEY` envs,
      `rule34-json-v1` after capture).
- [x] 5. rule34 fixture: redacted live capture (post + notes as the bytes are served)
      under the maintainer-supplied key.
- [x] 6. rule34 tests: registry membership, credential-required policy, captured-contract
      normalization, credentialed wire request keeping secrets out of identities.
- [x] 7. Kernel + persistence: `SOURCE_OPERATIONS` gains `e926` and `rule34`; migration
      `0022` seeds both platform rows; count pins updated (platforms 9 → 11).
- [x] 8. CLI: e621 surfaces gain explicit `--instance e621|e926`; gelbooru-family
      instance choices gain `rule34`.
- [x] 9. Gates: ruff, format, ty, full pytest; reviewer pass; changelog; bead close and
      archive.
