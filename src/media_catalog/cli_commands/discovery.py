"""Link-driven ingest and discovery sessions: fetch, discover."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import httpx

from media_catalog.adapter_factory import adapter_construction
from media_catalog.adapters.contracts import LookupStrategy
from media_catalog.adapters.pixiv import PixivAdapter
from media_catalog.cli_commands.support import add_json, add_sync_limits
from media_catalog.database import CatalogDatabase
from media_catalog.discovery import LOOKUP_PROVIDERS, DiscoveryOrchestrator
from media_catalog.discovery.policy import (
    ACTIVE,
    RECHECK_FORCE,
    RECHECK_STALE,
    RECHECK_UNSEARCHED,
    TRAILS,
    build_policy,
)
from media_catalog.discovery.run import DiscoveryRunService, SubjectInput
from media_catalog.link_resolution import resolve_link
from media_catalog.output import public_path
from media_catalog.remote_sync import MetadataSyncService, SyncLimits


def _fetch_adapter_for(platform: str) -> tuple[Any, float]:
    return adapter_construction(platform)


COMMANDS = ("fetch", "discover")


def register(commands: argparse._SubParsersAction) -> None:
    fetch = commands.add_parser(
        "fetch",
        description=(
            "Resolve a supported-site URL and sync its metadata"
            " (gelbooru-family links need DAPI credentials in the environment)"
        ),
    )
    fetch.add_argument("catalog", type=Path)
    fetch.add_argument("url", help="https post URL from any supported platform")
    add_sync_limits(fetch, listing=False)
    fetch.add_argument("--resolve-only", action="store_true")
    discover_cmd = commands.add_parser(
        "discover",
        description="One input initiates a bounded discovery session (offline plan by default)",
    )
    discover_cmd.add_argument("catalog", type=Path)
    input_group = discover_cmd.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--url",
        action="append",
        help="post URL from any supported platform (repeatable: one subject each)",
    )
    input_group.add_argument(
        "--post",
        type=int,
        action="append",
        help="existing catalog post id (repeatable: one subject each)",
    )
    input_group.add_argument(
        "--account",
        type=int,
        action="append",
        help="existing catalog account id (repeatable: one subject each)",
    )
    input_group.add_argument(
        "--session", type=int, help="re-report a prior session instead of starting one"
    )
    # --file stays outside the group: it is a standalone input (bare-file
    # discovery, repeatable) and remains attachable to a single --url exactly
    # as before.
    discover_cmd.add_argument(
        "--file",
        type=Path,
        action="append",
        help="arbitrary local image: discovery starts from its verified hashes"
        " (or attaches the file to a single --url seed)",
    )
    discover_cmd.add_argument("--media-root", type=Path)
    discover_cmd.add_argument("--declared-md5")
    discover_cmd.add_argument("--note")
    discover_cmd.add_argument("--live", action="store_true")
    discover_cmd.add_argument("--max-requests", type=int, default=12)
    discover_cmd.add_argument("--max-seconds", type=int, default=120)
    discover_cmd.add_argument("--search-term", help="artist search term for account-seed discovery")
    discover_cmd.add_argument(
        "--include-source",
        action="append",
        default=[],
        help="search only these sources (repeatable; catalog + provider keys)",
    )
    discover_cmd.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        help="remove these sources from the default target set (repeatable)",
    )
    discover_cmd.add_argument(
        "--method",
        action="append",
        default=[],
        help="search only these methods (repeatable; lookup strategies,"
        " local_md5/local_source_url/local_platform_identity, fetch_post)",
    )
    discover_cmd.add_argument(
        "--search-mode",
        choices=(TRAILS, ACTIVE),
        default=TRAILS,
        help="trails follows known references and hashes only; active also"
        " allows artist/text-style search (--search-term implies active)",
    )
    discover_cmd.add_argument(
        "--recheck",
        choices=(RECHECK_UNSEARCHED, RECHECK_STALE, RECHECK_FORCE),
        default=RECHECK_UNSEARCHED,
        help="unsearched skips fresh successful attempts (default); stale"
        " replans successes older than --stale-after; force re-executes all",
    )
    discover_cmd.add_argument(
        "--stale-after",
        help="staleness age for --recheck stale (e.g. 30d, 12h, 90m, 45s)",
    )
    discover_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="report the plan (including freshness decisions) without executing anything",
    )
    discover_cmd.add_argument(
        "--search-state",
        action="store_true",
        help="inspect per-subject search state offline: latest attempts and"
        " freshness verdicts; no session is created",
    )
    add_json(discover_cmd)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "fetch":
        return _execute_fetch(arguments)
    return _execute_discover(arguments)


def _execute_fetch(arguments: argparse.Namespace) -> dict[str, object]:
    resolved = resolve_link(arguments.url)
    catalog_label = public_path(arguments.catalog)
    if arguments.resolve_only:
        return {
            "catalog": catalog_label,
            "url": arguments.url,
            "platform": resolved.platform,
            "operation": resolved.operation.value,
            "target": resolved.target,
            "canonical_url": resolved.canonical_url,
            "status": "resolved",
        }
    limits = SyncLimits(
        arguments.max_requests,
        arguments.max_pages,
        arguments.max_records,
        arguments.max_seconds,
    )
    adapter, minimum_interval = _fetch_adapter_for(resolved.platform)
    with httpx.Client() as client:
        bound = adapter(client)
        if isinstance(bound, PixivAdapter):
            with bound as pixiv_adapter, CatalogDatabase(arguments.catalog) as database:
                result = MetadataSyncService(
                    database,
                    pixiv_adapter,
                    minimum_interval_seconds=minimum_interval,
                ).synchronize(
                    resolved.operation,
                    resolved.target,
                    limits=limits,
                    resume_from_run_id=arguments.resume_from,
                )
        else:
            with CatalogDatabase(arguments.catalog) as database:
                result = MetadataSyncService(
                    database,
                    bound,
                    minimum_interval_seconds=minimum_interval,
                ).synchronize(
                    resolved.operation,
                    resolved.target,
                    limits=limits,
                    resume_from_run_id=arguments.resume_from,
                )
    return {
        "catalog": catalog_label,
        "url": arguments.url,
        "platform": resolved.platform,
        "target": resolved.target,
        "canonical_url": resolved.canonical_url,
        **result.as_dict(),
    }


def _known_sources() -> frozenset[str]:
    return frozenset({"catalog"} | {provider.platform_key for provider in LOOKUP_PROVIDERS})


def _known_methods() -> frozenset[str]:
    return frozenset(
        {"local_md5", "local_source_url", "local_platform_identity", "fetch_post"}
        | {strategy.value for strategy in LookupStrategy}
    )


def _discover_subjects(arguments: argparse.Namespace) -> tuple[list[SubjectInput], Path | None]:
    """Build explicit subjects plus the single --url attachment, if any."""
    urls = list(arguments.url or [])
    posts = list(arguments.post or [])
    accounts = list(arguments.account or [])
    files = list(arguments.file or [])
    attached: Path | None = None
    if urls:
        if len(files) > 1:
            raise ValueError(
                "--file attaches to a single --url seed; multiple --file inputs"
                " are standalone subjects and cannot combine with --url"
            )
        if files and (posts or accounts or len(urls) > 1):
            raise ValueError(
                "--file attaches to a single --url seed; drop --file or the extra inputs"
            )
        attached = files[0] if files else None
        subjects = [SubjectInput(url=url) for url in urls]
    else:
        subjects = [
            *(SubjectInput(post_id=post) for post in posts),
            *(SubjectInput(account_id=account) for account in accounts),
            *(SubjectInput(file=path) for path in files),
        ]
    return subjects, attached


def _execute_discover(arguments: argparse.Namespace) -> dict[str, object]:
    if not 1 <= arguments.max_requests <= 100:
        raise ValueError("--max-requests must be between 1 and 100")
    if not 1 <= arguments.max_seconds <= 3600:
        raise ValueError("--max-seconds must be between 1 and 3600")
    if arguments.stale_after and arguments.recheck != RECHECK_STALE:
        raise ValueError("--stale-after is only meaningful with --recheck stale")
    subjects, attached = _discover_subjects(arguments)
    primary = subjects or attached is not None
    if arguments.search_state:
        if arguments.session is not None:
            raise ValueError("--search-state inspects subjects; --session re-reports one")
        if arguments.live or arguments.dry_run:
            raise ValueError("--search-state is offline inspection; no --live or --dry-run")
        if attached is not None:
            raise ValueError("--search-state takes subjects; a --url attachment is not one")
        if not subjects:
            raise ValueError("--search-state requires at least one subject input")
    elif arguments.session is not None:
        if primary:
            raise ValueError("--session re-reports a prior session; give no other input")
        if arguments.dry_run:
            raise ValueError("--dry-run plans a new session; --session re-reports one")
    elif not primary:
        raise ValueError("one input is required (--url, --post, --account, or --file alone)")
    if (arguments.session is not None or arguments.search_state) and (
        arguments.note or arguments.declared_md5 or arguments.media_root
    ):
        raise ValueError(
            "--note, --declared-md5, and --media-root seed new url sessions;"
            " they are meaningless with --session or --search-state"
        )
    policy = build_policy(
        include_sources=arguments.include_source,
        exclude_sources=arguments.exclude_source,
        methods=arguments.method,
        search_mode=arguments.search_mode,
        recheck=arguments.recheck,
        stale_after=arguments.stale_after,
        search_term=arguments.search_term,
        known_sources=_known_sources(),
        known_methods=_known_methods(),
    )
    catalog_label = public_path(arguments.catalog)
    with CatalogDatabase(arguments.catalog) as database:
        if arguments.session is not None:
            return {
                "catalog": catalog_label,
                **DiscoveryOrchestrator(database).report(arguments.session),
            }
        if arguments.search_state:
            return {
                "catalog": catalog_label,
                **DiscoveryRunService(database).search_state(subjects, policy=policy),
            }
        if len(subjects) == 1:
            subject = subjects[0]
            result = DiscoveryOrchestrator(database).start(
                url=subject.url,
                file=subject.file if subject.file is not None else attached,
                media_root=arguments.media_root,
                declared_md5=arguments.declared_md5,
                note=arguments.note,
                post_id=subject.post_id,
                account_id=subject.account_id,
                live=arguments.live,
                request_budget=arguments.max_requests,
                time_budget_seconds=arguments.max_seconds,
                search_term=arguments.search_term,
                policy=policy,
                dry_run=arguments.dry_run,
            )
            return {"catalog": catalog_label, **result}

        def progress(index: int, total: int, info: dict) -> None:
            print(
                f"[{index}/{total}] {info['subject']}: session {info['session_id']}"
                f" {info['status']} ({info['requests_used']} requests)",
                file=sys.stderr,
            )

        result = DiscoveryRunService(database, progress=progress).run(
            subjects,
            policy=policy,
            live=arguments.live,
            request_budget=arguments.max_requests,
            time_budget_seconds=arguments.max_seconds,
            search_term=arguments.search_term,
            dry_run=arguments.dry_run,
            declared_md5=arguments.declared_md5,
            media_root=arguments.media_root,
            note=arguments.note,
        )
    return {"catalog": catalog_label, **result}
