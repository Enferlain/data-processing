-- Remote media acquisition is explicit and independent from metadata sync and
-- local-file adoption.  Plans contain stable catalog references and redacted
-- digests only; rendered request URLs and credentials are never persisted here.

CREATE TABLE media_acquisition_plans (
    acquisition_plan_id INTEGER PRIMARY KEY,
    plan_version TEXT NOT NULL CHECK (length(plan_version) BETWEEN 1 AND 200),
    selection_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(selection_digest) = 64),
    requested_count INTEGER NOT NULL CHECK (requested_count >= 0),
    eligible_count INTEGER NOT NULL CHECK (eligible_count >= 0),
    satisfied_count INTEGER NOT NULL CHECK (satisfied_count >= 0),
    excluded_count INTEGER NOT NULL CHECK (excluded_count >= 0),
    created_at TEXT NOT NULL,
    CHECK (eligible_count + satisfied_count + excluded_count = requested_count)
);

CREATE INDEX media_acquisition_plans_created_idx
    ON media_acquisition_plans(created_at, acquisition_plan_id);

CREATE TABLE media_acquisition_plan_items (
    acquisition_plan_item_id INTEGER PRIMARY KEY,
    acquisition_plan_id INTEGER NOT NULL
        REFERENCES media_acquisition_plans(acquisition_plan_id) ON DELETE RESTRICT,
    item_key TEXT NOT NULL CHECK (length(item_key) BETWEEN 1 AND 200),
    media_occurrence_id INTEGER NOT NULL
        REFERENCES media_occurrences(media_occurrence_id) ON DELETE RESTRICT,
    variant_key TEXT NOT NULL CHECK (length(variant_key) BETWEEN 1 AND 500),
    material_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(material_digest) = 64),
    request_policy_key TEXT NOT NULL CHECK (length(request_policy_key) BETWEEN 1 AND 200),
    request_policy_version TEXT NOT NULL CHECK (
        length(request_policy_version) BETWEEN 1 AND 200
    ),
    source_raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    eligibility TEXT NOT NULL CHECK (
        eligibility IN ('eligible', 'already_satisfied', 'excluded')
    ),
    exclusion_reason TEXT CHECK (
        exclusion_reason IS NULL OR length(exclusion_reason) <= 500
    ),
    satisfied_asset_id INTEGER REFERENCES assets(asset_id) ON DELETE RESTRICT,
    declared_sha256 TEXT COLLATE NOCASE CHECK (
        declared_sha256 IS NULL OR length(declared_sha256) = 64
    ),
    declared_md5 TEXT COLLATE NOCASE CHECK (
        declared_md5 IS NULL OR length(declared_md5) = 32
    ),
    declared_file_size INTEGER CHECK (
        declared_file_size IS NULL OR declared_file_size >= 0
    ),
    declared_mime_type TEXT CHECK (
        declared_mime_type IS NULL OR length(declared_mime_type) <= 500
    ),
    declared_width INTEGER CHECK (declared_width IS NULL OR declared_width >= 0),
    declared_height INTEGER CHECK (declared_height IS NULL OR declared_height >= 0),
    created_at TEXT NOT NULL,
    CHECK (
        (eligibility = 'excluded' AND exclusion_reason IS NOT NULL)
        OR (eligibility != 'excluded' AND exclusion_reason IS NULL)
    ),
    CHECK (
        (eligibility = 'already_satisfied' AND satisfied_asset_id IS NOT NULL)
        OR (eligibility != 'already_satisfied' AND satisfied_asset_id IS NULL)
    ),
    UNIQUE (acquisition_plan_id, item_key),
    UNIQUE (acquisition_plan_id, media_occurrence_id, variant_key)
);

CREATE INDEX media_acquisition_plan_items_occurrence_idx
    ON media_acquisition_plan_items(media_occurrence_id, variant_key);
CREATE INDEX media_acquisition_plan_items_eligibility_idx
    ON media_acquisition_plan_items(acquisition_plan_id, eligibility);

CREATE TRIGGER media_acquisition_plans_no_update
BEFORE UPDATE ON media_acquisition_plans
BEGIN
    SELECT RAISE(ABORT, 'media acquisition plans are immutable');
END;

CREATE TRIGGER media_acquisition_plans_no_delete
BEFORE DELETE ON media_acquisition_plans
BEGIN
    SELECT RAISE(ABORT, 'media acquisition plans are immutable');
END;

CREATE TRIGGER media_acquisition_plan_items_no_update
BEFORE UPDATE ON media_acquisition_plan_items
BEGIN
    SELECT RAISE(ABORT, 'media acquisition plan items are immutable');
END;

CREATE TRIGGER media_acquisition_plan_items_no_delete
BEFORE DELETE ON media_acquisition_plan_items
BEGIN
    SELECT RAISE(ABORT, 'media acquisition plan items are immutable');
END;

CREATE TABLE media_acquisition_runs (
    acquisition_run_id INTEGER PRIMARY KEY,
    acquisition_plan_id INTEGER NOT NULL
        REFERENCES media_acquisition_plans(acquisition_plan_id) ON DELETE RESTRICT,
    managed_root_id INTEGER NOT NULL
        REFERENCES managed_roots(managed_root_id) ON DELETE RESTRICT,
    resumed_from_run_id INTEGER REFERENCES media_acquisition_runs(acquisition_run_id),
    status TEXT NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'complete', 'partial', 'failed', 'cancelled')
    ),
    termination_outcome TEXT CHECK (
        termination_outcome IS NULL OR termination_outcome IN (
            'success', 'partial', 'failed', 'cancelled', 'budget_exhausted',
            'interrupted', 'quarantined', 'stale'
        )
    ),
    max_items INTEGER NOT NULL CHECK (max_items > 0),
    max_item_bytes INTEGER NOT NULL CHECK (max_item_bytes > 0),
    max_total_bytes INTEGER NOT NULL CHECK (max_total_bytes > 0),
    max_attempts_per_item INTEGER NOT NULL CHECK (max_attempts_per_item > 0),
    max_seconds INTEGER NOT NULL CHECK (max_seconds > 0),
    max_redirects INTEGER NOT NULL CHECK (max_redirects > 0),
    max_quarantine_bytes INTEGER NOT NULL CHECK (max_quarantine_bytes >= 0),
    concurrency INTEGER NOT NULL CHECK (concurrency > 0),
    planned_count INTEGER NOT NULL DEFAULT 0 CHECK (planned_count >= 0),
    completed_count INTEGER NOT NULL DEFAULT 0 CHECK (completed_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    deferred_count INTEGER NOT NULL DEFAULT 0 CHECK (deferred_count >= 0),
    received_bytes INTEGER NOT NULL DEFAULT 0 CHECK (received_bytes >= 0),
    quarantined_bytes INTEGER NOT NULL DEFAULT 0 CHECK (quarantined_bytes >= 0),
    diagnostic TEXT CHECK (diagnostic IS NULL OR length(diagnostic) <= 1000),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    CHECK (
        (status = 'running' AND termination_outcome IS NULL AND finished_at IS NULL)
        OR (status != 'running' AND termination_outcome IS NOT NULL AND finished_at IS NOT NULL)
    )
);

CREATE INDEX media_acquisition_runs_status_idx
    ON media_acquisition_runs(status, started_at, acquisition_run_id);
CREATE INDEX media_acquisition_runs_plan_idx
    ON media_acquisition_runs(acquisition_plan_id, acquisition_run_id);
CREATE INDEX media_acquisition_runs_resumed_idx
    ON media_acquisition_runs(resumed_from_run_id);

CREATE TRIGGER media_acquisition_runs_immutable_inputs
BEFORE UPDATE ON media_acquisition_runs
WHEN NEW.acquisition_plan_id != OLD.acquisition_plan_id
  OR NEW.managed_root_id != OLD.managed_root_id
  OR NEW.resumed_from_run_id IS NOT OLD.resumed_from_run_id
  OR NEW.max_items != OLD.max_items
  OR NEW.max_item_bytes != OLD.max_item_bytes
  OR NEW.max_total_bytes != OLD.max_total_bytes
  OR NEW.max_attempts_per_item != OLD.max_attempts_per_item
  OR NEW.max_seconds != OLD.max_seconds
  OR NEW.max_redirects != OLD.max_redirects
  OR NEW.max_quarantine_bytes != OLD.max_quarantine_bytes
  OR NEW.concurrency != OLD.concurrency
  OR NEW.started_at != OLD.started_at
BEGIN
    SELECT RAISE(ABORT, 'media acquisition run inputs are immutable');
END;

CREATE TABLE media_acquisition_run_items (
    acquisition_run_item_id INTEGER PRIMARY KEY,
    acquisition_run_id INTEGER NOT NULL
        REFERENCES media_acquisition_runs(acquisition_run_id) ON DELETE RESTRICT,
    acquisition_plan_item_id INTEGER NOT NULL
        REFERENCES media_acquisition_plan_items(acquisition_plan_item_id) ON DELETE RESTRICT,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN (
        'pending', 'running', 'complete', 'failed', 'quarantined', 'stale',
        'deferred', 'interrupted', 'satisfied'
    )),
    outcome TEXT CHECK (
        outcome IS NULL OR outcome IN (
            'downloaded', 'downloaded_exact_only', 'existing', 'already_satisfied',
            'policy_failure', 'authentication_required', 'authorization_denied',
            'unavailable', 'rate_limited', 'transient_provider', 'timeout',
            'response_too_large', 'invalid_content', 'source_changed', 'interrupted',
            'storage_failure', 'hash_mismatch', 'inspection_failure',
            'storage_integrity_failure', 'stale_target', 'budget_exhausted', 'cancelled'
        )
    ),
    retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    received_bytes INTEGER NOT NULL DEFAULT 0 CHECK (received_bytes >= 0),
    asset_id INTEGER REFERENCES assets(asset_id) ON DELETE RESTRICT,
    sha256 TEXT COLLATE NOCASE CHECK (sha256 IS NULL OR length(sha256) = 64),
    md5 TEXT COLLATE NOCASE CHECK (md5 IS NULL OR length(md5) = 32),
    diagnostic TEXT CHECK (diagnostic IS NULL OR length(diagnostic) <= 1000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (state IN ('pending', 'running') AND outcome IS NULL)
        OR (state NOT IN ('pending', 'running') AND outcome IS NOT NULL)
    ),
    CHECK (
        asset_id IS NULL OR state IN ('complete', 'satisfied')
    ),
    UNIQUE (acquisition_run_id, acquisition_plan_item_id)
);

CREATE INDEX media_acquisition_run_items_state_idx
    ON media_acquisition_run_items(acquisition_run_id, state, acquisition_run_item_id);
CREATE INDEX media_acquisition_run_items_retry_idx
    ON media_acquisition_run_items(retryable, state, acquisition_run_id);
CREATE INDEX media_acquisition_run_items_asset_idx
    ON media_acquisition_run_items(asset_id);

CREATE TABLE media_acquisition_attempts (
    acquisition_attempt_id INTEGER PRIMARY KEY,
    acquisition_run_item_id INTEGER NOT NULL
        REFERENCES media_acquisition_run_items(acquisition_run_item_id) ON DELETE RESTRICT,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    state TEXT NOT NULL CHECK (state IN ('running', 'complete', 'failed', 'interrupted')),
    outcome TEXT CHECK (
        outcome IS NULL OR outcome IN (
            'downloaded', 'downloaded_exact_only', 'existing', 'policy_failure',
            'authentication_required', 'authorization_denied', 'unavailable',
            'rate_limited', 'transient_provider', 'timeout', 'response_too_large',
            'invalid_content', 'source_changed', 'interrupted', 'storage_failure',
            'hash_mismatch', 'inspection_failure', 'storage_integrity_failure',
            'budget_exhausted', 'cancelled'
        )
    ),
    retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    request_identity TEXT NOT NULL COLLATE NOCASE CHECK (length(request_identity) = 64),
    request_policy_key TEXT NOT NULL CHECK (length(request_policy_key) BETWEEN 1 AND 200),
    request_policy_version TEXT NOT NULL CHECK (
        length(request_policy_version) BETWEEN 1 AND 200
    ),
    status_code INTEGER CHECK (status_code IS NULL OR status_code BETWEEN 100 AND 599),
    redirect_count INTEGER NOT NULL DEFAULT 0 CHECK (redirect_count >= 0),
    response_etag TEXT CHECK (response_etag IS NULL OR length(response_etag) <= 1000),
    received_bytes INTEGER NOT NULL DEFAULT 0 CHECK (received_bytes >= 0),
    response_size INTEGER CHECK (response_size IS NULL OR response_size >= 0),
    retry_after TEXT,
    diagnostic TEXT CHECK (diagnostic IS NULL OR length(diagnostic) <= 1000),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    CHECK (
        (state = 'running' AND outcome IS NULL AND finished_at IS NULL)
        OR (state != 'running' AND outcome IS NOT NULL AND finished_at IS NOT NULL)
    ),
    UNIQUE (acquisition_run_item_id, attempt_number)
);

CREATE INDEX media_acquisition_attempts_item_idx
    ON media_acquisition_attempts(acquisition_run_item_id, attempt_number);
CREATE INDEX media_acquisition_attempts_outcome_idx
    ON media_acquisition_attempts(outcome, retryable);

CREATE TRIGGER media_acquisition_attempts_terminal_immutable
BEFORE UPDATE ON media_acquisition_attempts
WHEN OLD.state != 'running'
BEGIN
    SELECT RAISE(ABORT, 'terminal media acquisition attempts are immutable');
END;

CREATE TABLE media_acquisition_partials (
    acquisition_partial_id INTEGER PRIMARY KEY,
    acquisition_run_item_id INTEGER NOT NULL
        REFERENCES media_acquisition_run_items(acquisition_run_item_id) ON DELETE RESTRICT,
    managed_root_id INTEGER NOT NULL
        REFERENCES managed_roots(managed_root_id) ON DELETE RESTRICT,
    managed_root_identity TEXT NOT NULL CHECK (
        length(managed_root_identity) BETWEEN 3 AND 200
    ),
    staging_device INTEGER NOT NULL CHECK (staging_device >= 0),
    staging_inode INTEGER NOT NULL CHECK (staging_inode > 0),
    staging_name TEXT NOT NULL CHECK (
        length(staging_name) BETWEEN 1 AND 200
        AND instr(staging_name, '/') = 0
        AND instr(staging_name, char(92)) = 0
        AND staging_name NOT IN ('.', '..')
    ),
    request_identity TEXT NOT NULL COLLATE NOCASE CHECK (length(request_identity) = 64),
    strong_etag TEXT CHECK (
        strong_etag IS NULL
        OR (length(strong_etag) BETWEEN 3 AND 1000 AND substr(strong_etag, 1, 2) != 'W/')
    ),
    byte_count INTEGER NOT NULL CHECK (byte_count >= 0),
    prefix_sha256 TEXT NOT NULL COLLATE NOCASE CHECK (length(prefix_sha256) = 64),
    prefix_md5 TEXT NOT NULL COLLATE NOCASE CHECK (length(prefix_md5) = 32),
    state TEXT NOT NULL CHECK (state IN ('active', 'discarded', 'quarantined', 'consumed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX media_acquisition_partials_active_idx
    ON media_acquisition_partials(acquisition_run_item_id)
    WHERE state = 'active';
CREATE UNIQUE INDEX media_acquisition_partials_staging_idx
    ON media_acquisition_partials(managed_root_id, staging_name)
    WHERE state = 'active';

CREATE TABLE media_acquisition_verifications (
    acquisition_verification_id INTEGER PRIMARY KEY,
    acquisition_run_item_id INTEGER NOT NULL
        REFERENCES media_acquisition_run_items(acquisition_run_item_id) ON DELETE RESTRICT,
    claim_kind TEXT NOT NULL CHECK (
        claim_kind IN ('sha256', 'md5', 'file_size', 'mime_type', 'width', 'height')
    ),
    declared_value TEXT NOT NULL CHECK (length(declared_value) BETWEEN 1 AND 2000),
    verified_value TEXT NOT NULL CHECK (length(verified_value) BETWEEN 1 AND 2000),
    comparison_result TEXT NOT NULL CHECK (
        comparison_result IN ('matched', 'mismatched', 'not_comparable')
    ),
    source_raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    created_at TEXT NOT NULL,
    UNIQUE (acquisition_run_item_id, claim_kind)
);

CREATE INDEX media_acquisition_verifications_result_idx
    ON media_acquisition_verifications(comparison_result, claim_kind);

CREATE TABLE media_acquisition_quarantine (
    acquisition_quarantine_id INTEGER PRIMARY KEY,
    acquisition_run_item_id INTEGER NOT NULL
        REFERENCES media_acquisition_run_items(acquisition_run_item_id) ON DELETE RESTRICT,
    acquisition_attempt_id INTEGER
        REFERENCES media_acquisition_attempts(acquisition_attempt_id) ON DELETE RESTRICT,
    managed_root_id INTEGER NOT NULL
        REFERENCES managed_roots(managed_root_id) ON DELETE RESTRICT,
    quarantine_name TEXT NOT NULL CHECK (
        length(quarantine_name) BETWEEN 1 AND 200
        AND instr(quarantine_name, '/') = 0
        AND instr(quarantine_name, char(92)) = 0
        AND quarantine_name NOT IN ('.', '..')
    ),
    reason TEXT NOT NULL CHECK (reason IN (
        'hash_mismatch', 'source_changed', 'invalid_content', 'unsafe_partial',
        'storage_integrity_failure'
    )),
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT COLLATE NOCASE CHECK (sha256 IS NULL OR length(sha256) = 64),
    md5 TEXT COLLATE NOCASE CHECK (md5 IS NULL OR length(md5) = 32),
    state TEXT NOT NULL DEFAULT 'retained' CHECK (state IN ('retained', 'missing')),
    created_at TEXT NOT NULL,
    UNIQUE (managed_root_id, quarantine_name)
);

CREATE INDEX media_acquisition_quarantine_item_idx
    ON media_acquisition_quarantine(acquisition_run_item_id, acquisition_quarantine_id);
CREATE INDEX media_acquisition_quarantine_reason_idx
    ON media_acquisition_quarantine(reason, state);
