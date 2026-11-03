"""Helpers shared across the cli_commands command families."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import httpx

from media_catalog.acquisition import AcquisitionSelection
from media_catalog.adapters.danbooru import AIBOORU, DANBOORU, DanbooruAdapter
from media_catalog.adapters.e621 import E621_INSTANCES, E621Adapter
from media_catalog.adapters.gelbooru import GELBOORU_INSTANCES, GelbooruAdapter
from media_catalog.adapters.pawchive import PAWCHIVE_INSTANCES, PawchiveAdapter
from media_catalog.library import ExpansionLimits
from media_catalog.records import AcquisitionLimits

E621_CREDENTIAL_GUIDANCE = (
    "Optional e621 credentials are resolved from external E621_USERNAME and E621_API_KEY "
    "environment references; credentials are never CLI flags."
)

GELBOORU_DAPI_CREDENTIAL_GUIDANCE = (
    "Gelbooru-family DAPI credentials resolve per instance from external environment "
    "references: gelbooru requires GELBOORU_USER_ID and GELBOORU_API_KEY; safebooru's "
    "DAPI is anonymous and uses SAFEBOORU_USER_ID/SAFEBOORU_API_KEY only when both are "
    "configured. Credentials are never CLI flags."
)

GELBOORU_HTML_GUIDANCE = (
    "The anonymous Gelbooru HTML transport uses no credentials and never falls back "
    "to the credentialed DAPI transport."
)

SANKAKU_CREDENTIAL_GUIDANCE = (
    "Sankaku credentials are resolved from external SANKAKU_LOGIN and "
    "SANKAKU_PASSWORD environment references and exchanged for a bearer token "
    "at request time; neither credentials nor tokens are ever CLI flags or "
    "retained durably."
)


def add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit structured JSON")


def add_sync_limits(parser: argparse.ArgumentParser, *, listing: bool) -> None:
    parser.add_argument("--max-requests", type=int, default=3 if listing else 1)
    parser.add_argument("--max-pages", type=int, default=2 if listing else 1)
    parser.add_argument("--max-records", type=int, default=500 if listing else 250)
    parser.add_argument("--max-seconds", type=int, default=60)
    parser.add_argument("--resume-from", type=int)
    add_json(parser)


def add_acquisition_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-items", type=int, default=100)
    parser.add_argument("--max-item-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-seconds", type=int, default=300)
    parser.add_argument("--max-redirects", type=int, default=5)
    parser.add_argument("--max-quarantine-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--concurrency", type=int, choices=(1,), default=1)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def offline_replay_adapter(provider: str):
    # Reprocessing is offline: the adapter only normalizes, so its client is
    # a mock that fails loudly if anything ever tries to contact a provider.
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("reprocessing must not contact the provider")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    if provider in GELBOORU_INSTANCES:
        return GelbooruAdapter(GELBOORU_INSTANCES[provider], client=client)
    if provider in E621_INSTANCES:
        return E621Adapter(E621_INSTANCES[provider], client=client)
    if provider in PAWCHIVE_INSTANCES:
        return PawchiveAdapter(PAWCHIVE_INSTANCES[provider], client=client)
    return DanbooruAdapter(AIBOORU if provider == "aibooru" else DANBOORU, client=client)


def add_lookup_limits(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-results", type=int, default=200)
    parser.add_argument("--max-seconds", type=int, default=60)


def add_library_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("catalog", type=Path)
    parser.add_argument("seed", metavar="ACCOUNT:ID|POST:ID")
    parser.add_argument("--target", metavar="ACCOUNT:ID|ATTRIBUTION:ID")
    parser.add_argument("--selection-note")
    parser.add_argument("--max-requests", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-records", type=int, default=200)
    parser.add_argument("--max-seconds", type=int, default=60)
    add_json(parser)


def library_limits(arguments: argparse.Namespace) -> ExpansionLimits:
    return ExpansionLimits(
        arguments.max_requests,
        arguments.max_pages,
        arguments.max_records,
        arguments.max_seconds,
    )


def parse_acquisition_selections(values: list[str]) -> list[AcquisitionSelection]:
    selections: list[AcquisitionSelection] = []
    for value in values:
        occurrence, separator, variant = value.partition(":")
        if not occurrence.isdecimal() or int(occurrence) <= 0:
            raise ValueError("selection must start with a positive occurrence id")
        if separator and not variant:
            raise ValueError("selection variant must not be empty")
        selections.append(AcquisitionSelection(int(occurrence), variant or "primary"))
    return selections


def acquisition_limits(arguments: argparse.Namespace) -> AcquisitionLimits:
    return AcquisitionLimits(
        arguments.max_items,
        arguments.max_item_bytes,
        arguments.max_total_bytes,
        arguments.max_attempts,
        arguments.max_seconds,
        arguments.max_redirects,
        arguments.max_quarantine_bytes,
        arguments.concurrency,
    )
