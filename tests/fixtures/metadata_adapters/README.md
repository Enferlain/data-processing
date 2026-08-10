# Metadata adapter contract fixtures

These files are deliberately small, redacted JSON contracts. They contain provider response
shapes and expected normalized summaries, not downloaded media, credentials, or full private
profiles. Default tests load them without contacting any provider.

The gallery-dl comparison fixture is pinned to version 1.32.2 at commit
`2e88d6ae29780dbed02e4a5172a1aa0a1b1c91b5`. It is an oracle for reviewed field mappings only;
gallery-dl is neither imported nor executed by the catalog test suite. Updating the pin requires
regenerating and reviewing the affected expected mappings.

Fixture format version 1 requires a manifest, one or more cases, a secret-free semantic request
identity, a redacted response body, and an expected-normalization object. Update the manifest's
capture date, redaction notes, adapter/schema versions, and source whenever a fixture is replaced.
