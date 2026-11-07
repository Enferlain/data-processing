"""Keep operator credentials out of tests and mocked provider requests."""

import pytest

import media_catalog.credentials as credentials


@pytest.fixture(autouse=True)
def isolate_catalog_credential_files(monkeypatch):
    monkeypatch.setattr(credentials, "_credential_files", lambda: ())
