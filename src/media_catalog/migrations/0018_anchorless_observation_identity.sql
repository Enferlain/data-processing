-- Anchorless raw-observation identity (spike F4, Bead data-processing-40x).
--
-- store_raw dedups observations on (import_run_id, object_kind, native_id,
-- raw_payload_id), but rows with no import run and no remote run/request carry
-- NULL in that key, and SQLite treats NULLs as distinct: re-intake of
-- byte-identical payloads appended a new observation row each time while the
-- payload itself deduplicated.  Anchorless identity is now content
-- addressing -- object kind, native id when present, and payload bytes --
-- enforced by two disjoint partial unique indexes.  Rows anchored to an import
-- run or a remote request keep the pre-existing identity and are excluded
-- here.  Creating these indexes fails loudly on a catalog that already holds
-- anchorless duplicates, and legitimate flows produce them: candidate-lookup
-- retention (candidate_lookup/service.py) and library count probes
-- (library/probes.py) store anchorless observations, so a re-probe or retry
-- with byte-identical bytes duplicated rows under the old identity.  Sharing
-- one content-addressed observation across requests and probes is safe (their
-- references are non-unique), but repairing a pre-damaged catalog is out-of-
-- band surgery, not a migration: drop the 0012 immutability triggers, remove
-- or re-point the duplicate anchorless rows, recreate the triggers, then
-- migrate.

CREATE UNIQUE INDEX raw_observations_anchorless_native_idx
    ON raw_observations(object_kind, native_id, raw_payload_id)
    WHERE import_run_id IS NULL AND remote_run_id IS NULL
      AND remote_request_id IS NULL AND native_id IS NOT NULL;

CREATE UNIQUE INDEX raw_observations_anchorless_anonymous_idx
    ON raw_observations(object_kind, raw_payload_id)
    WHERE import_run_id IS NULL AND remote_run_id IS NULL
      AND remote_request_id IS NULL AND native_id IS NULL;
