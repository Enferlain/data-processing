-- Remote metadata persistence is additive.  Existing import runs, accounts,
-- posts, media occurrences, raw payloads, and managed-asset rows keep their
-- ids, constraints, and behavior.  Remote synchronization stores its own run
-- lifecycle, requests, and resumable checkpoints, plus neutral tags and
-- provider attribution records that are deliberately separate from accounts.

UPDATE platforms
SET display_name = 'Danbooru', base_url = 'https://danbooru.donmai.us'
WHERE platform_key = 'danbooru';
INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url)
VALUES ('aibooru', 'AIBooru', 'https://aibooru.online');

-- ---------------------------------------------------------------------------
-- Richer posts and media occurrences (reuse existing columns where present)
-- ---------------------------------------------------------------------------

-- posts already has updated_at and rating; only title and provider post type
-- are new.  Both default to NULL so existing rows and local imports are unchanged.
ALTER TABLE posts ADD COLUMN title TEXT;
ALTER TABLE posts ADD COLUMN provider_post_type TEXT;

-- media_occurrences already has role and mime_type; declared_file_size is new
-- and is a non-negative provider assertion only.
ALTER TABLE media_occurrences ADD COLUMN declared_file_size INTEGER
    CHECK (declared_file_size IS NULL OR declared_file_size >= 0);

-- ---------------------------------------------------------------------------
-- Remote runs, requests, and resumable checkpoints
-- ---------------------------------------------------------------------------

CREATE TABLE remote_runs (
    remote_run_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL CHECK (operation IN (
        'fetch_account', 'fetch_post', 'list_account_posts', 'fetch_attribution'
    )),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 500),
    adapter_version TEXT NOT NULL CHECK (length(adapter_version) BETWEEN 1 AND 200),
    schema_version TEXT NOT NULL CHECK (length(schema_version) BETWEEN 1 AND 200),
    resumed_from_run_id INTEGER REFERENCES remote_runs(remote_run_id),
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
    CHECK (
        budget_boundary IS NULL
        OR termination_outcome IS NOT NULL
    ),
    CHECK (
        termination_outcome IS NULL
        OR status IN ('complete', 'paused', 'failed')
    )
);

CREATE INDEX remote_runs_platform_idx
    ON remote_runs(platform_id, instance_host, operation, status);
CREATE INDEX remote_runs_resumed_idx ON remote_runs(resumed_from_run_id);
CREATE INDEX remote_runs_status_idx ON remote_runs(status, started_at);

CREATE TABLE remote_checkpoints (
    remote_checkpoint_id INTEGER PRIMARY KEY,
    remote_run_id INTEGER NOT NULL REFERENCES remote_runs(remote_run_id) ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (operation IN (
        'fetch_account', 'fetch_post', 'list_account_posts', 'fetch_attribution'
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

CREATE INDEX remote_checkpoints_run_idx
    ON remote_checkpoints(remote_run_id, remote_checkpoint_id);

CREATE TABLE remote_requests (
    remote_request_id INTEGER PRIMARY KEY,
    remote_run_id INTEGER NOT NULL REFERENCES remote_runs(remote_run_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    request_identity TEXT NOT NULL CHECK (length(request_identity) BETWEEN 1 AND 1000),
    operation TEXT NOT NULL CHECK (operation IN (
        'fetch_account', 'fetch_post', 'list_account_posts', 'fetch_attribution'
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

CREATE INDEX remote_requests_run_idx ON remote_requests(remote_run_id, attempt_number);
CREATE INDEX remote_requests_outcome_idx ON remote_requests(outcome);
CREATE INDEX remote_requests_raw_observation_idx
    ON remote_requests(raw_observation_id);

-- ---------------------------------------------------------------------------
-- Raw observation remote provenance (additive; local imports stay null)
-- ---------------------------------------------------------------------------

ALTER TABLE raw_observations ADD COLUMN remote_run_id INTEGER
    REFERENCES remote_runs(remote_run_id);
ALTER TABLE raw_observations ADD COLUMN remote_request_id INTEGER
    REFERENCES remote_requests(remote_request_id);
ALTER TABLE raw_observations ADD COLUMN adapter_version TEXT;
ALTER TABLE raw_observations ADD COLUMN schema_version TEXT;

-- A retained remote response is uniquely associated with the request that
-- captured it; replay of the same request id is idempotent while independent
-- requests keep their own observations even when their payload bytes collide.
CREATE UNIQUE INDEX raw_observations_remote_request_idx
    ON raw_observations(remote_request_id)
    WHERE remote_request_id IS NOT NULL;

CREATE INDEX raw_observations_remote_run_idx
    ON raw_observations(remote_run_id)
    WHERE remote_run_id IS NOT NULL;

-- Post-scoped external evidence is independent from discovery-run link
-- observations.  A source URL may be unresolved, while a provider-supplied
-- stable identifier can also point at a typed semantic reference.
CREATE TABLE post_external_references (
    post_external_reference_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    external_link_id INTEGER REFERENCES external_links(external_link_id),
    platform_reference_id INTEGER REFERENCES platform_references(platform_reference_id),
    reference_kind TEXT NOT NULL CHECK (reference_kind IN ('source_url', 'provider_id')),
    raw_observation_id INTEGER NOT NULL REFERENCES raw_observations(raw_observation_id),
    observed_at TEXT NOT NULL,
    CHECK (external_link_id IS NOT NULL OR platform_reference_id IS NOT NULL),
    UNIQUE (
        post_id, external_link_id, platform_reference_id, reference_kind, raw_observation_id
    )
);

CREATE INDEX post_external_references_post_idx
    ON post_external_references(post_id, post_external_reference_id);
CREATE INDEX post_external_references_platform_ref_idx
    ON post_external_references(platform_reference_id);

CREATE TABLE account_external_links (
    account_external_link_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    external_link_id INTEGER NOT NULL REFERENCES external_links(external_link_id),
    source_context TEXT NOT NULL CHECK (length(source_context) BETWEEN 1 AND 200),
    raw_observation_id INTEGER NOT NULL REFERENCES raw_observations(raw_observation_id),
    observed_at TEXT NOT NULL,
    UNIQUE (account_id, external_link_id, source_context, raw_observation_id)
);

CREATE INDEX account_external_links_account_idx
    ON account_external_links(account_id, account_external_link_id);

-- ---------------------------------------------------------------------------
-- Platform-scoped tags and append-only tag observations
-- ---------------------------------------------------------------------------

CREATE TABLE tags (
    tag_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    category TEXT NOT NULL CHECK (category IN (
        'general', 'artist', 'copyright', 'character', 'meta', 'unknown'
    )),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 500),
    normalization_version TEXT NOT NULL CHECK (
        length(normalization_version) BETWEEN 1 AND 200
    ),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (platform_id, category, name, normalization_version)
);

CREATE INDEX tags_platform_idx ON tags(platform_id, category);

CREATE TABLE post_tags (
    post_tag_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (post_id, tag_id)
);

CREATE INDEX post_tags_tag_idx ON post_tags(tag_id);

CREATE TABLE post_tag_observations (
    post_tag_observation_id INTEGER PRIMARY KEY,
    post_tag_id INTEGER NOT NULL REFERENCES post_tags(post_tag_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    provider_spelling TEXT NOT NULL CHECK (length(provider_spelling) BETWEEN 1 AND 500),
    translated_label TEXT CHECK (translated_label IS NULL OR length(translated_label) <= 500),
    position INTEGER CHECK (position IS NULL OR position >= 0),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (post_tag_id, observation_digest)
);

CREATE INDEX post_tag_observations_tag_idx
    ON post_tag_observations(post_tag_id, observed_at);

-- ---------------------------------------------------------------------------
-- Provider attribution entities (distinct from accounts)
-- ---------------------------------------------------------------------------

CREATE TABLE attribution_entities (
    attribution_entity_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    provider_attribution_id TEXT NOT NULL CHECK (
        length(provider_attribution_id) BETWEEN 1 AND 500
    ),
    adapter_version TEXT NOT NULL CHECK (length(adapter_version) BETWEEN 1 AND 200),
    availability TEXT NOT NULL DEFAULT 'available',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (platform_id, instance_host, provider_attribution_id)
);

CREATE INDEX attribution_entities_platform_idx
    ON attribution_entities(platform_id, instance_host);

CREATE TABLE attribution_snapshots (
    attribution_snapshot_id INTEGER PRIMARY KEY,
    attribution_entity_id INTEGER NOT NULL
        REFERENCES attribution_entities(attribution_entity_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    availability TEXT NOT NULL DEFAULT 'available',
    group_name TEXT CHECK (group_name IS NULL OR length(group_name) <= 500),
    is_deleted INTEGER CHECK (is_deleted IS NULL OR is_deleted IN (0, 1)),
    member_count INTEGER CHECK (member_count IS NULL OR member_count >= 0),
    snapshot_digest TEXT NOT NULL CHECK (length(snapshot_digest) = 64),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (attribution_entity_id, snapshot_digest, raw_observation_id)
);

CREATE INDEX attribution_snapshots_entity_idx
    ON attribution_snapshots(attribution_entity_id, observed_at);

CREATE TABLE attribution_names (
    attribution_name_id INTEGER PRIMARY KEY,
    attribution_entity_id INTEGER NOT NULL
        REFERENCES attribution_entities(attribution_entity_id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 500),
    name_kind TEXT NOT NULL DEFAULT 'primary' CHECK (name_kind IN (
        'primary', 'alias', 'other', 'group'
    )),
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (attribution_entity_id, name_kind, name, raw_observation_id)
);

CREATE INDEX attribution_names_entity_idx
    ON attribution_names(attribution_entity_id, name_kind);

CREATE TABLE attribution_urls (
    attribution_url_id INTEGER PRIMARY KEY,
    attribution_entity_id INTEGER NOT NULL
        REFERENCES attribution_entities(attribution_entity_id) ON DELETE CASCADE,
    url TEXT NOT NULL CHECK (length(url) BETWEEN 1 AND 2000),
    url_kind TEXT CHECK (url_kind IS NULL OR length(url_kind) <= 200),
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (attribution_entity_id, url, raw_observation_id)
);

CREATE INDEX attribution_urls_entity_idx ON attribution_urls(attribution_entity_id);

CREATE TABLE attribution_tag_links (
    attribution_tag_link_id INTEGER PRIMARY KEY,
    attribution_entity_id INTEGER NOT NULL
        REFERENCES attribution_entities(attribution_entity_id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (attribution_entity_id, tag_id, raw_observation_id)
);

CREATE INDEX attribution_tag_links_entity_idx
    ON attribution_tag_links(attribution_entity_id, tag_id);
