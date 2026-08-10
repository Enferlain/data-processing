from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SecretValue:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("secret value must not be empty")

    def __str__(self) -> str:
        return "<redacted>"


class EnvironmentCredentialResolver:
    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def resolve(self, reference: str, *, required: bool = True) -> SecretValue | None:
        if not reference or not reference.replace("_", "").isalnum():
            raise ValueError("credential reference must be an environment variable name")
        value = self._environ.get(reference)
        if value:
            return SecretValue(value)
        if required:
            raise ValueError(f"required credential environment reference is unset: {reference}")
        return None
