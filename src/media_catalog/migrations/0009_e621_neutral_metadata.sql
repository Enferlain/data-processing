-- Neutral remote metadata observations that were not representable by the
-- original tag/post projections.  Existing ids, rows, raw payloads, and
-- provider operation boundaries remain unchanged.  Every new row is typed,
-- append-only, and linked to the raw observation that supplied it.

-- ---------------------------------------------------------------------------
-- Native tag identity and provider category facts
-- ---------------------------------------------------------------------------

ALTER TABLE tags ADD COLUMN provider_tag_id TEXT;
ALTER TABLE tags ADD COLUMN native_category TEXT;
ALTER TABLE tags ADD COLUMN native_category_code INTEGER
    CHECK (native_category_code IS NULL OR native_category_code >= 0);
ALTER TABLE tags ADD COLUMN post_count INTEGER
    CHECK (post_count IS NULL OR post_count >= 0);
ALTER TABLE tags ADD COLUMN is_locked INTEGER
    CHECK (is_locked IS NULL OR is_locked IN (0, 1));
ALTER TABLE tags ADD COLUMN last_observed_at TEXT;
ALTER TABLE tags ADD COLUMN raw_observation_id INTEGER
    REFERENCES raw_observations(raw_observation_id);

CREATE UNIQUE INDEX tags_provider_identity_idx
    ON tags(platform_id, provider_tag_id)
    WHERE provider_tag_id IS NOT NULL;

CREATE TABLE tag_observations (
    tag_observation_id INTEGER PRIMARY KEY,
    tag_id INTEGER NOT NULL REFERENCES tags(tag_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    provider_tag_id TEXT,
    native_category TEXT,
    native_category_code INTEGER
        CHECK (native_category_code IS NULL OR native_category_code >= 0),
    post_count INTEGER CHECK (post_count IS NULL OR post_count >= 0),
    is_locked INTEGER CHECK (is_locked IS NULL OR is_locked IN (0, 1)),
    created_at TEXT,
    updated_at TEXT,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (tag_id, observation_digest)
);

CREATE INDEX tag_observations_tag_idx ON tag_observations(tag_id, observed_at);

CREATE TRIGGER tag_observations_immutable
BEFORE UPDATE ON tag_observations
BEGIN
    SELECT RAISE(ABORT, 'tag observations are immutable');
END;

CREATE TRIGGER tag_observations_no_delete
BEFORE DELETE ON tag_observations
BEGIN
    SELECT RAISE(ABORT, 'tag observations are immutable');
END;

ALTER TABLE post_tag_observations ADD COLUMN native_category TEXT;
ALTER TABLE post_tag_observations ADD COLUMN native_category_code INTEGER
    CHECK (native_category_code IS NULL OR native_category_code >= 0);

-- ---------------------------------------------------------------------------
-- Versioned provider alias observations (generic attribution evidence)
-- ---------------------------------------------------------------------------

CREATE TABLE tag_alias_observations (
    tag_alias_observation_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    provider_alias_id TEXT NOT NULL CHECK (length(provider_alias_id) BETWEEN 1 AND 500),
    antecedent_name TEXT NOT NULL CHECK (length(antecedent_name) BETWEEN 1 AND 500),
    consequent_name TEXT NOT NULL CHECK (length(consequent_name) BETWEEN 1 AND 500),
    status TEXT NOT NULL CHECK (length(status) BETWEEN 1 AND 100),
    post_count INTEGER CHECK (post_count IS NULL OR post_count >= 0),
    creator_id TEXT CHECK (creator_id IS NULL OR length(creator_id) BETWEEN 1 AND 500),
    created_at TEXT,
    updated_at TEXT,
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 1000),
    forum_topic_id INTEGER CHECK (forum_topic_id IS NULL OR forum_topic_id >= 0),
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (platform_id, provider_alias_id, observation_digest)
);

CREATE INDEX tag_alias_observations_lookup_idx
    ON tag_alias_observations(platform_id, antecedent_name, status, observed_at);

ALTER TABLE attribution_snapshots ADD COLUMN is_banned INTEGER
    CHECK (is_banned IS NULL OR is_banned IN (0, 1));
ALTER TABLE attribution_snapshots ADD COLUMN is_locked INTEGER
    CHECK (is_locked IS NULL OR is_locked IN (0, 1));
ALTER TABLE attribution_snapshots ADD COLUMN linked_user_id TEXT;
ALTER TABLE attribution_snapshots ADD COLUMN provider_created_at TEXT;
ALTER TABLE attribution_snapshots ADD COLUMN provider_updated_at TEXT;

CREATE TRIGGER tag_alias_observations_immutable
BEFORE UPDATE ON tag_alias_observations
BEGIN
    SELECT RAISE(ABORT, 'tag alias observations are immutable');
END;

CREATE TRIGGER tag_alias_observations_no_delete
BEFORE DELETE ON tag_alias_observations
BEGIN
    SELECT RAISE(ABORT, 'tag alias observations are immutable');
END;

-- ---------------------------------------------------------------------------
-- Typed post score/count/flag/pool observations
-- ---------------------------------------------------------------------------

CREATE TABLE post_metadata_observations (
    post_metadata_observation_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    score_up INTEGER CHECK (score_up IS NULL OR score_up >= 0),
    score_down INTEGER CHECK (score_down IS NULL OR score_down >= 0),
    score_total INTEGER,
    favorite_count INTEGER CHECK (favorite_count IS NULL OR favorite_count >= 0),
    comment_count INTEGER CHECK (comment_count IS NULL OR comment_count >= 0),
    flag_deleted INTEGER CHECK (flag_deleted IS NULL OR flag_deleted IN (0, 1)),
    flag_pending INTEGER CHECK (flag_pending IS NULL OR flag_pending IN (0, 1)),
    flag_flagged INTEGER CHECK (flag_flagged IS NULL OR flag_flagged IN (0, 1)),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (post_id, observation_digest)
);

CREATE INDEX post_metadata_observations_post_idx
    ON post_metadata_observations(post_id, observed_at);

CREATE TABLE post_pool_observations (
    post_pool_observation_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    pool_native_id TEXT NOT NULL CHECK (length(pool_native_id) BETWEEN 1 AND 500),
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (post_id, pool_native_id, observation_digest)
);

CREATE INDEX post_pool_observations_post_idx
    ON post_pool_observations(post_id, observed_at);

CREATE TABLE post_flag_observations (
    post_flag_observation_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    flag_name TEXT NOT NULL CHECK (length(flag_name) BETWEEN 1 AND 200),
    flag_value INTEGER NOT NULL CHECK (flag_value IN (0, 1)),
    observed_at TEXT NOT NULL,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    observation_digest TEXT NOT NULL CHECK (length(observation_digest) = 64),
    UNIQUE (post_id, flag_name, observation_digest)
);

CREATE INDEX post_flag_observations_post_idx
    ON post_flag_observations(post_id, flag_name, observed_at);

CREATE TRIGGER post_metadata_observations_immutable
BEFORE UPDATE ON post_metadata_observations
BEGIN
    SELECT RAISE(ABORT, 'post metadata observations are immutable');
END;

CREATE TRIGGER post_metadata_observations_no_delete
BEFORE DELETE ON post_metadata_observations
BEGIN
    SELECT RAISE(ABORT, 'post metadata observations are immutable');
END;

CREATE TRIGGER post_pool_observations_immutable
BEFORE UPDATE ON post_pool_observations
BEGIN
    SELECT RAISE(ABORT, 'post pool observations are immutable');
END;

CREATE TRIGGER post_pool_observations_no_delete
BEFORE DELETE ON post_pool_observations
BEGIN
    SELECT RAISE(ABORT, 'post pool observations are immutable');
END;

CREATE TRIGGER post_flag_observations_immutable
BEFORE UPDATE ON post_flag_observations
BEGIN
    SELECT RAISE(ABORT, 'post flag observations are immutable');
END;

CREATE TRIGGER post_flag_observations_no_delete
BEFORE DELETE ON post_flag_observations
BEGIN
    SELECT RAISE(ABORT, 'post flag observations are immutable');
END;
