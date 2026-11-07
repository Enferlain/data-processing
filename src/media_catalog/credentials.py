"""Load operator environment files before running catalog commands."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def _credential_files() -> tuple[Path, Path]:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or "")
    if not config_home.is_absolute():
        config_home = Path.home() / ".config"
    return config_home / "media-catalog" / "credentials.env", Path.cwd() / ".env"


def load_credentials() -> None:
    """Fill missing environment values; local .env overrides the central file."""
    values: dict[str, str] = {}
    for path in _credential_files():
        try:
            with path.open(encoding="utf-8") as stream:
                parsed = dotenv_values(stream=stream, interpolate=False)
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError):
            raise RuntimeError(f"cannot read credential file {path.name}") from None
        values.update({key: value for key, value in parsed.items() if value is not None})
    for key, value in values.items():
        os.environ.setdefault(key, value)
