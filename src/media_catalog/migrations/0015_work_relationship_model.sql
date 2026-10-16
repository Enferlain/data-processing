-- Kernel Phase D: work entities and the uniform typed-relationship model.
--
-- Works are minimal deterministic anchors (one per post with occurrences);
-- relationships are typed, provenance-bearing conclusions with epistemic
-- status and review state.  Immutability tiers follow the kernel contract
-- from day one: works and work representations are insert-only;
-- relationship rows may update only their current state fields; evidence
-- links, review decisions, and status transitions are fully immutable.

CREATE TABLE works (
    work_id INTEGER PRIMARY KEY,
    origin_post_id INTEGER NOT NULL REFERENCES posts(post_id),
    work_kind TEXT NOT NULL DEFAULT 'unknown'
        CHECK (work_kind IN ('single', 'multi_page', 'unknown')),
    created_at TEXT NOT NULL,
    UNIQUE (origin_post_id)
);

CREATE TABLE work_representations (
    work_id INTEGER NOT NULL REFERENCES works(work_id),
    media_occurrence_id INTEGER NOT NULL REFERENCES media_occurrences(media_occurrence_id),
    added_at TEXT NOT NULL,
    PRIMARY KEY (work_id, media_occurrence_id)
);

CREATE TABLE relationships (
    relationship_id INTEGER PRIMARY KEY,
    relationship_key TEXT NOT NULL UNIQUE CHECK (length(relationship_key) = 64),
    subject_kind TEXT NOT NULL
        CHECK (subject_kind IN ('work', 'media_occurrence', 'post', 'asset')),
    subject_id INTEGER NOT NULL CHECK (subject_id > 0),
    relation_kind TEXT NOT NULL CHECK (relation_kind IN (
        'same_bytes', 'thumbnail_of', 'reposted_from', 'parent_of', 'page_of',
        'same_work', 'variant_of', 'derived_from', 'reencoded_from', 'resized_from',
        'cropped_from', 'censored_variant_of', 'edited_from', 'transcoded_from',
        'extracted_from'
    )),
    target_kind TEXT NOT NULL
        CHECK (target_kind IN ('work', 'media_occurrence', 'post', 'asset')),
    target_id INTEGER NOT NULL CHECK (target_id > 0),
    epistemic_status TEXT NOT NULL CHECK (
        epistemic_status IN ('observed', 'verified', 'derived', 'inferred', 'reviewed')
    ),
    review_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (review_state IN ('pending', 'confirmed', 'rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (subject_kind <> target_kind OR subject_id <> target_id)
);

CREATE INDEX relationships_subject_idx ON relationships(subject_kind, subject_id);
CREATE INDEX relationships_target_idx ON relationships(target_kind, target_id);
CREATE INDEX relationships_kind_idx ON relationships(relation_kind);

CREATE TABLE relationship_evidence (
    relationship_id INTEGER NOT NULL REFERENCES relationships(relationship_id),
    evidence_id INTEGER NOT NULL REFERENCES match_evidence(evidence_id),
    added_at TEXT NOT NULL,
    PRIMARY KEY (relationship_id, evidence_id)
);

CREATE TABLE relationship_review_decisions (
    relationship_decision_id INTEGER PRIMARY KEY,
    relationship_id INTEGER NOT NULL REFERENCES relationships(relationship_id),
    prior_state TEXT NOT NULL CHECK (prior_state IN ('pending', 'confirmed', 'rejected')),
    decision TEXT NOT NULL CHECK (decision IN ('pending', 'confirmed', 'rejected')),
    note TEXT CHECK (note IS NULL OR length(note) <= 2000),
    decided_at TEXT NOT NULL
);

CREATE TABLE relationship_status_history (
    relationship_status_history_id INTEGER PRIMARY KEY,
    relationship_id INTEGER NOT NULL REFERENCES relationships(relationship_id),
    prior_status TEXT NOT NULL CHECK (
        prior_status IN ('observed', 'verified', 'derived', 'inferred', 'reviewed')
    ),
    new_status TEXT NOT NULL CHECK (
        new_status IN ('observed', 'verified', 'derived', 'inferred', 'reviewed')
    ),
    cause TEXT NOT NULL CHECK (length(cause) BETWEEN 1 AND 500),
    at TEXT NOT NULL
);

-- Works: deterministic anchors are immutable once written.
CREATE TRIGGER works_immutable
BEFORE UPDATE ON works
BEGIN
    SELECT RAISE(ABORT, 'works are deterministic anchors and immutable');
END;

CREATE TRIGGER works_no_delete
BEFORE DELETE ON works
BEGIN
    SELECT RAISE(ABORT, 'works are deterministic anchors and never deleted');
END;

CREATE TRIGGER work_representations_immutable
BEFORE UPDATE ON work_representations
BEGIN
    SELECT RAISE(ABORT, 'work representation links are append-only');
END;

CREATE TRIGGER work_representations_no_delete
BEFORE DELETE ON work_representations
BEGIN
    SELECT RAISE(ABORT, 'work representation links are append-only');
END;

-- Relationships: identity is immutable after insert; only the epistemic
-- status, review state, and updated_at may move, and never via deletion.
CREATE TRIGGER relationships_immutable_identity
BEFORE UPDATE ON relationships
WHEN NEW.relationship_key IS NOT OLD.relationship_key
  OR NEW.subject_kind IS NOT OLD.subject_kind
  OR NEW.subject_id IS NOT OLD.subject_id
  OR NEW.relation_kind IS NOT OLD.relation_kind
  OR NEW.target_kind IS NOT OLD.target_kind
  OR NEW.target_id IS NOT OLD.target_id
  OR NEW.created_at IS NOT OLD.created_at
BEGIN
    SELECT RAISE(ABORT, 'relationship identity is immutable after insert');
END;

CREATE TRIGGER relationships_no_delete
BEFORE DELETE ON relationships
BEGIN
    SELECT RAISE(ABORT, 'relationships are retained conclusions and never deleted');
END;

CREATE TRIGGER relationship_evidence_immutable
BEFORE UPDATE ON relationship_evidence
BEGIN
    SELECT RAISE(ABORT, 'relationship evidence links are append-only');
END;

CREATE TRIGGER relationship_evidence_no_delete
BEFORE DELETE ON relationship_evidence
BEGIN
    SELECT RAISE(ABORT, 'relationship evidence links are append-only');
END;

CREATE TRIGGER relationship_review_decisions_immutable
BEFORE UPDATE ON relationship_review_decisions
BEGIN
    SELECT RAISE(ABORT, 'review decisions are append-only');
END;

CREATE TRIGGER relationship_review_decisions_no_delete
BEFORE DELETE ON relationship_review_decisions
BEGIN
    SELECT RAISE(ABORT, 'review decisions are append-only');
END;

CREATE TRIGGER relationship_status_history_immutable
BEFORE UPDATE ON relationship_status_history
BEGIN
    SELECT RAISE(ABORT, 'status history is append-only');
END;

CREATE TRIGGER relationship_status_history_no_delete
BEFORE DELETE ON relationship_status_history
BEGIN
    SELECT RAISE(ABORT, 'status history is append-only');
END;
