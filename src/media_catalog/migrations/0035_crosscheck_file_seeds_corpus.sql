-- File-seeds corpus for whole-catalog cross-check (bead
-- data-processing-0ui, change add-crosscheck-file-seeds-corpus): widen
-- crosscheck_batches.corpus to admit 'file-seeds' so bare-file discovery
-- seeds batch cross-check exactly like post corpora.  Items already accept
-- seed_kind 'file' (0034).  CHECK widening follows the 0031 rebuild
-- convention; the migration runner disables foreign keys for the script, and
-- the table keeps its name, so the crosscheck_items reference is untouched.
-- Replay-safe: the rebuilt table is created IF NOT EXISTS and repopulated
-- from the live table.

CREATE TABLE IF NOT EXISTS crosscheck_batches_rebuilt (
    crosscheck_batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_key TEXT NOT NULL
        UNIQUE
        CHECK (length(batch_key) BETWEEN 8 AND 300),
    corpus TEXT NOT NULL
        CHECK (corpus IN ('hash-material', 'downloaded', 'file-seeds', 'all')),
    providers TEXT NOT NULL CHECK (length(providers) BETWEEN 1 AND 300),
    recheck TEXT NOT NULL
        CHECK (recheck IN ('unsearched', 'stale', 'force')),
    started_at TEXT NOT NULL,
    stopped_at TEXT,
    stopped_reason TEXT
        CHECK (stopped_reason IS NULL OR length(stopped_reason) <= 100)
);

INSERT INTO crosscheck_batches_rebuilt
    SELECT crosscheck_batch_id, batch_key, corpus, providers, recheck,
           started_at, stopped_at, stopped_reason
      FROM crosscheck_batches;

DROP TABLE crosscheck_batches;
ALTER TABLE crosscheck_batches_rebuilt RENAME TO crosscheck_batches;
