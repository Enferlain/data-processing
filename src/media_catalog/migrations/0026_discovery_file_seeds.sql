-- Discovery file seeds: intrinsic verified identity for a local file with
-- no known remote source (bead data-processing-b8n, change
-- add-local-file-discovery-root).  A file seed deliberately has no posts row
-- and no platform identity; a remote post appears only when a provider hit
-- is fetched and persisted.
--
-- Every statement is replay-safe (a catalog created at this schema and
-- rewound below it must migrate cleanly again, per the repair-fixture
-- convention in 0024): tables use IF NOT EXISTS, altered tables are rebuilt
-- with copy/drop/rename, and triggers and indexes use IF [NOT] EXISTS.

CREATE TABLE IF NOT EXISTS discovery_file_seeds (
    discovery_file_seed_id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovery_session_id INTEGER NOT NULL
        REFERENCES discovery_sessions(discovery_session_id),
    verified_md5 TEXT NOT NULL,
    verified_sha256 TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    mime_type TEXT,
    byte_size INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    note TEXT,
    observed_at TEXT NOT NULL
);

-- discovery_sessions gains the file-seed reference column.
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
    started_at TEXT NOT NULL,
    finished_at TEXT,
    time_budget_seconds INTEGER,
    search_term TEXT,
    FOREIGN KEY (seed_post_id) REFERENCES posts(post_id),
    FOREIGN KEY (seed_account_id) REFERENCES accounts(account_id)
);

INSERT INTO discovery_sessions_rebuilt
    SELECT discovery_session_id, input_kind, seed_post_id, seed_account_id,
           NULL, input_digest, live_authorized, status, step_count,
           request_budget, started_at, finished_at, time_budget_seconds,
           search_term
      FROM discovery_sessions;

DROP TABLE discovery_sessions;
ALTER TABLE discovery_sessions_rebuilt RENAME TO discovery_sessions;

-- discovery_steps gains the generation, target, and follow-up seed columns:
-- generation 0 = seed/local + first provider hop, 1 = follow-up from hits;
-- target is the normalized subject that step-identity dedupe keys on
-- alongside (source, method); seed_post_id names the fetched post a
-- follow-up lookup's material came from (NULL on first-hop steps).
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
    FOREIGN KEY (discovery_session_id)
        REFERENCES discovery_sessions(discovery_session_id),
    FOREIGN KEY (candidate_lookup_run_id)
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id)
);

INSERT INTO discovery_steps_rebuilt
    SELECT discovery_step_id, discovery_session_id, step_order, source_kind,
           source, method, status, outcome, result_count, detail,
           candidate_lookup_run_id, 0, NULL, NULL
      FROM discovery_steps;

DROP TABLE discovery_steps;
ALTER TABLE discovery_steps_rebuilt RENAME TO discovery_steps;

CREATE INDEX IF NOT EXISTS idx_discovery_steps_session
    ON discovery_steps(discovery_session_id, step_order);

-- A lookup run seeded by a bare local file carries the file seed id.  The
-- exactly-one-seed CHECK cannot be ALTERed, so the table is rebuilt with the
-- constraint widened to three seed kinds (0025 precedent).
CREATE TABLE IF NOT EXISTS candidate_lookup_runs_rebuilt (
    candidate_lookup_run_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    strategy TEXT NOT NULL CHECK (strategy IN (
        'source_post_url', 'external_post_id', 'declared_md5', 'verified_md5',
        'artist_exact_name', 'artist_alias', 'artist_text'
    )),
    strategy_version TEXT NOT NULL CHECK (length(strategy_version) BETWEEN 1 AND 200),
    adapter_version TEXT NOT NULL CHECK (length(adapter_version) BETWEEN 1 AND 200),
    schema_version TEXT NOT NULL CHECK (length(schema_version) BETWEEN 1 AND 200),
    seed_account_id INTEGER REFERENCES accounts(account_id),
    seed_post_id INTEGER REFERENCES posts(post_id),
    seed_file_id INTEGER REFERENCES discovery_file_seeds(discovery_file_seed_id),
    seed_revision TEXT NOT NULL CHECK (length(seed_revision) BETWEEN 1 AND 200),
    plan_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(plan_digest) = 64),
    query_kind TEXT NOT NULL CHECK (length(query_kind) BETWEEN 1 AND 200),
    material_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(material_digest) = 64),
    private_query_json TEXT NOT NULL,
    predecessor_run_id INTEGER REFERENCES candidate_lookup_runs_rebuilt(candidate_lookup_run_id),
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN (
        'running', 'complete', 'paused', 'failed'
    )),
    request_limit INTEGER NOT NULL CHECK (request_limit > 0),
    page_limit INTEGER NOT NULL CHECK (page_limit > 0),
    result_limit INTEGER NOT NULL CHECK (result_limit > 0),
    time_limit_seconds INTEGER NOT NULL CHECK (time_limit_seconds > 0),
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    termination_outcome TEXT CHECK (
        termination_outcome IS NULL OR termination_outcome IN (
            'success', 'unavailable', 'deleted', 'authentication_required',
            'authorization_denied', 'rate_limited', 'transient_provider',
            'malformed_response', 'budget_exhausted', 'local_persistence'
        )
    ),
    budget_boundary TEXT CHECK (
        budget_boundary IS NULL OR budget_boundary IN ('request', 'page', 'result', 'time')
    ),
    retry_after TEXT,
    diagnostic_summary TEXT CHECK (
        diagnostic_summary IS NULL OR length(diagnostic_summary) <= 1000
    ),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    -- exactly one subject endpoint seeds a lookup run; a bare local file
    -- is a third seed kind with no account, post, or platform identity
    CHECK (
        (seed_account_id IS NOT NULL AND seed_post_id IS NULL AND seed_file_id IS NULL)
        OR (seed_account_id IS NULL AND seed_post_id IS NOT NULL AND seed_file_id IS NULL)
        OR (seed_account_id IS NULL AND seed_post_id IS NULL AND seed_file_id IS NOT NULL)
    ),
    CHECK (
        budget_boundary IS NULL OR termination_outcome IS NOT NULL
    ),
    CHECK (
        termination_outcome IS NULL OR status IN ('complete', 'paused', 'failed')
    ),
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status != 'running' AND finished_at IS NOT NULL)
    )
);

-- The pre-0026 table has no seed_file_id; real catalogs apply this exactly
-- once (user_version), and the replay fixtures carry no file-seed data.
INSERT INTO candidate_lookup_runs_rebuilt
    SELECT candidate_lookup_run_id, platform_id, instance_host, strategy,
           strategy_version, adapter_version, schema_version, seed_account_id,
           seed_post_id, NULL, seed_revision, plan_digest, query_kind,
           material_digest, private_query_json, predecessor_run_id, status,
           request_limit, page_limit, result_limit, time_limit_seconds,
           request_count, page_count, result_count, termination_outcome,
           budget_boundary, retry_after, diagnostic_summary, started_at,
           finished_at
      FROM candidate_lookup_runs;

DROP TRIGGER IF EXISTS candidate_lookup_runs_immutable_inputs;
DROP TABLE candidate_lookup_runs;
ALTER TABLE candidate_lookup_runs_rebuilt RENAME TO candidate_lookup_runs;

CREATE TRIGGER candidate_lookup_runs_immutable_inputs
BEFORE UPDATE ON candidate_lookup_runs
WHEN NEW.candidate_lookup_run_id IS NOT OLD.candidate_lookup_run_id
  OR NEW.platform_id IS NOT OLD.platform_id
  OR NEW.instance_host IS NOT OLD.instance_host
  OR NEW.strategy IS NOT OLD.strategy
  OR NEW.strategy_version IS NOT OLD.strategy_version
  OR NEW.adapter_version IS NOT OLD.adapter_version
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.seed_account_id IS NOT OLD.seed_account_id
  OR NEW.seed_post_id IS NOT OLD.seed_post_id
  OR NEW.seed_file_id IS NOT OLD.seed_file_id
  OR NEW.seed_revision IS NOT OLD.seed_revision
  OR NEW.plan_digest IS NOT OLD.plan_digest
  OR NEW.query_kind IS NOT OLD.query_kind
  OR NEW.material_digest IS NOT OLD.material_digest
  OR NEW.private_query_json IS NOT OLD.private_query_json
  OR NEW.predecessor_run_id IS NOT OLD.predecessor_run_id
  OR NEW.request_limit IS NOT OLD.request_limit
  OR NEW.page_limit IS NOT OLD.page_limit
  OR NEW.result_limit IS NOT OLD.result_limit
  OR NEW.time_limit_seconds IS NOT OLD.time_limit_seconds
  OR NEW.started_at IS NOT OLD.started_at
BEGIN
    SELECT RAISE(ABORT, 'candidate lookup run inputs are immutable');
END;

CREATE INDEX IF NOT EXISTS candidate_lookup_runs_provider_idx
    ON candidate_lookup_runs(platform_id, instance_host, strategy, status);
CREATE INDEX IF NOT EXISTS candidate_lookup_runs_predecessor_idx
    ON candidate_lookup_runs(predecessor_run_id);
CREATE INDEX IF NOT EXISTS candidate_lookup_runs_status_idx
    ON candidate_lookup_runs(status, started_at, candidate_lookup_run_id);
CREATE INDEX IF NOT EXISTS candidate_lookup_runs_seed_account_idx
    ON candidate_lookup_runs(seed_account_id)
    WHERE seed_account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS candidate_lookup_runs_seed_post_idx
    ON candidate_lookup_runs(seed_post_id)
    WHERE seed_post_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS candidate_lookup_runs_seed_file_idx
    ON candidate_lookup_runs(seed_file_id)
    WHERE seed_file_id IS NOT NULL;
