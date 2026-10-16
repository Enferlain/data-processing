## 1. Seeder extension

- [x] 1.1 Add the `parent_of` seed pass over `post_relations` (post↔post, `observed`,
      provider-declaration evidence with the raw observation linked when present,
      deterministic-key idempotency, skip reporting for unusable endpoints); verify with a
      fixture test that a parent relation materializes once with evidence and re-seeding
      reports it as existing
- [x] 1.2 Update the guide's seeding description and record the change in `CHANGELOG.md`;
      run the full gates (`uv run ruff check .`, `uv run ruff format --check`,
      `uv run ty check src`, `uv run pytest`)
