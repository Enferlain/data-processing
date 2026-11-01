# Tasks

- [x] 1. Live-capture the three operation contracts anonymously (profile, listing page,
      post detail) plus the media-host and creators-dump probes that decide D3 and the
      non-goals.
- [x] 2. Adapter package: config (single-instance registry, policy floors, 4 MiB
      ceiling) + transport (`Accept: text/css`, offset-in-request-target paging) +
      normalization (flat detail, string ids, name+path occurrences, thumbnail variant,
      expiring-URL elision, brace tags).
- [x] 3. Kernel + persistence: `SOURCE_OPERATIONS` gains `pawchive`; migration `0023`
      seeds the platform row; platform-count pins updated (11 → 12).
- [x] 4. CLI: `pawchive-profile`, `pawchive-post`, `pawchive-list`; offline replay and
      reprocess provider choices resolve the instance.
- [x] 5. Fixture suite `pawchive.json` (three captured cases; manifest records the
      oversized-page evidence) and `tests/test_pawchive_adapter.py` (registry policy,
      captured contracts, continuation roll-forward, wire targets, tags parsing).
- [x] 6. Gates: ruff, format, ty, full pytest; reviewer pass; changelog; bead close and
      archive.
