"""Operator-facing search policy: what gets searched and how fresh is fresh.

Stage 1 of the discovery/search roadmap (change add-discovery-search-policy).
The policy is one value object carried through planning and execution; the
freshness verdict is a pure function over a ledger row so planner decisions
stay explainable and testable without I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from media_catalog.adapters.contracts import LOOKUP_STRATEGY_VERSION, LookupStrategy

TRAILS = "trails"
ACTIVE = "active"
SEARCH_MODES = frozenset({TRAILS, ACTIVE})

RECHECK_UNSEARCHED = "unsearched"
RECHECK_STALE = "stale"
RECHECK_FORCE = "force"
RECHECK_MODES = frozenset({RECHECK_UNSEARCHED, RECHECK_STALE, RECHECK_FORCE})

LOCAL_METHOD_VERSION = "local-v1"
FETCH_METHOD_VERSION = "fetch-v1"

LOCAL_METHODS = frozenset({"local_md5", "local_source_url", "local_platform_identity"})
FETCH_METHOD = "fetch_post"

# Methods that search by derived or operator-supplied queries (artist names,
# aliases, free text — later reverse-image and semantic searches) rather than
# following references the subject already carries.  Stage 2 extends this set
# alongside the method vocabulary.
ACTIVE_METHODS = frozenset(
    strategy.value for strategy in LookupStrategy if strategy.value.startswith("artist_")
)


def is_active_method(method: str) -> bool:
    return method in ACTIVE_METHODS


def method_version(method: str) -> str:
    """Version stamp of a search method's query semantics.

    Lookup strategies share the adapter strategy version; the local catalog
    methods and the follow-up fetch carry their own stamps so a semantics
    change can invalidate old attempts without touching the others.
    """
    if method in LOCAL_METHODS:
        return LOCAL_METHOD_VERSION
    if method == FETCH_METHOD:
        return FETCH_METHOD_VERSION
    LookupStrategy(method)  # raises ValueError for unknown methods
    return LOOKUP_STRATEGY_VERSION


@dataclass(frozen=True, slots=True)
class SearchPolicy:
    """What the operator wants searched, and how old a success may be."""

    included_sources: frozenset[str] | None = None
    excluded_sources: frozenset[str] = frozenset()
    methods: frozenset[str] | None = None
    search_mode: str = TRAILS
    recheck: str = RECHECK_UNSEARCHED
    stale_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.search_mode not in SEARCH_MODES:
            raise ValueError(f"unknown search mode: {self.search_mode}")
        if self.recheck not in RECHECK_MODES:
            raise ValueError(f"unknown recheck mode: {self.recheck}")
        if self.recheck == RECHECK_STALE and not self.stale_after_seconds:
            raise ValueError("recheck=stale requires a staleness age")
        if self.recheck != RECHECK_STALE and self.stale_after_seconds:
            raise ValueError("a staleness age is only meaningful with recheck=stale")
        if self.stale_after_seconds is not None and self.stale_after_seconds <= 0:
            raise ValueError("staleness age must be positive")
        if self.included_sources is not None and self.excluded_sources:
            overlap = self.included_sources & self.excluded_sources
            if overlap:
                raise ValueError(f"sources both included and excluded: {sorted(overlap)}")
        if self.included_sources is not None and not self.included_sources:
            raise ValueError("an empty include list would search nothing")

    def source_reason(self, source: str) -> str | None:
        """Why this search target is excluded, or None when allowed."""
        if self.included_sources is not None and source not in self.included_sources:
            return (
                "source not included by policy "
                f"(included: {', '.join(sorted(self.included_sources))})"
            )
        if source in self.excluded_sources:
            return "source excluded by policy"
        return None

    def method_reason(self, method: str) -> str | None:
        """Why this method is excluded, or None when allowed."""
        if self.methods is not None and method not in self.methods:
            return "method filtered by policy"
        if is_active_method(method) and self.search_mode != ACTIVE:
            return "active search disabled by policy (trails only)"
        return None

    def with_search_term(self, search_term: str | None) -> SearchPolicy:
        """An artist search term implies active search (pre-policy behavior)."""
        if search_term and self.search_mode == TRAILS:
            return replace(self, search_mode=ACTIVE)
        return self

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "search_mode": self.search_mode,
            "recheck": self.recheck,
        }
        if self.included_sources is not None:
            result["included_sources"] = sorted(self.included_sources)
        if self.excluded_sources:
            result["excluded_sources"] = sorted(self.excluded_sources)
        if self.methods is not None:
            result["methods"] = sorted(self.methods)
        if self.stale_after_seconds is not None:
            result["stale_after_seconds"] = self.stale_after_seconds
        return result


@dataclass(frozen=True, slots=True)
class FreshnessVerdict:
    fresh: bool
    reason: str


def freshness_verdict(
    policy: SearchPolicy,
    attempt: Any,
    *,
    method: str,
    now: datetime,
) -> FreshnessVerdict:
    """Is the latest attempt for this key still fresh under this policy?

    ``attempt`` is a ledger row (mapping) or None.  Only completed successful
    attempts can be fresh; failed, deferred, and interrupted work never is, so
    later runs retry it.  A zero-result success is fresh: it completed its
    bounded scope.

    """
    if attempt is None:
        return FreshnessVerdict(False, "never attempted")
    version = method_version(method)
    if attempt["strategy_version"] != version:
        return FreshnessVerdict(
            False,
            f"prior attempt under strategy version {attempt['strategy_version']}"
            f" (current {version})",
        )
    if attempt["status"] != "complete" or attempt["outcome"] != "success":
        state = attempt["outcome"] or attempt["status"]
        finished = attempt["finished_at"] or attempt["started_at"]
        return FreshnessVerdict(
            False, f"prior attempt ended {attempt['status']}/{state} at {finished}"
        )
    if policy.recheck == RECHECK_FORCE:
        return FreshnessVerdict(False, "force recheck requested by policy")
    finished_at = str(attempt["finished_at"])
    if policy.recheck == RECHECK_STALE:
        assert policy.stale_after_seconds is not None
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        age = now - finished
        if age > timedelta(seconds=policy.stale_after_seconds):
            return FreshnessVerdict(
                False,
                f"prior success at {finished_at} older than {policy.stale_after_seconds}s",
            )
    return FreshnessVerdict(
        True,
        f"fresh successful attempt {attempt['discovery_search_attempt_id']} at {finished_at}",
    )


_STALE_AFTER_PATTERN = re.compile(r"^(\d{1,8})([smhd])$")
_STALE_AFTER_UNITS = {"s": 1, "m": 60, "h": 3_600, "d": 86_400}


def parse_stale_after(value: str) -> int:
    match = _STALE_AFTER_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("--stale-after must be a duration like 30d, 12h, 90m, or 45s")
    return int(match.group(1)) * _STALE_AFTER_UNITS[match.group(2)]


def build_policy(
    *,
    include_sources: tuple[str, ...] | list[str] = (),
    exclude_sources: tuple[str, ...] | list[str] = (),
    methods: tuple[str, ...] | list[str] = (),
    search_mode: str = TRAILS,
    recheck: str = RECHECK_UNSEARCHED,
    stale_after: str | None = None,
    search_term: str | None = None,
    known_sources: frozenset[str] | set[str] | tuple[str, ...],
    known_methods: frozenset[str] | set[str] | tuple[str, ...],
) -> SearchPolicy:
    """Validate operator input into a policy, rejecting unknown names.

    Unknown source or method names are typos in waiting; they fail loudly with
    the valid vocabulary instead of silently matching nothing.
    """
    unknown_sources = sorted((set(include_sources) | set(exclude_sources)) - set(known_sources))
    if unknown_sources:
        raise ValueError(
            f"unknown search source(s): {', '.join(unknown_sources)}"
            f" (valid: {', '.join(sorted(known_sources))})"
        )
    unknown_methods = sorted(set(methods) - set(known_methods))
    if unknown_methods:
        raise ValueError(
            f"unknown search method(s): {', '.join(unknown_methods)}"
            f" (valid: {', '.join(sorted(known_methods))})"
        )
    if include_sources and exclude_sources:
        raise ValueError(
            "--include-source and --exclude-source are mutually exclusive;"
            " include already restricts the target set"
        )
    stale_seconds = parse_stale_after(stale_after) if stale_after else None
    policy = SearchPolicy(
        included_sources=frozenset(include_sources) or None,
        excluded_sources=frozenset(exclude_sources),
        methods=frozenset(methods) or None,
        search_mode=search_mode,
        recheck=recheck,
        stale_after_seconds=stale_seconds,
    )
    return policy.with_search_term(search_term)


def policy_from_dict(data: dict[str, Any]) -> SearchPolicy:
    """Rebuild a persisted policy snapshot (audit and execution re-read)."""
    return SearchPolicy(
        included_sources=(
            frozenset(data["included_sources"]) if "included_sources" in data else None
        ),
        excluded_sources=frozenset(data.get("excluded_sources", ())),
        methods=frozenset(data["methods"]) if "methods" in data else None,
        search_mode=data.get("search_mode", TRAILS),
        recheck=data.get("recheck", RECHECK_UNSEARCHED),
        stale_after_seconds=data.get("stale_after_seconds"),
    )
