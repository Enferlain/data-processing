"""Adapter doctor: offline contract replay and live probe semantics.

The offline replay over the committed suites is the doctor's own smoke test —
it re-executes every captured contract case in memory.  Drift detection and
live-probe behavior are exercised with in-memory cases and stub adapters; no
synthetic fixture ever enters the repository.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from media_catalog.adapters import AdapterOperation, AdapterRequest, ResponseEnvelope
from media_catalog.adapters.contracts import (
    AdapterFailure,
    AdapterOutcome,
    NormalizedItem,
    NormalizedPage,
)
from media_catalog.adapters.fixtures import FixtureCase, FixtureManifest, FixtureSuite
from media_catalog.doctor import (
    DOCTOR_PLATFORMS,
    DOCTOR_SURFACES,
    DoctorReport,
    DoctorSurface,
    ProbeResult,
    SurfaceReport,
    _live_probe,
    _replay_case,
    run_doctor,
)

NOW = "2026-11-01T00:00:00Z"


def test_offline_replay_is_green_over_every_committed_suite() -> None:
    report = run_doctor()
    assert not report.errors
    assert report.ok
    assert tuple(surface.platform for surface in report.surfaces) == DOCTOR_PLATFORMS
    total_cases = sum(len(surface.case_results) for surface in report.surfaces)
    assert total_cases >= 55  # 59 at introduction; grows with the suites


def test_unknown_platform_is_an_error_not_a_crash() -> None:
    report = run_doctor(platforms=("pawchive", "nope"))
    assert not report.ok
    assert any("unknown platform: nope" in error for error in report.errors)
    assert len(report.surfaces) == 1


def test_platform_filter_selects_one_surface() -> None:
    report = run_doctor(platforms=("pawchive",))
    assert report.ok
    assert [surface.platform for surface in report.surfaces] == ["pawchive"]


class _StubAdapter:
    adapter_version = "stub-v1"
    schema_version = "stub-json-v1"

    def __init__(
        self,
        page: NormalizedPage | None = None,
        failure: AdapterFailure | None = None,
        envelope: ResponseEnvelope | None = None,
    ) -> None:
        self._page = page
        self._failure = failure
        self._envelope = envelope

    def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
        if self._failure is not None:
            raise self._failure
        assert self._page is not None
        return self._page

    def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
        if self._failure is not None:
            raise self._failure
        assert self._envelope is not None
        return self._envelope


def _manifest(adapter_version: str = "stub-v1") -> FixtureManifest:
    return FixtureManifest(
        format_version=1,
        provider="stub",
        instance="stub",
        captured_at=NOW,
        adapter_version=adapter_version,
        schema_version="stub-json-v1",
        redactions=("in-memory test case",),
        source="in-memory",
    )


def _case(expected: dict[str, Any]) -> FixtureCase:
    return FixtureCase(
        name="probe_case",
        operation=AdapterOperation.FETCH_POST,
        target="1",
        request_identity="stub:fetch_post:1",
        response=ResponseEnvelope(
            provider="stub",
            instance="stub",
            operation=AdapterOperation.FETCH_POST,
            request_identity="stub:fetch_post:1",
            status_code=200,
            headers={"content-type": "application/json"},
            payload=b"{}",
            observed_at=NOW,
            adapter_version="stub-v1",
            schema_version="stub-json-v1",
            request_target="doctor:probe_case",
        ),
        expected=expected,
    )


def _suite(expected: dict[str, Any], adapter_version: str = "stub-v1") -> FixtureSuite:
    return FixtureSuite(manifest=_manifest(adapter_version), cases=(_case(expected),))


def _surface(adapter: Any = None, creds: tuple[str, ...] = (), probe: bool = True) -> DoctorSurface:
    return DoctorSurface(
        platform="stub",
        suite_file="stub.json",
        provider_key="stub",
        instance_key="stub",
        offline_adapter=lambda: adapter or _StubAdapter(),
        live_adapter=lambda: adapter or _StubAdapter(),
        live_credential_envs=creds,
        probe_case="probe_case" if probe else None,
    )


def _replay(
    adapter: _StubAdapter, expected: dict[str, Any], adapter_version: str = "stub-v1"
) -> str | None:
    suite = _suite(expected, adapter_version)
    result = _replay_case(adapter, suite, suite.cases[0], _surface())
    return result.reason


def _page(*items: NormalizedItem) -> NormalizedPage:
    return NormalizedPage(tuple(items))


def test_replay_accepts_a_matching_success_case() -> None:
    post = NormalizedItem(object_kind="post", native_id="1", data={"platform": "stub"})
    account = NormalizedItem(object_kind="account", native_id="7", data={"platform": "stub"})
    reason = _replay(
        _StubAdapter(page=_page(post, account)),
        {"outcome": "success", "post_ids": ["1"], "account_ids": ["7"]},
    )
    assert reason is None


def test_replay_detects_outcome_drift() -> None:
    adapter = _StubAdapter(failure=AdapterFailure(AdapterOutcome.UNAVAILABLE, "gone"))
    reason = _replay(adapter, {"outcome": "success", "post_ids": ["1"]})
    assert reason is not None
    assert "expected outcome success" in reason and "unavailable" in reason


def test_replay_detects_adapter_version_drift() -> None:
    reason = _replay(_StubAdapter(), {"outcome": "success"}, adapter_version="stub-v0")
    assert reason is not None
    assert "suite pins adapter stub-v0" in reason


def test_replay_detects_missing_ids_and_wrong_platform() -> None:
    post = NormalizedItem(object_kind="post", native_id="1", data={"platform": "stub"})
    reason = _replay(_StubAdapter(page=_page(post)), {"post_ids": ["2"]})
    assert reason is not None and "post_ids" in reason
    stranger = NormalizedItem(object_kind="post", native_id="1", data={"platform": "elsewhere"})
    reason = _replay(_StubAdapter(page=_page(stranger)), {"post_ids": ["1"]})
    assert reason is not None and "elsewhere" in reason


def test_replay_honors_normalized_state_outcomes() -> None:
    deleted = NormalizedItem(
        object_kind="post", native_id="9", data={"platform": "stub", "availability": "deleted"}
    )
    reason = _replay(
        _StubAdapter(page=_page(deleted)),
        {"outcome": "deleted", "post_ids": ["9"], "availability": "deleted"},
    )
    assert reason is None
    wrong = NormalizedItem(
        object_kind="post", native_id="9", data={"platform": "stub", "availability": "available"}
    )
    reason = _replay(
        _StubAdapter(page=_page(wrong)),
        {"outcome": "deleted", "post_ids": ["9"], "availability": "deleted"},
    )
    assert reason is not None and "availability" in reason


def test_replay_treats_transport_byte_limit_cases_as_acknowledged() -> None:
    reason = _replay(_StubAdapter(), {"outcome": "response_too_large"})
    assert reason is not None and "transport-level" in reason


def test_live_probe_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    post = NormalizedItem(object_kind="post", native_id="1", data={"platform": "stub"})
    adapter = _StubAdapter(page=_page(post), envelope=_case({}).response)
    probe = _live_probe(_surface(adapter), _suite({"post_ids": ["1"]}))
    assert probe.ok and not probe.skipped
    assert probe.outcome == "success"
    assert probe.elapsed_ms is not None


def test_live_probe_skips_when_credentials_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("STUB_USER", "STUB_KEY"):
        monkeypatch.delenv(name, raising=False)
    probe = _live_probe(_surface(_StubAdapter(), creds=("STUB_USER", "STUB_KEY")), _suite({}))
    assert probe.skipped and not probe.ok
    assert probe.reason is not None
    assert "STUB_USER" in probe.reason and "STUB_KEY" in probe.reason


def test_live_probe_reports_typed_provider_failure() -> None:
    failing = _StubAdapter(failure=AdapterFailure(AdapterOutcome.AUTHENTICATION_REQUIRED, "no"))
    probe = _live_probe(_surface(failing), _suite({}))
    assert not probe.ok and not probe.skipped
    assert probe.outcome == "authentication_required"


def test_skipped_probes_do_not_fail_the_report() -> None:
    report = SurfaceReport(
        platform="stub",
        suite_file="stub.json",
        case_results=(),
        probe=ProbeResult(ok=False, skipped=True, reason="missing credentials: X"),
    )
    assert report.ok
    assert report.failure_reasons == []


def test_cli_renders_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    from media_catalog.cli import main

    main(["adapter-doctor", "--platform", "pawchive"])
    out = capsys.readouterr().out
    assert "adapter doctor: ok" in out
    assert "pawchive" in out


def test_cli_json_report_is_complete(capsys: pytest.CaptureFixture[str]) -> None:
    from media_catalog.cli import main

    main(["adapter-doctor", "--platform", "pawchive", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert [surface["platform"] for surface in payload["surfaces"]] == ["pawchive"]
    assert payload["surfaces"][0]["probe"] is None


def test_catalog_doctor_surfaces_the_adapter_summary(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    from media_catalog.cli import main
    from media_catalog.database import CatalogDatabase

    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    main(["doctor", str(catalog), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    adapters = payload["adapters"]
    assert adapters["ok"] is True
    assert adapters["surfaces"]["pawchive"] is True
    assert adapters["failures"] == []


def test_catalog_doctor_names_adapter_failures(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from media_catalog.cli import main
    from media_catalog.database import CatalogDatabase

    failing = DoctorReport(surfaces=(), errors=("synthetic adapter error",))
    monkeypatch.setattr("media_catalog.cli.run_doctor", lambda **kwargs: failing)
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    main(["doctor", str(catalog), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["adapters"]["ok"] is False
    assert payload["adapters"]["errors"] == ["synthetic adapter error"]


def test_catalog_doctor_names_failing_surfaces(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from media_catalog.cli import main
    from media_catalog.database import CatalogDatabase
    from media_catalog.doctor import CaseResult, SurfaceReport

    failing_surface = SurfaceReport(
        platform="pawchive",
        suite_file="pawchive.json",
        case_results=(CaseResult("pawchive", "post_case", ok=False, reason="synthetic drift"),),
    )
    report = DoctorReport(surfaces=(failing_surface,))
    monkeypatch.setattr("media_catalog.cli.run_doctor", lambda **kwargs: report)
    catalog = tmp_path / "catalog.sqlite3"
    with CatalogDatabase(catalog):
        pass
    main(["doctor", str(catalog), "--json"])
    payload = json.loads(capsys.readouterr().out)
    adapters = payload["adapters"]
    assert adapters["ok"] is False
    assert adapters["surfaces"]["pawchive"] is False
    assert adapters["failures"] == ["pawchive: post_case: synthetic drift"]
    # Top-level ok reflects storage only; adapter health is the summary.
    assert payload["ok"] is True


def test_cli_failure_exits_nonzero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = DoctorReport(surfaces=(), errors=("synthetic error for exit-path test",))
    monkeypatch.setattr("media_catalog.cli.run_doctor", lambda **kwargs: broken)
    from media_catalog.cli import main

    with pytest.raises(SystemExit) as raised:
        main(["adapter-doctor"])
    assert raised.value.code == 2


def test_every_surface_registers_a_probe_case() -> None:
    for surface in DOCTOR_SURFACES:
        assert surface.probe_case, surface.platform
        assert surface.offline_adapter is not None


def test_every_registered_probe_case_exists_in_its_suite() -> None:
    from media_catalog.adapters.fixtures import load_fixture_suite
    from media_catalog.doctor import FIXTURES

    for surface in DOCTOR_SURFACES:
        suite = load_fixture_suite(FIXTURES / surface.suite_file)
        assert surface.probe_case in {case.name for case in suite.cases}, surface.platform


def test_probe_case_missing_from_suite_is_a_registration_failure() -> None:
    surface = DoctorSurface(
        platform="stub",
        suite_file="stub.json",
        provider_key="stub",
        instance_key="stub",
        offline_adapter=lambda: _StubAdapter(),
        live_adapter=lambda: _StubAdapter(),
        probe_case="does_not_exist",
    )
    probe = _live_probe(surface, _suite({}))
    assert not probe.ok and not probe.skipped
    assert probe.reason is not None and "registration bug" in probe.reason


def test_probe_checks_account_ids_and_fails_on_empty_pages() -> None:
    account = NormalizedItem(object_kind="account", native_id="7", data={"platform": "stub"})
    adapter = _StubAdapter(page=_page(account), envelope=_case({}).response)
    probe = _live_probe(_surface(adapter), _suite({"account_ids": ["7"]}))
    assert probe.ok
    empty = _StubAdapter(page=_page(), envelope=_case({}).response)
    probe = _live_probe(_surface(empty), _suite({"account_ids": ["7"]}))
    assert not probe.ok
    assert probe.reason is not None and "expected ids" in probe.reason


def test_probe_contains_transport_exceptions() -> None:
    import httpx as _httpx

    class _TransportBoom(_StubAdapter):
        def fetch(self, request: AdapterRequest) -> ResponseEnvelope:
            raise _httpx.ConnectError("no route to host")

    probe = _live_probe(_surface(_TransportBoom()), _suite({}))
    assert not probe.ok and not probe.skipped
    assert probe.reason is not None and "ConnectError" in probe.reason


def test_replay_contains_unexpected_normalizer_exceptions() -> None:
    class _Exploding(_StubAdapter):
        def normalize(self, response: ResponseEnvelope) -> NormalizedPage:
            raise ValueError("synthetic drift explosion")

    reason = _replay(_Exploding(), {"outcome": "success"})
    assert reason is not None and "ValueError" in reason
