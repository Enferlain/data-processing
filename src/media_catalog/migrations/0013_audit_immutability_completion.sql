-- Complete the audit-immutability sweep (Bead data-processing-5de).
-- Additive triggers plus two verbatim trigger recreations that add primary-key
-- guards to the 0006/0007 immutable-inputs triggers (matching 0012's stronger
-- pattern).  No data changes; the mutation sweep found zero delete statements
-- on every guarded surface and plain-insert-only writers for the two surfaces
-- gaining full immutability.

-- ---------------------------------------------------------------------------
-- Deletion guards for the pre-0012 update-only surfaces
-- ---------------------------------------------------------------------------

CREATE TRIGGER library_expansion_plans_no_delete
BEFORE DELETE ON library_expansion_plans
BEGIN
    SELECT RAISE(ABORT, 'library expansion plans cannot be deleted');
END;

CREATE TRIGGER library_expansion_probes_no_delete
BEFORE DELETE ON library_expansion_probes
BEGIN
    SELECT RAISE(ABORT, 'library expansion probes cannot be deleted');
END;

CREATE TRIGGER library_expansion_executions_no_delete
BEFORE DELETE ON library_expansion_executions
BEGIN
    SELECT RAISE(ABORT, 'library expansion executions cannot be deleted');
END;

CREATE TRIGGER library_expansion_posts_no_delete
BEFORE DELETE ON library_expansion_posts
BEGIN
    SELECT RAISE(ABORT, 'library expansion post associations cannot be deleted');
END;

CREATE TRIGGER candidate_lookup_requests_no_delete
BEFORE DELETE ON candidate_lookup_requests
BEGIN
    SELECT RAISE(ABORT, 'candidate lookup requests cannot be deleted');
END;

CREATE TRIGGER media_acquisition_attempts_no_delete
BEFORE DELETE ON media_acquisition_attempts
BEGIN
    SELECT RAISE(ABORT, 'media acquisition attempts cannot be deleted');
END;

-- ---------------------------------------------------------------------------
-- Full immutability for the plain-insert-only audit surfaces
-- ---------------------------------------------------------------------------

CREATE TRIGGER media_acquisition_verifications_immutable
BEFORE UPDATE ON media_acquisition_verifications
BEGIN
    SELECT RAISE(ABORT, 'acquisition verifications are append-only');
END;

CREATE TRIGGER media_acquisition_verifications_no_delete
BEFORE DELETE ON media_acquisition_verifications
BEGIN
    SELECT RAISE(ABORT, 'acquisition verifications are append-only');
END;

CREATE TRIGGER raw_payloads_immutable
BEFORE UPDATE ON raw_payloads
BEGIN
    SELECT RAISE(ABORT, 'source report payloads are append-only');
END;

CREATE TRIGGER raw_payloads_no_delete
BEFORE DELETE ON raw_payloads
BEGIN
    SELECT RAISE(ABORT, 'source report payloads are append-only');
END;

-- ---------------------------------------------------------------------------
-- Primary-key guards for the 0006/0007 immutable-inputs triggers, recreated
-- verbatim with one added disjunct each (the 0010 technique).
-- ---------------------------------------------------------------------------

DROP TRIGGER media_acquisition_runs_immutable_inputs;

CREATE TRIGGER media_acquisition_runs_immutable_inputs
BEFORE UPDATE ON media_acquisition_runs
WHEN NEW.acquisition_run_id IS NOT OLD.acquisition_run_id
  OR NEW.acquisition_plan_id != OLD.acquisition_plan_id
  OR NEW.managed_root_id != OLD.managed_root_id
  OR NEW.resumed_from_run_id IS NOT OLD.resumed_from_run_id
  OR NEW.max_items != OLD.max_items
  OR NEW.max_item_bytes != OLD.max_item_bytes
  OR NEW.max_total_bytes != OLD.max_total_bytes
  OR NEW.max_attempts_per_item != OLD.max_attempts_per_item
  OR NEW.max_seconds != OLD.max_seconds
  OR NEW.max_redirects != OLD.max_redirects
  OR NEW.max_quarantine_bytes != OLD.max_quarantine_bytes
  OR NEW.concurrency != OLD.concurrency
  OR NEW.started_at != OLD.started_at
BEGIN
    SELECT RAISE(ABORT, 'media acquisition run inputs are immutable');
END;

DROP TRIGGER candidate_lookup_runs_immutable_inputs;

CREATE TRIGGER candidate_lookup_runs_immutable_inputs
BEFORE UPDATE ON candidate_lookup_runs
WHEN NEW.candidate_lookup_run_id IS NOT OLD.candidate_lookup_run_id
  OR NEW.platform_id IS NOT OLD.platform_id
  OR NEW.instance_host IS NOT OLD.instance_host
  OR NEW.strategy IS NOT OLD.strategy
  OR NEW.strategy_version IS NOT OLD.strategy_version
  OR NEW.adapter_version IS NOT OLD.adapter_version
  OR NEW.schema_version IS NOT OLD.schema_version
  OR NEW.seed_account_id IS NOT OLD.seed_account_id
  OR NEW.seed_post_id IS NOT OLD.seed_post_id
  OR NEW.seed_revision IS NOT OLD.seed_revision
  OR NEW.plan_digest IS NOT OLD.plan_digest
  OR NEW.query_kind IS NOT OLD.query_kind
  OR NEW.material_digest IS NOT OLD.material_digest
  OR NEW.private_query_json IS NOT OLD.private_query_json
  OR NEW.predecessor_run_id IS NOT OLD.predecessor_run_id
  OR NEW.request_limit IS NOT OLD.request_limit
  OR NEW.page_limit IS NOT OLD.page_limit
  OR NEW.result_limit IS NOT OLD.result_limit
  OR NEW.time_limit_seconds IS NOT OLD.time_limit_seconds
  OR NEW.started_at IS NOT OLD.started_at
BEGIN
    SELECT RAISE(ABORT, 'candidate lookup run inputs are immutable');
END;
