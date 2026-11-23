-- Widen platform_references.object_kind with a 'series' kind (bead
-- data-processing-7jx, change add-series-references).  SQLite cannot ALTER
-- a CHECK, so this rebuilds the table the way 0003 did on this very table
-- and 0038 did for the remote-operation tables: create the rebuilt shape,
-- copy every row with explicit columns preserving ids, drop the index and
-- old table, rename, recreate the index.  The migration engine runs with
-- FK enforcement disabled and gates the commit on PRAGMA foreign_key_check,
-- so the six dependent tables re-validate against the rebuilt parent.
--
-- Series semantics are evidence-only: resolved_account_id/resolved_post_id
-- guards are untouched (a series reference keeps both NULL), and the
-- candidate reference-kind triggers already reject non-account/post
-- targets.  The records-layer OBJECT_KINDS mirror in
-- src/media_catalog/records/common.py widens with this migration; both
-- must agree.
DROP TRIGGER IF EXISTS account_candidate_reference_kind_insert;
DROP TRIGGER IF EXISTS account_candidate_reference_kind_update;
DROP TRIGGER IF EXISTS attribution_candidate_reference_kind_insert;
DROP TRIGGER IF EXISTS attribution_candidate_reference_kind_update;
DROP TRIGGER IF EXISTS post_candidate_reference_kind_insert;
DROP TRIGGER IF EXISTS post_candidate_reference_kind_update;


CREATE TABLE platform_references_rebuilt (
    platform_reference_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    object_kind TEXT NOT NULL
        CHECK (object_kind IN ('account', 'post', 'artist', 'media_asset', 'series')),
    identifier_kind TEXT NOT NULL CHECK (
        identifier_kind IN ('stable_id', 'handle', 'slug', 'hash', 'opaque')
    ),
    native_identifier TEXT NOT NULL,
    canonical_target_url TEXT NOT NULL,
    recognizer_name TEXT NOT NULL,
    recognizer_version TEXT NOT NULL,
    resolved_account_id INTEGER REFERENCES accounts(account_id),
    resolved_post_id INTEGER REFERENCES posts(post_id),
    CHECK (NOT (resolved_account_id IS NOT NULL AND resolved_post_id IS NOT NULL)),
    CHECK (resolved_account_id IS NULL OR object_kind = 'account'),
    CHECK (resolved_post_id IS NULL OR object_kind = 'post'),
    UNIQUE (
        platform_id, instance_host, object_kind, identifier_kind,
        native_identifier, recognizer_version
    )
);

INSERT INTO platform_references_rebuilt
    (platform_reference_id, platform_id, instance_host, object_kind, identifier_kind,
     native_identifier, canonical_target_url, recognizer_name, recognizer_version,
     resolved_account_id, resolved_post_id)
SELECT platform_reference_id, platform_id, instance_host, object_kind, identifier_kind,
       native_identifier, canonical_target_url, recognizer_name, recognizer_version,
       resolved_account_id, resolved_post_id
  FROM platform_references;

DROP INDEX platform_references_lookup_idx;
DROP TABLE platform_references;
ALTER TABLE platform_references_rebuilt RENAME TO platform_references;

CREATE INDEX platform_references_lookup_idx
    ON platform_references(platform_id, instance_host, object_kind, identifier_kind);

CREATE TRIGGER account_candidate_reference_kind_insert
BEFORE INSERT ON account_match_candidates WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'account'
        THEN RAISE(ABORT, 'account candidate target reference must be an account') END;
END;

CREATE TRIGGER account_candidate_reference_kind_update
BEFORE UPDATE OF target_reference_id ON account_match_candidates
WHEN NEW.target_reference_id IS NOT NULL
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

CREATE TRIGGER post_candidate_reference_kind_update
BEFORE UPDATE OF target_reference_id ON post_match_candidates
WHEN NEW.target_reference_id IS NOT NULL
BEGIN
    SELECT CASE WHEN (SELECT object_kind FROM platform_references
                      WHERE platform_reference_id = NEW.target_reference_id) <> 'post'
        THEN RAISE(ABORT, 'post candidate target reference must be a post') END;
END;

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
