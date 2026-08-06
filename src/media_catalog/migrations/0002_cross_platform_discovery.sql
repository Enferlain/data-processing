INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url) VALUES
    ('pixiv', 'Pixiv', 'https://www.pixiv.net'),
    ('mastodon', 'Mastodon-compatible', NULL),
    ('danbooru', 'Danbooru-compatible', NULL),
    ('gelbooru', 'Gelbooru-compatible', NULL),
    ('e621', 'e621-compatible', NULL);

CREATE TABLE discovery_runs (
    discovery_run_id INTEGER PRIMARY KEY,
    extractor_version TEXT NOT NULL,
    canonicalizer_version TEXT NOT NULL,
    recognizer_version TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
    scanned_count INTEGER NOT NULL DEFAULT 0 CHECK (scanned_count >= 0),
    observed_count INTEGER NOT NULL DEFAULT 0 CHECK (observed_count >= 0),
    recognized_count INTEGER NOT NULL DEFAULT 0 CHECK (recognized_count >= 0),
    unresolved_count INTEGER NOT NULL DEFAULT 0 CHECK (unresolved_count >= 0),
    existing_count INTEGER NOT NULL DEFAULT 0 CHECK (existing_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    diagnostic TEXT CHECK (diagnostic IS NULL OR length(diagnostic) <= 1000)
);

CREATE TABLE external_links (
    external_link_id INTEGER PRIMARY KEY,
    canonical_url TEXT NOT NULL,
    canonicalization_version TEXT NOT NULL,
    resolution_state TEXT NOT NULL CHECK (
        resolution_state IN ('recognized', 'unresolved', 'invalid', 'redirect_required')
    ),
    resolution_reason TEXT CHECK (resolution_reason IS NULL OR length(resolution_reason) <= 500),
    UNIQUE (canonical_url, canonicalization_version)
);

CREATE TABLE link_observations (
    link_observation_id INTEGER PRIMARY KEY,
    external_link_id INTEGER NOT NULL REFERENCES external_links(external_link_id),
    discovery_run_id INTEGER NOT NULL REFERENCES discovery_runs(discovery_run_id),
    subject_kind TEXT NOT NULL CHECK (subject_kind IN ('account', 'post')),
    subject_account_id INTEGER REFERENCES accounts(account_id) ON DELETE CASCADE,
    subject_post_id INTEGER REFERENCES posts(post_id) ON DELETE CASCADE,
    account_snapshot_id INTEGER REFERENCES account_snapshots(account_snapshot_id),
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    source_context TEXT NOT NULL,
    json_path TEXT,
    original_url TEXT NOT NULL,
    original_query TEXT,
    original_fragment TEXT,
    observed_at TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    occurrence_digest TEXT NOT NULL CHECK (length(occurrence_digest) = 64),
    CHECK (
        (subject_kind = 'account' AND subject_account_id IS NOT NULL AND subject_post_id IS NULL) OR
        (subject_kind = 'post' AND subject_post_id IS NOT NULL AND subject_account_id IS NULL)
    ),
    UNIQUE (occurrence_digest, extractor_version)
);

CREATE TABLE platform_references (
    platform_reference_id INTEGER PRIMARY KEY,
    external_link_id INTEGER NOT NULL REFERENCES external_links(external_link_id),
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    object_kind TEXT NOT NULL CHECK (object_kind IN ('account', 'post', 'artist', 'media_asset')),
    native_identifier TEXT NOT NULL,
    canonical_target_url TEXT NOT NULL,
    recognizer_name TEXT NOT NULL,
    recognizer_version TEXT NOT NULL,
    resolved_account_id INTEGER REFERENCES accounts(account_id),
    resolved_post_id INTEGER REFERENCES posts(post_id),
    CHECK (NOT (resolved_account_id IS NOT NULL AND resolved_post_id IS NOT NULL)),
    CHECK (resolved_account_id IS NULL OR object_kind = 'account'),
    CHECK (resolved_post_id IS NULL OR object_kind = 'post'),
    UNIQUE (platform_id, instance_host, object_kind, native_identifier, recognizer_version)
);

CREATE TABLE identities (
    identity_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT
);

CREATE TABLE identity_accounts (
    identity_id INTEGER NOT NULL REFERENCES identities(identity_id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(account_id),
    account_candidate_id INTEGER REFERENCES account_match_candidates(account_candidate_id),
    decision_id INTEGER REFERENCES account_candidate_decisions(account_decision_id),
    added_at TEXT NOT NULL,
    PRIMARY KEY (identity_id, account_id),
    UNIQUE (account_id)
);

CREATE TABLE account_match_candidates (
    account_candidate_id INTEGER PRIMARY KEY,
    candidate_key TEXT NOT NULL UNIQUE CHECK (length(candidate_key) = 64),
    subject_account_id INTEGER NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    target_account_id INTEGER REFERENCES accounts(account_id),
    target_reference_id INTEGER REFERENCES platform_references(platform_reference_id),
    relation_kind TEXT NOT NULL CHECK (relation_kind IN ('same_identity', 'officially_linked')),
    current_state TEXT NOT NULL DEFAULT 'pending' CHECK (
        current_state IN ('pending', 'confirmed', 'rejected')
    ),
    score INTEGER NOT NULL DEFAULT 0,
    score_version TEXT NOT NULL,
    score_components_json TEXT NOT NULL DEFAULT '{}',
    evidence_generation INTEGER NOT NULL DEFAULT 0 CHECK (evidence_generation >= 0),
    review_revision INTEGER NOT NULL DEFAULT 0 CHECK (review_revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((target_account_id IS NULL) <> (target_reference_id IS NULL)),
    CHECK (target_account_id IS NULL OR target_account_id <> subject_account_id)
);

CREATE TABLE post_match_candidates (
    post_candidate_id INTEGER PRIMARY KEY,
    candidate_key TEXT NOT NULL UNIQUE CHECK (length(candidate_key) = 64),
    subject_post_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    target_post_id INTEGER REFERENCES posts(post_id),
    target_reference_id INTEGER REFERENCES platform_references(platform_reference_id),
    relation_kind TEXT NOT NULL CHECK (
        relation_kind IN ('sourced_from', 'same_work', 'repost_of', 'variant_of',
                          'derived_from', 'unresolved')
    ),
    current_state TEXT NOT NULL DEFAULT 'pending' CHECK (
        current_state IN ('pending', 'confirmed', 'rejected')
    ),
    score INTEGER NOT NULL DEFAULT 0,
    score_version TEXT NOT NULL,
    score_components_json TEXT NOT NULL DEFAULT '{}',
    evidence_generation INTEGER NOT NULL DEFAULT 0 CHECK (evidence_generation >= 0),
    review_revision INTEGER NOT NULL DEFAULT 0 CHECK (review_revision >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((target_post_id IS NULL) <> (target_reference_id IS NULL)),
    CHECK (target_post_id IS NULL OR target_post_id <> subject_post_id)
);

CREATE TABLE match_evidence (
    evidence_id INTEGER PRIMARY KEY,
    evidence_digest TEXT NOT NULL UNIQUE CHECK (length(evidence_digest) = 64),
    stance TEXT NOT NULL CHECK (stance IN ('supports', 'contradicts', 'neutral')),
    evidence_kind TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('subject_to_target', 'symmetric', 'none')),
    strength TEXT NOT NULL CHECK (strength IN ('weak', 'moderate', 'strong', 'exact')),
    detector TEXT NOT NULL,
    detector_version TEXT NOT NULL,
    link_observation_id INTEGER REFERENCES link_observations(link_observation_id),
    platform_reference_id INTEGER REFERENCES platform_references(platform_reference_id),
    observed_at TEXT NOT NULL,
    explanation TEXT NOT NULL CHECK (length(explanation) <= 1000),
    components_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE account_candidate_evidence (
    account_candidate_id INTEGER NOT NULL REFERENCES account_match_candidates(account_candidate_id) ON DELETE CASCADE,
    evidence_id INTEGER NOT NULL REFERENCES match_evidence(evidence_id),
    PRIMARY KEY (account_candidate_id, evidence_id)
);

CREATE TABLE post_candidate_evidence (
    post_candidate_id INTEGER NOT NULL REFERENCES post_match_candidates(post_candidate_id) ON DELETE CASCADE,
    evidence_id INTEGER NOT NULL REFERENCES match_evidence(evidence_id),
    PRIMARY KEY (post_candidate_id, evidence_id)
);

CREATE TABLE post_candidate_characteristics (
    post_candidate_id INTEGER NOT NULL REFERENCES post_match_candidates(post_candidate_id) ON DELETE CASCADE,
    characteristic TEXT NOT NULL CHECK (
        characteristic IN ('exact_bytes', 'visual_similarity', 'resized', 'reencoded',
                           'text_added', 'text_removed', 'meaningful_edit', 'progression', 'unknown')
    ),
    direction TEXT NOT NULL DEFAULT 'none' CHECK (
        direction IN ('subject_to_target', 'target_to_subject', 'symmetric', 'none')
    ),
    source_label TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    PRIMARY KEY (post_candidate_id, characteristic, direction, source_label)
);

CREATE TABLE account_candidate_decisions (
    account_decision_id INTEGER PRIMARY KEY,
    account_candidate_id INTEGER NOT NULL REFERENCES account_match_candidates(account_candidate_id) ON DELETE CASCADE,
    prior_state TEXT NOT NULL CHECK (prior_state IN ('pending', 'confirmed', 'rejected')),
    decision TEXT NOT NULL CHECK (decision IN ('pending', 'confirmed', 'rejected')),
    evidence_generation INTEGER NOT NULL CHECK (evidence_generation >= 0),
    note TEXT CHECK (note IS NULL OR length(note) <= 2000),
    decided_at TEXT NOT NULL
);

CREATE TABLE post_candidate_decisions (
    post_decision_id INTEGER PRIMARY KEY,
    post_candidate_id INTEGER NOT NULL REFERENCES post_match_candidates(post_candidate_id) ON DELETE CASCADE,
    prior_state TEXT NOT NULL CHECK (prior_state IN ('pending', 'confirmed', 'rejected')),
    decision TEXT NOT NULL CHECK (decision IN ('pending', 'confirmed', 'rejected')),
    evidence_generation INTEGER NOT NULL CHECK (evidence_generation >= 0),
    note TEXT CHECK (note IS NULL OR length(note) <= 2000),
    decided_at TEXT NOT NULL
);

CREATE TRIGGER account_candidate_reference_kind_insert
BEFORE INSERT ON account_match_candidates WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'account'
        THEN RAISE(ABORT, 'account candidate target reference must be an account') END;
END;

CREATE TRIGGER post_candidate_reference_kind_insert
BEFORE INSERT ON post_match_candidates WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'post'
        THEN RAISE(ABORT, 'post candidate target reference must be a post') END;
END;

CREATE TRIGGER account_candidate_reference_kind_update
BEFORE UPDATE OF target_reference_id ON account_match_candidates
WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'account'
        THEN RAISE(ABORT, 'account candidate target reference must be an account') END;
END;

CREATE TRIGGER post_candidate_reference_kind_update
BEFORE UPDATE OF target_reference_id ON post_match_candidates
WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'post'
        THEN RAISE(ABORT, 'post candidate target reference must be a post') END;
END;

CREATE INDEX link_observations_subject_account_idx ON link_observations(subject_account_id, source_context);
CREATE INDEX link_observations_subject_post_idx ON link_observations(subject_post_id, source_context);
CREATE INDEX external_links_state_idx ON external_links(resolution_state);
CREATE INDEX platform_references_lookup_idx ON platform_references(platform_id, instance_host, object_kind);
CREATE INDEX account_candidates_state_idx ON account_match_candidates(current_state, score DESC);
CREATE INDEX post_candidates_state_idx ON post_match_candidates(current_state, score DESC);
CREATE INDEX account_decisions_candidate_idx ON account_candidate_decisions(account_candidate_id, account_decision_id);
CREATE INDEX post_decisions_candidate_idx ON post_candidate_decisions(post_candidate_id, post_decision_id);
