"""Provider-neutral metadata adapter contracts."""

from .contracts import (
    Adapter,
    AdapterFailure,
    AdapterOperation,
    AdapterOutcome,
    AdapterRequest,
    Continuation,
    NormalizedItem,
    NormalizedPage,
    ResponseEnvelope,
)
from .fixtures import FixtureCase, FixtureManifest, FixtureSuite, load_fixture_suite

__all__ = [
    "Adapter",
    "AdapterFailure",
    "AdapterOperation",
    "AdapterOutcome",
    "AdapterRequest",
    "Continuation",
    "FixtureCase",
    "FixtureManifest",
    "FixtureSuite",
    "NormalizedItem",
    "NormalizedPage",
    "ResponseEnvelope",
    "load_fixture_suite",
]
