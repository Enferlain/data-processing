-- e621-family live captures (2026-11-02, posts 6531990/6577789 et al.) show
-- the current wire reports negative downvote counts; the score_down CHECK
-- inherited from 0009 rejects them, failing every e621/e926 post
-- persistence that carries any downvote.  SQLite cannot ALTER a CHECK, so
-- the table is rebuilt (preserving rows, uniqueness, indexes, and the
-- immutability/no-delete triggers' table binding via drop+recreate).

CREATE TABLE post_metadata_observations_rebuilt (
    post_metadata_observation_id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    score_up INTEGER CHECK (score_up IS NULL OR score_up >= 0),
    -- downvote counts may legitimately be negative on the live wire
    score_down INTEGER,
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

INSERT INTO post_metadata_observations_rebuilt
    SELECT post_metadata_observation_id, post_id, observed_at, score_up,
           score_down, score_total, favorite_count, comment_count,
           flag_deleted, flag_pending, flag_flagged, raw_observation_id,
           observation_digest
      FROM post_metadata_observations;

DROP TRIGGER IF EXISTS post_metadata_observations_immutable;
DROP TRIGGER IF EXISTS post_metadata_observations_no_delete;
DROP TABLE post_metadata_observations;
ALTER TABLE post_metadata_observations_rebuilt
    RENAME TO post_metadata_observations;

CREATE INDEX post_metadata_observations_post_idx
    ON post_metadata_observations(post_id, observed_at);

CREATE TRIGGER post_metadata_observations_no_delete BEFORE DELETE ON post_metadata_observations
BEGIN
    SELECT RAISE(ABORT, 'post metadata observations are immutable');
END;

CREATE TRIGGER post_metadata_observations_immutable BEFORE UPDATE ON post_metadata_observations
BEGIN
    SELECT RAISE(ABORT, 'post metadata observations are immutable');
END;
