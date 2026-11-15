-- Operator labels (bead data-processing-j7l, change add-operator-labels):
-- free-form local facts on catalog subjects.  Two tables in the
-- provenance-kernel style: labels are retireable, never deleted; assertions
-- are append-only apply/revoke rows whose latest per (label, subject) is the
-- current state.  Nothing here touches provider tag tables.  Subjects are
-- polymorphic (subject_kind + subject_id) exactly like relationships, with
-- file_seed added for bare-file discovery seeds.  Additive only; replay-safe.

CREATE TABLE IF NOT EXISTS operator_labels (
    operator_label_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
        UNIQUE
        COLLATE NOCASE
        CHECK (length(name) BETWEEN 1 AND 100),
    description TEXT,
    created_at TEXT NOT NULL,
    retired_at TEXT
        CHECK (retired_at IS NULL OR length(retired_at) >= 1)
);

CREATE TABLE IF NOT EXISTS operator_label_assertions (
    operator_label_assertion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_label_id INTEGER NOT NULL
        REFERENCES operator_labels(operator_label_id) ON DELETE CASCADE,
    subject_kind TEXT NOT NULL
        CHECK (subject_kind IN ('file_seed', 'post', 'asset', 'work')),
    subject_id INTEGER NOT NULL CHECK (subject_id > 0),
    state TEXT NOT NULL CHECK (state IN ('applied', 'revoked')),
    asserted_by TEXT NOT NULL CHECK (length(asserted_by) BETWEEN 1 AND 200),
    note TEXT,
    observed_at TEXT NOT NULL
);

-- Latest-state lookups per (label, subject): current state is the row with the
-- greatest (observed_at, rowid); the index serves the per-subject scan.
CREATE INDEX IF NOT EXISTS idx_operator_label_assertions_subject
    ON operator_label_assertions(operator_label_id, subject_kind, subject_id);
