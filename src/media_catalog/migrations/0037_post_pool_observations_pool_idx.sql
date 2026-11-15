-- Pool co-membership lookup index (bead data-processing-rip, change
-- add-pool-membership-evidence): the pool_member labeling family pairs
-- observations by pool_native_id, which had no index (only post-side).
-- Without it the pairing join degenerates on the posts join; with it the
-- family scan is an index seek per pool.  Additive, replay-safe.

CREATE INDEX IF NOT EXISTS idx_post_pool_observations_pool
    ON post_pool_observations(pool_native_id, post_id);
