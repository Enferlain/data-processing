"""Opt-in post-text enrichment: artist commentary and overlay notes (Bead data-processing-vus).

Never part of default sync: an operator enriches one already-retained post
at a time.  The run contract is the pool-fetch shape -- the run row commits
before the fetch, the fetch happens outside any transaction, every response
retains its raw report (malformed included), provider-fault runs end
``failed``, transport errors leave an auditable ``local_persistence`` run,
and the request, raw report, observations, and finish commit together.
Documents are parsed strictly before the transaction: any shape violation
classifies the whole response ``malformed_response`` (the pool-fetch
semantic), a commentary entry whose every field the provider reports empty
is absence (a successful empty set), and observations count only newly
inserted rows so unchanged re-observation reports zero.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    PostCommentaryObservationRecord,
    PostNoteObservationRecord,
    RawRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
    validate_remote_outcome,
)
from media_catalog.remote_sync.service import _response_outcome
from media_catalog.writer import CatalogWriter

ENRICHMENT_SCHEMA_VERSION = "post-text-enrichment-v1"

# parse(document, native_post_id) -> normalized entries, or None when the
# document violates the provider contract (classified malformed_response).
_Parser = Callable[[Any, str], "list[dict[str, Any]] | None"]
# record(writer, post_id, entries, observed_at, raw_observation_id) -> inserted count
_Recorder = Callable[[CatalogWriter, int, "list[dict[str, Any]]", str, int], int]


def fetch_commentary(
    database: CatalogDatabase,
    adapter: Any,
    native_post_id: str,
    *,
    clock: Any,
    time_budget_seconds: int = 60,
) -> dict[str, Any]:
    """Fetch one danbooru-family post's artist commentary by native id."""

    return _enrich(
        database,
        adapter,
        AdapterOperation.FETCH_COMMENTARY,
        native_post_id,
        "commentary",
        clock=clock,
        time_budget_seconds=time_budget_seconds,
        parse=parse_commentary,
        record=_record_commentary,
    )


def fetch_notes(
    database: CatalogDatabase,
    adapter: Any,
    native_post_id: str,
    *,
    clock: Any,
    time_budget_seconds: int = 60,
) -> dict[str, Any]:
    """Fetch one post's overlay notes by native id (gelbooru dapi, e621)."""

    return _enrich(
        database,
        adapter,
        AdapterOperation.FETCH_NOTES,
        native_post_id,
        "notes",
        clock=clock,
        time_budget_seconds=time_budget_seconds,
        parse=parse_notes,
        record=_record_notes,
    )


def parse_commentary(document: Any, native_post_id: str) -> list[dict[str, Any]] | None:
    """The provider returns 0 or 1 commentary objects for a post search.

    Providers report missing text as empty strings; absent is absent.  An
    entry whose every field is empty is absence, not an observation.
    """

    entries: list[dict[str, Any]] = []
    for entry in document:
        if not isinstance(entry, dict):
            return None
        post_id = entry.get("post_id")
        if isinstance(post_id, bool) or str(post_id) != native_post_id:
            return None

        def _text(name: str, entry: dict[str, Any] = entry) -> str | None:
            value = entry.get(name)
            if not isinstance(value, str) or not value.strip():
                return None
            return value

        facts = {
            "original_title": _text("original_title"),
            "original_description": _text("original_description"),
            "translated_title": _text("translated_title"),
            "translated_description": _text("translated_description"),
        }
        if any(facts.values()):
            entries.append(facts)
    return entries


def parse_notes(document: Any, native_post_id: str) -> list[dict[str, Any]] | None:
    """Strict note entries: any violation rejects the whole document."""

    del native_post_id
    entries: list[dict[str, Any]] = []
    for entry in document:
        if not isinstance(entry, dict):
            return None
        native = entry.get("id")
        body = entry.get("body")
        if isinstance(native, bool) or not isinstance(native, int) or native <= 0:
            return None
        if not isinstance(body, str) or not body.strip():
            return None
        parsed: dict[str, Any] = {"note_native_id": str(native), "body": body}
        for source, target in (
            ("x", "position_x"),
            ("y", "position_y"),
            ("width", "width"),
            ("height", "height"),
            ("version", "version"),
        ):
            value = entry.get(source)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            parsed[target] = value
        entries.append(parsed)
    return entries


def _record_commentary(
    writer: CatalogWriter,
    post_id: int,
    entries: list[dict[str, Any]],
    observed_at: str,
    raw_observation_id: int,
) -> int:
    if not entries:
        return 0
    result = writer.record_post_commentary(
        post_id,
        PostCommentaryObservationRecord(observed_at=observed_at, **entries[0]),
        raw_observation_id=raw_observation_id,
    )
    return 1 if result.outcome == "inserted" else 0


def _record_notes(
    writer: CatalogWriter,
    post_id: int,
    entries: list[dict[str, Any]],
    observed_at: str,
    raw_observation_id: int,
) -> int:
    inserted = 0
    for entry in entries:
        result = writer.record_post_note(
            post_id,
            PostNoteObservationRecord(observed_at=observed_at, **entry),
            raw_observation_id=raw_observation_id,
        )
        inserted += result.outcome == "inserted"
    return inserted


def _enrich(
    database: CatalogDatabase,
    adapter: Any,
    operation: AdapterOperation,
    native_post_id: str,
    object_kind: str,
    *,
    clock: Any,
    time_budget_seconds: int,
    parse: _Parser,
    record: _Recorder,
) -> dict[str, Any]:
    """Shared bounded enrichment flow over one already-retained post."""

    post_id = _require_post(database, adapter.instance_key, native_post_id)
    now = str(clock())
    writer = CatalogWriter(database)
    with database.transaction():
        run_id = writer.begin_remote_run(
            RemoteRunRecord(
                platform=adapter.instance_key,
                operation=operation.value,
                target=native_post_id,
                adapter_version=str(adapter.adapter_version),
                schema_version=ENRICHMENT_SCHEMA_VERSION,
                request_budget=1,
                page_budget=1,
                record_budget=100,
                time_budget_seconds=time_budget_seconds,
                started_at=now,
            )
        )
    try:
        response: ResponseEnvelope = adapter.fetch(
            AdapterRequest(operation=operation, target=native_post_id)
        )
    except BaseException:
        with database.transaction():
            writer.finish_remote_run(
                run_id,
                status="failed",
                outcome="local_persistence",
                request_count=0,
                page_count=0,
                record_count=0,
                finished_at=str(clock()),
                diagnostic="adapter fetch raised",
            )
        raise
    outcome = _response_outcome(response.status_code)
    entries: list[dict[str, Any]] = []
    if outcome.value == "success":
        document = _parse_document(response.payload)
        if document is None:
            outcome_name = "malformed_response"
        else:
            parsed = parse(document, native_post_id)
            if parsed is None:
                outcome_name = "malformed_response"
            else:
                entries = parsed
                outcome_name = "success"
    else:
        outcome_name = outcome.value
    validate_remote_outcome(outcome_name)
    media_type = response.headers.get("content-type", "application/json").split(";", 1)[0]
    observations = 0
    with database.transaction():
        request_id = writer.record_remote_request(
            RemoteRequestRecord(
                remote_run_id=run_id,
                attempt_number=1,
                request_identity=response.request_identity,
                operation=operation.value,
                target=native_post_id,
                outcome=outcome_name,
                request_started_at=response.observed_at,
                status_code=response.status_code,
                response_adapter_version=response.adapter_version,
                response_schema_version=response.schema_version,
                object_kind=object_kind,
                native_id=native_post_id,
                media_type=media_type,
                response_size=len(response.payload),
                response_observed_at=response.observed_at,
                request_finished_at=response.observed_at,
                transport_key=response.transport_key,
                transport_version=response.transport_version,
            )
        )
        # Every response retains its raw report, malformed or not.
        raw_observation_id = writer.store_raw(
            RawRecord(
                payload=response.payload,
                media_type=media_type,
                object_kind=object_kind,
                native_id=native_post_id,
                observed_at=response.observed_at,
                platform=adapter.instance_key,
                adapter_version=response.adapter_version,
                schema_version=ENRICHMENT_SCHEMA_VERSION,
                transport_key=response.transport_key,
                transport_version=response.transport_version,
                status=str(response.status_code),
            ),
            remote_run_id=run_id,
            remote_request_id=request_id,
        )
        if entries:
            observations = record(
                writer, post_id, entries, response.observed_at, raw_observation_id
            )
        writer.finish_remote_run(
            run_id,
            status="complete" if outcome_name == "success" else "failed",
            outcome=outcome_name,
            request_count=1,
            page_count=1,
            record_count=observations,
            finished_at=str(clock()),
        )
    return {
        "remote_run_id": run_id,
        "post_id": post_id,
        "native_post_id": native_post_id,
        "outcome": outcome_name,
        "observations": observations,
    }


def _require_post(database: CatalogDatabase, platform_key: str, native_post_id: str) -> int:
    """Enrichment is defined for catalog posts; unknown ids are refused."""

    row = database.connection.execute(
        """SELECT p.post_id FROM posts p
             JOIN platforms pl ON pl.platform_id = p.platform_id
            WHERE pl.platform_key = ? AND p.native_post_id = ?""",
        (platform_key, native_post_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"no retained {platform_key} post with native id {native_post_id!r}")
    return int(row[0])


def _parse_document(payload: bytes) -> list[Any] | None:
    """Accept a bare JSON array or the modern dapi wrapper dict."""

    try:
        document = json.loads(payload)
    except ValueError:
        return None
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        # Modern dapi json=1 responses wrap arrays under a result key --
        # "note" for note queries, following the in-repo dapi precedent
        # ("post"/"tag" for the existing operations).
        for key in ("note", "notes"):
            entries = document.get(key)
            if isinstance(entries, list):
                return entries
    return None
