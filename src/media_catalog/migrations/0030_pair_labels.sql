-- Labeled pair dataset for heuristic calibration (bead data-processing-w7j).
-- Labels are operator ground truth about how two images relate — a calibration
-- dataset, deliberately distinct from candidate review states: a label is not
-- an identity claim, it is training/evaluation data for future matchers.

CREATE TABLE IF NOT EXISTS pair_labels (
    pair_label_id INTEGER PRIMARY KEY,
    post_a_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    post_b_id INTEGER NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
    queue_signal TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('same', 'variant', 'different', 'unsure')),
    relation_note TEXT CHECK (relation_note IS NULL OR length(relation_note) <= 2000),
    labeled_at TEXT NOT NULL,
    CHECK (post_a_id < post_b_id),
    UNIQUE (post_a_id, post_b_id, queue_signal)
);

CREATE INDEX IF NOT EXISTS pair_labels_pair_idx ON pair_labels(post_a_id, post_b_id);

CREATE TABLE IF NOT EXISTS pair_label_decisions (
    pair_label_decision_id INTEGER PRIMARY KEY,
    pair_label_id INTEGER NOT NULL
        REFERENCES pair_labels(pair_label_id) ON DELETE CASCADE,
    prior_verdict TEXT NOT NULL
        CHECK (prior_verdict IN ('same', 'variant', 'different', 'unsure')),
    verdict TEXT NOT NULL CHECK (verdict IN ('same', 'variant', 'different', 'unsure')),
    note TEXT CHECK (note IS NULL OR length(note) <= 2000),
    decided_at TEXT NOT NULL
);
