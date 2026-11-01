"""Adapter health doctor: one surface that verifies every adapter.

Offline (default): every registered suite-format fixture case replays under the
current adapters — version agreement, expected outcome (success or typed
failure), expected identifier membership, and per-item platform attribution.
This is the contract-drift tripwire; the per-family tests still pin exact facts.

Live (``--live``): one bounded metadata request per platform through the real
adapter at its pacing floor, targeting the identifier its own captured contract
already covers.  Missing credentials skip with a named reason.  The flag is the
operator authorization — no live request happens without it.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from media_catalog.adapters import AdapterRequest, ResponseEnvelope
from media_catalog.adapters.contracts import AdapterFailure
from media_catalog.adapters.danbooru import (
    AIBOORU,
    DANBOORU,
    DanbooruAdapter,
    DanbooruCredentials,
)
from media_catalog.adapters.e621 import E621, E926, E621Adapter
from media_catalog.adapters.fixtures import FixtureSuite, load_fixture_suite
from media_catalog.adapters.gelbooru import (
    GELBOORU,
    RULE34,
    SAFEBOORU,
    GelbooruAdapter,
    GelbooruCredentials,
    GelbooruHtmlAdapter,
)
from media_catalog.adapters.pawchive import PAWCHIVE, PawchiveAdapter
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.adapters.sankaku import SANKAKU, SankakuAdapter, SankakuCredentials

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "metadata_adapters"
OBSERVED_AT = "2026-11-01T00:00:00Z"

# Credential policy per live probe: environment variable names that must all
# resolve before a credentials-required platform is probed.  Anonymous
# platforms declare none.
_ANONYMOUS: tuple[str, ...] = ()
_GELBOORU_STYLE = ("GELBOORU_USER_ID", "GELBOORU_API_KEY")
_RULE34_STYLE = ("RULE34_USER_ID", "RULE34_API_KEY")
_SANKAKU_STYLE = ("SANKAKU_LOGIN", "SANKAKU_PASSWORD")
_PIXIV_STYLE = ("PIXIV_REFRESH_TOKEN",)


def _json_encoded_text(payload: bytes) -> bytes:
    """Decode a JSON-encoded text document (HTML suites) back to raw bytes."""

    return json.loads(payload.decode("utf-8")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class DoctorSurface:
    """One registered adapter surface and how the doctor exercises it."""

    platform: str
    suite_file: str
    instance_key: str
    provider_key: str
    # Offline construction (normalize-only, dummy secrets never sent anywhere).
    offline_adapter: Callable[[], Any]
    # Live construction (real client, real credential resolution).
    live_adapter: Callable[[], Any] | None
    live_credential_envs: tuple[str, ...] = _ANONYMOUS
    probe_case: str | None = None
    # HTML suites store their document as a JSON-encoded string; the family
    # tests decode it before feeding the adapter, and so does the doctor.
    decode_payload: Callable[[bytes], bytes] | None = None
    # The HTML adapter parses the post id out of the envelope's request
    # target, so that surface derives a real one; everything else stays
    # opaque by design (listing continuations resolve terminally).
    request_target: Callable[[Any], str] = lambda case: f"doctor:{case.name}"


@dataclass(frozen=True, slots=True)
class CaseResult:
    suite: str
    case: str
    ok: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    skipped: bool = False
    reason: str | None = None
    outcome: str | None = None
    status_code: int | None = None
    response_bytes: int | None = None
    elapsed_ms: int | None = None


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    platform: str
    suite_file: str
    case_results: tuple[CaseResult, ...] = ()
    probe: ProbeResult | None = None

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.case_results) and (
            self.probe is None or self.probe.ok or self.probe.skipped
        )

    @property
    def failure_reasons(self) -> list[str]:
        reasons = [
            f"{result.case}: {result.reason}" for result in self.case_results if not result.ok
        ]
        if self.probe is not None and not self.probe.ok and not self.probe.skipped:
            reasons.append(f"live probe: {self.probe.reason}")
        return reasons


@dataclass(frozen=True, slots=True)
class DoctorReport:
    surfaces: tuple[SurfaceReport, ...] = ()
    errors: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.errors and all(surface.ok for surface in self.surfaces)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "surfaces": [
                {
                    "platform": surface.platform,
                    "suite": surface.suite_file,
                    "ok": surface.ok,
                    "cases": [
                        {
                            "case": result.case,
                            "ok": result.ok,
                            "reason": result.reason,
                        }
                        for result in surface.case_results
                    ],
                    "probe": (
                        None
                        if surface.probe is None
                        else {
                            "ok": surface.probe.ok,
                            "skipped": surface.probe.skipped,
                            "reason": surface.probe.reason,
                            "outcome": surface.probe.outcome,
                            "status_code": surface.probe.status_code,
                            "response_bytes": surface.probe.response_bytes,
                            "elapsed_ms": surface.probe.elapsed_ms,
                        }
                    ),
                }
                for surface in self.surfaces
            ],
        }


def _danbooru_offline(instance: Any) -> Callable[[], Any]:
    return lambda: DanbooruAdapter(
        instance,
        client=httpx.Client(transport=_refuse_transport()),
        credentials=DanbooruCredentials("doctor-offline", "never-sent"),
    )


def _gelbooru_offline(instance: Any) -> Callable[[], Any]:
    return lambda: GelbooruAdapter(instance, client=httpx.Client(transport=_refuse_transport()))


def _refuse_transport() -> httpx.MockTransport:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("offline doctor replay must not contact a provider")

    return httpx.MockTransport(refuse)


def _danbooru_live(instance: Any) -> Callable[[], Any]:
    # Danbooru-family reads work anonymously; credentials resolve when the
    # environment carries them and stay absent otherwise.
    return lambda: DanbooruAdapter(
        instance, client=httpx.Client(), credentials=DanbooruCredentials.from_environment(instance)
    )


DOCTOR_SURFACES: tuple[DoctorSurface, ...] = (
    DoctorSurface(
        platform="danbooru",
        suite_file="danbooru.json",
        provider_key="danbooru",
        instance_key="danbooru",
        offline_adapter=_danbooru_offline(DANBOORU),
        live_adapter=_danbooru_live(DANBOORU),
        probe_case="post_with_attribution",
    ),
    DoctorSurface(
        platform="aibooru",
        suite_file="aibooru.json",
        provider_key="danbooru",
        instance_key="aibooru",
        offline_adapter=_danbooru_offline(AIBOORU),
        live_adapter=_danbooru_live(AIBOORU),
        probe_case="compatible_post",
    ),
    DoctorSurface(
        platform="e621",
        suite_file="e621.json",
        provider_key="e621",
        instance_key="e621",
        offline_adapter=lambda: E621Adapter(
            E621, client=httpx.Client(transport=_refuse_transport())
        ),
        live_adapter=lambda: E621Adapter(E621, client=httpx.Client()),
        probe_case="normal_post",
    ),
    DoctorSurface(
        platform="e926",
        suite_file="e926.json",
        provider_key="e621",
        instance_key="e926",
        offline_adapter=lambda: E621Adapter(
            E926, client=httpx.Client(transport=_refuse_transport())
        ),
        live_adapter=lambda: E621Adapter(E926, client=httpx.Client()),
        probe_case="post_6823045",
    ),
    DoctorSurface(
        platform="gelbooru",
        suite_file="gelbooru.json",
        provider_key="gelbooru",
        instance_key="gelbooru",
        offline_adapter=_gelbooru_offline(GELBOORU),
        live_adapter=lambda: GelbooruAdapter(
            GELBOORU,
            client=httpx.Client(),
            credentials=GelbooruCredentials.from_environment(GELBOORU),
        ),
        live_credential_envs=_GELBOORU_STYLE,
        probe_case="post_12370900",
    ),
    DoctorSurface(
        platform="safebooru",
        suite_file="safebooru.json",
        provider_key="gelbooru",
        instance_key="safebooru",
        offline_adapter=_gelbooru_offline(SAFEBOORU),
        live_adapter=lambda: GelbooruAdapter(SAFEBOORU, client=httpx.Client()),
        probe_case="post_7272295",
    ),
    DoctorSurface(
        platform="rule34",
        suite_file="rule34.json",
        provider_key="gelbooru",
        instance_key="rule34",
        offline_adapter=_gelbooru_offline(RULE34),
        live_adapter=lambda: GelbooruAdapter(
            RULE34,
            client=httpx.Client(),
            credentials=GelbooruCredentials.from_environment(RULE34),
        ),
        live_credential_envs=_RULE34_STYLE,
        probe_case="post_19210742",
    ),
    DoctorSurface(
        platform="gelbooru-html",
        suite_file="gelbooru_html.json",
        provider_key="gelbooru",
        instance_key="gelbooru",
        offline_adapter=lambda: GelbooruHtmlAdapter(
            client=httpx.Client(transport=_refuse_transport())
        ),
        live_adapter=lambda: GelbooruHtmlAdapter(client=httpx.Client()),
        probe_case="html_post_12370900",
        decode_payload=_json_encoded_text,
        request_target=lambda case: f"post:{case.target}",
    ),
    DoctorSurface(
        platform="pixiv",
        suite_file="pixiv.json",
        provider_key="pixiv",
        instance_key="pixiv",
        offline_adapter=lambda: PixivAdapter(
            client=httpx.Client(transport=_refuse_transport()),
            base_url="https://app-api.pixiv.net",
            refresh_token_env=None,
        ),
        live_adapter=lambda: PixivAdapter(
            client=httpx.Client(),
            base_url="https://app-api.pixiv.net",
            refresh_token_env="PIXIV_REFRESH_TOKEN",
        ),
        live_credential_envs=_PIXIV_STYLE,
        probe_case="profile",
    ),
    DoctorSurface(
        platform="sankaku",
        suite_file="sankaku.json",
        provider_key="sankaku",
        instance_key="sankaku",
        offline_adapter=lambda: SankakuAdapter(
            client=httpx.Client(transport=_refuse_transport()),
            credentials=SankakuCredentials("doctor-offline", "never-sent"),
        ),
        live_adapter=lambda: SankakuAdapter(
            client=httpx.Client(), credentials=SankakuCredentials.from_environment(SANKAKU)
        ),
        live_credential_envs=_SANKAKU_STYLE,
        probe_case="post_wvaemE6YDaz",
    ),
    DoctorSurface(
        platform="pawchive",
        suite_file="pawchive.json",
        provider_key="pawchive",
        instance_key="pawchive",
        offline_adapter=lambda: PawchiveAdapter(
            PAWCHIVE, client=httpx.Client(transport=_refuse_transport())
        ),
        live_adapter=lambda: PawchiveAdapter(PAWCHIVE, client=httpx.Client()),
        probe_case="post_patreon_75232195_70439020",
    ),
)

DOCTOR_PLATFORMS: tuple[str, ...] = tuple(surface.platform for surface in DOCTOR_SURFACES)


def _load_suite(surface: DoctorSurface) -> FixtureSuite:
    return load_fixture_suite(FIXTURES / surface.suite_file)


def _replay_case(
    adapter: Any, suite: FixtureSuite, case: Any, surface: DoctorSurface
) -> CaseResult:
    if suite.manifest.adapter_version != adapter.adapter_version:
        return CaseResult(
            suite.manifest.instance,
            case.name,
            ok=False,
            reason=(
                f"suite pins adapter {suite.manifest.adapter_version}, "
                f"adapter is {adapter.adapter_version}"
            ),
        )
    expected: Mapping[str, Any] = case.expected
    want_outcome = expected.get("outcome", "success")
    if want_outcome == "response_too_large":
        # Transport-level case: the byte limit is enforced while reading the
        # live response, not during normalization.  The family tests pin it
        # end to end; here it is acknowledged, not re-proven.
        return CaseResult(
            suite.manifest.instance,
            case.name,
            ok=True,
            reason="transport-level case; byte limit verified by family tests",
        )
    payload = case.response.payload
    if surface.decode_payload is not None:
        payload = surface.decode_payload(payload)
    envelope = ResponseEnvelope(
        provider=suite.manifest.provider,
        instance=suite.manifest.instance,
        operation=case.operation,
        request_identity=case.request_identity,
        status_code=case.response.status_code,
        headers=dict(case.response.headers),
        payload=payload,
        observed_at=OBSERVED_AT,
        adapter_version=suite.manifest.adapter_version,
        schema_version=suite.manifest.schema_version,
        # Opaque by design (design.md D2): listing continuations resolve
        # terminally, matching offline-replay semantics everywhere.
        request_target=surface.request_target(case),
    )
    try:
        page = adapter.normalize(envelope)
    except AdapterFailure as failure:
        if failure.outcome.value != want_outcome:
            return CaseResult(
                suite.manifest.instance,
                case.name,
                ok=False,
                reason=(f"expected outcome {want_outcome}, adapter raised {failure.outcome.value}"),
            )
        return CaseResult(suite.manifest.instance, case.name, ok=True)
    except Exception as error:
        return CaseResult(
            suite.manifest.instance,
            case.name,
            ok=False,
            reason=f"normalizer raised {type(error).__name__}: {error}",
        )
    if want_outcome == "success":
        return _check_success_case(suite, case, page)
    # Normalized-state outcomes (deleted or unavailable posts, empty miss
    # pages) are modeled on the page, not raised: the family adapters
    # normalize provider states into availability facts.
    wanted_posts = list(expected.get("post_ids") or [])
    posts = {item.native_id: item for item in page.items if item.object_kind == "post"}
    if not wanted_posts:
        if posts:
            return CaseResult(
                suite.manifest.instance,
                case.name,
                ok=False,
                reason=f"expected an empty miss page, {len(posts)} posts normalized",
            )
        return CaseResult(suite.manifest.instance, case.name, ok=True)
    missing = [value for value in wanted_posts if value not in posts]
    if missing:
        return CaseResult(
            suite.manifest.instance,
            case.name,
            ok=False,
            reason=f"post_ids {missing} absent from normalized page",
        )
    want_availability = str(expected.get("availability", want_outcome))
    wrong = sorted(
        value
        for value in wanted_posts
        if str(posts[value].data.get("availability")) != want_availability
    )
    if wrong:
        return CaseResult(
            suite.manifest.instance,
            case.name,
            ok=False,
            reason=(
                f"posts {wrong} availability != {want_availability} "
                f"(expected outcome {want_outcome})"
            ),
        )
    return CaseResult(suite.manifest.instance, case.name, ok=True)


def _check_success_case(suite: FixtureSuite, case: Any, page: Any) -> CaseResult:
    expected: Mapping[str, Any] = case.expected
    post_ids = {item.native_id for item in page.items if item.object_kind == "post"}
    account_ids = {item.native_id for item in page.items if item.object_kind == "account"}
    for expected_key, have in (("post_ids", post_ids), ("account_ids", account_ids)):
        wanted = expected.get(expected_key)
        if wanted is None:
            continue
        missing = [value for value in wanted if value not in have]
        if missing:
            return CaseResult(
                suite.manifest.instance,
                case.name,
                ok=False,
                reason=f"{expected_key} {missing} absent from normalized page",
            )
    wrong_platform = sorted(
        {
            str(item.data.get("platform"))
            for item in page.items
            if item.data.get("platform") not in (None, suite.manifest.instance)
        }
    )
    if wrong_platform:
        return CaseResult(
            suite.manifest.instance,
            case.name,
            ok=False,
            reason=(f"items attributed to {wrong_platform} instead of {suite.manifest.instance}"),
        )
    return CaseResult(suite.manifest.instance, case.name, ok=True)


def _missing_credentials(envs: Sequence[str]) -> list[str]:
    return [name for name in envs if not os.environ.get(name, "").strip()]


def _live_probe(surface: DoctorSurface, suite: FixtureSuite) -> ProbeResult:
    missing = _missing_credentials(surface.live_credential_envs)
    if missing or surface.live_adapter is None or surface.probe_case is None:
        return ProbeResult(
            ok=False,
            skipped=True,
            reason=f"missing credentials: {', '.join(missing)}" if missing else "no probe",
        )
    case = next(
        (case for case in suite.cases if case.name == surface.probe_case),
        None,
    )
    if case is None:
        return ProbeResult(
            ok=False,
            reason=f"probe case {surface.probe_case!r} not in suite (registration bug)",
        )
    adapter = surface.live_adapter()
    started = time.monotonic()
    try:
        envelope = adapter.fetch(AdapterRequest(operation=case.operation, target=case.target))
        page = adapter.normalize(envelope)
    except AdapterFailure as failure:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(
            ok=False,
            reason=f"provider outcome {failure.outcome.value}",
            outcome=failure.outcome.value,
            elapsed_ms=elapsed_ms,
        )
    except Exception as error:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(
            ok=False,
            reason=f"transport raised {type(error).__name__}: {error}",
            elapsed_ms=elapsed_ms,
        )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    post_ids = {item.native_id for item in page.items if item.object_kind == "post"}
    account_ids = {item.native_id for item in page.items if item.object_kind == "account"}
    wanted = case.expected.get("post_ids") or []
    wanted_accounts = case.expected.get("account_ids") or []
    found_posts = [value for value in wanted if value in post_ids]
    found_accounts = [value for value in wanted_accounts if value in account_ids]
    if wanted:
        ok = len(found_posts) == len(wanted)
    elif wanted_accounts:
        ok = len(found_accounts) == len(wanted_accounts)
    else:
        ok = bool(page.items)
    return ProbeResult(
        ok=ok,
        outcome="success",
        status_code=envelope.status_code,
        response_bytes=len(envelope.payload),
        elapsed_ms=elapsed_ms,
        reason=(None if ok else f"normalized page lacks expected ids {wanted or wanted_accounts}"),
    )


def run_doctor(*, live: bool = False, platforms: Sequence[str] = ()) -> DoctorReport:
    """Replay every registered suite; optionally probe every platform live."""

    errors: list[str] = []
    reports: list[SurfaceReport] = []
    selected = tuple(platforms) or DOCTOR_PLATFORMS
    by_platform = {surface.platform: surface for surface in DOCTOR_SURFACES}
    for platform in selected:
        surface = by_platform.get(platform)
        if surface is None:
            errors.append(f"unknown platform: {platform} (known: {', '.join(DOCTOR_PLATFORMS)})")
            continue
        try:
            suite = _load_suite(surface)
        except (OSError, ValueError) as error:
            errors.append(f"{surface.suite_file}: {error}")
            continue
        adapter = surface.offline_adapter()
        case_results = tuple(_replay_case(adapter, suite, case, surface) for case in suite.cases)
        probe = _live_probe(surface, suite) if live else None
        reports.append(
            SurfaceReport(
                platform=surface.platform,
                suite_file=surface.suite_file,
                case_results=case_results,
                probe=probe,
            )
        )
    return DoctorReport(surfaces=tuple(reports), errors=tuple(errors))


def render_report(report: DoctorReport, *, live: bool) -> str:
    lines: list[str] = []
    status = "ok" if report.ok else "FAIL"
    lines.append(f"adapter doctor: {status}")
    for surface in report.surfaces:
        failed = [result for result in surface.case_results if not result.ok]
        marker = "ok" if surface.ok else "FAIL"
        lines.append(
            f"  {surface.platform:14} {marker:4} {surface.suite_file} "
            f"({len(surface.case_results)} cases"
            + (f", {len(failed)} failed" if failed else "")
            + ")"
        )
        for result in failed:
            lines.append(f"      {result.case}: {result.reason}")
        if surface.probe is not None:
            probe = surface.probe
            if probe.skipped:
                lines.append(f"      live: skipped ({probe.reason})")
            elif probe.ok:
                lines.append(
                    f"      live: ok outcome={probe.outcome} "
                    f"http={probe.status_code} bytes={probe.response_bytes} {probe.elapsed_ms}ms"
                )
            else:
                lines.append(f"      live: FAIL {probe.reason}")
    for error in report.errors:
        lines.append(f"  error: {error}")
    if not live:
        lines.append("  (offline only; pass --live to probe providers)")
    return "\n".join(lines)
