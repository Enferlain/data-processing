# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Sub agent usage

Sub agents are enabled by default for research and implementation in this repo, use them as per the instructions. If there are no instructions, ask the user.

## Python Quality Gates

Use the project environment through `uv`.

### Tests

```bash
# Full suite
uv run pytest

# Focused file
uv run pytest tests/test_example.py
```

### Linting and formatting

```bash
# Required repository lint gate
uv run ruff check .

# Apply safe lint fixes
uv run ruff check . --fix

# Format files changed by the current task
uv run ruff format path/to/file.py tests/test_file.py

# Verify formatting for changed files
uv run ruff format --check path/to/file.py tests/test_file.py
```

Ruff targets Python 3.13, enforces absolute imports across parent-package boundaries, and excludes
the vendored `src/xarchive/vendor` subtree. Preserve the repository's 100-character line length and
import-sorting rules rather than copying formatting assumptions from adjacent projects.

### Type checking

```bash
# Required blocking first-party source gate
uv run ty check src

# Focused package or file; use the normal exit status for work in that scope
uv run ty check src/media_catalog
uv run ty check src/media_catalog/cli.py
```

ty targets Python 3.13 and excludes vendored xarchive code. The repository-wide command is a
required quality gate. Do not add blanket ignores or lower rule severities to make a task appear
green.

## Changelog

Update `CHANGELOG.md` after every completed unit of work, including internal refactors and
documentation changes. Add entries under today's date using the file's existing "Added",
"Changed", "Removed", and "Fixed" subtitles and follow its concision rules.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
