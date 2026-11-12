-- Whole-catalog cross-check (bead data-processing-p1t, change
-- add-catalog-cross-check): durable batch state over the existing candidate
-- lookup runs and checkpoints.  Batches key an invocation chain (corpus +
-- provider set + recheck policy); items record per subject × provider ×
-- strategy outcomes with reasons.  Matches stay candidates: no relationship
-- or pair rows are ever written here.  Replay-safe per the 0024/0026
-- convention.

CREATE TABLE IF NOT EXISTS crosscheck_batches (
    crosscheck_batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_key TEXT NOT NULL
        UNIQUE
        CHECK (length(batch_key) BETWEEN 8 AND 300),
    corpus TEXT NOT NULL
        CHECK (corpus IN ('hash-material', 'downloaded', 'all')),
    providers TEXT NOT NULL CHECK (length(providers) BETWEEN 1 AND 300),
    recheck TEXT NOT NULL
        CHECK (recheck IN ('unsearched', 'stale', 'force')),
    started_at TEXT NOT NULL,
    stopped_at TEXT,
    stopped_reason TEXT
        CHECK (stopped_reason IS NULL OR length(stopped_reason) <= 100)
);

CREATE TABLE IF NOT EXISTS crosscheck_items (
    crosscheck_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crosscheck_batch_id INTEGER NOT NULL
        REFERENCES crosscheck_batches(crosscheck_batch_id) ON DELETE CASCADE,
    seed_kind TEXT NOT NULL CHECK (seed_kind IN ('post', 'file')),
    seed_id INTEGER NOT NULL,
    provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 100),
    strategy TEXT NOT NULL CHECK (length(strategy) BETWEEN 1 AND 100),
    state TEXT NOT NULL
        CHECK (state IN ('pending', 'checked', 'matched', 'skipped', 'failed')),
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 200),
    candidate_lookup_run_id INTEGER
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id),
    matched_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE (
        crosscheck_batch_id, seed_kind, seed_id, provider, strategy
    )
);

-- Resume reads key on the batch; per-item state lookups stay exact.
CREATE INDEX IF NOT EXISTS idx_crosscheck_items_batch
    ON crosscheck_items(crosscheck_batch_id, state);
