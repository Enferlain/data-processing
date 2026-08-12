"""Explicit, one-request provider count probes for library expansion."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from media_catalog.adapters import AdapterFailure, AdapterOperation, AdapterOutcome, AdapterRequest
from media_catalog.adapters.pixiv.transport import PixivAdapter
from media_catalog.database import CatalogDatabase
from media_catalog.library.contracts import LibraryExpansionPlan
from media_catalog.records import (
    LibraryExpansionPlanRecord,
    LibraryExpansionProbeRecord,
    RawRecord,
)
from media_catalog.writer import CatalogWriter

Clock = Callable[[], datetime | str]


def _now(clock: Clock | None) -> str:
    value = clock() if clock is not None else datetime.now(UTC)
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError("library probe clock must return a timezone-aware timestamp")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _seed_ids(seed: str) -> tuple[int | None, int | None]:
    kind, _, raw_id = seed.partition(":")
    value = int(raw_id)
    return (value, None) if kind == "account" else (None, value)


def materialize_expansion_plan(
    writer: CatalogWriter, plan: LibraryExpansionPlan, *, created_at: str
) -> int:
    """Persist one executable offline plan idempotently."""

    selected = plan.selected
    if selected is None:
        raise ValueError("library expansion plan requires an explicit selected target")
    target = selected.target
    seed_account_id, seed_post_id = _seed_ids(plan.seed)
    return writer.record_library_expansion_plan(
        LibraryExpansionPlanRecord(
            target.provider,
            target.instance,
            target.kind.value,
            target.catalog_id if target.kind.value == "account" else None,
            target.catalog_id if target.kind.value == "attribution" else None,
            seed_account_id,
            seed_post_id,
            plan.seed_revision,
            selected.authority.mode.value,
            selected.authority.reference,
            selected.authority.note,
            target.capability.key,
            target.capability.version,
            target.native_id,
            target.revision,
            target.capability.adapter_version,
            target.capability.schema_version,
            plan.source_revision,
            plan.limits.requests,
            plan.limits.pages,
            plan.limits.records,
            plan.limits.seconds,
            plan.estimate.state,
            plan.estimate.count,
            plan.estimate.observed_at,
            plan.estimate.source,
            json.dumps(plan.exclusions, sort_keys=True, separators=(",", ":")),
            plan.digest,
            plan.material_digest,
            created_at,
        )
    )


@dataclass(frozen=True, slots=True)
class CountProbeResult:
    probe_id: int
    plan_id: int
    outcome: str
    count: int | None
    observed_at: str
    request_count: int
    raw_observation_id: int | None = None
    diagnostic: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id,
            "plan_id": self.plan_id,
            "outcome": self.outcome,
            "count": self.count,
            "observed_at": self.observed_at,
            "request_count": self.request_count,
            "raw_observation_id": self.raw_observation_id,
            "diagnostic": self.diagnostic,
        }


def _status_outcome(status_code: int) -> AdapterOutcome:
    if 200 <= status_code < 300:
        return AdapterOutcome.SUCCESS
    return {
        401: AdapterOutcome.AUTHENTICATION_REQUIRED,
        403: AdapterOutcome.AUTHORIZATION_DENIED,
        404: AdapterOutcome.UNAVAILABLE,
        410: AdapterOutcome.DELETED,
        429: AdapterOutcome.RATE_LIMITED,
    }.get(
        status_code,
        AdapterOutcome.TRANSIENT_PROVIDER
        if status_code >= 500
        else AdapterOutcome.MALFORMED_RESPONSE,
    )


def _pixiv_count(payload: bytes) -> int:
    try:
        body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Pixiv count response is not valid JSON") from error
    if not isinstance(body, dict) or not isinstance(body.get("profile"), dict):
        raise ValueError("Pixiv count response has no profile object")
    value = body["profile"].get("total_illusts")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("Pixiv count response has no non-negative integer total")
    return value


class LibraryCountProbeService:
    """Run an explicit count probe without listing posts or requesting media."""

    def __init__(
        self,
        database: CatalogDatabase,
        *,
        pixiv_adapter: PixivAdapter | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.database = database
        self.writer = CatalogWriter(database)
        self.pixiv_adapter = pixiv_adapter
        self.clock = clock

    def probe(self, plan: LibraryExpansionPlan) -> CountProbeResult:
        selected = plan.selected
        if selected is None:
            raise ValueError("count probe requires an executable expansion plan")
        timestamp = _now(self.clock)
        with self.database.transaction():
            plan_id = materialize_expansion_plan(self.writer, plan, created_at=timestamp)
        capability = selected.target.capability
        if capability.count_probe_key is None:
            record = LibraryExpansionProbeRecord(
                plan_id,
                capability.key,
                capability.version,
                capability.adapter_version,
                capability.schema_version,
                1,
                plan.limits.seconds,
                "unsupported",
                timestamp,
                timestamp,
                diagnostic_summary="provider has no fixture-backed count capability",
            )
            with self.database.transaction():
                probe_id = self.writer.record_library_expansion_probe(record)
            return CountProbeResult(
                probe_id,
                plan_id,
                "unsupported",
                None,
                timestamp,
                0,
                diagnostic=record.diagnostic_summary,
            )
        if selected.target.provider != "pixiv" or self.pixiv_adapter is None:
            raise ValueError("Pixiv count probe requires an injected Pixiv adapter")
        identity = f"pixiv:fetch_account:{selected.target.native_id}"
        try:
            response = self.pixiv_adapter.fetch(
                AdapterRequest(AdapterOperation.FETCH_ACCOUNT, selected.target.native_id)
            )
        except AdapterFailure as error:
            observed_at = _now(self.clock)
            record = LibraryExpansionProbeRecord(
                plan_id,
                capability.count_probe_key,
                capability.version,
                capability.adapter_version,
                capability.schema_version,
                1,
                plan.limits.seconds,
                error.outcome.value,
                timestamp,
                observed_at,
                status_code=error.status_code,
                retry_after=error.retry_at,
                request_identity=identity,
                diagnostic_summary=error.public_message,
            )
            with self.database.transaction():
                probe_id = self.writer.record_library_expansion_probe(record)
            return CountProbeResult(
                probe_id,
                plan_id,
                error.outcome.value,
                None,
                observed_at,
                1,
                diagnostic=error.public_message,
            )

        outcome = _status_outcome(response.status_code)
        count: int | None = None
        diagnostic: str | None = None
        if outcome is AdapterOutcome.SUCCESS:
            try:
                count = _pixiv_count(response.payload)
            except ValueError as error:
                outcome = AdapterOutcome.MALFORMED_RESPONSE
                diagnostic = str(error)
        with self.database.transaction():
            raw_id = self.writer.store_raw(
                RawRecord(
                    response.payload,
                    response.headers.get("content-type", "application/json").split(";", 1)[0],
                    "account",
                    selected.target.native_id,
                    response.observed_at,
                    platform="pixiv",
                    adapter_version=response.adapter_version,
                    schema_version=response.schema_version,
                    status=str(response.status_code),
                )
            )
            probe_id = self.writer.record_library_expansion_probe(
                LibraryExpansionProbeRecord(
                    plan_id,
                    capability.count_probe_key,
                    capability.version,
                    response.adapter_version,
                    response.schema_version,
                    1,
                    plan.limits.seconds,
                    outcome.value,
                    timestamp,
                    response.observed_at,
                    status_code=response.status_code,
                    count_value=count,
                    request_identity=response.request_identity,
                    raw_observation_id=raw_id,
                    diagnostic_summary=diagnostic,
                )
            )
        return CountProbeResult(
            probe_id,
            plan_id,
            outcome.value,
            count,
            response.observed_at,
            1,
            raw_id,
            diagnostic,
        )
