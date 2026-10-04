-- Close the provenance-kernel storage-enforcement gaps (Bead data-processing-ts5).
-- Additive triggers only: no data changes, no table rebuilds.  The enforcement
-- strength of each surface follows the writer audit -- tables whose current
-- fields legitimately update (provenance events, adoption attempts, candidates,
-- evidence, evidence links) get no-DELETE guards only; insert-only audit rows
-- are fully immutable; remote requests may only attach their retained source
-- report after insert; remote-run declared inputs are immutable while state,
-- counters, outcome, retry guidance, diagnostic, and finish time advance.

-- ---------------------------------------------------------------------------
-- Insert-only audit surfaces: immutable and undeletable (0009-style)
-- ---------------------------------------------------------------------------

CREATE TRIGGER raw_observations_immutable
BEFORE UPDATE ON raw_observations
BEGIN
    SELECT RAISE(ABORT, 'source reports are append-only');
END;

CREATE TRIGGER raw_observations_no_delete
BEFORE DELETE ON raw_observations
BEGIN
    SELECT RAISE(ABORT, 'source reports are append-only');
END;

CREATE TRIGGER post_tag_observations_immutable
BEFORE UPDATE ON post_tag_observations
BEGIN
    SELECT RAISE(ABORT, 'post tag observations are append-only');
END;

CREATE TRIGGER post_tag_observations_no_delete
BEFORE DELETE ON post_tag_observations
BEGIN
    SELECT RAISE(ABORT, 'post tag observations are append-only');
END;

CREATE TRIGGER observation_revisions_immutable
BEFORE UPDATE ON observation_revisions
BEGIN
    SELECT RAISE(ABORT, 'provenance event revisions are append-only');
END;

CREATE TRIGGER observation_revisions_no_delete
BEFORE DELETE ON observation_revisions
BEGIN
    SELECT RAISE(ABORT, 'provenance event revisions are append-only');
END;

CREATE TRIGGER account_candidate_decisions_immutable
BEFORE UPDATE ON account_candidate_decisions
BEGIN
    SELECT RAISE(ABORT, 'account review decisions are append-only');
END;

CREATE TRIGGER account_candidate_decisions_no_delete
BEFORE DELETE ON account_candidate_decisions
BEGIN
    SELECT RAISE(ABORT, 'account review decisions are append-only');
END;

CREATE TRIGGER post_candidate_decisions_immutable
BEFORE UPDATE ON post_candidate_decisions
BEGIN
    SELECT RAISE(ABORT, 'post review decisions are append-only');
END;

CREATE TRIGGER post_candidate_decisions_no_delete
BEFORE DELETE ON post_candidate_decisions
BEGIN
    SELECT RAISE(ABORT, 'post review decisions are append-only');
END;

-- ---------------------------------------------------------------------------
-- Current-field surfaces: never deleted, updates stay possible
-- ---------------------------------------------------------------------------

CREATE TRIGGER observations_no_delete
BEFORE DELETE ON observations
BEGIN
    SELECT RAISE(ABORT, 'provenance events cannot be deleted');
END;

CREATE TRIGGER adoption_attempts_no_delete
BEFORE DELETE ON adoption_attempts
BEGIN
    SELECT RAISE(ABORT, 'adoption attempts cannot be deleted');
END;

CREATE TRIGGER account_match_candidates_no_delete
BEFORE DELETE ON account_match_candidates
BEGIN
    SELECT RAISE(ABORT, 'account match candidates cannot be deleted');
END;

CREATE TRIGGER post_match_candidates_no_delete
BEFORE DELETE ON post_match_candidates
BEGIN
    SELECT RAISE(ABORT, 'post match candidates cannot be deleted');
END;

CREATE TRIGGER match_evidence_no_delete
BEFORE DELETE ON match_evidence
BEGIN
    SELECT RAISE(ABORT, 'match evidence cannot be deleted');
END;

CREATE TRIGGER account_candidate_evidence_no_delete
BEFORE DELETE ON account_candidate_evidence
BEGIN
    SELECT RAISE(ABORT, 'account candidate evidence links cannot be deleted');
END;

CREATE TRIGGER post_candidate_evidence_no_delete
BEFORE DELETE ON post_candidate_evidence
BEGIN
    SELECT RAISE(ABORT, 'post candidate evidence links cannot be deleted');
END;

-- ---------------------------------------------------------------------------
-- Remote requests: immutable after insert except attaching the retained
-- source report (raw_observation_id from NULL) -- the writer's two-step for
-- the circular raw_observations.remote_request_id reference.
-- ---------------------------------------------------------------------------

CREATE TRIGGER remote_requests_immutable_fields
BEFORE UPDATE ON remote_requests
WHEN NEW.remote_run_id IS NOT OLD.remote_run_id
  OR NEW.attempt_number IS NOT OLD.attempt_number
  OR NEW.request_identity IS NOT OLD.request_identity
  OR NEW.operation IS NOT OLD.operation
  OR NEW.target IS NOT OLD.target
  OR NEW.status_code IS NOT OLD.status_code
  OR NEW.outcome IS NOT OLD.outcome
  OR NEW.retry_after IS NOT OLD.retry_after
  OR NEW.rate_limit_state IS NOT OLD.rate_limit_state
  OR NEW.response_adapter_version IS NOT OLD.response_adapter_version
  OR NEW.response_schema_version IS NOT OLD.response_schema_version
  OR NEW.object_kind IS NOT OLD.object_kind
  OR NEW.native_id IS NOT OLD.native_id
  OR NEW.media_type IS NOT OLD.media_type
  OR NEW.response_size IS NOT OLD.response_size
  OR NEW.remote_checkpoint_id IS NOT OLD.remote_checkpoint_id
  OR NEW.request_started_at IS NOT OLD.request_started_at
  OR NEW.response_observed_at IS NOT OLD.response_observed_at
  OR NEW.request_finished_at IS NOT OLD.request_finished_at
  OR NEW.transport_key IS NOT OLD.transport_key
  OR NEW.transport_version IS NOT OLD.transport_version
  OR NEW.remote_request_id IS NOT OLD.remote_request_id
  OR (NEW.raw_observation_id IS NOT OLD.raw_observation_id
      AND OLD.raw_observation_id IS NOT NULL)
BEGIN
    SELECT RAISE(ABORT, 'remote request fields are immutable');
END;

CREATE TRIGGER remote_requests_no_delete
BEFORE DELETE ON remote_requests
BEGIN
    SELECT RAISE(ABORT, 'remote requests cannot be deleted');
END;

-- ---------------------------------------------------------------------------
-- Remote runs: declared inputs are immutable once the run begins (0007/0006
-- pattern; origin columns are already covered by the 0008/0010 triggers).
-- ---------------------------------------------------------------------------

CREATE TRIGGER remote_runs_immutable_inputs
BEFORE UPDATE ON remote_runs
WHEN NEW.platform_id IS NOT OLD.platform_id
  OR NEW.instance_host IS NOT OLD.instance_host
  OR NEW.operation IS NOT OLD.operation
  OR NEW.target IS NOT OLD.target
  OR NEW.adapter_version IS NOT OLD.adapter_version
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.request_budget IS NOT OLD.request_budget
  OR NEW.page_budget IS NOT OLD.page_budget
  OR NEW.record_budget IS NOT OLD.record_budget
  OR NEW.time_budget_seconds IS NOT OLD.time_budget_seconds
  OR NEW.started_at IS NOT OLD.started_at
  OR NEW.resumed_from_run_id IS NOT OLD.resumed_from_run_id
  OR NEW.transport_key IS NOT OLD.transport_key
  OR NEW.transport_version IS NOT OLD.transport_version
  OR NEW.remote_run_id IS NOT OLD.remote_run_id
BEGIN
    SELECT RAISE(ABORT, 'remote run inputs are immutable');
END;
