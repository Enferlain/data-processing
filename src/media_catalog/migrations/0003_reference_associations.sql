DROP TRIGGER account_candidate_reference_kind_insert;
DROP TRIGGER post_candidate_reference_kind_insert;
DROP TRIGGER account_candidate_reference_kind_update;
DROP TRIGGER post_candidate_reference_kind_update;

CREATE TABLE platform_references_new (
    platform_reference_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    instance_host TEXT NOT NULL DEFAULT '',
    object_kind TEXT NOT NULL CHECK (object_kind IN ('account', 'post', 'artist', 'media_asset')),
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

INSERT INTO platform_references_new
    (platform_reference_id, platform_id, instance_host, object_kind, identifier_kind,
     native_identifier, canonical_target_url, recognizer_name, recognizer_version,
     resolved_account_id, resolved_post_id)
SELECT platform_reference_id, platform_id, instance_host, object_kind,
       CASE
           WHEN recognizer_name IN ('x-account', 'mastodon-account') THEN 'handle'
           WHEN recognizer_name LIKE '%-media' THEN 'hash'
           WHEN recognizer_name IN (
               'x-post', 'pixiv-user', 'pixiv-artwork', 'mastodon-status',
               'danbooru-post', 'danbooru-artist', 'gelbooru-post', 'gelbooru-artist',
               'e621-post', 'e621-artist'
           ) THEN 'stable_id'
           ELSE 'opaque'
       END,
       native_identifier, canonical_target_url, recognizer_name, recognizer_version,
       resolved_account_id, resolved_post_id
FROM platform_references;

CREATE TABLE external_link_references (
    external_link_id INTEGER NOT NULL
        REFERENCES external_links(external_link_id) ON DELETE CASCADE,
    platform_reference_id INTEGER NOT NULL
        REFERENCES platform_references_new(platform_reference_id) ON DELETE CASCADE,
    PRIMARY KEY (external_link_id, platform_reference_id)
);

INSERT INTO external_link_references (external_link_id, platform_reference_id)
SELECT external_link_id, platform_reference_id FROM platform_references;

DROP INDEX platform_references_lookup_idx;
DROP TABLE platform_references;
ALTER TABLE platform_references_new RENAME TO platform_references;

CREATE INDEX platform_references_lookup_idx
    ON platform_references(platform_id, instance_host, object_kind, identifier_kind);
CREATE INDEX external_link_references_reference_idx
    ON external_link_references(platform_reference_id, external_link_id);

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
