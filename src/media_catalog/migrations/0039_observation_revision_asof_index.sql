-- As-of revision playback index (bead data-processing-i94, change
-- add-observation-revision-asof-index): the as-of query -- latest revision
-- of one observation at or before a cutoff -- resolves as a single
-- indexed seek instead of a table scan.  The append-only triggers
-- on raw_observations and observation_revisions already exist (0013-era
-- audit immutability); this migration adds only the index.  Additive and
-- replay-safe.

CREATE INDEX IF NOT EXISTS idx_observation_revisions_observation_playback
    ON observation_revisions(observation_id, observation_revision_id DESC);
