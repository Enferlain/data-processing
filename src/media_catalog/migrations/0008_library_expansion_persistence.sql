-- Artist-library expansion persistence is additive.  Existing import runs,
-- accounts, posts, media occurrences, raw payloads, remote metadata/acquisition
-- tables, and bounded candidate-lookup tables keep their ids, constraints, and
-- behavior.  This migration stores immutable expansion provenance -- plans,
-- count probes, and execution/resume lineage -- and records the optional
-- internal origin of a metadata remote run so an expansion and its remote run
-- are associated at creation rather than repaired after a crash.
--
-- Expansion tables do not duplicate remote-run status, counters, checkpoints,
-- or raw payloads.  Execution and resume state is derived by joining the unique
-- remote_run reference to existing remote_runs/remote_checkpoints rows.

-- ---------------------------------------------------------------------------
-- Optional internal origin on remote metadata runs (additive)
-- ---------------------------------------------------------------------------

-- A standalone metadata run keeps a NULL origin.  An expansion-originated run
-- records its kind and the expansion plan digest so the run can be traced to its
-- plan without scanning execution rows.  Both columns are nullable with NULL
-- defaults, so existing remote_runs rows and standalone callers are unchanged.
-- The columns are added without inline CHECK constraints because SQLite does not
-- allow a CHECK on ALTER TABLE ADD COLUMN that cannot be verified against
-- existing rows; the origin shape is enforced by the triggers below and by the
-- application record layer.
ALTER TABLE remote_runs ADD COLUMN origin_kind TEXT;
ALTER TABLE remote_runs ADD COLUMN origin_reference TEXT COLLATE NOCASE;

-- An origin is either absent (standalone metadata run) or supplied as a kind
-- plus a stable reference together.
CREATE TRIGGER remote_runs_origin_consistent
BEFORE INSERT ON remote_runs
WHEN (NEW.origin_kind IS NULL) != (NEW.origin_reference IS NULL)
BEGIN
    SELECT RAISE(ABORT, 'remote run origin kind and reference must be supplied together');
END;

-- A supplied origin kind belongs to a closed vocabulary.  NULL (standalone run)
-- is always permitted.
CREATE TRIGGER remote_runs_origin_kind_vocabulary
BEFORE INSERT ON remote_runs
WHEN NEW.origin_kind IS NOT NULL AND NEW.origin_kind NOT IN ('library_expansion')
BEGIN
    SELECT RAISE(ABORT, 'unsupported remote run origin kind');
END;

-- A supplied origin reference is the stable 64-character expansion plan digest.
-- The 64-character lowercase-hex shape is also validated by the record layer.
CREATE TRIGGER remote_runs_origin_reference_length
BEFORE INSERT ON remote_runs
WHEN NEW.origin_reference IS NOT NULL AND length(NEW.origin_reference) != 64
BEGIN
    SELECT RAISE(ABORT, 'remote run origin reference must be 64 characters');
END;

-- The origin is recorded at run creation and never re-paired afterwards; the
-- existing remote-run UPDATE path advances status/counters without touching it.
CREATE TRIGGER remote_runs_origin_immutable
BEFORE UPDATE ON remote_runs
WHEN NEW.origin_kind IS NOT OLD.origin_kind
  OR NEW.origin_reference IS NOT OLD.origin_reference
BEGIN
    SELECT RAISE(ABORT, 'remote run origin is immutable');
END;

CREATE INDEX remote_runs_origin_idx
    ON remote_runs(origin_kind, origin_reference)
    WHERE origin_kind IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Immutable library expansion plans
-- ---------------------------------------------------------------------------

CREATE TABLE library_expansion_plans (
    library_expansion_plan_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    target_kind TEXT NOT NULL CHECK (target_kind IN ('account', 'attribution')),
    -- the plan references exactly one typed internal catalog target.  The
    -- platform/native text below is retained as descriptive provenance; the
    -- typed id (not the text) is the authoritative catalog reference.
    target_account_id INTEGER REFERENCES accounts(account_id),
    target_attribution_id INTEGER REFERENCES attribution_entities(attribution_entity_id),
    seed_account_id INTEGER REFERENCES accounts(account_id),
    seed_post_id INTEGER REFERENCES posts(post_id),
    seed_revision TEXT NOT NULL CHECK (length(seed_revision) BETWEEN 1 AND 200),
    authority_mode TEXT NOT NULL CHECK (authority_mode IN ('confirmed', 'explicit')),
    authority_reference TEXT CHECK (
        authority_reference IS NULL OR length(authority_reference) BETWEEN 1 AND 500
    ),
    selection_note TEXT CHECK (selection_note IS NULL OR length(selection_note) <= 1000),
    capability_key TEXT NOT NULL CHECK (length(capability_key) BETWEEN 1 AND 200),
    capability_version TEXT NOT NULL CHECK (length(capability_version) BETWEEN 1 AND 200),
    target_native_id TEXT NOT NULL CHECK (length(target_native_id) BETWEEN 1 AND 500),
    target_revision TEXT NOT NULL CHECK (length(target_revision) BETWEEN 1 AND 200),
    adapter_version TEXT NOT NULL CHECK (length(adapter_version) BETWEEN 1 AND 200),
    schema_version TEXT NOT NULL CHECK (length(schema_version) BETWEEN 1 AND 200),
    source_revision TEXT NOT NULL CHECK (length(source_revision) BETWEEN 1 AND 200),
    request_limit INTEGER NOT NULL CHECK (request_limit > 0),
    page_limit INTEGER NOT NULL CHECK (page_limit > 0),
    record_limit INTEGER NOT NULL CHECK (record_limit > 0),
    time_limit_seconds INTEGER NOT NULL CHECK (time_limit_seconds > 0),
    estimate_state TEXT NOT NULL CHECK (estimate_state IN ('count', 'unknown')),
    estimate_count INTEGER CHECK (estimate_count IS NULL OR estimate_count >= 0),
    estimate_observed_at TEXT,
    estimate_source TEXT CHECK (
        estimate_source IS NULL OR estimate_source IN ('retained_probe', 'provider_estimate')
    ),
    exclusions_json TEXT NOT NULL,
    plan_digest TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(plan_digest) = 64),
    material_digest TEXT NOT NULL COLLATE NOCASE CHECK (length(material_digest) = 64),
    created_at TEXT NOT NULL,
    -- exactly one catalog seed authorizes an expansion plan
    CHECK (
        (seed_account_id IS NOT NULL AND seed_post_id IS NULL)
        OR (seed_account_id IS NULL AND seed_post_id IS NOT NULL)
    ),
    -- the plan references exactly one typed internal target and its kind matches
    -- that target; an account target never masquerades as an attribution (or vice versa)
    CHECK (
        (target_kind = 'account'
            AND target_account_id IS NOT NULL
            AND target_attribution_id IS NULL)
        OR (target_kind = 'attribution'
            AND target_attribution_id IS NOT NULL
            AND target_account_id IS NULL)
    ),
    -- confirmed authority references a review decision/evidence path; an
    -- explicit selection asserts no relationship and carries only a note
    CHECK (
        (authority_mode = 'confirmed' AND authority_reference IS NOT NULL)
        OR (authority_mode = 'explicit' AND authority_reference IS NULL)
    ),
    -- a retained count carries its value, observation time, and source; the
    -- absence of a retained estimate is represented explicitly as unknown
    CHECK (
        (estimate_state = 'count'
            AND estimate_count IS NOT NULL
            AND estimate_observed_at IS NOT NULL
            AND estimate_source IS NOT NULL)
        OR (estimate_state = 'unknown'
            AND estimate_count IS NULL
            AND estimate_observed_at IS NULL
            AND estimate_source IS NULL)
    )
);

CREATE INDEX library_expansion_plans_target_idx
    ON library_expansion_plans(platform_id, instance_host, target_kind, created_at);
CREATE INDEX library_expansion_plans_target_account_idx
    ON library_expansion_plans(target_account_id)
    WHERE target_account_id IS NOT NULL;
CREATE INDEX library_expansion_plans_target_attribution_idx
    ON library_expansion_plans(target_attribution_id)
    WHERE target_attribution_id IS NOT NULL;
CREATE INDEX library_expansion_plans_digest_idx
    ON library_expansion_plans(plan_digest);
CREATE INDEX library_expansion_plans_seed_account_idx
    ON library_expansion_plans(seed_account_id)
    WHERE seed_account_id IS NOT NULL;
CREATE INDEX library_expansion_plans_seed_post_idx
    ON library_expansion_plans(seed_post_id)
    WHERE seed_post_id IS NOT NULL;

-- A plan is an immutable offline snapshot: every column is fixed at creation.
CREATE TRIGGER library_expansion_plans_immutable
BEFORE UPDATE ON library_expansion_plans
BEGIN
    SELECT RAISE(ABORT, 'library expansion plans are immutable');
END;

-- ---------------------------------------------------------------------------
-- Optional explicit count probes (one bounded observation per probe)
-- ---------------------------------------------------------------------------

CREATE TABLE library_expansion_probes (
    library_expansion_probe_id INTEGER PRIMARY KEY,
    library_expansion_plan_id INTEGER NOT NULL
        REFERENCES library_expansion_plans(library_expansion_plan_id) ON DELETE CASCADE,
    capability_key TEXT NOT NULL CHECK (length(capability_key) BETWEEN 1 AND 200),
    capability_version TEXT NOT NULL CHECK (length(capability_version) BETWEEN 1 AND 200),
    adapter_version TEXT NOT NULL CHECK (length(adapter_version) BETWEEN 1 AND 200),
    schema_version TEXT NOT NULL CHECK (length(schema_version) BETWEEN 1 AND 200),
    request_limit INTEGER NOT NULL CHECK (request_limit > 0),
    time_limit_seconds INTEGER NOT NULL CHECK (time_limit_seconds > 0),
    outcome TEXT NOT NULL CHECK (outcome IN (
        'success', 'unsupported', 'unavailable', 'deleted', 'authentication_required',
        'authorization_denied', 'rate_limited', 'transient_provider',
        'malformed_response', 'local_persistence'
    )),
    status_code INTEGER CHECK (status_code IS NULL OR status_code BETWEEN 100 AND 599),
    count_value INTEGER CHECK (count_value IS NULL OR count_value >= 0),
    retry_after TEXT,
    request_identity TEXT CHECK (
        request_identity IS NULL OR length(request_identity) BETWEEN 1 AND 1000
    ),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    diagnostic_summary TEXT CHECK (
        diagnostic_summary IS NULL OR length(diagnostic_summary) <= 1000
    ),
    requested_at TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    -- a successful probe retains a timestamped count; any other outcome has none
    CHECK (
        (outcome = 'success' AND count_value IS NOT NULL)
        OR (outcome != 'success' AND count_value IS NULL)
    ),
    -- an unsupported capability makes no provider request and retains nothing;
    -- any other outcome records the sanitized request identity it made
    CHECK (
        (outcome = 'unsupported'
            AND request_identity IS NULL
            AND status_code IS NULL
            AND raw_observation_id IS NULL)
        OR (outcome != 'unsupported' AND request_identity IS NOT NULL)
    ),
    -- a retained raw response is only meaningful when a request was made
    CHECK (raw_observation_id IS NULL OR request_identity IS NOT NULL),
    -- retry guidance is only meaningful for a rate-limited probe
    CHECK (retry_after IS NULL OR outcome = 'rate_limited')
);

CREATE INDEX library_expansion_probes_plan_idx
    ON library_expansion_probes(library_expansion_plan_id, library_expansion_probe_id);
CREATE INDEX library_expansion_probes_raw_observation_idx
    ON library_expansion_probes(raw_observation_id)
    WHERE raw_observation_id IS NOT NULL;

-- A probe is an immutable provider observation retained as audit history.
CREATE TRIGGER library_expansion_probes_immutable
BEFORE UPDATE ON library_expansion_probes
BEGIN
    SELECT RAISE(ABORT, 'library expansion probes are immutable');
END;

-- ---------------------------------------------------------------------------
-- Execution and resume lineage (status derived from the linked remote run)
-- ---------------------------------------------------------------------------

CREATE TABLE library_expansion_executions (
    library_expansion_execution_id INTEGER PRIMARY KEY,
    library_expansion_plan_id INTEGER NOT NULL
        REFERENCES library_expansion_plans(library_expansion_plan_id) ON DELETE CASCADE,
    remote_run_id INTEGER NOT NULL REFERENCES remote_runs(remote_run_id),
    predecessor_execution_id INTEGER
        REFERENCES library_expansion_executions(library_expansion_execution_id),
    execution_kind TEXT NOT NULL CHECK (execution_kind IN ('initial', 'resume')),
    created_at TEXT NOT NULL,
    -- one execution lineage entry per underlying remote run
    UNIQUE (remote_run_id),
    -- an initial execution starts a lineage; a resume continues a prior one
    CHECK (
        (execution_kind = 'initial' AND predecessor_execution_id IS NULL)
        OR (execution_kind = 'resume' AND predecessor_execution_id IS NOT NULL)
    )
);

CREATE INDEX library_expansion_executions_plan_idx
    ON library_expansion_executions(library_expansion_plan_id, library_expansion_execution_id);
CREATE INDEX library_expansion_executions_predecessor_idx
    ON library_expansion_executions(predecessor_execution_id)
    WHERE predecessor_execution_id IS NOT NULL;

-- Execution lineage is immutable once the remote run association is recorded;
-- status and continuation are derived from the linked remote run.
CREATE TRIGGER library_expansion_executions_immutable
BEFORE UPDATE ON library_expansion_executions
BEGIN
    SELECT RAISE(ABORT, 'library expansion executions are immutable');
END;

-- The remote run is created with the immutable plan digest as its origin.  This
-- makes an interrupted run recoverable even if the process stops before the
-- execution association itself is inserted.
CREATE TRIGGER library_expansion_execution_origin_matches
BEFORE INSERT ON library_expansion_executions
WHEN NOT EXISTS (
    SELECT 1
      FROM library_expansion_plans plan
      JOIN remote_runs run ON run.remote_run_id = NEW.remote_run_id
     WHERE plan.library_expansion_plan_id = NEW.library_expansion_plan_id
       AND run.origin_kind = 'library_expansion'
       AND run.origin_reference = plan.plan_digest
)
BEGIN
    SELECT RAISE(ABORT, 'library expansion remote run origin does not match its plan');
END;

CREATE TRIGGER library_expansion_execution_lineage_matches
BEFORE INSERT ON library_expansion_executions
WHEN (
    (NEW.execution_kind = 'initial' AND (
        SELECT resumed_from_run_id FROM remote_runs WHERE remote_run_id = NEW.remote_run_id
    ) IS NOT NULL)
    OR (NEW.execution_kind = 'resume' AND NOT EXISTS (
        SELECT 1
          FROM library_expansion_executions predecessor
          JOIN remote_runs run ON run.remote_run_id = NEW.remote_run_id
         WHERE predecessor.library_expansion_execution_id = NEW.predecessor_execution_id
           AND predecessor.library_expansion_plan_id = NEW.library_expansion_plan_id
           AND run.resumed_from_run_id = predecessor.remote_run_id
    ))
)
BEGIN
    SELECT RAISE(ABORT, 'library expansion execution lineage is incompatible');
END;

-- ---------------------------------------------------------------------------
-- Immutable expansion-to-post associations (one row per committed listing post)
-- ---------------------------------------------------------------------------

-- Each row records that a single catalog post was discovered and committed by a
-- specific expansion execution, with the raw observation of the normalized
-- listing page that produced it.  The post and occurrence data themselves are
-- not copied; downstream browsing/acquisition join through this association and
-- the execution's plan to reach the typed target.  A post whose listing summary
-- lacked occurrence details is flagged so the caller can request an explicit
-- detail synchronization rather than inventing an occurrence.
CREATE TABLE library_expansion_posts (
    library_expansion_post_id INTEGER PRIMARY KEY,
    library_expansion_execution_id INTEGER NOT NULL REFERENCES
        library_expansion_executions(library_expansion_execution_id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(post_id),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    details_required INTEGER NOT NULL DEFAULT 0 CHECK (details_required IN (0, 1)),
    observed_at TEXT NOT NULL,
    -- a discovered post is associated with an execution at most once
    UNIQUE (library_expansion_execution_id, post_id)
);

CREATE INDEX library_expansion_posts_execution_idx
    ON library_expansion_posts(library_expansion_execution_id, library_expansion_post_id);
CREATE INDEX library_expansion_posts_post_idx
    ON library_expansion_posts(post_id);

-- An expansion-to-post association is durable audit history; resume re-issues an
-- existing association idempotently (ON CONFLICT DO NOTHING) rather than
-- mutating the recorded provenance.
CREATE TRIGGER library_expansion_posts_immutable
BEFORE UPDATE ON library_expansion_posts
BEGIN
    SELECT RAISE(ABORT, 'library expansion posts are immutable');
END;
