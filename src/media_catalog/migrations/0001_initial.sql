CREATE TABLE platforms (
    platform_id INTEGER PRIMARY KEY,
    platform_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    base_url TEXT,
    adapter_name TEXT,
    adapter_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO platforms (platform_key, display_name, base_url)
VALUES ('x', 'X', 'https://x.com');

CREATE TABLE import_runs (
    import_run_id INTEGER PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source_reference TEXT NOT NULL,
    source_digest TEXT NOT NULL,
    source_size INTEGER NOT NULL CHECK (source_size >= 0),
    adapter_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
    UNIQUE (source_kind, source_digest)
);

CREATE TABLE import_run_counts (
    import_run_id INTEGER NOT NULL REFERENCES import_runs(import_run_id) ON DELETE CASCADE,
    entity_kind TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    inserted_count INTEGER NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    updated_count INTEGER NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
    existing_count INTEGER NOT NULL DEFAULT 0 CHECK (existing_count >= 0),
    skipped_count INTEGER NOT NULL DEFAULT 0 CHECK (skipped_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    PRIMARY KEY (import_run_id, entity_kind)
);

CREATE TABLE import_diagnostics (
    diagnostic_id INTEGER PRIMARY KEY,
    import_run_id INTEGER NOT NULL REFERENCES import_runs(import_run_id) ON DELETE CASCADE,
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
    record_key TEXT,
    code TEXT NOT NULL,
    message TEXT NOT NULL CHECK (length(message) <= 1000),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE raw_payloads (
    raw_payload_id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
    media_type TEXT NOT NULL,
    payload BLOB NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0)
);

CREATE TABLE raw_observations (
    raw_observation_id INTEGER PRIMARY KEY,
    raw_payload_id INTEGER NOT NULL REFERENCES raw_payloads(raw_payload_id),
    import_run_id INTEGER REFERENCES import_runs(import_run_id),
    platform_id INTEGER REFERENCES platforms(platform_id),
    object_kind TEXT NOT NULL,
    native_id TEXT,
    media_type TEXT NOT NULL,
    source_schema TEXT,
    status TEXT,
    observed_at TEXT NOT NULL,
    UNIQUE (import_run_id, object_kind, native_id, raw_payload_id)
);

CREATE TABLE accounts (
    account_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    native_account_id TEXT NOT NULL,
    canonical_url TEXT,
    availability TEXT NOT NULL DEFAULT 'available',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (platform_id, native_account_id)
);

CREATE TABLE account_snapshots (
    account_snapshot_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    handle TEXT,
    display_name TEXT,
    bio TEXT,
    location TEXT,
    website_url TEXT,
    profile_url TEXT,
    avatar_url TEXT,
    banner_url TEXT,
    followers INTEGER CHECK (followers IS NULL OR followers >= 0),
    following INTEGER CHECK (following IS NULL OR following >= 0),
    verified INTEGER CHECK (verified IS NULL OR verified IN (0, 1)),
    verification_type TEXT,
    snapshot_digest TEXT NOT NULL CHECK (length(snapshot_digest) = 64),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (account_id, snapshot_digest, raw_observation_id)
);

CREATE TABLE posts (
    post_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    native_post_id TEXT NOT NULL,
    canonical_url TEXT,
    text_content TEXT,
    language TEXT,
    created_at TEXT,
    updated_at TEXT,
    deleted_at TEXT,
    availability TEXT NOT NULL DEFAULT 'available',
    rating TEXT,
    status TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (platform_id, native_post_id)
);

CREATE TABLE post_participants (
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    role TEXT NOT NULL,
    confidence REAL,
    review_state TEXT NOT NULL DEFAULT 'observed',
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    PRIMARY KEY (post_id, account_id, role)
);

CREATE TABLE post_relations (
    source_post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    target_post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    PRIMARY KEY (source_post_id, target_post_id, relation_type)
);

CREATE TABLE observations (
    observation_id INTEGER PRIMARY KEY,
    subject_kind TEXT NOT NULL CHECK (subject_kind = 'post'),
    subject_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_event_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    collection_data TEXT,
    import_run_id INTEGER REFERENCES import_runs(import_run_id),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (source_kind, source_event_key, event_type)
);

CREATE TABLE observation_revisions (
    observation_revision_id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    collection_data TEXT,
    import_run_id INTEGER REFERENCES import_runs(import_run_id),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (observation_id, import_run_id, raw_observation_id)
);

CREATE TABLE media_occurrences (
    media_occurrence_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    media_index INTEGER NOT NULL CHECK (media_index >= 0),
    media_type TEXT NOT NULL,
    role TEXT,
    remote_url TEXT,
    preview_url TEXT,
    mime_type TEXT,
    width INTEGER CHECK (width IS NULL OR width >= 0),
    height INTEGER CHECK (height IS NULL OR height >= 0),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    variants_json TEXT,
    alt_text TEXT,
    availability TEXT NOT NULL DEFAULT 'available',
    declared_md5 TEXT,
    declared_sha256 TEXT,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observed_at TEXT NOT NULL,
    UNIQUE (post_id, source_key)
);

CREATE TABLE assets (
    asset_id INTEGER PRIMARY KEY,
    verified_sha256 TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(verified_sha256) = 64),
    verified_md5 TEXT COLLATE NOCASE CHECK (verified_md5 IS NULL OR length(verified_md5) = 32),
    phash TEXT,
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size >= 0),
    mime_type TEXT,
    width INTEGER CHECK (width IS NULL OR width >= 0),
    height INTEGER CHECK (height IS NULL OR height >= 0),
    storage_kind TEXT NOT NULL,
    storage_path TEXT,
    verified_at TEXT,
    verification_method TEXT NOT NULL
);

CREATE TABLE occurrence_assets (
    media_occurrence_id INTEGER NOT NULL REFERENCES media_occurrences(media_occurrence_id) ON DELETE CASCADE,
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    verification_source TEXT NOT NULL,
    PRIMARY KEY (media_occurrence_id, asset_id, relationship)
);

CREATE INDEX account_snapshots_handle_idx ON account_snapshots(handle);
CREATE INDEX account_snapshots_display_name_idx ON account_snapshots(display_name);
CREATE INDEX posts_text_idx ON posts(text_content);
CREATE INDEX observations_event_subject_idx ON observations(event_type, subject_kind, subject_id);
CREATE INDEX media_occurrences_url_idx ON media_occurrences(remote_url);
CREATE INDEX assets_md5_idx ON assets(verified_md5);
