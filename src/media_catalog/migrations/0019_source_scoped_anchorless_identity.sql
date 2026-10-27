-- Source-scoped anchorless identity (Bead data-processing-7o0).
--
-- 0018 made anchorless raw-observation identity content addressing over
-- (object_kind, native_id, payload) -- but that key conflates sources: the
-- real catalog holds danbooru/aibooru candidate-lookup groups where both
-- instances returned byte-identical bodies, so the second source's
-- observation could never land and the shared row kept the first writer's
-- platform attribution.  An observation is "this source reported these
-- bytes"; the source belongs in the identity.  Sharing remains, scoped to a
-- source: retries and re-probes against the SAME source resolve to one
-- observation referenced by any number of requesting rows; different
-- sources never fold.
--
-- Index-only change: drop 0018's two partial unique indexes, create
-- platform-scoped replacements with the same anchorless WHERE clauses.  A
-- catalog that still holds 0018-definition duplicates fails at 0018 first;
-- repair out of band first (scripts/repair_anchorless_observations.py).

DROP INDEX IF EXISTS raw_observations_anchorless_native_idx;
DROP INDEX IF EXISTS raw_observations_anchorless_anonymous_idx;

CREATE UNIQUE INDEX raw_observations_anchorless_native_idx
    ON raw_observations(platform_id, object_kind, native_id, raw_payload_id)
    WHERE import_run_id IS NULL AND remote_run_id IS NULL
      AND remote_request_id IS NULL AND native_id IS NOT NULL;

CREATE UNIQUE INDEX raw_observations_anchorless_anonymous_idx
    ON raw_observations(platform_id, object_kind, raw_payload_id)
    WHERE import_run_id IS NULL AND remote_run_id IS NULL
      AND remote_request_id IS NULL AND native_id IS NULL;
