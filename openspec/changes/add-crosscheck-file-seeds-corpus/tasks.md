# Tasks

- [x] 1. Migration `0035_crosscheck_file_seeds_corpus.sql`: rebuild
  `crosscheck_batches` widening the `corpus` CHECK with `file-seeds`; batches
  preserved; fresh catalogs create the widened shape directly.
  Verify: `uv run pytest tests/test_crosscheck.py -k migration`.
- [x] 2. Corpus wiring: `CORPORA` entry, `select_corpus` file-seeds branch with
  canonical lowest-id-per-hash-pair subjects, CLI `--corpus` help text.
  Verify: `uv run pytest tests/test_crosscheck.py -k "corpus or file_seed"`.
- [x] 3. Batch behavior: file-seed subjects run through the coordinator with
  `file:ID` seeds, verified-md5 material, honest skips for material-less
  strategies, items recorded with seed kind `file`, matches stay candidates.
  Verify: `uv run pytest tests/test_crosscheck.py`.
- [x] 4. Gates and docs: full `uv run pytest`, `uv run ruff check .`, `ruff
  format` on changed files, `uv run ty check src`, CHANGELOG + media-catalog
  docs entry.
