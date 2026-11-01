# Tasks

- [x] 1. `media_catalog.doctor`: registration table (11 surfaces), offline replay engine
      with the D1 comparator, report model, live probe engine with per-family credential
      policy.
- [x] 2. CLI: `doctor` subcommand with `--live`, `--platform`, `--json`; nonzero exit on
      any failure; secrets never rendered.
- [x] 3. Tests: full offline replay over the committed suites green; drift detection
      (wrong expected outcome, stale manifest version, wrong platform attribution) via
      in-memory cases; live probe OK/typed-failure/skip paths over MockTransport; CLI
      surface and exit codes.
- [x] 4. Gates: ruff, format, ty, full pytest; reviewer pass; changelog; bead close and
      archive.
