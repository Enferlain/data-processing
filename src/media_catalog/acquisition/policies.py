from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from urllib.parse import SplitResult, urljoin, urlsplit

from media_catalog.adapters.e621.config import E621_USER_AGENT


class RequestPolicyError(ValueError):
    """A secret-safe provider request-policy failure."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PolicyIdentity:
    key: str
    version: str


@dataclass(frozen=True, slots=True)
class CredentialReference:
    """A non-secret reference resolved only immediately before a request."""

    key: str

    def __post_init__(self) -> None:
        if not self.key or len(self.key) > 200:
            raise ValueError("credential reference key must be between 1 and 200 characters")


@dataclass(frozen=True, slots=True)
class ResolvedCredentials:
    """Ephemeral authorization material; repr intentionally reveals no values."""

    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    cookies: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        object.__setattr__(self, "cookies", MappingProxyType(dict(self.cookies)))

    def __repr__(self) -> str:
        return (
            "ResolvedCredentials("
            f"header_names={tuple(sorted(self.headers))!r}, "
            f"cookie_names={tuple(sorted(self.cookies))!r})"
        )


CredentialResolver = Callable[[CredentialReference], ResolvedCredentials]


@dataclass(frozen=True, slots=True)
class ResponseExpectations:
    content_type_prefixes: tuple[str, ...]
    allow_missing_content_type: bool = True

    def accepts(self, content_type: str | None) -> bool:
        if not content_type:
            return self.allow_missing_content_type
        media_type = content_type.partition(";")[0].strip().lower()
        return any(media_type.startswith(prefix) for prefix in self.content_type_prefixes)


@dataclass(frozen=True, slots=True)
class RetryClassification:
    category: str
    retryable: bool


def _default_status_classifier(status_code: int) -> RetryClassification:
    if status_code in {401}:
        return RetryClassification("authentication_required", False)
    if status_code in {403}:
        return RetryClassification("authorization_denied", False)
    if status_code in {404, 410}:
        return RetryClassification("unavailable", False)
    if status_code == 429:
        return RetryClassification("rate_limited", True)
    if status_code in {408, 425} or 500 <= status_code <= 599:
        return RetryClassification("transient_provider", True)
    if 200 <= status_code <= 299:
        return RetryClassification("success", False)
    return RetryClassification("invalid_content", False)


@dataclass(frozen=True, slots=True)
class RequestRecipe:
    """An ephemeral request with a deliberately redacted public representation."""

    policy: PolicyIdentity
    provider: str
    operation: str
    media_occurrence_id: int
    variant_key: str
    request_identity: str
    url: str = field(repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    credential_reference: CredentialReference | None = field(default=None, repr=False)
    response: ResponseExpectations = field(
        default_factory=lambda: ResponseExpectations(("image/",)), repr=False
    )
    redirect_hosts: frozenset[str] = field(default_factory=frozenset, repr=False)
    status_classifier: Callable[[int], RetryClassification] = field(
        default=_default_status_classifier, repr=False, compare=False
    )
    method: str = "GET"

    def __post_init__(self) -> None:
        if self.method != "GET" or self.media_occurrence_id <= 0:
            raise ValueError("media request recipe requires GET and a positive occurrence id")
        if len(self.request_identity) != 64:
            raise ValueError("request identity must be a SHA-256 digest")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))

    def as_dict(self) -> dict[str, object]:
        """Return durable-safe identity fields, never the rendered URL or values."""

        return {
            "policy_key": self.policy.key,
            "policy_version": self.policy.version,
            "provider": self.provider,
            "operation": self.operation,
            "media_occurrence_id": self.media_occurrence_id,
            "variant_key": self.variant_key,
            "request_identity": self.request_identity,
            "method": self.method,
            "header_names": sorted(self.headers),
            "credential_reference": (
                self.credential_reference.key if self.credential_reference else None
            ),
        }

    def __repr__(self) -> str:
        return f"RequestRecipe({self.as_dict()!r})"

    def classify_status(self, status_code: int) -> RetryClassification:
        return self.status_classifier(status_code)


def _request_digest(material: object) -> str:
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parsed_https_url(url: str) -> SplitResult:
    try:
        parsed = urlsplit(url)
        port = parsed.port
        hostname = parsed.hostname
    except (TypeError, ValueError) as error:
        raise RequestPolicyError("invalid_url", "request URL is invalid") from error
    if parsed.scheme.lower() != "https":
        raise RequestPolicyError("scheme_not_allowed", "request destination must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise RequestPolicyError("userinfo_not_allowed", "request destination contains user-info")
    if not hostname:
        raise RequestPolicyError("invalid_host", "request destination has no host")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise RequestPolicyError("ip_literal_not_allowed", "IP-literal destinations are forbidden")
    if port not in (None, 443):
        raise RequestPolicyError("port_not_allowed", "request destination uses an unexpected port")
    if parsed.fragment:
        raise RequestPolicyError("fragment_not_allowed", "request destination contains a fragment")
    return parsed


def validate_destination(url: str, *, allowed_hosts: frozenset[str]) -> SplitResult:
    """Validate a request destination without reflecting its sensitive components."""

    parsed = _parsed_https_url(url)
    hostname_value = parsed.hostname
    if hostname_value is None:
        raise RequestPolicyError("invalid_host", "request destination has no host")
    hostname = hostname_value.lower().rstrip(".")
    if hostname not in allowed_hosts:
        raise RequestPolicyError("host_not_allowed", "request destination host is not trusted")
    return parsed


def validate_redirect(
    current_url: str,
    location: str,
    *,
    allowed_hosts: frozenset[str],
) -> str:
    """Resolve and validate one manual redirect hop before it is requested."""

    if not location:
        raise RequestPolicyError("invalid_redirect", "redirect has no destination")
    destination = urljoin(current_url, location)
    validate_destination(destination, allowed_hosts=allowed_hosts)
    return destination


class MediaRequestPolicy:
    """Versioned provider media-policy contract."""

    identity: PolicyIdentity
    provider: str
    allowed_hosts: frozenset[str]
    redirect_hosts: frozenset[str]
    headers: Mapping[str, str]
    response_expectations: ResponseExpectations
    credential_reference: CredentialReference | None = None

    def recipe(
        self,
        *,
        media_occurrence_id: int,
        variant_key: str,
        selected_url: str,
    ) -> RequestRecipe:
        parsed = validate_destination(selected_url, allowed_hosts=self.allowed_hosts)
        hostname = parsed.hostname
        if hostname is None:
            raise RequestPolicyError("invalid_host", "request destination has no host")
        if not variant_key:
            raise RequestPolicyError("invalid_variant", "variant key is required")
        operation = self.operation_for_variant(variant_key)
        identity = _request_digest(
            {
                "policy": [self.identity.key, self.identity.version],
                "provider": self.provider,
                "operation": operation,
                "occurrence": media_occurrence_id,
                "variant": variant_key,
                # Digest the sensitive rendered target instead of persisting it.
                "target_digest": hashlib.sha256(selected_url.encode("utf-8")).hexdigest(),
                "host": hostname.lower(),
                "header_names": sorted(self.headers),
                "credential_reference": (
                    self.credential_reference.key if self.credential_reference else None
                ),
            }
        )
        return RequestRecipe(
            policy=self.identity,
            provider=self.provider,
            operation=operation,
            media_occurrence_id=media_occurrence_id,
            variant_key=variant_key,
            request_identity=identity,
            url=selected_url,
            headers=self.headers,
            credential_reference=self.credential_reference,
            response=self.response_expectations,
            redirect_hosts=self.redirect_hosts,
            status_classifier=self.classify_status,
        )

    def validate_redirect(self, current_url: str, location: str) -> str:
        return validate_redirect(current_url, location, allowed_hosts=self.redirect_hosts)

    def operation_for_variant(self, variant_key: str) -> str:
        return "download-media"

    def declared_exact_claims_apply(self, variant_key: str) -> bool:
        """Whether occurrence-level exact claims describe this selected representation."""

        return variant_key in {"primary", "original"}

    def classify_status(self, status_code: int) -> RetryClassification:
        return _default_status_classifier(status_code)


class PixivMediaPolicy(MediaRequestPolicy):
    identity = PolicyIdentity("pixiv-media", "pixiv-media-v1")
    provider = "pixiv"
    allowed_hosts = frozenset({"i.pximg.net"})
    redirect_hosts = allowed_hosts
    headers = MappingProxyType({"Referer": "https://app-api.pixiv.net/"})
    response_expectations = ResponseExpectations(
        ("image/", "video/", "application/zip", "application/octet-stream")
    )

    def operation_for_variant(self, variant_key: str) -> str:
        return "download-ugoira-archive" if variant_key == "archive" else "download-image"


class DanbooruMediaPolicy(MediaRequestPolicy):
    def __init__(
        self,
        *,
        provider: str,
        base_host: str,
        media_hosts: tuple[str, ...],
        version: str = "danbooru-media-v1",
    ) -> None:
        if not provider or not media_hosts:
            raise ValueError("Danbooru media policy requires provider and media hosts")
        hosts = frozenset(host.lower().rstrip(".") for host in (base_host, *media_hosts))
        for host in hosts:
            _parsed_https_url(f"https://{host}/")
        self.identity = PolicyIdentity(f"{provider}-media", version)
        self.provider = provider
        self.allowed_hosts = hosts
        self.redirect_hosts = hosts
        self.headers = MappingProxyType({"Referer": f"https://{base_host}/"})
        self.response_expectations = ResponseExpectations(
            ("image/", "video/", "application/zip", "application/octet-stream")
        )

    def operation_for_variant(self, variant_key: str) -> str:
        if variant_key not in {"primary", "original", "sample", "preview"}:
            raise RequestPolicyError("invalid_variant", "Danbooru media variant is not supported")
        return f"download-{variant_key}"


class E621MediaPolicy(MediaRequestPolicy):
    """Policy for explicitly selected e621 media URLs returned by metadata."""

    identity = PolicyIdentity("e621-media", "e621-media-v1")
    provider = "e621"
    # Keep the media-host admission rule deliberately bounded.  The provider's
    # returned URLs use ``staticN.e621.net``; enumerate the supported one-digit
    # host range instead of broadening the generic exact-host validator.
    allowed_hosts = frozenset(f"static{index}.e621.net" for index in range(1, 10))
    redirect_hosts = allowed_hosts
    headers = MappingProxyType(
        {
            "User-Agent": E621_USER_AGENT,
            "Referer": "https://e621.net/",
        }
    )
    response_expectations = ResponseExpectations(
        ("image/", "video/"),
        allow_missing_content_type=False,
    )

    def operation_for_variant(self, variant_key: str) -> str:
        if variant_key not in {"original", "sample", "preview"}:
            raise RequestPolicyError("invalid_variant", "e621 media variant is not supported")
        return f"download-{variant_key}"

    def declared_exact_claims_apply(self, variant_key: str) -> bool:
        """Only the returned original owns e621's declared file claims."""

        return variant_key == "original"


PIXIV_MEDIA_POLICY = PixivMediaPolicy()
DANBOORU_MEDIA_POLICY = DanbooruMediaPolicy(
    provider="danbooru",
    base_host="danbooru.donmai.us",
    media_hosts=("cdn.donmai.us",),
)
AIBOORU_MEDIA_POLICY = DanbooruMediaPolicy(
    provider="aibooru",
    base_host="aibooru.online",
    media_hosts=("safe.aibooru.online", "general.aibooru.online", "aibooru.download"),
)
E621_MEDIA_POLICY = E621MediaPolicy()

_BUILTIN_POLICIES: dict[str, MediaRequestPolicy] = {
    "pixiv": PIXIV_MEDIA_POLICY,
    "danbooru": DANBOORU_MEDIA_POLICY,
    "aibooru": AIBOORU_MEDIA_POLICY,
    "e621": E621_MEDIA_POLICY,
}


def media_request_policy_for_platform(platform: str) -> MediaRequestPolicy | None:
    return _BUILTIN_POLICIES.get(platform)


def policy_identity_for_platform(platform: str) -> PolicyIdentity | None:
    """Return the installed media policy identity without rendering a request."""

    policy = media_request_policy_for_platform(platform)
    return policy.identity if policy else None


_DIAGNOSTIC_COMPONENT = re.compile(r"^[a-z][a-z0-9_-]{0,99}$")


def safe_failure_diagnostic(
    provider: str,
    category: str,
    *,
    error: BaseException | None = None,
) -> str:
    """Create bounded failure evidence without rendering an untrusted exception.

    ``error`` is accepted so callers make the redaction decision explicit. Its text is
    intentionally never included because transport exceptions commonly embed signed
    URLs, request headers, or proxy credentials.
    """

    del error
    if not _DIAGNOSTIC_COMPONENT.fullmatch(provider):
        provider = "unknown-provider"
    if not _DIAGNOSTIC_COMPONENT.fullmatch(category):
        category = "request-failure"
    return f"{provider}:{category}"
