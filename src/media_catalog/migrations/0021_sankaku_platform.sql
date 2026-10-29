-- New provider family (Bead data-processing-4ly, change
-- add-sankaku-metadata-adapter): Sankaku.  Platform rows are migration-seeded
-- (the safebooru/aibooru precedent); the kernel's SOURCE_OPERATIONS registry
-- admits runs at the record layer, but persistence resolves platform ids from
-- this table, so both must agree.

INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url)
VALUES ('sankaku', 'Sankaku', 'https://sankaku.app');
