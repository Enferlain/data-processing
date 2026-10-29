"""Ephemeral external credentials for the Sankaku API."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from media_catalog.adapters.sankaku.config import SankakuInstance


@dataclass(frozen=True, slots=True)
class SankakuCredentials:
    """A login/password pair whose values are never represented publicly."""

    login: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.login.strip() or not self.password.strip():
            raise ValueError("both Sankaku login and password are required")
        if any(ord(character) < 32 for value in (self.login, self.password) for character in value):
            raise ValueError("Sankaku credentials must not contain control characters")

    @classmethod
    def from_environment(
        cls,
        instance: SankakuInstance,
        environ: Mapping[str, str] | None = None,
    ) -> SankakuCredentials:
        values = os.environ if environ is None else environ
        login = values.get(instance.login_env)
        password = values.get(instance.password_env)
        if not login or not password:
            raise ValueError(f"configure both {instance.login_env} and {instance.password_env}")
        return cls(login, password)

    def secret_values(self) -> tuple[str, str]:
        """Credential values for sanitization passes; never rendered directly."""
        return (self.login, self.password)
