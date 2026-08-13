-- Extend the closed remote-operation vocabulary for provider attribution metadata.
-- SQLite cannot alter a CHECK constraint in place, so rebuild the three remote
-- operation tables while preserving every row id and all existing relationships.
-- The migration engine runs this script with foreign-key enforcement disabled,
-- then validates the complete catalog before committing the version bump.

-- ---------------------------------------------------------------------------
-- remote_runs
-- ---------------------------------------------------------------------------

-- These expansion guards refer to remote_runs by name.  Temporarily remove
-- them while the referenced table is rebuilt; they are recreated below with
-- the same predicates and failure messages.
DROP TRIGGER IF EXISTS library_expansion_execution_origin_matches;
DROP TRIGGER IF EXISTS library_expansion_execution_lineage_matches;

CREATE TABLE remote_runs_rebuilt (
    remote_run_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL CHECK (operation IN (
        'fetch_account', 'fetch_post', 'list_account_posts', 'fetch_attribution',
        'fetch_tag', 'fetch_tag_alias'
    )),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 500),
    adapter_version TEXT NOT NULL CHECK (length(adapter_version) BETWEEN 1 AND 200),
    schema_version TEXT NOT NULL CHECK (length(schema_version) BETWEEN 1 AND 200),
    resumed_from_run_id INTEGER REFERENCES remote_runs_rebuilt(remote_run_id),
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN (
        'running', 'complete', 'paused', 'failed'
    )),
    request_budget INTEGER NOT NULL CHECK (request_budget > 0),
    page_budget INTEGER NOT NULL CHECK (page_budget > 0),
    record_budget INTEGER NOT NULL CHECK (record_budget > 0),
    time_budget_seconds INTEGER NOT NULL CHECK (time_budget_seconds > 0),
    request_count INTEGER NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    record_count INTEGER NOT NULL DEFAULT 0 CHECK (record_count >= 0),
    termination_outcome TEXT CHECK (
        termination_outcome IS NULL OR termination_outcome IN (
            'success', 'unavailable', 'deleted', 'authentication_required',
            'authorization_denied', 'rate_limited', 'transient_provider',
            'malformed_response', 'budget_exhausted', 'local_persistence'
        )
    ),
    budget_boundary TEXT CHECK (
        budget_boundary IS NULL OR budget_boundary IN ('request', 'page', 'record', 'time')
    ),
    retry_after TEXT,
    diagnostic_summary TEXT CHECK (
        diagnostic_summary IS NULL OR length(diagnostic_summary) <= 1000
    ),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    origin_kind TEXT,
    origin_reference TEXT COLLATE NOCASE,
    CHECK (
        budget_boundary IS NULL
        OR termination_outcome IS NOT NULL
    ),
    CHECK (
        termination_outcome IS NULL
        OR status IN ('complete', 'paused', 'failed')
    )
);

INSERT INTO remote_runs_rebuilt (
    remote_run_id, platform_id, instance_host, operation, target, adapter_version,
    schema_version, resumed_from_run_id, status, request_budget, page_budget,
    record_budget, time_budget_seconds, request_count, page_count, record_count,
    termination_outcome, budget_boundary, retry_after, diagnostic_summary,
    started_at, finished_at, origin_kind, origin_reference
)
SELECT remote_run_id, platform_id, instance_host, operation, target, adapter_version,
       schema_version, resumed_from_run_id, status, request_budget, page_budget,
       record_budget, time_budget_seconds, request_count, page_count, record_count,
       termination_outcome, budget_boundary, retry_after, diagnostic_summary,
       started_at, finished_at, origin_kind, origin_reference
FROM remote_runs;

DROP TABLE remote_runs;
ALTER TABLE remote_runs_rebuilt RENAME TO remote_runs;

CREATE INDEX remote_runs_platform_idx
    ON remote_runs(platform_id, instance_host, operation, status);
CREATE INDEX remote_runs_resumed_idx ON remote_runs(resumed_from_run_id);
CREATE INDEX remote_runs_status_idx ON remote_runs(status, started_at);
CREATE INDEX remote_runs_origin_idx
    ON remote_runs(origin_kind, origin_reference)
    WHERE origin_kind IS NOT NULL;

-- Recreate the origin invariants from migration 0008 after rebuilding the table.
CREATE TRIGGER remote_runs_origin_consistent
BEFORE INSERT ON remote_runs
WHEN (NEW.origin_kind IS NULL) != (NEW.origin_reference IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'remote run origin kind and reference must be supplied together');
END;

CREATE TRIGGER remote_runs_origin_kind_vocabulary
BEFORE INSERT ON remote_runs
WHEN NEW.origin_kind IS NOT NULL AND NEW.origin_kind NOT IN ('library_expansion')
BEGIN
    SELECT RAISE(ABORT, 'unsupported remote run origin kind');
END;

CREATE TRIGGER remote_runs_origin_reference_length
BEFORE INSERT ON remote_runs
WHEN NEW.origin_reference IS NOT NULL AND length(NEW.origin_reference) != 64
BEGIN
    SELECT RAISE(ABORT, 'remote run origin reference must be 64 characters');
END;

CREATE TRIGGER remote_runs_origin_immutable
BEFORE UPDATE ON remote_runs
WHEN NEW.origin_kind IS NOT OLD.origin_kind
  OR NEW.origin_reference IS NOT OLD.origin_reference
BEGIN
    SELECT RAISE(ABORT, 'remote run origin is immutable');
END;

CREATE TRIGGER library_expansion_execution_origin_matches
BEFORE INSERT ON library_expansion_executions
WHEN NOT EXISTS (
    SELECT 1
      FROM library_expansion_plans plan
      JOIN remote_runs run ON run.remote_run_id = NEW.remote_run_id
     WHERE plan.library_expansion_plan_id = NEW.library_expansion_plan_id
       AND run.origin_kind = 'library_expansion'
       AND run.origin_reference = plan.plan_digest
)
BEGIN
    SELECT RAISE(ABORT, 'library expansion remote run origin does not match its plan');
END;

CREATE TRIGGER library_expansion_execution_lineage_matches
BEFORE INSERT ON library_expansion_executions
WHEN (
    (NEW.execution_kind = 'initial' AND (
        SELECT resumed_from_run_id FROM remote_runs WHERE remote_run_id = NEW.remote_run_id
    ) IS NOT NULL)
    OR (NEW.execution_kind = 'resume' AND NOT EXISTS (
        SELECT 1
          FROM library_expansion_executions predecessor
          JOIN remote_runs run ON run.remote_run_id = NEW.remote_run_id
         WHERE predecessor.library_expansion_execution_id = NEW.predecessor_execution_id
           AND predecessor.library_expansion_plan_id = NEW.library_expansion_plan_id
           AND run.resumed_from_run_id = predecessor.remote_run_id
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'library expansion execution lineage is incompatible');
END;

-- ---------------------------------------------------------------------------
-- remote_checkpoints
-- ---------------------------------------------------------------------------

CREATE TABLE remote_checkpoints_rebuilt (
    remote_checkpoint_id INTEGER PRIMARY KEY,
    remote_run_id INTEGER NOT NULL REFERENCES remote_runs(remote_run_id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (operation IN (
        'fetch_account', 'fetch_post', 'list_account_posts', 'fetch_attribution',
        'fetch_tag', 'fetch_tag_alias'
    )),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 500),
    continuation_adapter TEXT NOT NULL CHECK (length(continuation_adapter) BETWEEN 1 AND 200),
    continuation_version TEXT NOT NULL CHECK (length(continuation_version) BETWEEN 1 AND 200),
    continuation_json TEXT NOT NULL,
    last_page_identity TEXT,
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    committed_at TEXT NOT NULL,
    UNIQUE (remote_run_id, operation, target)
);

INSERT INTO remote_checkpoints_rebuilt (
    remote_checkpoint_id, remote_run_id, operation, target, continuation_adapter,
    continuation_version, continuation_json, last_page_identity, page_count, committed_at
)
SELECT remote_checkpoint_id, remote_run_id, operation, target, continuation_adapter,
       continuation_version, continuation_json, last_page_identity, page_count, committed_at
FROM remote_checkpoints;

DROP TABLE remote_checkpoints;
ALTER TABLE remote_checkpoints_rebuilt RENAME TO remote_checkpoints;

CREATE INDEX remote_checkpoints_run_idx
    ON remote_checkpoints(remote_run_id, remote_checkpoint_id);

-- ---------------------------------------------------------------------------
-- remote_requests
-- ---------------------------------------------------------------------------

CREATE TABLE remote_requests_rebuilt (
    remote_request_id INTEGER PRIMARY KEY,
    remote_run_id INTEGER NOT NULL REFERENCES remote_runs(remote_run_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    request_identity TEXT NOT NULL CHECK (length(request_identity) BETWEEN 1 AND 1000),
    operation TEXT NOT NULL CHECK (operation IN (
        'fetch_account', 'fetch_post', 'list_account_posts', 'fetch_attribution',
        'fetch_tag', 'fetch_tag_alias'
    )),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 500),
    status_code INTEGER CHECK (status_code IS NULL OR status_code BETWEEN 100 AND 599),
    outcome TEXT NOT NULL CHECK (outcome IN (
        'success', 'unavailable', 'deleted', 'authentication_required',
        'authorization_denied', 'rate_limited', 'transient_provider',
        'malformed_response', 'budget_exhausted', 'local_persistence'
    )),
    retry_after TEXT,
    rate_limit_state TEXT,
    response_adapter_version TEXT CHECK (
        response_adapter_version IS NULL OR length(response_adapter_version) BETWEEN 1 AND 200
    ),
    response_schema_version TEXT CHECK (
        response_schema_version IS NULL OR length(response_schema_version) BETWEEN 1 AND 200
    ),
    object_kind TEXT,
    native_id TEXT,
    media_type TEXT,
    response_size INTEGER CHECK (response_size IS NULL OR response_size >= 0),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    remote_checkpoint_id INTEGER REFERENCES remote_checkpoints(remote_checkpoint_id),
    request_started_at TEXT NOT NULL,
    response_observed_at TEXT,
    request_finished_at TEXT,
    UNIQUE (remote_run_id, attempt_number)
);

INSERT INTO remote_requests_rebuilt (
    remote_request_id, remote_run_id, attempt_number, request_identity, operation,
    target, status_code, outcome, retry_after, rate_limit_state,
    response_adapter_version, response_schema_version, object_kind, native_id,
    media_type, response_size, raw_observation_id, remote_checkpoint_id,
    request_started_at, response_observed_at, request_finished_at
)
SELECT remote_request_id, remote_run_id, attempt_number, request_identity, operation,
       target, status_code, outcome, retry_after, rate_limit_state,
       response_adapter_version, response_schema_version, object_kind, native_id,
       media_type, response_size, raw_observation_id, remote_checkpoint_id,
       request_started_at, response_observed_at, request_finished_at
FROM remote_requests;

DROP TABLE remote_requests;
ALTER TABLE remote_requests_rebuilt RENAME TO remote_requests;

CREATE INDEX remote_requests_run_idx ON remote_requests(remote_run_id, attempt_number);
CREATE INDEX remote_requests_outcome_idx ON remote_requests(outcome);
CREATE INDEX remote_requests_raw_observation_idx
    ON remote_requests(raw_observation_id);
