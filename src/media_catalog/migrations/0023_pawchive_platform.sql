-- Pawchive metadata adapter (Bead data-processing-629, change
-- add-pawchive-metadata-adapter): the kemono API family's only maintained
-- instance (maintainer statement 2026-10-31).  Platform rows are
-- migration-seeded (the aibooru/safebooru/e926 precedent); the kernel's
-- SOURCE_OPERATIONS registry admits runs at the record layer, but
-- persistence resolves platform ids from this table, so both must agree.

INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url)
VALUES ('pawchive', 'Pawchive', 'https://pawchive.pw');
