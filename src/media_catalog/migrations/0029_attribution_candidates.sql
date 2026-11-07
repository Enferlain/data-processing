-- Attribution-entity candidates (bead data-processing-s1j): a recognized
-- artist-record URL (attribution-subject link observation resolving to a
-- platform account reference) becomes a reviewable candidate asserting the
-- artist claims that account identity.  Mirrors the account candidate
-- tables; subject is the attribution entity, target is an account reference
-- (resolved account when the catalog knows one).

CREATE TABLE IF NOT EXISTS attribution_match_candidates (
    attribution_candidate_id INTEGER PRIMARY KEY,
    candidate_key TEXT NOT NULL UNIQUE CHECK (length(candidate_key) = 64),
    subject_attribution_id INTEGER NOT NULL
        REFERENCES attribution_entities(attribution_entity_id) ON DELETE CASCADE,
    target_account_id INTEGER REFERENCES accounts(account_id),
    target_reference_id INTEGER REFERENCES platform_references(platform_reference_id),
    relation_kind TEXT NOT NULL CHECK (relation_kind IN ('same_identity', 'officially_linked')),
    current_state TEXT NOT NULL DEFAULT 'pending' CHECK (
        current_state IN ('pending', 'confirmed', 'rejected')
    ),
    score INTEGER NOT NULL DEFAULT 0,
    score_version TEXT NOT NULL,
    score_components_json TEXT,
    evidence_generation INTEGER NOT NULL DEFAULT 0,
    review_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (target_account_id IS NOT NULL OR target_reference_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS attribution_candidates_subject_idx
    ON attribution_match_candidates(subject_attribution_id);
CREATE INDEX IF NOT EXISTS attribution_candidates_state_idx
    ON attribution_match_candidates(current_state);

CREATE TABLE IF NOT EXISTS attribution_candidate_evidence (
    attribution_candidate_id INTEGER NOT NULL
        REFERENCES attribution_match_candidates(attribution_candidate_id) ON DELETE CASCADE,
    evidence_id INTEGER NOT NULL REFERENCES match_evidence(evidence_id),
    PRIMARY KEY (attribution_candidate_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS attribution_candidate_decisions (
    attribution_decision_id INTEGER PRIMARY KEY,
    attribution_candidate_id INTEGER NOT NULL
        REFERENCES attribution_match_candidates(attribution_candidate_id) ON DELETE CASCADE,
    prior_state TEXT NOT NULL CHECK (prior_state IN ('pending', 'confirmed', 'rejected')),
    decision TEXT NOT NULL CHECK (decision IN ('pending', 'confirmed', 'rejected')),
    evidence_generation INTEGER NOT NULL CHECK (evidence_generation >= 0),
    note TEXT CHECK (note IS NULL OR length(note) <= 2000),
    decided_at TEXT NOT NULL
);

-- Storage-enforcement trigger family, mirroring the account candidate
-- tables (convention from the 2026-10-04 close-kernel-storage-enforcement
-- change): decisions append-only, candidates and evidence links
-- undeletable, target references must be account objects.
CREATE TRIGGER IF NOT EXISTS attribution_candidate_reference_kind_insert
BEFORE INSERT ON attribution_match_candidates WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'account'
        THEN RAISE(ABORT, 'attribution candidate target reference must be an account') END;
END;

CREATE TRIGGER IF NOT EXISTS attribution_candidate_reference_kind_update
BEFORE UPDATE OF target_reference_id ON attribution_match_candidates
WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'account'
        THEN RAISE(ABORT, 'attribution candidate target reference must be an account') END;
END;

CREATE TRIGGER IF NOT EXISTS attribution_candidate_decisions_immutable
BEFORE UPDATE ON attribution_candidate_decisions
BEGIN
    SELECT RAISE(ABORT, 'attribution review decisions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS attribution_candidate_decisions_no_delete
BEFORE DELETE ON attribution_candidate_decisions
BEGIN
    SELECT RAISE(ABORT, 'attribution review decisions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS attribution_match_candidates_no_delete
BEFORE DELETE ON attribution_match_candidates
BEGIN
    SELECT RAISE(ABORT, 'attribution match candidates cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS attribution_candidate_evidence_no_delete
BEFORE DELETE ON attribution_candidate_evidence
BEGIN
    SELECT RAISE(ABORT, 'attribution candidate evidence links cannot be deleted');
END;
