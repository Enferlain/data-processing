"""Read-only, deterministic target resolution for artist-library expansion."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

from media_catalog.adapters.danbooru.adapter import ADAPTER_VERSION as DANBOORU_ADAPTER_VERSION
from media_catalog.adapters.danbooru.config import AIBOORU, DANBOORU
from media_catalog.adapters.pixiv.transport import PIXIV_ADAPTER_VERSION, PIXIV_SCHEMA_VERSION
from media_catalog.database import CatalogDatabase
from media_catalog.library.contracts import (
    ExpansionAuthority,
    ExpansionAuthorityMode,
    ExpansionCapability,
    ExpansionEstimate,
    ExpansionLimits,
    ExpansionTarget,
    ExpansionTargetChoice,
    ExpansionTargetKind,
    LibraryExpansionPlan,
    stable_digest,
)

DatabaseSource = CatalogDatabase | Path | str
MAX_EXCLUSIONS = 100
CAPABILITY_VERSION = "library-expansion-v1"

_CAPABILITIES = {
    ("pixiv", ExpansionTargetKind.ACCOUNT): ExpansionCapability(
        "pixiv-account-artworks",
        CAPABILITY_VERSION,
        "pixiv",
        ExpansionTargetKind.ACCOUNT,
        "list_account_posts",
        PIXIV_ADAPTER_VERSION,
        PIXIV_SCHEMA_VERSION,
        "pixiv-account-count",
    ),
    ("danbooru", ExpansionTargetKind.ATTRIBUTION): ExpansionCapability(
        "danbooru-attribution-posts",
        CAPABILITY_VERSION,
        "danbooru",
        ExpansionTargetKind.ATTRIBUTION,
        "list_account_posts",
        DANBOORU_ADAPTER_VERSION,
        DANBOORU.schema_version,
    ),
    ("aibooru", ExpansionTargetKind.ATTRIBUTION): ExpansionCapability(
        "aibooru-attribution-posts",
        CAPABILITY_VERSION,
        "aibooru",
        ExpansionTargetKind.ATTRIBUTION,
        "list_account_posts",
        DANBOORU_ADAPTER_VERSION,
        AIBOORU.schema_version,
    ),
}


def expansion_capability(
    provider: str, target_kind: ExpansionTargetKind
) -> ExpansionCapability | None:
    return _CAPABILITIES.get((provider, target_kind))


def _connection(database: DatabaseSource) -> tuple[sqlite3.Connection, bool]:
    if isinstance(database, CatalogDatabase):
        snapshot = sqlite3.connect(":memory:")
        snapshot.row_factory = sqlite3.Row
        try:
            database.connection.backup(snapshot)
            snapshot.execute("PRAGMA query_only = ON")
        except BaseException:
            snapshot.close()
            raise
        return snapshot, True
    opened = CatalogDatabase.open_read_only(Path(database))
    return opened.connection, True


def _parse_reference(value: str, *, label: str) -> tuple[str, int]:
    kind, separator, raw_id = value.strip().partition(":")
    if not separator or kind not in {"account", "post", "attribution"} or not raw_id.isdecimal():
        raise ValueError(f"{label} must use account:ID, post:ID, or attribution:ID")
    database_id = int(raw_id)
    if database_id <= 0:
        raise ValueError(f"{label} ID must be positive")
    return kind, database_id


def _account_target(connection: sqlite3.Connection, account_id: int) -> ExpansionTarget:
    row = connection.execute(
        """SELECT a.account_id, a.native_account_id, a.availability, a.last_seen_at,
                  p.platform_key, s.account_snapshot_id, s.observed_at, s.snapshot_digest,
                  s.raw_observation_id
             FROM accounts a JOIN platforms p USING(platform_id)
             LEFT JOIN account_snapshots s ON s.account_snapshot_id = (
                 SELECT latest.account_snapshot_id FROM account_snapshots latest
                  WHERE latest.account_id = a.account_id
                  ORDER BY latest.observed_at DESC, latest.account_snapshot_id DESC LIMIT 1
             )
            WHERE a.account_id = ?""",
        (account_id,),
    ).fetchone()
    if row is None:
        raise ValueError("expansion target account not found")
    capability = expansion_capability(str(row["platform_key"]), ExpansionTargetKind.ACCOUNT)
    if capability is None:
        raise ValueError("unsupported account expansion target")
    revision = stable_digest(
        row["account_id"],
        row["platform_key"],
        row["native_account_id"],
        row["availability"],
        row["last_seen_at"],
        row["account_snapshot_id"],
        row["observed_at"],
        row["snapshot_digest"],
        row["raw_observation_id"],
    )
    return ExpansionTarget(
        ExpansionTargetKind.ACCOUNT,
        int(row["account_id"]),
        str(row["platform_key"]),
        "",
        str(row["native_account_id"]),
        str(row["availability"]),
        revision,
        capability,
    )


def _attribution_target(connection: sqlite3.Connection, attribution_id: int) -> ExpansionTarget:
    row = connection.execute(
        """SELECT ae.attribution_entity_id, ae.instance_host,
                  ae.provider_attribution_id, ae.adapter_version, ae.availability,
                  ae.last_seen_at, p.platform_key,
                  s.attribution_snapshot_id, s.observed_at, s.snapshot_digest,
                  s.raw_observation_id, name.attribution_name_id,
                  name.name AS primary_name, name.observed_at AS name_observed_at,
                  name.raw_observation_id AS name_raw_observation_id
             FROM attribution_entities ae JOIN platforms p USING(platform_id)
             LEFT JOIN attribution_snapshots s ON s.attribution_snapshot_id = (
                 SELECT latest.attribution_snapshot_id FROM attribution_snapshots latest
                  WHERE latest.attribution_entity_id = ae.attribution_entity_id
                  ORDER BY latest.observed_at DESC, latest.attribution_snapshot_id DESC LIMIT 1
             )
             LEFT JOIN attribution_names name ON name.attribution_name_id = (
                 SELECT latest_name.attribution_name_id FROM attribution_names latest_name
                  WHERE latest_name.attribution_entity_id = ae.attribution_entity_id
                    AND latest_name.name_kind = 'primary'
                  ORDER BY latest_name.observed_at DESC,
                           latest_name.attribution_name_id DESC LIMIT 1
             )
            WHERE ae.attribution_entity_id = ?""",
        (attribution_id,),
    ).fetchone()
    if row is None:
        raise ValueError("expansion target attribution not found")
    capability = expansion_capability(str(row["platform_key"]), ExpansionTargetKind.ATTRIBUTION)
    if capability is None:
        raise ValueError("unsupported attribution expansion target")
    if row["primary_name"] is None:
        raise ValueError("attribution expansion target has no current primary name")
    revision = stable_digest(
        row["attribution_entity_id"],
        row["platform_key"],
        row["instance_host"],
        row["provider_attribution_id"],
        row["adapter_version"],
        row["availability"],
        row["last_seen_at"],
        row["attribution_snapshot_id"],
        row["observed_at"],
        row["snapshot_digest"],
        row["raw_observation_id"],
        row["attribution_name_id"],
        row["primary_name"],
        row["name_observed_at"],
        row["name_raw_observation_id"],
    )
    return ExpansionTarget(
        ExpansionTargetKind.ATTRIBUTION,
        int(row["attribution_entity_id"]),
        str(row["platform_key"]),
        str(row["instance_host"]),
        str(row["provider_attribution_id"]),
        str(row["availability"]),
        revision,
        capability,
    )


def _seed_revision(connection: sqlite3.Connection, kind: str, database_id: int) -> str:
    if kind == "account":
        return _account_seed_revision(connection, database_id)
    row = connection.execute(
        """SELECT post.post_id, platform.platform_key, post.native_post_id,
                  post.canonical_url, post.updated_at, post.last_seen_at,
                  post.raw_observation_id
             FROM posts post JOIN platforms platform USING(platform_id)
            WHERE post.post_id = ?""",
        (database_id,),
    ).fetchone()
    if row is None:
        raise ValueError("expansion seed post not found")
    participant_rows = tuple(
        tuple(item)
        for item in connection.execute(
            """SELECT account_id, role, review_state, raw_observation_id
                 FROM post_participants WHERE post_id = ?
                ORDER BY account_id, role""",
            (database_id,),
        )
    )
    reference_rows = tuple(
        tuple(item)
        for item in connection.execute(
            """SELECT per.post_external_reference_id, per.raw_observation_id,
                      pr.platform_reference_id, pr.instance_host, pr.object_kind,
                      pr.identifier_kind, pr.native_identifier
                 FROM post_external_references per
                 LEFT JOIN platform_references pr USING(platform_reference_id)
                WHERE per.post_id = ?
                ORDER BY per.post_external_reference_id""",
            (database_id,),
        )
    )
    return stable_digest(tuple(row), participant_rows, reference_rows)


def _account_seed_revision(connection: sqlite3.Connection, account_id: int) -> str:
    row = connection.execute(
        """SELECT a.account_id, p.platform_key, a.native_account_id, a.availability,
                  a.last_seen_at, s.account_snapshot_id, s.observed_at,
                  s.snapshot_digest, s.raw_observation_id
             FROM accounts a JOIN platforms p USING(platform_id)
             LEFT JOIN account_snapshots s ON s.account_snapshot_id = (
                 SELECT latest.account_snapshot_id FROM account_snapshots latest
                  WHERE latest.account_id = a.account_id
                  ORDER BY latest.observed_at DESC, latest.account_snapshot_id DESC LIMIT 1
             ) WHERE a.account_id = ?""",
        (account_id,),
    ).fetchone()
    if row is None:
        raise ValueError("expansion seed account not found")
    return stable_digest(tuple(row))


def _choice(
    target: ExpansionTarget,
    authority: ExpansionAuthority,
    source_kind: str,
    source_reference: str,
) -> ExpansionTargetChoice:
    return ExpansionTargetChoice(target, authority, source_kind, source_reference)


def _candidate_choices(
    connection: sqlite3.Connection, seed_kind: str, seed_id: int
) -> tuple[list[ExpansionTargetChoice], list[dict[str, str]]]:
    choices: list[ExpansionTargetChoice] = []
    exclusions: list[dict[str, str]] = []
    if seed_kind == "account":
        try:
            choices.append(
                _choice(
                    _account_target(connection, seed_id),
                    ExpansionAuthority(ExpansionAuthorityMode.EXPLICIT),
                    "seed_account",
                    f"account:{seed_id}",
                )
            )
        except ValueError as error:
            exclusions.append({"source": f"account:{seed_id}", "reason": str(error)})
        for row in connection.execute(
            """SELECT DISTINCT target.account_id, ia.account_candidate_id, ia.decision_id
                 FROM identity_accounts seed_membership
                 JOIN identity_accounts ia USING(identity_id)
                 JOIN accounts target ON target.account_id = ia.account_id
                 JOIN account_match_candidates candidate
                   ON candidate.account_candidate_id = ia.account_candidate_id
                 JOIN account_candidate_decisions decision
                   ON decision.account_decision_id = ia.decision_id
                WHERE seed_membership.account_id = ? AND target.account_id != ?
                  AND candidate.current_state = 'confirmed'
                  AND candidate.relation_kind = 'same_identity'
                  AND decision.decision = 'confirmed'
                ORDER BY target.account_id""",
            (seed_id, seed_id),
        ):
            reference = (
                f"account_candidate:{row['account_candidate_id']}/decision:{row['decision_id']}"
            )
            try:
                target = _account_target(connection, int(row["account_id"]))
            except ValueError as error:
                exclusions.append({"source": f"account:{row['account_id']}", "reason": str(error)})
                continue
            choices.append(
                _choice(
                    target,
                    ExpansionAuthority(ExpansionAuthorityMode.CONFIRMED, reference),
                    "confirmed_identity",
                    reference,
                )
            )
    else:
        for row in connection.execute(
            """SELECT account_id, role, raw_observation_id
                 FROM post_participants
                WHERE post_id = ? ORDER BY account_id, role""",
            (seed_id,),
        ):
            role = str(row["role"])
            source = f"post_participant:{seed_id}:{row['account_id']}:{role}"
            if role not in {"author", "creator"}:
                exclusions.append({"source": source, "reason": "unsupported_participant_role"})
                continue
            try:
                target = _account_target(connection, int(row["account_id"]))
            except ValueError as error:
                exclusions.append({"source": source, "reason": str(error)})
                continue
            choices.append(
                _choice(
                    target,
                    ExpansionAuthority(ExpansionAuthorityMode.EXPLICIT),
                    "observed_authorship",
                    source,
                )
            )
        for row in connection.execute(
            """SELECT DISTINCT ae.attribution_entity_id,
                      per.post_external_reference_id, per.raw_observation_id
                 FROM post_external_references per
                 JOIN platform_references pr USING(platform_reference_id)
                 JOIN attribution_entities ae
                   ON ae.platform_id = pr.platform_id
                  AND ae.instance_host = pr.instance_host
                  AND ae.provider_attribution_id = pr.native_identifier
                WHERE per.post_id = ? AND pr.object_kind = 'artist'
                  AND pr.identifier_kind = 'stable_id'
                ORDER BY ae.attribution_entity_id, per.post_external_reference_id""",
            (seed_id,),
        ):
            source = f"post_external_reference:{row['post_external_reference_id']}"
            try:
                target = _attribution_target(connection, int(row["attribution_entity_id"]))
            except ValueError as error:
                exclusions.append({"source": source, "reason": str(error)})
                continue
            choices.append(
                _choice(
                    target,
                    ExpansionAuthority(ExpansionAuthorityMode.EXPLICIT),
                    "observed_attribution",
                    source,
                )
            )
    return choices, exclusions


def _explicit_choice(
    connection: sqlite3.Connection, target: str, selection_note: str | None
) -> ExpansionTargetChoice:
    kind, database_id = _parse_reference(target, label="expansion target")
    if kind == "post":
        raise ValueError("expansion target must use account:ID or attribution:ID")
    if selection_note is None or not selection_note.strip():
        raise ValueError("explicit expansion target requires a selection note")
    resolved = (
        _account_target(connection, database_id)
        if kind == "account"
        else _attribution_target(connection, database_id)
    )
    return _choice(
        resolved,
        ExpansionAuthority(ExpansionAuthorityMode.EXPLICIT, note=selection_note.strip()),
        "explicit_selection",
        resolved.reference,
    )


def _estimate(connection: sqlite3.Connection, target: ExpansionTarget | None) -> ExpansionEstimate:
    if target is None:
        return ExpansionEstimate("unknown")
    target_column = (
        "plan.target_account_id"
        if target.kind is ExpansionTargetKind.ACCOUNT
        else "plan.target_attribution_id"
    )
    row = connection.execute(
        f"""SELECT probe.count_value, probe.observed_at
               FROM library_expansion_probes probe
               JOIN library_expansion_plans plan USING(library_expansion_plan_id)
              WHERE {target_column} = ? AND probe.outcome = 'success'
              ORDER BY probe.observed_at DESC, probe.library_expansion_probe_id DESC LIMIT 1""",
        (target.catalog_id,),
    ).fetchone()
    if row is None:
        return ExpansionEstimate("unknown")
    return ExpansionEstimate(
        "count", int(row["count_value"]), str(row["observed_at"]), "retained_probe"
    )


def _deduplicate(choices: list[ExpansionTargetChoice]) -> tuple[ExpansionTargetChoice, ...]:
    selected: dict[str, ExpansionTargetChoice] = {}
    for choice in choices:
        current = selected.get(choice.target.reference)
        if current is None or (
            current.authority.mode is ExpansionAuthorityMode.EXPLICIT
            and choice.authority.mode is ExpansionAuthorityMode.CONFIRMED
        ):
            selected[choice.target.reference] = choice
    return tuple(
        sorted(selected.values(), key=lambda item: (item.target.kind.value, item.target.catalog_id))
    )


def plan_library_expansion(
    database: DatabaseSource,
    seed: str,
    *,
    target: str | None = None,
    selection_note: str | None = None,
    limits: ExpansionLimits | None = None,
) -> LibraryExpansionPlan:
    """Resolve a finite expansion plan without writes or provider access."""

    if limits is None:
        limits = ExpansionLimits()
    seed_kind, seed_id = _parse_reference(seed, label="expansion seed")
    if seed_kind == "attribution":
        raise ValueError("expansion seed must use account:ID or post:ID")
    connection, owned = _connection(database)
    try:
        seed_revision = _seed_revision(connection, seed_kind, seed_id)
        choices, exclusions = _candidate_choices(connection, seed_kind, seed_id)
        explicit = _explicit_choice(connection, target, selection_note) if target else None
        if explicit is not None:
            choices.append(explicit)
        normalized = _deduplicate(choices)
        selected = (
            explicit if explicit is not None else normalized[0] if len(normalized) == 1 else None
        )
        bounded_exclusions = tuple(exclusions[:MAX_EXCLUSIONS])
        source_revision = stable_digest(
            seed_revision,
            *(choice.digest for choice in normalized),
            bounded_exclusions,
        )
        return LibraryExpansionPlan(
            seed,
            seed_revision,
            limits,
            normalized,
            selected,
            _estimate(connection, selected.target if selected else None),
            bounded_exclusions,
            source_revision,
        )
    finally:
        if owned:
            connection.close()


def replan_library_execution(
    database: CatalogDatabase,
    execution_id: int,
) -> LibraryExpansionPlan:
    """Reconstruct and stale-check the immutable plan behind an execution."""

    if execution_id <= 0:
        raise ValueError("library expansion execution id must be positive")
    row = database.connection.execute(
        """SELECT plan.seed_account_id, plan.seed_post_id, plan.target_kind,
                  plan.target_account_id, plan.target_attribution_id,
                  plan.selection_note, plan.request_limit, plan.page_limit,
                  plan.record_limit, plan.time_limit_seconds, plan.plan_digest,
                  plan.estimate_state, plan.estimate_count,
                  plan.estimate_observed_at, plan.estimate_source
             FROM library_expansion_executions execution
             JOIN library_expansion_plans plan USING(library_expansion_plan_id)
            WHERE execution.library_expansion_execution_id = ?""",
        (execution_id,),
    ).fetchone()
    if row is None:
        raise ValueError("library expansion execution not found")
    seed = (
        f"account:{row['seed_account_id']}"
        if row["seed_account_id"] is not None
        else f"post:{row['seed_post_id']}"
    )
    target_id = (
        row["target_account_id"]
        if row["target_kind"] == "account"
        else row["target_attribution_id"]
    )
    target = f"{row['target_kind']}:{target_id}"
    limits = ExpansionLimits(
        int(row["request_limit"]),
        int(row["page_limit"]),
        int(row["record_limit"]),
        int(row["time_limit_seconds"]),
    )

    def stored_snapshot(candidate: LibraryExpansionPlan) -> LibraryExpansionPlan:
        estimate = (
            ExpansionEstimate("unknown")
            if row["estimate_state"] == "unknown"
            else ExpansionEstimate(
                "count",
                int(row["estimate_count"]),
                str(row["estimate_observed_at"]),
                str(row["estimate_source"]),
            )
        )
        return replace(candidate, estimate=estimate)

    automatic = stored_snapshot(plan_library_expansion(database, seed, limits=limits))
    if automatic.digest == row["plan_digest"]:
        return automatic
    note = row["selection_note"]
    if note is not None:
        explicit = stored_snapshot(
            plan_library_expansion(
                database,
                seed,
                target=target,
                selection_note=str(note),
                limits=limits,
            )
        )
        if explicit.digest == row["plan_digest"]:
            return explicit
    raise ValueError("stale library expansion plan; create a new offline plan")
