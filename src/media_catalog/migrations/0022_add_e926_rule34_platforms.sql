-- Batch A of the remaining-adapter lane (Bead data-processing-2e5, change
-- add-e926-rule34-instances): the e621 engine gains its SFW sibling and the
-- gelbooru 0.2 family gains the credentialed rule34.xxx instance.  Platform
-- rows are migration-seeded (the aibooru/safebooru precedent); the kernel's
-- SOURCE_OPERATIONS registry admits runs at the record layer, but persistence
-- resolves platform ids from this table, so both must agree.

INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url)
VALUES ('e926', 'e926', 'https://e926.net');
INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url)
VALUES ('rule34', 'rule34.xxx', 'https://api.rule34.xxx');
