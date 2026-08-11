from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest

from media_catalog.acquisition.policies import (
    AIBOORU_MEDIA_POLICY,
    DANBOORU_MEDIA_POLICY,
    PIXIV_MEDIA_POLICY,
    CredentialReference,
    MediaRequestPolicy,
    PolicyIdentity,
    RequestPolicyError,
    ResolvedCredentials,
    ResponseExpectations,
    media_request_policy_for_platform,
    safe_failure_diagnostic,
    validate_destination,
    validate_redirect,
)
from media_catalog.database import CatalogDatabase
from media_catalog.records import (
    AcquisitionAttemptRecord,
    AcquisitionLimits,
    AcquisitionPlanItemRecord,
    AcquisitionPlanRecord,
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
)
from media_catalog.writer import CatalogWriter

NOW = "2026-08-10T12:00:00Z"


@pytest.mark.parametrize(
    ("url", "category"),
    [
        ("http://i.pximg.net/image.jpg", "scheme_not_allowed"),
        ("https://user:password@i.pximg.net/image.jpg", "userinfo_not_allowed"),
        ("https://127.0.0.1/image.jpg", "ip_literal_not_allowed"),
        ("https://[::1]/image.jpg", "ip_literal_not_allowed"),
        ("https://i.pximg.net:8443/image.jpg", "port_not_allowed"),
        ("https://example.com/image.jpg", "host_not_allowed"),
        ("https://i.pximg.net/image.jpg#secret", "fragment_not_allowed"),
    ],
)
def test_destination_validation_fails_closed_without_reflecting_url(
    url: str, category: str
) -> None:
    marker = "password" if "password" in url else "image.jpg"
    with pytest.raises(RequestPolicyError) as captured:
        validate_destination(url, allowed_hosts=frozenset({"i.pximg.net"}))

    assert captured.value.category == category
    assert marker not in str(captured.value)
    assert url not in repr(captured.value)


def test_redirect_validation_checks_every_resolved_destination() -> None:
    current = "https://i.pximg.net/img-original/signed.jpg?token=top-secret"
    assert validate_redirect(
        current,
        "/img-original/next.jpg?signature=hidden",
        allowed_hosts=frozenset({"i.pximg.net"}),
    ).startswith("https://i.pximg.net/")

    for location in (
        "http://i.pximg.net/downgrade.jpg",
        "https://example.com/off-policy.jpg",
        "//127.0.0.1/private.jpg",
        "https://person:secret@i.pximg.net/private.jpg",
    ):
        with pytest.raises(RequestPolicyError) as captured:
            validate_redirect(
                current, location, allowed_hosts=frozenset({"i.pximg.net"})
            )
        rendered = f"{captured.value!r} {captured.value}"
        assert "top-secret" not in rendered
        assert "secret" not in rendered


def test_pixiv_original_and_ugoira_recipes_are_ephemeral_and_redacted() -> None:
    original_url = "https://i.pximg.net/img-original/work.jpg?token=signed-value"
    original = PIXIV_MEDIA_POLICY.recipe(
        media_occurrence_id=17,
        variant_key="original",
        selected_url=original_url,
    )
    archive = PIXIV_MEDIA_POLICY.recipe(
        media_occurrence_id=18,
        variant_key="archive",
        selected_url="https://i.pximg.net/img-zip-ugoira/work.zip?expires=123",
    )

    assert original.url == original_url
    assert original.headers == {"Referer": "https://app-api.pixiv.net/"}
    assert original.operation == "download-image"
    assert archive.operation == "download-ugoira-archive"
    assert archive.response.accepts("application/zip")
    assert original.response.accepts("image/jpeg; charset=binary")
    assert original.credential_reference is None
    assert len(original.request_identity) == 64
    public = json.dumps(original.as_dict(), sort_keys=True)
    assert original_url not in public
    assert "signed-value" not in public
    assert "signed-value" not in repr(original)


@pytest.mark.parametrize(
    ("policy", "url"),
    [
        (DANBOORU_MEDIA_POLICY, "https://cdn.donmai.us/original/file.jpg"),
        (DANBOORU_MEDIA_POLICY, "https://danbooru.donmai.us/data/sample.jpg"),
        (AIBOORU_MEDIA_POLICY, "https://aibooru.download/data/file.png"),
        (AIBOORU_MEDIA_POLICY, "https://safe.aibooru.online/data/preview.jpg"),
        (AIBOORU_MEDIA_POLICY, "https://general.aibooru.online/data/sample.jpg"),
    ],
)
@pytest.mark.parametrize("variant", ["original", "sample", "preview"])
def test_danbooru_family_recipes_cover_explicit_instances_and_variants(
    policy: MediaRequestPolicy, url: str, variant: str
) -> None:
    recipe = policy.recipe(
        media_occurrence_id=71,
        variant_key=variant,
        selected_url=url,
    )

    assert recipe.operation == f"download-{variant}"
    assert recipe.headers["Referer"].startswith("https://")
    assert recipe.response.accepts("image/webp")
    assert recipe.credential_reference is None


def test_danbooru_policy_rejects_unknown_variant_and_cross_instance_host() -> None:
    with pytest.raises(RequestPolicyError, match="variant"):
        DANBOORU_MEDIA_POLICY.recipe(
            media_occurrence_id=1,
            variant_key="thumbnail-unknown",
            selected_url="https://cdn.donmai.us/a.jpg",
        )
    with pytest.raises(RequestPolicyError) as captured:
        DANBOORU_MEDIA_POLICY.recipe(
            media_occurrence_id=1,
            variant_key="original",
            selected_url="https://aibooru.download/a.jpg",
        )
    assert captured.value.category == "host_not_allowed"


def test_policy_lookup_and_retry_classification() -> None:
    assert media_request_policy_for_platform("pixiv") is PIXIV_MEDIA_POLICY
    assert media_request_policy_for_platform("danbooru") is DANBOORU_MEDIA_POLICY
    assert media_request_policy_for_platform("aibooru") is AIBOORU_MEDIA_POLICY
    assert media_request_policy_for_platform("unknown") is None

    expected = {
        401: ("authentication_required", False),
        403: ("authorization_denied", False),
        404: ("unavailable", False),
        410: ("unavailable", False),
        429: ("rate_limited", True),
        500: ("transient_provider", True),
        503: ("transient_provider", True),
        418: ("invalid_content", False),
        200: ("success", False),
    }
    for status, result in expected.items():
        classification = PIXIV_MEDIA_POLICY.classify_status(status)
        assert (classification.category, classification.retryable) == result


def test_credentials_and_request_diagnostics_never_render_values() -> None:
    bearer = "Bearer super-secret-token"
    cookie = "session=super-secret-cookie"
    credentials = ResolvedCredentials(
        headers={"Authorization": bearer},
        cookies={"Cookie": cookie},
    )
    assert bearer not in repr(credentials)
    assert cookie not in repr(credentials)

    class AuthenticatedFixturePolicy(MediaRequestPolicy):
        identity = PolicyIdentity("fixture-media", "fixture-media-v1")
        provider = "fixture"
        allowed_hosts = frozenset({"media.fixture.invalid"})
        redirect_hosts = allowed_hosts
        headers = MappingProxyType({"Accept": "image/*"})
        response_expectations = ResponseExpectations(("image/",))
        credential_reference = CredentialReference("fixture-media-credentials")

    signed_url = (
        "https://media.fixture.invalid/a.jpg?"
        "X-Amz-Credential=secret-config&X-Amz-Signature=signed-secret"
    )
    recipe = AuthenticatedFixturePolicy().recipe(
        media_occurrence_id=99,
        variant_key="original",
        selected_url=signed_url,
    )
    output = json.dumps(recipe.as_dict(), sort_keys=True) + repr(recipe)
    assert signed_url not in output
    assert "secret-config" not in output
    assert "signed-secret" not in output
    assert bearer not in output
    assert cookie not in output
    assert "fixture-media-credentials" in output

    failure = RuntimeError(
        f"request {signed_url} failed with {bearer} and Cookie: {cookie}"
    )
    diagnostic = safe_failure_diagnostic("fixture", "policy_failure", error=failure)
    assert diagnostic == "fixture:policy_failure"
    assert signed_url not in diagnostic
    assert bearer not in diagnostic
    assert cookie not in diagnostic


def test_provider_exact_claims_apply_only_to_original_representation() -> None:
    for policy in (PIXIV_MEDIA_POLICY, DANBOORU_MEDIA_POLICY, AIBOORU_MEDIA_POLICY):
        assert policy.declared_exact_claims_apply("primary")
        assert policy.declared_exact_claims_apply("original")
        assert not policy.declared_exact_claims_apply("sample")
        assert not policy.declared_exact_claims_apply("preview")


def test_explicit_443_is_allowed_but_redirect_hosts_remain_exact() -> None:
    recipe = PIXIV_MEDIA_POLICY.recipe(
        media_occurrence_id=1,
        variant_key="original",
        selected_url="https://i.pximg.net:443/image.jpg",
    )
    assert recipe.provider == "pixiv"
    with pytest.raises(RequestPolicyError, match="trusted"):
        PIXIV_MEDIA_POLICY.validate_redirect(
            recipe.url, "https://sub.i.pximg.net/image.jpg"
        )


def test_persisted_attempt_contains_only_redacted_request_evidence(tmp_path: Path) -> None:
    signed_url = "https://i.pximg.net/a.jpg?token=persisted-secret"
    bearer = "Bearer persisted-bearer"
    recipe = PIXIV_MEDIA_POLICY.recipe(
        media_occurrence_id=1,
        variant_key="original",
        selected_url=signed_url,
    )
    diagnostic = safe_failure_diagnostic(
        "pixiv",
        "policy_failure",
        error=RuntimeError(f"{signed_url} Authorization: {bearer}"),
    )

    with CatalogDatabase(tmp_path / "catalog.sqlite3") as database:
        writer = CatalogWriter(database)
        with database.transaction():
            platform_id = int(
                database.connection.execute(
                    "SELECT platform_id FROM platforms WHERE platform_key = 'pixiv'"
                ).fetchone()[0]
            )
            post_id = int(
                database.connection.execute(
                    """INSERT INTO posts (
                           platform_id, native_post_id, first_seen_at, last_seen_at
                       ) VALUES (?, 'fixture-post', ?, ?)""",
                    (platform_id, NOW, NOW),
                ).lastrowid
            )
            occurrence_id = int(
                database.connection.execute(
                    """INSERT INTO media_occurrences (
                           post_id, source_key, media_index, media_type, remote_url,
                           observed_at
                       ) VALUES (?, 'fixture:p0', 0, 'image', ?, ?)""",
                    (post_id, signed_url, NOW),
                ).lastrowid
            )
            database.connection.execute(
                """INSERT INTO managed_roots (
                       managed_root_id, root_kind, root_identity, display_label, created_at
                   ) VALUES (1, 'managed', 'fixture-dev:fixture-ino', 'managed', ?)""",
                (NOW,),
            )
            plan_id = writer.create_acquisition_plan(
                AcquisitionPlanRecord("plan-v1", "a" * 64, 1, 1, 0, 0, NOW)
            )
            plan_item_id = writer.add_acquisition_plan_item(
                AcquisitionPlanItemRecord(
                    plan_id,
                    "fixture-item",
                    occurrence_id,
                    "original",
                    "b" * 64,
                    recipe.policy.key,
                    recipe.policy.version,
                    "eligible",
                    NOW,
                )
            )
            run_id = writer.begin_acquisition_run(
                AcquisitionRunRecord(
                    plan_id,
                    1,
                    AcquisitionLimits(1, 1000, 1000, 1, 30, 1, 1000),
                    1,
                    NOW,
                )
            )
            run_item_id = writer.record_acquisition_run_item(
                AcquisitionRunItemRecord(run_id, plan_item_id, "running", NOW, NOW)
            )
            writer.record_acquisition_attempt(
                AcquisitionAttemptRecord(
                    run_item_id,
                    1,
                    "failed",
                    recipe.request_identity,
                    recipe.policy.key,
                    recipe.policy.version,
                    NOW,
                    outcome="policy_failure",
                    diagnostic=diagnostic,
                    finished_at=NOW,
                )
            )

        attempt = database.connection.execute(
            "SELECT * FROM media_acquisition_attempts"
        ).fetchone()
        durable = json.dumps(dict(attempt), sort_keys=True)
        assert recipe.request_identity in durable
        assert "pixiv:policy_failure" in durable
        assert signed_url not in durable
        assert "persisted-secret" not in durable
        assert bearer not in durable
