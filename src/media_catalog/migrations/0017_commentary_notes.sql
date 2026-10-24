-- Commentary and notes enrichment (Bead data-processing-vus): opt-in
-- bounded fetches for post-attached text -- danbooru-family artist
-- commentary and gelbooru/e621 overlay notes.  Observations are
-- append-only and digest-deduplicated over the text facts: unchanged
-- re-observation is idempotent; any text, position, or version change
-- lands as a new observation.  The three remote-operation tables are
-- rebuilt again to extend the operation vocabulary (the 0010/0016 idiom).
-- ---------------------------------------------------------------------------
-- Operation vocabulary: fetch_pool
-- ---------------------------------------------------------------------------
-- SQLite cannot alter a CHECK constraint in place, so rebuild the three
-- remote operation tables while preserving every row id and all existing
-- relationships (the migration engine runs this script with foreign-key
-- enforcement disabled, then validates the complete catalog before
-- committing the version bump) -- the same idiom migration 0010 used to add
-- the tag operations.

DROP TRIGGER IF EXISTS library_expansion_execution_origin_matches;
DROP TRIGGER IF EXISTS library_expansion_execution_lineage_matches;

CREATE TABLE remote_runs_rebuilt (
    remote_run_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL CHECK (operation IN (
        'fetch_account', 'fetch_post', 'list_account_posts', 'fetch_attribution',
        'fetch_tag', 'fetch_tag_alias', 'fetch_pool', 'fetch_commentary',
        'fetch_notes'
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
    transport_key TEXT
    CHECK (transport_key IS NULL OR length(transport_key) BETWEEN 1 AND 200),
    transport_version TEXT
    CHECK (
        transport_version IS NULL
        OR length(transport_version) BETWEEN 1 AND 200
    ),
    CHECK ((transport_key IS NULL) = (transport_version IS NULL)),
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
    started_at, finished_at, origin_kind, origin_reference, transport_key,
    transport_version
)
SELECT remote_run_id, platform_id, instance_host, operation, target, adapter_version,
       schema_version, resumed_from_run_id, status, request_budget, page_budget,
       record_budget, time_budget_seconds, request_count, page_count, record_count,
       termination_outcome, budget_boundary, retry_after, diagnostic_summary,
       started_at, finished_at, origin_kind, origin_reference, transport_key,
       transport_version
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

CREATE TRIGGER remote_runs_origin_consistent
BEFORE INSERT ON remote_runs
WHEN (NEW.origin_kind IS NULL) != (NEW.origin_reference IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'remote run origin kind and reference must be supplied together');
END;

CREATE TRIGGER remote_runs_origin_kind_vocabulary
BEFORE INSERT ON remote_runs
WHEN NEW.origin_kind IS NOT NULL AND NEW.origin_kind NOT IN ('library_expansion', 'reprocess')
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

CREATE TRIGGER remote_runs_immutable_inputs
BEFORE UPDATE ON remote_runs
WHEN NEW.platform_id IS NOT OLD.platform_id
  OR NEW.instance_host IS NOT OLD.instance_host
  OR NEW.operation IS NOT OLD.operation
  OR NEW.target IS NOT OLD.target
  OR NEW.adapter_version IS NOT OLD.adapter_version
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.request_budget IS NOT OLD.request_budget
  OR NEW.page_budget IS NOT OLD.page_budget
  OR NEW.record_budget IS NOT OLD.record_budget
  OR NEW.time_budget_seconds IS NOT OLD.time_budget_seconds
  OR NEW.started_at IS NOT OLD.started_at
  OR NEW.resumed_from_run_id IS NOT OLD.resumed_from_run_id
  OR NEW.transport_key IS NOT OLD.transport_key
  OR NEW.transport_version IS NOT OLD.transport_version
  OR NEW.remote_run_id IS NOT OLD.remote_run_id
BEGIN
    SELECT RAISE(ABORT, 'remote run inputs are immutable');
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
        'fetch_tag', 'fetch_tag_alias', 'fetch_pool', 'fetch_commentary',
        'fetch_notes'
    )),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 500),
    continuation_adapter TEXT NOT NULL CHECK (length(continuation_adapter) BETWEEN 1 AND 200),
    continuation_version TEXT NOT NULL CHECK (length(continuation_version) BETWEEN 1 AND 200),
    continuation_json TEXT NOT NULL,
    last_page_identity TEXT,
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    committed_at TEXT NOT NULL,
    transport_key TEXT
    CHECK (transport_key IS NULL OR length(transport_key) BETWEEN 1 AND 200),
    transport_version TEXT
    CHECK (
        transport_version IS NULL
        OR length(transport_version) BETWEEN 1 AND 200
    ),
    CHECK ((transport_key IS NULL) = (transport_version IS NULL)),
    UNIQUE (remote_run_id, operation, target)
);

INSERT INTO remote_checkpoints_rebuilt (
    remote_checkpoint_id, remote_run_id, operation, target, continuation_adapter,
    continuation_version, continuation_json, last_page_identity, page_count,
    committed_at, transport_key, transport_version
)
SELECT remote_checkpoint_id, remote_run_id, operation, target, continuation_adapter,
       continuation_version, continuation_json, last_page_identity, page_count,
       committed_at, transport_key, transport_version
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
        'fetch_tag', 'fetch_tag_alias', 'fetch_pool', 'fetch_commentary',
        'fetch_notes'
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
    transport_key TEXT
    CHECK (transport_key IS NULL OR length(transport_key) BETWEEN 1 AND 200),
    transport_version TEXT
    CHECK (
        transport_version IS NULL
        OR length(transport_version) BETWEEN 1 AND 200
    ),
    CHECK ((transport_key IS NULL) = (transport_version IS NULL)),
    UNIQUE (remote_run_id, attempt_number)
);

INSERT INTO remote_requests_rebuilt (
    remote_request_id, remote_run_id, attempt_number, request_identity, operation,
    target, status_code, outcome, retry_after, rate_limit_state,
    response_adapter_version, response_schema_version, object_kind, native_id,
    media_type, response_size, raw_observation_id, remote_checkpoint_id,
    request_started_at, response_observed_at, request_finished_at, transport_key,
    transport_version
)
SELECT remote_request_id, remote_run_id, attempt_number, request_identity, operation,
       target, status_code, outcome, retry_after, rate_limit_state,
       response_adapter_version, response_schema_version, object_kind, native_id,
       media_type, response_size, raw_observation_id, remote_checkpoint_id,
       request_started_at, response_observed_at, request_finished_at, transport_key,
       transport_version
FROM remote_requests;

DROP TABLE remote_requests;
ALTER TABLE remote_requests_rebuilt RENAME TO remote_requests;

CREATE INDEX remote_requests_run_idx ON remote_requests(remote_run_id, attempt_number);
CREATE INDEX remote_requests_outcome_idx ON remote_requests(outcome);
CREATE INDEX remote_requests_raw_observation_idx
    ON remote_requests(raw_observation_id);

CREATE TRIGGER remote_requests_immutable_fields
BEFORE UPDATE ON remote_requests
WHEN NEW.remote_run_id IS NOT OLD.remote_run_id
  OR NEW.attempt_number IS NOT OLD.attempt_number
  OR NEW.request_identity IS NOT OLD.request_identity
  OR NEW.operation IS NOT OLD.operation
  OR NEW.target IS NOT OLD.target
  OR NEW.status_code IS NOT OLD.status_code
  OR NEW.outcome IS NOT OLD.outcome
  OR NEW.retry_after IS NOT OLD.retry_after
  OR NEW.rate_limit_state IS NOT OLD.rate_limit_state
  OR NEW.response_adapter_version IS NOT OLD.response_adapter_version
  OR NEW.response_schema_version IS NOT OLD.response_schema_version
  OR NEW.object_kind IS NOT OLD.object_kind
  OR NEW.native_id IS NOT OLD.native_id
  OR NEW.media_type IS NOT OLD.media_type
  OR NEW.response_size IS NOT OLD.response_size
  OR NEW.remote_checkpoint_id IS NOT OLD.remote_checkpoint_id
  OR NEW.request_started_at IS NOT OLD.request_started_at
  OR NEW.response_observed_at IS NOT OLD.response_observed_at
  OR NEW.request_finished_at IS NOT OLD.request_finished_at
  OR NEW.transport_key IS NOT OLD.transport_key
  OR NEW.transport_version IS NOT OLD.transport_version
  OR NEW.remote_request_id IS NOT OLD.remote_request_id
  OR (NEW.raw_observation_id IS NOT OLD.raw_observation_id
      AND OLD.raw_observation_id IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'remote request fields are immutable');
END;

CREATE TRIGGER remote_requests_no_delete
BEFORE DELETE ON remote_requests
BEGIN
    SELECT RAISE(ABORT, 'remote requests cannot be deleted');
END;


-- ---------------------------------------------------------------------------
-- Commentary and note observations
-- ---------------------------------------------------------------------------

CREATE TABLE post_commentary_observations (
    post_commentary_observation_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    original_title TEXT,
    original_description TEXT,
    translated_title TEXT,
    translated_description TEXT,
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (post_id, observation_digest)
);

CREATE INDEX post_commentary_observations_post_idx
    ON post_commentary_observations(post_id, observed_at);

CREATE TABLE post_note_observations (
    post_note_observation_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    note_native_id TEXT NOT NULL CHECK (length(note_native_id) BETWEEN 1 AND 100),
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 10000),
    position_x INTEGER,
    position_y INTEGER,
    width INTEGER,
    height INTEGER,
    version INTEGER,
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (post_id, note_native_id, observation_digest)
);

CREATE INDEX post_note_observations_post_idx
    ON post_note_observations(post_id, observed_at);

CREATE TRIGGER post_commentary_observations_no_update
    BEFORE UPDATE ON post_commentary_observations
BEGIN
    SELECT RAISE(ABORT, 'post commentary observations are append-only');
END;

CREATE TRIGGER post_commentary_observations_no_delete
    BEFORE DELETE ON post_commentary_observations
BEGIN
    SELECT RAISE(ABORT, 'post commentary observations are append-only');
END;

CREATE TRIGGER post_note_observations_no_update
    BEFORE UPDATE ON post_note_observations
BEGIN
    SELECT RAISE(ABORT, 'post note observations are append-only');
END;

CREATE TRIGGER post_note_observations_no_delete
    BEFORE DELETE ON post_note_observations
BEGIN
    SELECT RAISE(ABORT, 'post note observations are append-only');
END;
