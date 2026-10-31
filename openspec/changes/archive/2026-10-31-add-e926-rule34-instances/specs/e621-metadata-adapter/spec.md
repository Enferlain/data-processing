# Spec Delta

## ADDED Requirements

### Requirement: e621-engine instances are registered and identified
The adapter SHALL serve a registered family of e621-engine instances. Each instance SHALL
declare a distinct platform key, its canonical HTTPS base URL on its declared host, and a
per-instance schema version; runs, requests, raw observations, and platform rows SHALL carry
the instance's platform key. A metadata operation SHALL be admitted only for a platform key
whose operations are registered in the kernel's per-platform operation registry, and
instance selection SHALL be explicit on every surface that offers more than one instance.
The credential policy SHALL be unchanged across the family: external credential references
are optional, and partial credentials fail before network access.

#### Scenario: Operator selects the SFW instance
- **WHEN** an operator runs a metadata operation against the registered `e926` instance
- **THEN** all requests target `https://e926.net` and every retained row is attributed to
  the `e926` platform key

#### Scenario: Unregistered platform key
- **WHEN** a remote run names a platform key that no registered e621-engine instance uses
- **THEN** the run contract refuses the operation before any request is made

#### Scenario: Anonymous SFW metadata fetch
- **WHEN** public `e926` metadata is requested without configured credentials
- **THEN** the request proceeds anonymously with the same descriptive User-Agent, pacing,
  and budget controls as any family request
