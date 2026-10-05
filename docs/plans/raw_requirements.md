# raw requirements for repo capability

- items matched against sources from other databases (both recorded and non recorded items)
- items matched against hashes, starting with hash types that already exist in their databases
- relationships between items
- similarity metrics used on images, thumbnails are cheap but probably wouldn't match so use deepest source. needs testing for what similary metrics work and if thumbnails work or not.
- robust duplicate and similarity methods (we will always look for existing methods first instead of writing from scratch)
