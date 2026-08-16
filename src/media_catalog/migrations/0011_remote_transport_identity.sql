-- Add explicit, optional transport provenance to remote synchronization material.
-- Every pair is nullable for legacy rows and non-remote imports.  Existing IDs,
-- foreign keys, indexes, and triggers remain untouched by these additive columns.

ALTER TABLE remote_runs ADD COLUMN transport_key TEXT
    CHECK (transport_key IS NULL OR length(transport_key) BETWEEN 1 AND 200);
ALTER TABLE remote_runs ADD COLUMN transport_version TEXT
    CHECK (
        transport_version IS NULL
        OR length(transport_version) BETWEEN 1 AND 200
    )
    CHECK ((transport_key IS NULL) = (transport_version IS NULL));

ALTER TABLE remote_requests ADD COLUMN transport_key TEXT
    CHECK (transport_key IS NULL OR length(transport_key) BETWEEN 1 AND 200);
ALTER TABLE remote_requests ADD COLUMN transport_version TEXT
    CHECK (
        transport_version IS NULL
        OR length(transport_version) BETWEEN 1 AND 200
    )
    CHECK ((transport_key IS NULL) = (transport_version IS NULL));

ALTER TABLE remote_checkpoints ADD COLUMN transport_key TEXT
    CHECK (transport_key IS NULL OR length(transport_key) BETWEEN 1 AND 200);
ALTER TABLE remote_checkpoints ADD COLUMN transport_version TEXT
    CHECK (
        transport_version IS NULL
        OR length(transport_version) BETWEEN 1 AND 200
    )
    CHECK ((transport_key IS NULL) = (transport_version IS NULL));

ALTER TABLE raw_observations ADD COLUMN transport_key TEXT
    CHECK (transport_key IS NULL OR length(transport_key) BETWEEN 1 AND 200);
ALTER TABLE raw_observations ADD COLUMN transport_version TEXT
    CHECK (
        transport_version IS NULL
        OR length(transport_version) BETWEEN 1 AND 200
    )
    CHECK ((transport_key IS NULL) = (transport_version IS NULL));
