-- The gelbooru-engine family grows its first new instance (Bead
-- data-processing-x5w, change extend-gelbooru-family-instances): safebooru.org.
-- Platform rows are migration-seeded (the aibooru precedent in 0005); the
-- kernel's SOURCE_OPERATIONS registry admits runs at the record layer, but
-- persistence resolves platform ids from this table, so both must agree.

INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url)
VALUES ('safebooru', 'Safebooru', 'https://safebooru.org');
