"""Public, redacted contracts for artist-library expansion planning."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

MAX_EXPANSION_REQUESTS = 100
MAX_EXPANSION_PAGES = 100
MAX_EXPANSION_RECORDS = 10_000
MAX_EXPANSION_SECONDS = 3_600


def stable_digest(*parts: object) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ExpansionTargetKind(StrEnum):
    ACCOUNT = "account"
    ATTRIBUTION = "attribution"


class ExpansionAuthorityMode(StrEnum):
    CONFIRMED = "confirmed"
    EXPLICIT = "explicit"


@dataclass(frozen=True, slots=True)
class ExpansionLimits:
    requests: int = 3
    pages: int = 3
    records: int = 200
    seconds: int = 60

    def __post_init__(self) -> None:
        limits = {
            "requests": (self.requests, MAX_EXPANSION_REQUESTS),
            "pages": (self.pages, MAX_EXPANSION_PAGES),
            "records": (self.records, MAX_EXPANSION_RECORDS),
            "seconds": (self.seconds, MAX_EXPANSION_SECONDS),
        }
        for name, (value, maximum) in limits.items():
            if not isinstance(value, int) or isinstance(value, bool) or not 0 < value <= maximum:
                raise ValueError(f"library expansion {name} must be between 1 and {maximum}")

    def as_dict(self) -> dict[str, int]:
        return {
            "requests": self.requests,
            "pages": self.pages,
            "records": self.records,
            "seconds": self.seconds,
        }


@dataclass(frozen=True, slots=True)
class ExpansionCapability:
    key: str
    version: str
    provider: str
    target_kind: ExpansionTargetKind
    operation: str
    adapter_version: str
    schema_version: str
    count_probe_key: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "version": self.version,
            "provider": self.provider,
            "target_kind": self.target_kind.value,
            "operation": self.operation,
            "adapter_version": self.adapter_version,
            "schema_version": self.schema_version,
            "count_probe_supported": self.count_probe_key is not None,
        }


@dataclass(frozen=True, slots=True)
class ExpansionAuthority:
    mode: ExpansionAuthorityMode
    reference: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.mode is ExpansionAuthorityMode.CONFIRMED and not self.reference:
            raise ValueError("confirmed expansion authority requires review provenance")
        if self.mode is ExpansionAuthorityMode.EXPLICIT and self.reference is not None:
            raise ValueError("explicit expansion authority cannot claim review provenance")
        if self.note is not None and (not self.note.strip() or len(self.note) > 1_000):
            raise ValueError("expansion selection note must contain 1 to 1000 characters")

    def as_dict(self) -> dict[str, object]:
        return {"mode": self.mode.value, "reference": self.reference, "note": self.note}


@dataclass(frozen=True, slots=True)
class ExpansionTarget:
    kind: ExpansionTargetKind
    catalog_id: int
    provider: str
    instance: str
    native_id: str
    availability: str
    revision: str
    capability: ExpansionCapability

    @property
    def reference(self) -> str:
        return f"{self.kind.value}:{self.catalog_id}"

    def as_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference,
            "kind": self.kind.value,
            "catalog_id": self.catalog_id,
            "provider": self.provider,
            "instance": self.instance,
            "native_id": self.native_id,
            "availability": self.availability,
            "revision": self.revision,
            "capability": self.capability.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class ExpansionTargetChoice:
    target: ExpansionTarget
    authority: ExpansionAuthority
    source_kind: str
    source_reference: str

    @property
    def digest(self) -> str:
        return stable_digest(
            self.target.reference,
            self.target.revision,
            self.target.capability.as_dict(),
            self.authority.mode.value,
            self.authority.reference,
            self.authority.note,
            self.source_kind,
            self.source_reference,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "target": self.target.as_dict(),
            "authority": self.authority.as_dict(),
            "source_kind": self.source_kind,
            "source_reference": self.source_reference,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class ExpansionEstimate:
    state: str
    count: int | None = None
    observed_at: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.state == "unknown":
            if any(value is not None for value in (self.count, self.observed_at, self.source)):
                raise ValueError("unknown expansion estimate cannot carry count provenance")
        elif self.state == "count":
            if self.count is None or self.count < 0 or not self.observed_at or not self.source:
                raise ValueError("count expansion estimate requires non-negative provenance")
        else:
            raise ValueError(f"unsupported expansion estimate state: {self.state}")

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "count": self.count,
            "observed_at": self.observed_at,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class LibraryExpansionPlan:
    seed: str
    seed_revision: str
    limits: ExpansionLimits
    choices: tuple[ExpansionTargetChoice, ...]
    selected: ExpansionTargetChoice | None
    estimate: ExpansionEstimate
    exclusions: tuple[dict[str, str], ...]
    source_revision: str

    @property
    def material_digest(self) -> str:
        return stable_digest(*(choice.digest for choice in self.choices))

    @property
    def digest(self) -> str:
        return stable_digest(
            self.seed,
            self.seed_revision,
            self.limits.as_dict(),
            self.material_digest,
            self.selected.digest if self.selected else None,
            self.estimate.as_dict(),
            self.exclusions,
            self.source_revision,
        )

    @property
    def execution_revision(self) -> str:
        """Digest of material that can make an existing execution plan stale."""
        return stable_digest(
            self.seed,
            self.seed_revision,
            self.limits.as_dict(),
            self.material_digest,
            self.selected.digest if self.selected else None,
            self.exclusions,
            self.source_revision,
        )

    @property
    def executable(self) -> bool:
        return self.selected is not None

    @property
    def ambiguity(self) -> str | None:
        return (
            "ambiguous_selection_required"
            if self.selected is None and len(self.choices) > 1
            else None
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "seed": self.seed,
            "seed_revision": self.seed_revision,
            "limits": self.limits.as_dict(),
            "choices": [choice.as_dict() for choice in self.choices],
            "choice_count": len(self.choices),
            "selected": self.selected.as_dict() if self.selected else None,
            "estimate": self.estimate.as_dict(),
            "exclusions": list(self.exclusions),
            "excluded_count": len(self.exclusions),
            "source_revision": self.source_revision,
            "digest": self.digest,
            "executable": self.executable,
            "ambiguity": self.ambiguity,
            "network_requested": False,
        }
