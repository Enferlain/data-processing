-- Discovery search policy stage 1 (bead data-processing-19p, change
-- add-discovery-search-policy): durable cross-session search state.  Attempts
-- are the append-only ledger keyed by subject x search target x method x
-- strategy version x query-evidence digest; sessions gain request accounting
-- and the effective policy snapshot; steps gain their query-evidence digest
-- so planner decisions are comparable across sessions.  Bare file seeds gain
-- a content index so repeat discovery of the same file can reuse the same
-- seed identity (intrinsic verified hashes) instead of creating a new subject.
--
-- Every statement is replay-safe per the 0024/0026 repair-fixture convention:
-- IF NOT EXISTS for new tables and indexes, rebuild for altered tables.

CREATE TABLE IF NOT EXISTS discovery_search_attempts (
    discovery_search_attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_post_id INTEGER REFERENCES posts(post_id),
    subject_account_id INTEGER REFERENCES accounts(account_id),
    subject_file_id INTEGER
        REFERENCES discovery_file_seeds(discovery_file_seed_id),
    source_kind TEXT NOT NULL CHECK (length(source_kind) BETWEEN 1 AND 100),
    source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 100),
    method TEXT NOT NULL CHECK (length(method) BETWEEN 1 AND 100),
    strategy_version TEXT NOT NULL CHECK (length(strategy_version) BETWEEN 1 AND 200),
    query_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(query_digest) = 64),
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
    outcome TEXT CHECK (
        outcome IS NULL OR outcome IN (
            'success', 'unavailable', 'deleted', 'authentication_required',
            'authorization_denied', 'rate_limited', 'transient_provider',
            'malformed_response', 'budget_exhausted', 'local_persistence',
            'error', 'provider_failure'
        )
    ),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    -- the bounded scope that was searched; a zero-result attempt records its
    -- scope here and asserts nothing about what was not searched
    scope TEXT CHECK (scope IS NULL OR length(scope) <= 1000),
    requests_used INTEGER NOT NULL DEFAULT 0 CHECK (requests_used >= 0),
    discovery_session_id INTEGER NOT NULL
        REFERENCES discovery_sessions(discovery_session_id),
    discovery_step_id INTEGER REFERENCES discovery_steps(discovery_step_id),
    candidate_lookup_run_id INTEGER
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    -- exactly one subject endpoint owns an attempt
    CHECK (
        (subject_post_id IS NOT NULL AND subject_account_id IS NULL AND subject_file_id IS NULL)
        OR (subject_post_id IS NULL AND subject_account_id IS NOT NULL AND subject_file_id IS NULL)
        OR (subject_post_id IS NULL AND subject_account_id IS NULL AND subject_file_id IS NOT NULL)
    ),
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status != 'running' AND finished_at IS NOT NULL)
    )
);

DROP TRIGGER IF EXISTS discovery_search_attempts_immutable_inputs;
CREATE TRIGGER discovery_search_attempts_immutable_inputs
BEFORE UPDATE ON discovery_search_attempts
WHEN NEW.discovery_search_attempt_id IS NOT OLD.discovery_search_attempt_id
  OR NEW.subject_post_id IS NOT OLD.subject_post_id
  OR NEW.subject_account_id IS NOT OLD.subject_account_id
  OR NEW.subject_file_id IS NOT OLD.subject_file_id
  OR NEW.source_kind IS NOT OLD.source_kind
  OR NEW.source IS NOT OLD.source
  OR NEW.method IS NOT OLD.method
  OR NEW.strategy_version IS NOT OLD.strategy_version
  OR NEW.query_digest IS NOT OLD.query_digest
  OR NEW.discovery_session_id IS NOT OLD.discovery_session_id
  OR NEW.discovery_step_id IS NOT OLD.discovery_step_id
  OR NEW.started_at IS NOT OLD.started_at
BEGIN
    SELECT RAISE(ABORT, 'discovery search attempt inputs are immutable');
END;

-- latest attempt per (subject, target, method, evidence): the freshness read
CREATE INDEX IF NOT EXISTS idx_discovery_search_attempts_key
    ON discovery_search_attempts(
        subject_post_id, subject_account_id, subject_file_id,
        source_kind, source, method, query_digest,
        discovery_search_attempt_id
    );

-- discovery_steps gains the query-evidence digest the attempt ledger keys on.
CREATE TABLE IF NOT EXISTS discovery_steps_rebuilt (
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
    generation INTEGER NOT NULL DEFAULT 0,
    target TEXT,
    seed_post_id INTEGER REFERENCES posts(post_id),
    query_digest TEXT,
    FOREIGN KEY (discovery_session_id)
        REFERENCES discovery_sessions(discovery_session_id),
    FOREIGN KEY (candidate_lookup_run_id)
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id)
);

INSERT INTO discovery_steps_rebuilt
    SELECT discovery_step_id, discovery_session_id, step_order, source_kind,
           source, method, status, outcome, result_count, detail,
           candidate_lookup_run_id, generation, target, seed_post_id, NULL
      FROM discovery_steps;

DROP TABLE discovery_steps;
ALTER TABLE discovery_steps_rebuilt RENAME TO discovery_steps;

CREATE INDEX IF NOT EXISTS idx_discovery_steps_session
    ON discovery_steps(discovery_session_id, step_order);

-- discovery_sessions gains request accounting and the effective policy that
-- produced its decisions.
CREATE TABLE IF NOT EXISTS discovery_sessions_rebuilt (
    discovery_session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_kind TEXT NOT NULL,
    seed_post_id INTEGER,
    seed_account_id INTEGER,
    seed_file_id INTEGER REFERENCES discovery_file_seeds(discovery_file_seed_id),
    input_digest TEXT,
    live_authorized INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'planning',
    step_count INTEGER NOT NULL DEFAULT 0,
    request_budget INTEGER,
    time_budget_seconds INTEGER,
    search_term TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    requests_used INTEGER NOT NULL DEFAULT 0 CHECK (requests_used >= 0),
    policy_json TEXT,
    FOREIGN KEY (seed_post_id) REFERENCES posts(post_id),
    FOREIGN KEY (seed_account_id) REFERENCES accounts(account_id)
);

INSERT INTO discovery_sessions_rebuilt
    SELECT discovery_session_id, input_kind, seed_post_id, seed_account_id,
           seed_file_id, input_digest, live_authorized, status, step_count,
           request_budget, time_budget_seconds, search_term, started_at,
           finished_at, 0, NULL
      FROM discovery_sessions;

DROP TABLE discovery_sessions;
ALTER TABLE discovery_sessions_rebuilt RENAME TO discovery_sessions;

-- content identity for bare file seeds: repeat discovery of the same bytes
-- reuses the same seed subject.  Not unique -- catalogs predating this
-- change may already hold duplicate rows for one file; lookup takes the
-- lowest id.
CREATE INDEX IF NOT EXISTS idx_discovery_file_seeds_hashes
    ON discovery_file_seeds(verified_md5, verified_sha256);
