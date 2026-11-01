# Tasks

- [x] 1. `link_resolution` module: per-family resolvers, id grammar validation,
      canonical round-trip URLs, actionable errors.
- [x] 2. `catalog fetch` command: resolution → platform adapter factory → metadata
      sync; `--resolve-only`; sync limits; resume; JSON output.
- [x] 3. Pawchive temporal fix: zoneless stamps qualify as UTC (gelbooru
      precedent), pinned by adapter test; live end-to-end fetch verified on e926
      and pawchive against the real catalog.
- [x] 4. Tests: resolution table over every platform's captured post id, variant
      spellings, malformed-input matrix, CLI resolve-only and routed-sync paths.
- [x] 5. Gates: ruff, format, ty, full pytest; reviewer; changelog; bead close and
      archive.
