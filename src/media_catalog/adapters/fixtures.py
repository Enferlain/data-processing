"""Loader and validation for committed, redacted adapter contract fixtures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .contracts import AdapterOperation, ResponseEnvelope

FIXTURE_FORMAT_VERSION = 1


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"fixture {name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class FixtureManifest:
    format_version: int
    provider: str
    instance: str
    captured_at: str
    adapter_version: str
    schema_version: str
    redactions: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if self.format_version != FIXTURE_FORMAT_VERSION:
            raise ValueError(f"unsupported fixture format version: {self.format_version}")
        for name in (
            "provider",
            "instance",
            "captured_at",
            "adapter_version",
            "schema_version",
            "source",
        ):
            _required_text(getattr(self, name), name)
        if not self.redactions:
            raise ValueError("fixture manifest must describe its redactions")


@dataclass(frozen=True, slots=True)
class FixtureCase:
    name: str
    operation: AdapterOperation
    target: str
    request_identity: str
    response: ResponseEnvelope
    expected: Mapping[str, Any]

    def __post_init__(self) -> None:
        _required_text(self.name, "case name")
        _required_text(self.target, "case target")
        object.__setattr__(self, "expected", MappingProxyType(dict(self.expected)))


@dataclass(frozen=True, slots=True)
class FixtureSuite:
    manifest: FixtureManifest
    cases: tuple[FixtureCase, ...]

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("fixture suite must contain at least one case")
        names = [case.name for case in self.cases]
        if len(names) != len(set(names)):
            raise ValueError("fixture case names must be unique")


def _response_bytes(body: object) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def load_fixture_suite(path: Path | str) -> FixtureSuite:
    fixture_path = Path(path)
    root = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(root, dict) or not isinstance(root.get("manifest"), dict):
        raise ValueError("fixture suite must contain a manifest object")
    manifest_data = root["manifest"]
    manifest = FixtureManifest(
        format_version=int(manifest_data.get("format_version", 0)),
        provider=_required_text(manifest_data.get("provider"), "provider"),
        instance=_required_text(manifest_data.get("instance"), "instance"),
        captured_at=_required_text(manifest_data.get("captured_at"), "captured_at"),
        adapter_version=_required_text(manifest_data.get("adapter_version"), "adapter_version"),
        schema_version=_required_text(manifest_data.get("schema_version"), "schema_version"),
        redactions=tuple(
            _required_text(item, "redaction")
            for item in manifest_data.get("redactions", ())
        ),
        source=_required_text(manifest_data.get("source"), "source"),
    )
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("fixture cases must be a list")
    cases: list[FixtureCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict) or not isinstance(raw_case.get("response"), dict):
            raise ValueError("fixture case and response must be objects")
        response_data = raw_case["response"]
        operation = AdapterOperation(_required_text(raw_case.get("operation"), "operation"))
        request_identity = _required_text(raw_case.get("request_identity"), "request_identity")
        response = ResponseEnvelope(
            provider=manifest.provider,
            instance=manifest.instance,
            operation=operation,
            request_identity=request_identity,
            status_code=int(response_data.get("status_code", 0)),
            headers=response_data.get("headers", {}),
            payload=_response_bytes(response_data.get("body")),
            observed_at=manifest.captured_at,
            adapter_version=manifest.adapter_version,
            schema_version=manifest.schema_version,
        )
        expected = raw_case.get("expected")
        if not isinstance(expected, dict):
            raise ValueError("fixture expected normalization must be an object")
        cases.append(
            FixtureCase(
                name=_required_text(raw_case.get("name"), "case name"),
                operation=operation,
                target=_required_text(raw_case.get("target"), "target"),
                request_identity=request_identity,
                response=response,
                expected=expected,
            )
        )
    return FixtureSuite(manifest, tuple(cases))
