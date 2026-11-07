-- Link observations gain the attribution entity as a third subject kind
-- (bead data-processing-9er): artist-record URLs persisted in
-- attribution_urls are opaque strings that never enter the recognized link
-- graph, so a fetched artist's stable account links (the tag <-> handle
-- identity bridge) stop one table short.  The scan pass now observes them.
--
-- SQLite cannot ALTER a CHECK, so the table is rebuilt (0025/0026 pattern),
-- replay-safe: IF NOT EXISTS scaffolding, copy/drop/rename, IF NOT EXISTS
-- indexes.

CREATE TABLE IF NOT EXISTS link_observations_rebuilt (
    link_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_link_id INTEGER NOT NULL REFERENCES external_links(external_link_id),
    discovery_run_id INTEGER REFERENCES discovery_runs(discovery_run_id),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('account', 'post', 'attribution')),
    subject_account_id INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    subject_post_id INTEGER REFERENCES posts(post_id) ON DELETE CASCADE,
    subject_attribution_id INTEGER
        REFERENCES attribution_entities(attribution_entity_id) ON DELETE CASCADE,
    account_snapshot_id INTEGER REFERENCES account_snapshots(account_snapshot_id),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    source_context TEXT NOT NULL,
    json_path TEXT,
    original_url TEXT NOT NULL,
    original_query TEXT,
    original_fragment TEXT,
    observed_at TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    occurrence_digest TEXT NOT NULL UNIQUE,
    CHECK (
        (subject_kind = 'account' AND subject_account_id IS NOT NULL
         AND subject_post_id IS NULL AND subject_attribution_id IS NULL) OR
        (subject_kind = 'post' AND subject_post_id IS NOT NULL
         AND subject_account_id IS NULL AND subject_attribution_id IS NULL) OR
        (subject_kind = 'attribution' AND subject_attribution_id IS NOT NULL
         AND subject_account_id IS NULL AND subject_post_id IS NULL)
    ),
    UNIQUE (occurrence_digest, extractor_version)
);

INSERT INTO link_observations_rebuilt
    SELECT link_observation_id, external_link_id, discovery_run_id, subject_kind,
           subject_account_id, subject_post_id, NULL, account_snapshot_id,
           raw_observation_id, source_context, json_path, original_url,
           original_query, original_fragment, observed_at, extractor_version,
           occurrence_digest
      FROM link_observations;

DROP TABLE link_observations;
ALTER TABLE link_observations_rebuilt RENAME TO link_observations;

CREATE INDEX IF NOT EXISTS link_observations_subject_account_idx
    ON link_observations(subject_account_id) WHERE subject_account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS link_observations_subject_post_idx
    ON link_observations(subject_post_id) WHERE subject_post_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS link_observations_subject_attribution_idx
    ON link_observations(subject_attribution_id) WHERE subject_attribution_id IS NOT NULL;
