-- Unified discovery orchestration (Bead data-processing-v28, change
-- add-discovery-orchestration; roadmap docs/plans/priority.md P0.1).  Sessions
-- bind existing machinery (seed stub posts, candidate lookup runs, assets);
-- they record identity, steps, statuses, and linkage only -- no parallel
-- facts, evidence, or candidates.

CREATE TABLE IF NOT EXISTS discovery_sessions (
    discovery_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_kind TEXT NOT NULL,
    seed_post_id INTEGER,
    seed_account_id INTEGER,
    input_digest TEXT,
    live_authorized INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'planning',
    step_count INTEGER NOT NULL DEFAULT 0,
    request_budget INTEGER,
    time_budget_seconds INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (seed_post_id) REFERENCES posts(post_id),
    FOREIGN KEY (seed_account_id) REFERENCES accounts(account_id)
);

CREATE TABLE IF NOT EXISTS discovery_steps (
    discovery_step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovery_session_id INTEGER NOT NULL,
    step_order INTEGER NOT NULL,
    source_kind TEXT NOT NULL,
    source TEXT NOT NULL,
    method TEXT NOT NULL,
    status TEXT NOT NULL,
    outcome TEXT,
    result_count INTEGER,
    detail TEXT,
    candidate_lookup_run_id INTEGER,
    FOREIGN KEY (discovery_session_id)
        REFERENCES discovery_sessions(discovery_session_id),
    FOREIGN KEY (candidate_lookup_run_id)
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id)
);

CREATE INDEX IF NOT EXISTS idx_discovery_steps_session
    ON discovery_steps(discovery_session_id, step_order);
