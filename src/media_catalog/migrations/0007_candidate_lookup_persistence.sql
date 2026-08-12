-- Bounded candidate-lookup persistence is additive.  Existing import runs,
-- accounts, posts, media occurrences, raw payloads, discovery candidates, and
-- remote metadata/acquisition tables keep their ids, constraints, and behavior.
--
-- One lookup run covers one seed (account or post), one provider instance, and
-- one lookup strategy.  A multi-strategy request is a bounded batch of
-- independent runs.  Dedicated tables preserve domain constraints without
-- weakening the closed metadata operation vocabulary encoded on remote_runs.
-- Lookup raw-observation provenance lives on the lookup request and result
-- rather than extending the shared raw_observations columns, so existing remote
-- persistence is untouched.

-- ---------------------------------------------------------------------------
-- Durable lookup runs
-- ---------------------------------------------------------------------------

CREATE TABLE candidate_lookup_runs (
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
    seed_revision TEXT NOT NULL CHECK (length(seed_revision) BETWEEN 1 AND 200),
    plan_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(plan_digest) = 64),
    query_kind TEXT NOT NULL CHECK (length(query_kind) BETWEEN 1 AND 200),
    material_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(material_digest) = 64),
    private_query_json TEXT NOT NULL,
    predecessor_run_id INTEGER REFERENCES candidate_lookup_runs(candidate_lookup_run_id),
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
    -- exactly one subject endpoint seeds a lookup run
    CHECK (
        (seed_account_id IS NOT NULL AND seed_post_id IS NULL)
        OR (seed_account_id IS NULL AND seed_post_id IS NOT NULL)
    ),
    -- a budget boundary is only meaningful once the run has terminated
    CHECK (
        budget_boundary IS NULL OR termination_outcome IS NOT NULL
    ),
    -- a termination outcome is only recorded for a non-running run
    CHECK (
        termination_outcome IS NULL OR status IN ('complete', 'paused', 'failed')
    ),
    -- a finished run carries a finish timestamp; a running run does not
    CHECK (
        (status = 'running' AND finished_at IS NULL)
        OR (status != 'running' AND finished_at IS NOT NULL)
    )
);

CREATE INDEX candidate_lookup_runs_provider_idx
    ON candidate_lookup_runs(platform_id, instance_host, strategy, status);
CREATE INDEX candidate_lookup_runs_predecessor_idx
    ON candidate_lookup_runs(predecessor_run_id);
CREATE INDEX candidate_lookup_runs_status_idx
    ON candidate_lookup_runs(status, started_at, candidate_lookup_run_id);
CREATE INDEX candidate_lookup_runs_seed_account_idx
    ON candidate_lookup_runs(seed_account_id)
    WHERE seed_account_id IS NOT NULL;
CREATE INDEX candidate_lookup_runs_seed_post_idx
    ON candidate_lookup_runs(seed_post_id)
    WHERE seed_post_id IS NOT NULL;

-- Immutable run inputs: seed, strategy, digests, private query material,
-- predecessor, limits, and start time can never change after the run begins.
-- Counters, state, outcome, retry time, diagnostic, and finish time advance.
CREATE TRIGGER candidate_lookup_runs_immutable_inputs
BEFORE UPDATE ON candidate_lookup_runs
WHEN NEW.platform_id IS NOT OLD.platform_id
  OR NEW.instance_host IS NOT OLD.instance_host
  OR NEW.strategy IS NOT OLD.strategy
  OR NEW.strategy_version IS NOT OLD.strategy_version
  OR NEW.adapter_version IS NOT OLD.adapter_version
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.seed_account_id IS NOT OLD.seed_account_id
  OR NEW.seed_post_id IS NOT OLD.seed_post_id
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

-- ---------------------------------------------------------------------------
-- Resumable checkpoints (one committed continuation per run)
-- ---------------------------------------------------------------------------

CREATE TABLE candidate_lookup_checkpoints (
    candidate_lookup_checkpoint_id INTEGER PRIMARY KEY,
    candidate_lookup_run_id INTEGER NOT NULL
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id) ON DELETE CASCADE,
    continuation_adapter TEXT NOT NULL CHECK (length(continuation_adapter) BETWEEN 1 AND 200),
    continuation_version TEXT NOT NULL CHECK (length(continuation_version) BETWEEN 1 AND 200),
    continuation_json TEXT NOT NULL,
    last_page_identity TEXT,
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    result_count INTEGER NOT NULL DEFAULT 0 CHECK (result_count >= 0),
    committed_at TEXT NOT NULL,
    UNIQUE (candidate_lookup_run_id)
);

CREATE INDEX candidate_lookup_checkpoints_run_idx
    ON candidate_lookup_checkpoints(candidate_lookup_run_id);

-- ---------------------------------------------------------------------------
-- Sanitized lookup requests (one attempt identity per run/attempt)
-- ---------------------------------------------------------------------------

CREATE TABLE candidate_lookup_requests (
    candidate_lookup_request_id INTEGER PRIMARY KEY,
    candidate_lookup_run_id INTEGER NOT NULL
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    request_identity TEXT NOT NULL CHECK (length(request_identity) BETWEEN 1 AND 1000),
    state TEXT NOT NULL CHECK (state IN ('running', 'complete', 'failed')),
    outcome TEXT CHECK (
        outcome IS NULL OR outcome IN (
            'success', 'unavailable', 'deleted', 'authentication_required',
            'authorization_denied', 'rate_limited', 'transient_provider',
            'malformed_response', 'budget_exhausted', 'local_persistence'
        )
    ),
    status_code INTEGER CHECK (status_code IS NULL OR status_code BETWEEN 100 AND 599),
    retry_after TEXT,
    response_size INTEGER CHECK (response_size IS NULL OR response_size >= 0),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    candidate_lookup_checkpoint_id INTEGER
        REFERENCES candidate_lookup_checkpoints(candidate_lookup_checkpoint_id),
    started_at TEXT NOT NULL,
    observed_at TEXT,
    finished_at TEXT,
    CHECK (
        (state = 'running' AND outcome IS NULL AND finished_at IS NULL)
        OR (state != 'running' AND outcome IS NOT NULL AND finished_at IS NOT NULL)
    ),
    UNIQUE (candidate_lookup_run_id, attempt_number)
);

CREATE INDEX candidate_lookup_requests_run_idx
    ON candidate_lookup_requests(candidate_lookup_run_id, attempt_number);
CREATE INDEX candidate_lookup_requests_outcome_idx
    ON candidate_lookup_requests(state, outcome);
CREATE INDEX candidate_lookup_requests_raw_observation_idx
    ON candidate_lookup_requests(raw_observation_id)
    WHERE raw_observation_id IS NOT NULL;

-- A terminal request is an immutable audit record; only a running request may
-- advance toward its terminal state.
CREATE TRIGGER candidate_lookup_requests_terminal_immutable
BEFORE UPDATE ON candidate_lookup_requests
WHEN OLD.state != 'running'
BEGIN
    SELECT RAISE(ABORT, 'terminal candidate lookup requests are immutable');
END;

-- ---------------------------------------------------------------------------
-- Typed, idempotent lookup results
-- ---------------------------------------------------------------------------

CREATE TABLE candidate_lookup_results (
    candidate_lookup_result_id INTEGER PRIMARY KEY,
    candidate_lookup_run_id INTEGER NOT NULL
        REFERENCES candidate_lookup_runs(candidate_lookup_run_id) ON DELETE CASCADE,
    result_kind TEXT NOT NULL CHECK (result_kind IN (
        'post_match', 'account_match', 'attribution', 'weak_lead', 'inconclusive'
    )),
    result_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(result_digest) = 64),
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    result_order INTEGER NOT NULL CHECK (result_order >= 0),
    normalized_post_id INTEGER REFERENCES posts(post_id),
    attribution_entity_id INTEGER REFERENCES attribution_entities(attribution_entity_id),
    platform_reference_id INTEGER REFERENCES platform_references(platform_reference_id),
    post_candidate_id INTEGER REFERENCES post_match_candidates(post_candidate_id),
    account_candidate_id INTEGER REFERENCES account_match_candidates(account_candidate_id),
    match_evidence_id INTEGER REFERENCES match_evidence(evidence_id),
    raw_observation_id INTEGER NOT NULL REFERENCES raw_observations(raw_observation_id),
    normalized_name TEXT CHECK (normalized_name IS NULL OR length(normalized_name) BETWEEN 1 AND 500),
    match_mode TEXT CHECK (
        match_mode IS NULL OR match_mode IN (
            'exact', 'alias', 'handle', 'display_name', 'text'
        )
    ),
    explanation TEXT CHECK (explanation IS NULL OR length(explanation) <= 1000),
    observed_at TEXT NOT NULL,
    UNIQUE (candidate_lookup_run_id, result_digest),
    -- each typed reference is only populated for its governing result kind
    CHECK (normalized_post_id IS NULL OR result_kind = 'post_match'),
    CHECK (platform_reference_id IS NULL OR result_kind = 'account_match'),
    CHECK (attribution_entity_id IS NULL OR result_kind IN ('attribution', 'weak_lead')),
    CHECK (post_candidate_id IS NULL OR result_kind = 'post_match'),
    CHECK (account_candidate_id IS NULL OR result_kind = 'account_match'),
    CHECK (match_evidence_id IS NULL OR result_kind IN ('post_match', 'account_match')),
    CHECK (normalized_name IS NULL OR result_kind = 'weak_lead'),
    CHECK (match_mode IS NULL OR result_kind = 'weak_lead'),
    -- and each kind requires its governing reference to be present
    CHECK (result_kind != 'post_match' OR normalized_post_id IS NOT NULL),
    CHECK (result_kind != 'account_match' OR platform_reference_id IS NOT NULL),
    CHECK (result_kind != 'attribution' OR attribution_entity_id IS NOT NULL),
    CHECK (
        result_kind != 'weak_lead'
        OR (normalized_name IS NOT NULL AND match_mode IS NOT NULL)
    )
);

CREATE INDEX candidate_lookup_results_run_order_idx
    ON candidate_lookup_results(candidate_lookup_run_id, page_number, result_order);
CREATE INDEX candidate_lookup_results_post_idx
    ON candidate_lookup_results(normalized_post_id)
    WHERE normalized_post_id IS NOT NULL;
CREATE INDEX candidate_lookup_results_attribution_idx
    ON candidate_lookup_results(attribution_entity_id)
    WHERE attribution_entity_id IS NOT NULL;
CREATE INDEX candidate_lookup_results_evidence_idx
    ON candidate_lookup_results(match_evidence_id)
    WHERE match_evidence_id IS NOT NULL;
CREATE INDEX candidate_lookup_results_candidates_idx
    ON candidate_lookup_results(post_candidate_id, account_candidate_id)
    WHERE post_candidate_id IS NOT NULL OR account_candidate_id IS NOT NULL;
