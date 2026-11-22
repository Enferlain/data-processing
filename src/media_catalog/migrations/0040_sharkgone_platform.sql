-- Register the operator's personal Danbooru-software booru as a platform
-- (bead data-processing-9ds, change add-sharkgone-instance).  It is a
-- niche discovery source, never danbooru failover.  The kernel's
-- SOURCE_OPERATIONS map in src/media_catalog/records/common.py must carry
-- the same platform key; both must agree.

INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url)
VALUES ('sharkgone', 'Sharkgone', 'https://booru.sharkgone.com');
