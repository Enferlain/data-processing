# Tasks: danbooru bootstrap index

## 1. Importer

- [x] 1.1 `importers/danbooru_parquet.py`: pyarrow row-group streaming,
      `.as_py()` scalar conversion, proven URL extraction + canonicalization,
      `is_deleted OR is_banned` fold, capabilities incl. artist names,
      scope-aware revision, columns_absent reporting, atomic swap.
- [x] 1.2 CLI: `--provider danbooru --artifact` (choices extended); target
      `danbooru`, default path `<catalog-stem>-indexes/danbooru/lookup.sqlite`.

## 2. Verification

- [x] 2.1 Fixture test (synthetic parquet): artists present, x-status
      canonicalization applies, deleted fold, capabilities recorded.
- [x] 2.2 Real-artifact shakeout: head-5000 import verified (3.7 s, artists
      populated, capabilities in index_meta; caught the pyarrow scalar
      `__index__`-on-None crash, fixed via `.as_py()`).
- [x] 2.3 Full real import (11,740,666 rows, 43 min, integrity ok, 6.0 GB)
      + registration; review findings fixed (--download/--export rejected for
      danbooru with clear errors; whitespace-only source normalized).
- [x] 2.4 Coverage: grabber file-seed md5s hit danbooru 16,163/24,160
      (66.9%) vs 12.9% on e621; e621-miss subjects resolved 12/40 offline
      (matching the live crosscheck), 28 both-miss.
- [x] 2.5 Docs + CHANGELOG (real numbers recorded).
