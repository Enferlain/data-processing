from __future__ import annotations

import os

import pytest

import media_catalog.cli as cli
import media_catalog.credentials as credentials
from media_catalog.credentials import _credential_files, load_credentials


@pytest.fixture
def env_files(tmp_path, monkeypatch):
    central = tmp_path / "credentials.env"
    local = tmp_path / ".env"
    monkeypatch.setattr(credentials, "_credential_files", lambda: (central, local))
    keys = ("CATALOG_TEST_KEY", "CATALOG_TEST_OTHER", "CATALOG_TEST_BARE")
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    yield central, local
    # The loader mutates os.environ directly, outside monkeypatch's tracking.
    for key in keys:
        os.environ.pop(key, None)


def test_credential_file_locations(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    assert _credential_files() == (
        tmp_path / ".config/media-catalog/credentials.env",
        tmp_path / ".env",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom"))
    assert _credential_files()[0] == tmp_path / "custom/media-catalog/credentials.env"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative-config")
    assert _credential_files()[0] == tmp_path / ".config/media-catalog/credentials.env"


@pytest.mark.parametrize("shell_value", [None, "shell", ""])
def test_credentials_precedence(env_files, monkeypatch, shell_value):
    central, local = env_files
    central.write_text("CATALOG_TEST_KEY=central\nCATALOG_TEST_OTHER=central-only\n")
    local.write_text("CATALOG_TEST_KEY=local\n")
    if shell_value is not None:
        monkeypatch.setenv("CATALOG_TEST_KEY", shell_value)
    load_credentials()
    assert os.environ["CATALOG_TEST_KEY"] == ("local" if shell_value is None else shell_value)
    assert os.environ["CATALOG_TEST_OTHER"] == "central-only"


def test_missing_files_are_optional(env_files):
    load_credentials()
    assert "CATALOG_TEST_KEY" not in os.environ


def test_quotes_exports_and_literal_dollars(env_files):
    central, _ = env_files
    central.write_text(
        '# comments\nexport CATALOG_TEST_KEY="spaces # $HOME ${HOME} \\"quoted\\""\n'
        "CATALOG_TEST_OTHER=''\nCATALOG_TEST_BARE\n",
        encoding="utf-8",
    )
    load_credentials()
    assert os.environ["CATALOG_TEST_KEY"] == 'spaces # $HOME ${HOME} "quoted"'
    assert os.environ["CATALOG_TEST_OTHER"] == ""
    assert "CATALOG_TEST_BARE" not in os.environ


def test_cli_loads_credentials_before_dispatch(env_files, monkeypatch, capsys):
    central, _ = env_files
    central.write_text("CATALOG_TEST_KEY=loaded-before-dispatch\n")

    def run(arguments):
        assert os.environ["CATALOG_TEST_KEY"] == "loaded-before-dispatch"
        return {"status": "ok"}

    monkeypatch.setattr(cli, "_run", run)
    cli.main(["init", "unused.sqlite3"])
    assert "loaded-before-dispatch" not in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["invalid-utf8", "directory"])
def test_cli_reports_unreadable_credentials_without_values(env_files, failure):
    central, _ = env_files
    if failure == "invalid-utf8":
        central.write_bytes(b"CATALOG_TEST_KEY=private-sentinel\xff")
    else:
        central.mkdir()
    with pytest.raises(SystemExit) as caught:
        cli.main(["init", "unused.sqlite3"])
    assert str(caught.value) == "error: cannot read credential file credentials.env"


def test_local_env_symlink(env_files):
    central, local = env_files
    central.write_text("CATALOG_TEST_KEY=linked\n")
    local.symlink_to(central)
    load_credentials()
    assert os.environ["CATALOG_TEST_KEY"] == "linked"
