from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from media_catalog.database import CatalogDatabase
from media_catalog.links import (
    CANONICALIZER_VERSION,
    EXTRACTOR_VERSION,
    RECOGNIZER_VERSION,
    SCORING_VERSION,
    account_occurrences,
    post_occurrences,
    recognize_url,
)
from media_catalog.records import LinkOccurrence, validate_relation, validate_review_state
from media_catalog.writer import CatalogWriter

STRENGTH_SCORES = {"weak": 10, "moderate": 35, "strong": 70, "exact": 100}


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    run_id: int
    status: str
    versions: dict[str, str]
    counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class DiscoveryService:
    def __init__(self, database: CatalogDatabase) -> None:
        self.database = database
        self.connection = database.connection
        self.writer = CatalogWriter(database)

    def discover(self) -> DiscoveryResult:
        now = _now()
        counts = {
            key: 0
            for key in ("scanned", "observed", "recognized", "unresolved", "existing", "failed")
        }
        versions = {
            "extractor": EXTRACTOR_VERSION,
            "canonicalizer": CANONICALIZER_VERSION,
            "recognizer": RECOGNIZER_VERSION,
            "scoring": SCORING_VERSION,
        }
        with self.database.transaction():
            run_id = self.writer.begin_discovery(
                extractor_version=EXTRACTOR_VERSION,
                canonicalizer_version=CANONICALIZER_VERSION,
                recognizer_version=RECOGNIZER_VERSION,
                scoring_version=SCORING_VERSION,
                started_at=now,
            )
            for occurrence in self._occurrences(counts):
                counts["scanned"] += 1
                try:
                    result = recognize_url(occurrence.original_url)
                    digest = _digest(
                        occurrence.subject_kind,
                        occurrence.subject_id,
                        occurrence.account_snapshot_id,
                        occurrence.raw_observation_id,
                        occurrence.source_context,
                        occurrence.json_path or "",
                        occurrence.original_url,
                        occurrence.observed_at,
                    )
                    stored, reference_id = self.writer.store_link_observation(
                        run_id,
                        occurrence,
                        canonical_url=result.canonical.canonical_url,
                        canonicalization_version=CANONICALIZER_VERSION,
                        resolution_state=result.canonical.state,
                        resolution_reason=result.canonical.reason,
                        extractor_version=EXTRACTOR_VERSION,
                        occurrence_digest=digest,
                        original_query=result.canonical.original_query,
                        original_fragment=result.canonical.original_fragment,
                        reference=result.reference,
                    )
                    counts["existing" if stored.outcome == "existing" else "observed"] += 1
                    counts["recognized" if reference_id is not None else "unresolved"] += 1
                    if reference_id is not None:
                        self._generate_candidate(occurrence, stored.id, reference_id, now)
                except (TypeError, ValueError, json.JSONDecodeError):
                    counts["failed"] += 1
            self.connection.execute(
                """DELETE FROM external_links
                   WHERE NOT EXISTS (
                       SELECT 1 FROM link_observations lo
                       WHERE lo.external_link_id = external_links.external_link_id
                   ) AND NOT EXISTS (
                       SELECT 1 FROM platform_references pr
                       WHERE pr.external_link_id = external_links.external_link_id
                   )"""
            )
            self.writer.finish_discovery(
                run_id, status="complete", finished_at=_now(), counts=counts
            )
        return DiscoveryResult(run_id, "complete", versions, counts)

    def _occurrences(self, counts: dict[str, int]) -> list[LinkOccurrence]:
        occurrences: list[LinkOccurrence] = []
        snapshots = self.connection.execute(
            """SELECT account_id, account_snapshot_id, observed_at, website_url, profile_url,
                      bio, raw_observation_id FROM account_snapshots"""
        )
        for row in snapshots:
            occurrences.extend(account_occurrences(dict(row)))
        posts = self.connection.execute(
            """SELECT p.post_id, p.canonical_url, p.text_content,
                      COALESCE(ro.observed_at, p.last_seen_at) AS observed_at,
                      p.raw_observation_id, rp.payload
               FROM posts p
               LEFT JOIN raw_observations ro ON ro.raw_observation_id = p.raw_observation_id
               LEFT JOIN raw_payloads rp ON rp.raw_payload_id = ro.raw_payload_id"""
        )
        for row in posts:
            try:
                occurrences.extend(post_occurrences(dict(row), row["payload"]))
            except (TypeError, ValueError):
                counts["failed"] += 1
        return occurrences

    def _generate_candidate(
        self, occurrence: LinkOccurrence, observation_id: int, reference_id: int, now: str
    ) -> None:
        reference = self.connection.execute(
            """SELECT object_kind, resolved_account_id, resolved_post_id
               FROM platform_references WHERE platform_reference_id = ?""",
            (reference_id,),
        ).fetchone()
        if occurrence.subject_kind == "account" and reference["object_kind"] == "account":
            if reference["resolved_account_id"] == occurrence.subject_id:
                return
            self._upsert_candidate(
                "account",
                occurrence.subject_id,
                reference_id,
                reference["resolved_account_id"],
                "same_identity",
                observation_id,
                now,
            )
        elif occurrence.subject_kind == "post" and reference["object_kind"] == "post":
            if reference["resolved_post_id"] == occurrence.subject_id:
                return
            self._upsert_candidate(
                "post",
                occurrence.subject_id,
                reference_id,
                reference["resolved_post_id"],
                "sourced_from",
                observation_id,
                now,
            )

    def _upsert_candidate(
        self,
        kind: str,
        subject_id: int,
        reference_id: int,
        resolved_id: int | None,
        relation: str,
        observation_id: int,
        now: str,
    ) -> None:
        semantic_reference = self.connection.execute(
            """SELECT platform_id, instance_host, object_kind, native_identifier
               FROM platform_references WHERE platform_reference_id = ?""",
            (reference_id,),
        ).fetchone()
        key = _digest(
            kind,
            subject_id,
            relation,
            semantic_reference["platform_id"],
            semantic_reference["instance_host"],
            semantic_reference["object_kind"],
            semantic_reference["native_identifier"],
        )
        table = f"{kind}_match_candidates"
        id_column = f"{kind}_candidate_id"
        subject_column = f"subject_{kind}_id"
        target_column = f"target_{kind}_id"
        self.connection.execute(
            f"""INSERT INTO {table}
                (candidate_key, {subject_column}, {target_column}, target_reference_id,
                 relation_kind, score_version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(candidate_key) DO UPDATE SET
                 {target_column} = COALESCE({table}.{target_column}, excluded.{target_column}),
                 target_reference_id = CASE WHEN excluded.{target_column} IS NOT NULL THEN NULL
                                            ELSE excluded.target_reference_id END,
                 updated_at = excluded.updated_at""",
            (
                key,
                subject_id,
                resolved_id,
                None if resolved_id else reference_id,
                relation,
                SCORING_VERSION,
                now,
                now,
            ),
        )
        candidate_id = int(
            self.connection.execute(
                f"SELECT {id_column} FROM {table} WHERE candidate_key = ?", (key,)
            ).fetchone()[0]
        )
        occurrence_digest = self.connection.execute(
            """SELECT occurrence_digest FROM link_observations
               WHERE link_observation_id = ?""",
            (observation_id,),
        ).fetchone()[0]
        evidence_digest = _digest(kind, key, occurrence_digest, "official_link")
        self.connection.execute(
            """INSERT INTO match_evidence
               (evidence_digest, stance, evidence_kind, direction, strength, detector,
                detector_version, link_observation_id, platform_reference_id, observed_at,
                explanation, components_json)
               VALUES (?, 'supports', 'official_link', 'subject_to_target', 'strong',
                       'link-discovery', ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            (
                evidence_digest,
                EXTRACTOR_VERSION,
                observation_id,
                reference_id,
                now,
                "A catalog field directly links the subject to the target reference.",
                json.dumps({"strength_points": STRENGTH_SCORES["strong"]}, sort_keys=True),
            ),
        )
        evidence_id = int(
            self.connection.execute(
                "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?",
                (evidence_digest,),
            ).fetchone()[0]
        )
        join_table = f"{kind}_candidate_evidence"
        self.connection.execute(
            f"""INSERT INTO {join_table} ({id_column}, evidence_id)
                VALUES (?, ?) ON CONFLICT DO NOTHING""",
            (candidate_id, evidence_id),
        )
        score = self.connection.execute(
            f"""SELECT COALESCE(SUM(CASE e.strength WHEN 'exact' THEN 100 WHEN 'strong' THEN 70
                        WHEN 'moderate' THEN 35 ELSE 10 END), 0), COUNT(*)
                FROM {join_table} ce JOIN match_evidence e ON e.evidence_id = ce.evidence_id
                WHERE ce.{id_column} = ? AND e.stance = 'supports'""",
            (candidate_id,),
        ).fetchone()
        components = json.dumps(
            {"supporting_evidence": score[1], "points": score[0]}, sort_keys=True
        )
        self.connection.execute(
            f"""UPDATE {table} SET score = ?, score_components_json = ?,
                    evidence_generation = ?, updated_at = ? WHERE {id_column} = ?""",
            (score[0], components, score[1], now, candidate_id),
        )

    def links(self, **filters: object) -> dict[str, object]:
        clauses: list[str] = []
        parameters: list[object] = []
        mapping = {
            "subject_kind": "lo.subject_kind",
            "source_context": "lo.source_context",
            "platform": "p.platform_key",
            "instance": "pr.instance_host",
            "object_kind": "pr.object_kind",
            "state": "el.resolution_state",
        }
        for key, column in mapping.items():
            if filters.get(key) is not None:
                clauses.append(f"{column} = ?")
                parameters.append(filters[key])
        if filters.get("subject_id") is not None:
            clauses.append("(lo.subject_account_id = ? OR lo.subject_post_id = ?)")
            parameters.extend((filters["subject_id"], filters["subject_id"]))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.connection.execute(
            f"""SELECT lo.link_observation_id, lo.subject_kind, lo.subject_account_id,
                       lo.subject_post_id, lo.source_context, lo.original_url, lo.json_path,
                       el.canonical_url, el.resolution_state, el.resolution_reason,
                       p.platform_key, pr.instance_host, pr.object_kind, pr.native_identifier,
                       pr.canonical_target_url
                FROM link_observations lo JOIN external_links el USING (external_link_id)
                LEFT JOIN platform_references pr USING (external_link_id)
                LEFT JOIN platforms p ON p.platform_id = pr.platform_id
                {where} ORDER BY lo.link_observation_id""",
            parameters,
        )
        results = [dict(row) for row in rows]
        for item in results:
            for field in ("original_url", "canonical_url", "canonical_target_url"):
                if item[field] is not None:
                    item[field] = _public_url(str(item[field]))
        return {
            "filters": {key: value for key, value in filters.items() if value is not None},
            "results": results,
        }

    def candidates(self, *, kind: str | None = None, state: str | None = None) -> dict[str, object]:
        if state is not None:
            validate_review_state(state)
        kinds = (kind,) if kind else ("account", "post")
        results: list[dict[str, Any]] = []
        for selected in kinds:
            if selected not in {"account", "post"}:
                raise ValueError(f"unsupported candidate kind: {selected}")
            table = f"{selected}_match_candidates"
            id_column = f"{selected}_candidate_id"
            sql = f"SELECT * FROM {table}"
            parameters: tuple[object, ...] = ()
            if state:
                sql += " WHERE current_state = ?"
                parameters = (state,)
            sql += f" ORDER BY score DESC, {id_column}"
            for row in self.connection.execute(sql, parameters):
                item = dict(row)
                item["kind"] = selected
                item["match_ref"] = f"{selected}:{item[id_column]}"
                results.append(item)
        return {"filters": {"kind": kind, "state": state}, "results": results}

    def candidate(self, match_ref: str) -> dict[str, object]:
        kind, candidate_id = _parse_match_ref(match_ref)
        table = f"{kind}_match_candidates"
        id_column = f"{kind}_candidate_id"
        row = self.connection.execute(
            f"SELECT * FROM {table} WHERE {id_column} = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"candidate not found: {match_ref}")
        join_table = f"{kind}_candidate_evidence"
        evidence = [
            dict(item)
            for item in self.connection.execute(
                f"""SELECT e.* FROM {join_table} ce
                    JOIN match_evidence e USING (evidence_id)
                    WHERE ce.{id_column} = ? ORDER BY e.evidence_id""",
                (candidate_id,),
            )
        ]
        decision_table = f"{kind}_candidate_decisions"
        history = [
            dict(item)
            for item in self.connection.execute(
                f"SELECT * FROM {decision_table} WHERE {id_column} = ? ORDER BY rowid",
                (candidate_id,),
            )
        ]
        return {
            "match_ref": match_ref,
            "kind": kind,
            "candidate": dict(row),
            "evidence": evidence,
            "history": history,
        }

    def review(
        self,
        match_ref: str,
        decision: str,
        *,
        note: str | None = None,
        expected_generation: int | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        state = validate_review_state(decision)
        kind, candidate_id = _parse_match_ref(match_ref)
        table = f"{kind}_match_candidates"
        id_column = f"{kind}_candidate_id"
        decision_table = f"{kind}_candidate_decisions"
        with self.database.transaction():
            row = self.connection.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"candidate not found: {match_ref}")
            generation = int(row["evidence_generation"])
            revision = int(row["review_revision"])
            if expected_generation is not None and generation != expected_generation:
                raise ValueError(
                    f"stale review: expected evidence generation {expected_generation}, "
                    f"found {generation}"
                )
            if expected_revision is not None and revision != expected_revision:
                raise ValueError(
                    f"stale review: expected review revision {expected_revision}, found {revision}"
                )
            updated = self.connection.execute(
                f"""UPDATE {table} SET current_state = ?, review_revision = review_revision + 1,
                         updated_at = ? WHERE {id_column} = ? AND review_revision = ?""",
                (state, _now(), candidate_id, revision),
            )
            if updated.rowcount != 1:
                raise ValueError("stale review: candidate changed concurrently")
            cursor = self.connection.execute(
                f"""INSERT INTO {decision_table}
                    ({id_column}, prior_state, decision, evidence_generation, note, decided_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (candidate_id, row["current_state"], state, generation, note, _now()),
            )
            decision_id = int(cursor.lastrowid)
            identity_id = None
            if (
                kind == "account"
                and state == "confirmed"
                and row["relation_kind"] == "same_identity"
            ):
                identity_id = self._confirm_identity(row, candidate_id, decision_id)
            elif (
                kind == "account"
                and row["relation_kind"] == "same_identity"
                and row["current_state"] == "confirmed"
            ):
                self._rebuild_identity_component(
                    int(row["subject_account_id"]), row["target_account_id"]
                )
        return {
            "match_ref": match_ref,
            "decision_id": decision_id,
            "decision": state,
            "evidence_generation": generation,
            "review_revision": revision + 1,
            "identity_id": identity_id,
        }

    def _confirm_identity(self, candidate: Any, candidate_id: int, decision_id: int) -> int:
        subject_id = int(candidate["subject_account_id"])
        target_id = candidate["target_account_id"]
        reference_id = candidate["target_reference_id"]
        if target_id is None:
            reference = self.connection.execute(
                """SELECT pr.*, p.platform_key FROM platform_references pr
                   JOIN platforms p USING (platform_id) WHERE platform_reference_id = ?""",
                (reference_id,),
            ).fetchone()
            if reference is None or reference["object_kind"] != "account":
                raise ValueError("account candidate has no compatible target")
            stable = (
                reference["platform_key"] == "pixiv"
                and str(reference["native_identifier"]).isdigit()
            )
            if not stable:
                raise ValueError("target account reference does not expose a stable native ID")
            now = _now()
            self.connection.execute(
                """INSERT INTO accounts
                   (platform_id, native_account_id, canonical_url, availability,
                    first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, 'unknown', ?, ?) ON CONFLICT DO NOTHING""",
                (
                    reference["platform_id"],
                    reference["native_identifier"],
                    reference["canonical_target_url"],
                    now,
                    now,
                ),
            )
            target_id = int(
                self.connection.execute(
                    """SELECT account_id FROM accounts
                       WHERE platform_id = ? AND native_account_id = ?""",
                    (reference["platform_id"], reference["native_identifier"]),
                ).fetchone()[0]
            )
            self.connection.execute(
                """UPDATE platform_references SET resolved_account_id = ?
                   WHERE platform_reference_id = ?""",
                (target_id, reference_id),
            )
            self.connection.execute(
                """UPDATE account_match_candidates
                   SET target_account_id = ?, target_reference_id = NULL
                   WHERE account_candidate_id = ?""",
                (target_id, candidate_id),
            )
        target_id = int(target_id)
        groups = {
            int(item["account_id"]): int(item["identity_id"])
            for item in self.connection.execute(
                """SELECT account_id, identity_id FROM identity_accounts
                   WHERE account_id IN (?, ?)""",
                (subject_id, target_id),
            )
        }
        if subject_id in groups and target_id in groups and groups[subject_id] != groups[target_id]:
            raise ValueError("identity conflict: accounts already belong to different identities")
        identity_id = groups.get(subject_id) or groups.get(target_id)
        if identity_id is None:
            identity_id = int(
                self.connection.execute(
                    "INSERT INTO identities (created_at) VALUES (?)", (_now(),)
                ).lastrowid
            )
        for account_id in (subject_id, target_id):
            self.connection.execute(
                """INSERT INTO identity_accounts
                   (identity_id, account_id, account_candidate_id, decision_id, added_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_id) DO NOTHING""",
                (identity_id, account_id, candidate_id, decision_id, _now()),
            )
        return identity_id

    def _rebuild_identity_component(
        self, subject_account_id: int, target_account_id: int | None
    ) -> None:
        involved = {subject_account_id}
        if target_account_id is not None:
            involved.add(int(target_account_id))
        old_groups: dict[int, int] = {}
        for item in self.connection.execute(
            """SELECT identity_id, account_id FROM identity_accounts
               WHERE identity_id IN (
                   SELECT identity_id FROM identity_accounts WHERE account_id IN (?, ?)
               )""",
            (subject_account_id, target_account_id or -1),
        ):
            involved.add(int(item["account_id"]))
            old_groups[int(item["account_id"])] = int(item["identity_id"])
        edges = [
            dict(row)
            for row in self.connection.execute(
                """SELECT c.account_candidate_id, c.subject_account_id, c.target_account_id,
                          (SELECT d.account_decision_id FROM account_candidate_decisions d
                           WHERE d.account_candidate_id = c.account_candidate_id
                             AND d.decision = 'confirmed'
                           ORDER BY d.account_decision_id DESC LIMIT 1) AS decision_id
                   FROM account_match_candidates c
                   WHERE c.current_state = 'confirmed' AND c.relation_kind = 'same_identity'
                     AND c.target_account_id IS NOT NULL"""
            )
        ]
        changed = True
        while changed:
            changed = False
            for edge in edges:
                endpoints = {
                    int(edge["subject_account_id"]),
                    int(edge["target_account_id"]),
                }
                if endpoints & involved and not endpoints <= involved:
                    involved.update(endpoints)
                    changed = True
        if not involved:
            return
        placeholders = ",".join("?" for _ in involved)
        self.connection.execute(
            f"DELETE FROM identity_accounts WHERE account_id IN ({placeholders})",
            tuple(involved),
        )
        edges = [
            edge
            for edge in edges
            if int(edge["subject_account_id"]) in involved
            or int(edge["target_account_id"]) in involved
        ]
        parent: dict[int, int] = {}

        def find(account_id: int) -> int:
            parent.setdefault(account_id, account_id)
            while parent[account_id] != account_id:
                parent[account_id] = parent[parent[account_id]]
                account_id = parent[account_id]
            return account_id

        for edge in edges:
            first = int(edge["subject_account_id"])
            second = int(edge["target_account_id"])
            first_root, second_root = find(first), find(second)
            if first_root != second_root:
                parent[second_root] = first_root
        components: dict[int, list[int]] = {}
        for account_id in parent:
            components.setdefault(find(account_id), []).append(account_id)
        used_identities: set[int] = set()
        for accounts in components.values():
            identity_id = next(
                (
                    old_groups[account_id]
                    for account_id in accounts
                    if account_id in old_groups and old_groups[account_id] not in used_identities
                ),
                None,
            )
            if identity_id is None:
                identity_id = int(
                    self.connection.execute(
                        "INSERT INTO identities (created_at) VALUES (?)", (_now(),)
                    ).lastrowid
                )
            used_identities.add(identity_id)
            for account_id in accounts:
                evidence = next(
                    edge
                    for edge in edges
                    if account_id
                    in {int(edge["subject_account_id"]), int(edge["target_account_id"])}
                )
                self.connection.execute(
                    """INSERT INTO identity_accounts
                       (identity_id, account_id, account_candidate_id, decision_id, added_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        identity_id,
                        account_id,
                        evidence["account_candidate_id"],
                        evidence["decision_id"],
                        _now(),
                    ),
                )
        self.connection.execute(
            """DELETE FROM identities WHERE NOT EXISTS (
                   SELECT 1 FROM identity_accounts ia
                   WHERE ia.identity_id = identities.identity_id
               )"""
        )

    def add_characteristic(
        self,
        match_ref: str,
        characteristic: str,
        *,
        direction: str = "none",
        source_label: str = "manual",
    ) -> None:
        kind, candidate_id = _parse_match_ref(match_ref)
        if kind != "post":
            raise ValueError("image characteristics apply only to post candidates")
        with self.database.transaction():
            self.connection.execute(
                """INSERT INTO post_candidate_characteristics
                   (post_candidate_id, characteristic, direction, source_label, added_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (candidate_id, characteristic, direction, source_label, _now()),
            )

    def create_post_candidate(
        self,
        subject_post_id: int,
        target_post_id: int,
        relation: str,
        *,
        explanation: str,
        strength: str = "moderate",
    ) -> str:
        validate_relation(relation, candidate_kind="post")
        if subject_post_id == target_post_id:
            raise ValueError("post candidate endpoints must be different")
        if strength not in STRENGTH_SCORES:
            raise ValueError(f"unsupported evidence strength: {strength}")
        if relation == "same_work":
            subject_post_id, target_post_id = sorted((subject_post_id, target_post_id))
        key = _digest("post", subject_post_id, relation, "local", target_post_id)
        now = _now()
        with self.database.transaction():
            self.connection.execute(
                """INSERT INTO post_match_candidates
                   (candidate_key, subject_post_id, target_post_id, relation_kind,
                    score_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(candidate_key) DO NOTHING""",
                (
                    key,
                    subject_post_id,
                    target_post_id,
                    relation,
                    SCORING_VERSION,
                    now,
                    now,
                ),
            )
            candidate_id = int(
                self.connection.execute(
                    """SELECT post_candidate_id FROM post_match_candidates
                       WHERE candidate_key = ?""",
                    (key,),
                ).fetchone()[0]
            )
            evidence_digest = _digest("manual", key, explanation, strength)
            self.connection.execute(
                """INSERT INTO match_evidence
                   (evidence_digest, stance, evidence_kind, direction, strength, detector,
                    detector_version, observed_at, explanation, components_json)
                   VALUES (?, 'supports', 'manual_assessment', ?, ?, 'manual', 'manual-v1',
                           ?, ?, ?) ON CONFLICT DO NOTHING""",
                (
                    evidence_digest,
                    "symmetric" if relation == "same_work" else "subject_to_target",
                    strength,
                    now,
                    explanation,
                    json.dumps({"strength_points": STRENGTH_SCORES[strength]}, sort_keys=True),
                ),
            )
            evidence_id = int(
                self.connection.execute(
                    "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?",
                    (evidence_digest,),
                ).fetchone()[0]
            )
            self.connection.execute(
                """INSERT INTO post_candidate_evidence (post_candidate_id, evidence_id)
                   VALUES (?, ?) ON CONFLICT DO NOTHING""",
                (candidate_id, evidence_id),
            )
            score = int(
                self.connection.execute(
                    """SELECT COALESCE(SUM(CASE e.strength WHEN 'exact' THEN 100
                               WHEN 'strong' THEN 70 WHEN 'moderate' THEN 35 ELSE 10 END), 0)
                       FROM post_candidate_evidence ce JOIN match_evidence e USING (evidence_id)
                       WHERE ce.post_candidate_id = ? AND e.stance = 'supports'""",
                    (candidate_id,),
                ).fetchone()[0]
            )
            generation = int(
                self.connection.execute(
                    """SELECT COUNT(*) FROM post_candidate_evidence
                       WHERE post_candidate_id = ?""",
                    (candidate_id,),
                ).fetchone()[0]
            )
            self.connection.execute(
                """UPDATE post_match_candidates SET score = ?, score_components_json = ?,
                          evidence_generation = ?, updated_at = ? WHERE post_candidate_id = ?""",
                (
                    score,
                    json.dumps(
                        {"supporting_evidence": generation, "points": score}, sort_keys=True
                    ),
                    generation,
                    now,
                    candidate_id,
                ),
            )
        return f"post:{candidate_id}"


def _digest(*values: object) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parse_match_ref(value: str) -> tuple[str, int]:
    kind, separator, raw_id = value.partition(":")
    if not separator or kind not in {"account", "post"} or not raw_id.isdigit():
        raise ValueError(f"invalid candidate reference: {value}")
    return kind, int(raw_id)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
    except ValueError:
        return "<invalid-url>"
    safe_keys = {"page", "s", "id"}
    query = urlencode(
        [
            (key, item if key.lower() in safe_keys else "<redacted>")
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme, host, parsed.path, query, ""))
