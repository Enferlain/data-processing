-- Local search indexes (bead data-processing-an1, change
-- add-local-search-indexes): registrations bind provider lookup projections
-- (disposable SQLite files OUTSIDE the catalog) to discovery target names;
-- index hits are session-scoped leads for the normal fetch pipeline.
-- Identity rule: the target NAME is the registration's identity; the path is
-- mutable plumbing (moving the projection and re-pointing preserves search
-- history and freshness). Every statement is replay-safe per the 0024/0026
-- convention.

CREATE TABLE IF NOT EXISTS search_index_registrations (
    search_index_registration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_name TEXT NOT NULL
        UNIQUE
        CHECK (length(target_name) BETWEEN 1 AND 100),
    provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 100),
    index_format TEXT NOT NULL CHECK (index_format IN ('lookup-v1')),
    private_path TEXT NOT NULL,
    snapshot_revision TEXT NOT NULL DEFAULT ''
        CHECK (length(snapshot_revision) <= 200),
    registered_at TEXT NOT NULL,
    last_refreshed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_search_index_registrations_provider
    ON search_index_registrations(provider);

CREATE TABLE IF NOT EXISTS discovery_index_hits (
    discovery_index_hit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovery_session_id INTEGER NOT NULL
        REFERENCES discovery_sessions(discovery_session_id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 100),
    post_native_id TEXT NOT NULL
        CHECK (length(post_native_id) BETWEEN 1 AND 100),
    md5 TEXT CHECK (md5 IS NULL OR length(md5) = 32),
    snapshot_revision TEXT NOT NULL
        CHECK (length(snapshot_revision) BETWEEN 1 AND 200),
    recorded_at TEXT NOT NULL
);

-- Lead reads key on the session (wave-A fetch planning).
CREATE INDEX IF NOT EXISTS idx_discovery_index_hits_session
    ON discovery_index_hits(discovery_session_id);
