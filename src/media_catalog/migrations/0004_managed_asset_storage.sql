-- Managed asset persistence is additive.  Existing asset and occurrence ids,
-- imported hash assertions, and the legacy storage_path column remain intact.

ALTER TABLE assets ADD COLUMN detected_mime_type TEXT;
ALTER TABLE assets ADD COLUMN detected_width INTEGER CHECK (detected_width IS NULL OR detected_width >= 0);
ALTER TABLE assets ADD COLUMN detected_height INTEGER CHECK (detected_height IS NULL OR detected_height >= 0);
ALTER TABLE assets ADD COLUMN detected_frame_count INTEGER CHECK (
    detected_frame_count IS NULL OR detected_frame_count >= 0
);

CREATE TABLE managed_roots (
    managed_root_id INTEGER PRIMARY KEY,
    root_kind TEXT NOT NULL CHECK (root_kind IN ('source', 'managed')),
    root_identity TEXT NOT NULL CHECK (length(root_identity) BETWEEN 1 AND 200),
    display_label TEXT NOT NULL CHECK (length(display_label) BETWEEN 1 AND 200),
    private_path TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (root_kind, root_identity)
);

CREATE TABLE asset_locations (
    asset_location_id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    managed_root_id INTEGER NOT NULL REFERENCES managed_roots(managed_root_id) ON DELETE RESTRICT,
    relative_path TEXT NOT NULL CHECK (length(relative_path) > 0),
    location_kind TEXT NOT NULL CHECK (location_kind IN ('managed', 'external', 'legacy')),
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size >= 0),
    recorded_sha256 TEXT COLLATE NOCASE CHECK (
        recorded_sha256 IS NULL OR length(recorded_sha256) = 64
    ),
    created_at TEXT NOT NULL,
    UNIQUE (managed_root_id, relative_path),
    UNIQUE (asset_id, managed_root_id, relative_path)
);

CREATE TABLE occurrence_sources (
    occurrence_source_id INTEGER PRIMARY KEY,
    media_occurrence_id INTEGER NOT NULL REFERENCES media_occurrences(media_occurrence_id)
        ON DELETE CASCADE,
    managed_root_id INTEGER REFERENCES managed_roots(managed_root_id) ON DELETE RESTRICT,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('legacy_local', 'managed', 'external')),
    relative_path TEXT NOT NULL CHECK (length(relative_path) > 0),
    source_identity TEXT,
    recorded_at TEXT NOT NULL,
    UNIQUE (media_occurrence_id, managed_root_id, relative_path, source_kind)
);

CREATE INDEX occurrence_sources_path_idx
    ON occurrence_sources(managed_root_id, relative_path);
CREATE INDEX occurrence_sources_occurrence_idx
    ON occurrence_sources(media_occurrence_id, occurrence_source_id);

CREATE TABLE asset_fingerprints (
    asset_fingerprint_id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    fingerprint_kind TEXT NOT NULL CHECK (fingerprint_kind IN ('sha256', 'md5', 'phash')),
    fingerprint_value TEXT NOT NULL CHECK (length(fingerprint_value) > 0),
    algorithm TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    source TEXT NOT NULL CHECK (length(source) <= 200),
    verification_status TEXT NOT NULL CHECK (
        verification_status IN ('legacy', 'calculated', 'verified', 'mismatch', 'unavailable')
    ),
    observed_at TEXT NOT NULL,
    UNIQUE (asset_id, fingerprint_kind, algorithm, algorithm_version, source)
);

CREATE INDEX asset_fingerprints_lookup_idx
    ON asset_fingerprints(fingerprint_kind, fingerprint_value);
CREATE INDEX asset_fingerprints_asset_idx
    ON asset_fingerprints(asset_id, fingerprint_kind);

-- storage_path predates occurrence-level provenance.  Preserve it as an
-- explicitly ambiguous assertion; do not manufacture occurrence source rows.
CREATE TABLE asset_legacy_assertions (
    asset_legacy_assertion_id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
    legacy_path TEXT NOT NULL CHECK (length(legacy_path) > 0),
    assertion_kind TEXT NOT NULL CHECK (assertion_kind = 'ambiguous_asset_path'),
    associated_occurrence_id INTEGER REFERENCES media_occurrences(media_occurrence_id),
    recorded_at TEXT NOT NULL,
    UNIQUE (asset_id, legacy_path)
);

INSERT INTO asset_legacy_assertions (
    asset_id, legacy_path, assertion_kind, associated_occurrence_id, recorded_at
)
SELECT asset_id, storage_path, 'ambiguous_asset_path', NULL, COALESCE(verified_at, CURRENT_TIMESTAMP)
FROM assets
WHERE storage_path IS NOT NULL AND length(storage_path) > 0;

CREATE INDEX asset_legacy_assertions_asset_idx
    ON asset_legacy_assertions(asset_id);

CREATE TABLE adoption_runs (
    adoption_run_id INTEGER PRIMARY KEY,
    source_root_id INTEGER REFERENCES managed_roots(managed_root_id) ON DELETE RESTRICT,
    managed_root_id INTEGER NOT NULL REFERENCES managed_roots(managed_root_id) ON DELETE RESTRICT,
    source_root_identity TEXT,
    managed_root_identity TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    fingerprint_algorithm TEXT,
    limits_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'partial', 'failed', 'cancelled')),
    planned_count INTEGER NOT NULL DEFAULT 0 CHECK (planned_count >= 0),
    completed_count INTEGER NOT NULL DEFAULT 0 CHECK (completed_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    diagnostic TEXT CHECK (diagnostic IS NULL OR length(diagnostic) <= 1000)
);

CREATE INDEX adoption_runs_status_idx ON adoption_runs(status, started_at);
CREATE INDEX adoption_runs_roots_idx ON adoption_runs(source_root_id, managed_root_id);

CREATE TABLE adoption_items (
    adoption_item_id INTEGER PRIMARY KEY,
    adoption_run_id INTEGER NOT NULL REFERENCES adoption_runs(adoption_run_id) ON DELETE CASCADE,
    item_key TEXT NOT NULL CHECK (length(item_key) BETWEEN 1 AND 200),
    media_occurrence_id INTEGER REFERENCES media_occurrences(media_occurrence_id)
        ON DELETE SET NULL,
    occurrence_source_id INTEGER REFERENCES occurrence_sources(occurrence_source_id)
        ON DELETE SET NULL,
    asset_id INTEGER REFERENCES assets(asset_id) ON DELETE SET NULL,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'adopted', 'adopted_exact_only', 'existing', 'missing', 'unsafe_path',
        'unreadable', 'source_changed', 'limit_exceeded', 'hash_mismatch',
        'inspection_failed', 'storage_integrity_failed'
    )),
    detected_mime_type TEXT,
    detected_width INTEGER CHECK (detected_width IS NULL OR detected_width >= 0),
    detected_height INTEGER CHECK (detected_height IS NULL OR detected_height >= 0),
    detected_frame_count INTEGER CHECK (detected_frame_count IS NULL OR detected_frame_count >= 0),
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size >= 0),
    sha256 TEXT COLLATE NOCASE CHECK (sha256 IS NULL OR length(sha256) = 64),
    md5 TEXT COLLATE NOCASE CHECK (md5 IS NULL OR length(md5) = 32),
    diagnostic TEXT CHECK (diagnostic IS NULL OR length(diagnostic) <= 1000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (adoption_run_id, item_key)
);

CREATE INDEX adoption_items_outcome_idx ON adoption_items(outcome, adoption_run_id);
CREATE INDEX adoption_items_occurrence_idx ON adoption_items(media_occurrence_id, outcome);

CREATE TABLE adoption_attempts (
    adoption_attempt_id INTEGER PRIMARY KEY,
    adoption_item_id INTEGER NOT NULL REFERENCES adoption_items(adoption_item_id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    outcome TEXT NOT NULL CHECK (outcome IN (
        'adopted', 'adopted_exact_only', 'existing', 'missing', 'unsafe_path',
        'unreadable', 'source_changed', 'limit_exceeded', 'hash_mismatch',
        'inspection_failed', 'storage_integrity_failed'
    )),
    sha256 TEXT COLLATE NOCASE CHECK (sha256 IS NULL OR length(sha256) = 64),
    md5 TEXT COLLATE NOCASE CHECK (md5 IS NULL OR length(md5) = 32),
    byte_size INTEGER CHECK (byte_size IS NULL OR byte_size >= 0),
    detected_mime_type TEXT,
    detected_width INTEGER CHECK (detected_width IS NULL OR detected_width >= 0),
    detected_height INTEGER CHECK (detected_height IS NULL OR detected_height >= 0),
    detected_frame_count INTEGER CHECK (detected_frame_count IS NULL OR detected_frame_count >= 0),
    diagnostic TEXT CHECK (diagnostic IS NULL OR length(diagnostic) <= 1000),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (adoption_item_id, attempt_number)
);

CREATE INDEX adoption_attempts_outcome_idx ON adoption_attempts(outcome, adoption_item_id);
