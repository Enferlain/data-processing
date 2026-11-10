-- Artist-identifier leads (bead data-processing-an1, change
-- add-index-artist-identifier): the artists-export index method resolves a
-- subject's source URL to provider artist ENTRIES (not posts), recorded as
-- session-scoped leads with the snapshot revision. Leads never create posts,
-- occurrences, assets, or observations and never feed the fetch bridge.
-- Every statement is replay-safe per the 0024/0026 convention.

CREATE TABLE IF NOT EXISTS discovery_artist_leads (
    discovery_artist_lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
    discovery_session_id INTEGER NOT NULL
        REFERENCES discovery_sessions(discovery_session_id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (length(provider) BETWEEN 1 AND 100),
    artist_native_id TEXT NOT NULL
        CHECK (length(artist_native_id) BETWEEN 1 AND 100),
    artist_name TEXT NOT NULL CHECK (length(artist_name) BETWEEN 1 AND 200),
    other_names TEXT NOT NULL DEFAULT '',
    matched_url TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    snapshot_revision TEXT NOT NULL
        CHECK (length(snapshot_revision) BETWEEN 1 AND 200),
    recorded_at TEXT NOT NULL
);

-- Lead reads key on the session (operator inspection, later artist search).
CREATE INDEX IF NOT EXISTS idx_discovery_artist_leads_session
    ON discovery_artist_leads(discovery_session_id);
