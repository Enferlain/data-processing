"""Conservative, idempotent interpretation of normalized lookup results."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from media_catalog.adapters import LookupStrategy, NormalizedLookupResult
from media_catalog.links import RECOGNIZER_VERSION, recognize_url

INTERPRETER_VERSION = "candidate-lookup-interpreter-v1"
SCORING_VERSION = "candidate-lookup-score-v1"


def _digest(*parts: object) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class InterpretedResult:
    result_kind: str
    result_digest: str
    normalized_post_id: int | None = None
    attribution_entity_id: int | None = None
    platform_reference_id: int | None = None
    post_candidate_id: int | None = None
    account_candidate_id: int | None = None
    match_evidence_id: int | None = None
    normalized_name: str | None = None
    match_mode: str | None = None
    explanation: str | None = None


class LookupInterpreter:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def interpret(
        self,
        result: NormalizedLookupResult,
        *,
        seed_post_id: int | None,
        seed_account_id: int | None,
        strategy: LookupStrategy,
        raw_observation_id: int,
        observed_at: str,
        seed_material_digest: str,
        query_values: tuple[str, ...],
    ) -> InterpretedResult:
        stable_digest = _digest(
            INTERPRETER_VERSION,
            strategy.value,
            seed_post_id,
            result.result_kind,
            result.native_id,
            result.rank,
            raw_observation_id,
        )
        if result.result_kind == "attribution":
            entity_id = self._attribution_id(result)
            account_match = self._artist_account_candidate(
                result,
                seed_account_id=seed_account_id,
                raw_observation_id=raw_observation_id,
                observed_at=observed_at,
                material_digest=seed_material_digest,
            )
            if account_match is not None:
                reference_id, candidate_id, evidence_id = account_match
                return InterpretedResult(
                    "account_match",
                    stable_digest,
                    platform_reference_id=reference_id,
                    account_candidate_id=candidate_id,
                    match_evidence_id=evidence_id,
                    explanation=(
                        "A stable account URL on the provider attribution record produced "
                        "a review candidate."
                    ),
                )
            name = result.data.get("name")
            mode = {
                LookupStrategy.ARTIST_EXACT_NAME: "exact",
                LookupStrategy.ARTIST_ALIAS: "alias",
                LookupStrategy.ARTIST_TEXT: "text",
            }.get(strategy)
            if isinstance(name, str) and name and mode is not None:
                return InterpretedResult(
                    "weak_lead",
                    stable_digest,
                    attribution_entity_id=entity_id,
                    normalized_name=name.casefold(),
                    match_mode=mode,
                    explanation=(
                        "Provider artist search returned a non-authoritative attribution lead."
                    ),
                )
            return InterpretedResult(
                "attribution", stable_digest, attribution_entity_id=entity_id
            )
        if result.result_kind != "post" or result.native_id is None:
            return InterpretedResult(
                "inconclusive", stable_digest, explanation="Lookup returned no typed match target."
            )
        normalized_post_id = self._post_id(result)
        if seed_post_id is None or normalized_post_id == seed_post_id:
            return InterpretedResult(
                "post_match", stable_digest, normalized_post_id=normalized_post_id
            )
        relation: str | None = None
        strength = "moderate"
        direction = "symmetric"
        evidence_kind = "declared_hash"
        characteristic: str | None = None
        subject_id, target_id = sorted((seed_post_id, normalized_post_id))
        if strategy is LookupStrategy.SOURCE_POST_URL:
            source = result.data.get("source")
            seed_row = self.connection.execute(
                "SELECT canonical_url FROM posts WHERE post_id = ?", (seed_post_id,)
            ).fetchone()
            seed_url = seed_row[0] if seed_row is not None else None
            if isinstance(source, str) and _same_x_post(source, seed_url):
                relation = "sourced_from"
                subject_id, target_id = normalized_post_id, seed_post_id
                strength = "strong"
                direction = "subject_to_target"
                evidence_kind = "provider_source_reference"
        elif strategy is LookupStrategy.VERIFIED_MD5:
            returned_md5 = result.data.get("declared_md5")
            if (
                isinstance(returned_md5, str)
                and len(query_values) == 1
                and returned_md5.casefold() == query_values[0].casefold()
            ):
                relation = "same_work"
                strength = "exact"
                evidence_kind = "verified_exact_hash"
                characteristic = "exact_bytes"
        elif strategy is LookupStrategy.DECLARED_MD5:
            returned_md5 = result.data.get("declared_md5")
            if (
                isinstance(returned_md5, str)
                and len(query_values) == 1
                and returned_md5.casefold() == query_values[0].casefold()
            ):
                relation = "same_work"
                evidence_kind = "declared_hash"
        elif strategy is LookupStrategy.EXTERNAL_POST_ID:
            external_ids = result.data.get("external_ids")
            if (
                isinstance(external_ids, dict)
                and len(query_values) == 1
                and str(external_ids.get("pixiv_id")) == query_values[0]
            ):
                relation = "same_work"
                strength = "strong"
                evidence_kind = "shared_stable_external_id"
        if relation is None:
            return InterpretedResult(
                "post_match",
                stable_digest,
                normalized_post_id=normalized_post_id,
                explanation="Provider result did not independently establish a relationship.",
            )
        candidate_id, evidence_id = self._post_candidate(
            subject_id,
            target_id,
            relation,
            strength,
            direction,
            evidence_kind,
            raw_observation_id,
            observed_at,
            seed_material_digest,
        )
        if characteristic is not None:
            self.connection.execute(
                """INSERT INTO post_candidate_characteristics
                   (post_candidate_id, characteristic, direction, source_label, added_at)
                   VALUES (?, ?, 'symmetric', ?, ?) ON CONFLICT DO NOTHING""",
                (candidate_id, characteristic, INTERPRETER_VERSION, observed_at),
            )
        return InterpretedResult(
            "post_match",
            stable_digest,
            normalized_post_id=normalized_post_id,
            post_candidate_id=candidate_id,
            match_evidence_id=evidence_id,
        )

    def _post_id(self, result: NormalizedLookupResult) -> int:
        row = self.connection.execute(
            """SELECT p.post_id FROM posts p JOIN platforms platform USING(platform_id)
               WHERE platform.platform_key = ? AND p.native_post_id = ?""",
            (result.data.get("platform"), result.native_id),
        ).fetchone()
        if row is None:
            raise ValueError("normalized lookup post was not persisted")
        return int(row[0])

    def _attribution_id(self, result: NormalizedLookupResult) -> int:
        row = self.connection.execute(
            """SELECT ae.attribution_entity_id FROM attribution_entities ae
               JOIN platforms platform USING(platform_id)
               WHERE platform.platform_key = ? AND ae.provider_attribution_id = ?""",
            (result.data.get("platform"), result.native_id),
        ).fetchone()
        if row is None:
            raise ValueError("normalized lookup attribution was not persisted")
        return int(row[0])

    def _post_candidate(
        self,
        subject_id: int,
        target_id: int,
        relation: str,
        strength: str,
        direction: str,
        evidence_kind: str,
        raw_observation_id: int,
        observed_at: str,
        material_digest: str,
    ) -> tuple[int, int]:
        key = _digest("post", subject_id, relation, "local", target_id)
        endpoints = tuple(sorted((subject_id, target_id)))
        existing = self.connection.execute(
            """SELECT post_candidate_id, candidate_key, relation_kind
               FROM post_match_candidates
               WHERE relation_kind IN ('sourced_from', 'same_work')
                 AND MIN(subject_post_id, target_post_id) = ?
                 AND MAX(subject_post_id, target_post_id) = ?
               ORDER BY CASE relation_kind WHEN 'sourced_from' THEN 0 ELSE 1 END,
                        post_candidate_id LIMIT 1""",
            endpoints,
        ).fetchone()
        if existing is None:
            self.connection.execute(
                """INSERT INTO post_match_candidates
                   (candidate_key, subject_post_id, target_post_id, relation_kind,
                    score_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (key, subject_id, target_id, relation, SCORING_VERSION, observed_at, observed_at),
            )
            candidate_id = int(self.connection.execute(
                "SELECT post_candidate_id FROM post_match_candidates WHERE candidate_key = ?",
                (key,),
            ).fetchone()[0])
        else:
            candidate_id = int(existing["post_candidate_id"])
            if relation == "sourced_from" and existing["relation_kind"] == "same_work":
                self.connection.execute(
                    """UPDATE post_match_candidates SET candidate_key = ?, subject_post_id = ?,
                              target_post_id = ?, relation_kind = 'sourced_from', updated_at = ?
                       WHERE post_candidate_id = ?""",
                    (key, subject_id, target_id, observed_at, candidate_id),
                )
            else:
                key = str(existing["candidate_key"])
                self.connection.execute(
                    "UPDATE post_match_candidates SET updated_at = ? WHERE post_candidate_id = ?",
                    (observed_at, candidate_id),
                )
        evidence_digest = _digest(
            INTERPRETER_VERSION,
            key,
            evidence_kind,
            direction,
            material_digest,
            raw_observation_id,
        )
        points = {"weak": 10, "moderate": 35, "strong": 70, "exact": 100}[strength]
        self.connection.execute(
            """INSERT INTO match_evidence
               (evidence_digest, stance, evidence_kind, direction, strength, detector,
                detector_version, observed_at, explanation, components_json)
               VALUES (?, 'supports', ?, ?, ?, 'candidate-lookup', ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (
                evidence_digest,
                evidence_kind,
                direction,
                strength,
                INTERPRETER_VERSION,
                observed_at,
                "A bounded provider lookup connected these post records.",
                json.dumps(
                    {"raw_observation_id": raw_observation_id, "strength_points": points},
                    sort_keys=True,
                ),
            ),
        )
        evidence_id = int(self.connection.execute(
            "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?", (evidence_digest,)
        ).fetchone()[0])
        self.connection.execute(
            """INSERT INTO post_candidate_evidence (post_candidate_id, evidence_id)
               VALUES (?, ?) ON CONFLICT DO NOTHING""",
            (candidate_id, evidence_id),
        )
        score, generation = self.connection.execute(
            """SELECT COALESCE(SUM(CASE e.strength WHEN 'exact' THEN 100
                       WHEN 'strong' THEN 70 WHEN 'moderate' THEN 35 ELSE 10 END), 0), COUNT(*)
               FROM post_candidate_evidence ce JOIN match_evidence e USING(evidence_id)
               WHERE ce.post_candidate_id = ? AND e.stance = 'supports'""",
            (candidate_id,),
        ).fetchone()
        self.connection.execute(
            """UPDATE post_match_candidates SET score = ?, score_components_json = ?,
                      evidence_generation = ?, updated_at = ? WHERE post_candidate_id = ?""",
            (
                score,
                json.dumps({"points": score, "supporting_evidence": generation}, sort_keys=True),
                generation,
                observed_at,
                candidate_id,
            ),
        )
        return candidate_id, evidence_id

    def _artist_account_candidate(
        self,
        result: NormalizedLookupResult,
        *,
        seed_account_id: int | None,
        raw_observation_id: int,
        observed_at: str,
        material_digest: str,
    ) -> tuple[int, int, int] | None:
        if seed_account_id is None:
            return None
        urls = result.data.get("urls")
        if not isinstance(urls, (list, tuple)):
            return None
        for url in urls:
            if not isinstance(url, str):
                continue
            recognized = recognize_url(url)
            reference = recognized.reference
            if (
                reference is None
                or reference.object_kind != "account"
                or reference.identifier_kind != "stable_id"
            ):
                continue
            platform_row = self.connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = ?", (reference.platform,)
            ).fetchone()
            if platform_row is None:
                continue
            platform_id = int(platform_row[0])
            resolved = self.connection.execute(
                """SELECT account_id FROM accounts
                   WHERE platform_id = ? AND native_account_id = ?""",
                (platform_id, reference.native_id),
            ).fetchone()
            resolved_id = int(resolved[0]) if resolved is not None else None
            self.connection.execute(
                """INSERT INTO platform_references (
                       platform_id, instance_host, object_kind, identifier_kind,
                       native_identifier, canonical_target_url, recognizer_name,
                       recognizer_version, resolved_account_id
                   ) VALUES (?, ?, 'account', 'stable_id', ?, ?, ?, ?, ?)
                   ON CONFLICT(platform_id, instance_host, object_kind, native_identifier,
                               identifier_kind, recognizer_version) DO UPDATE SET
                   canonical_target_url = excluded.canonical_target_url,
                   resolved_account_id = COALESCE(
                       platform_references.resolved_account_id, excluded.resolved_account_id
                   )""",
                (
                    platform_id,
                    reference.instance_host,
                    reference.native_id,
                    reference.canonical_url,
                    reference.recognizer,
                    RECOGNIZER_VERSION,
                    resolved_id,
                ),
            )
            reference_id = int(self.connection.execute(
                """SELECT platform_reference_id FROM platform_references
                   WHERE platform_id = ? AND instance_host = ? AND object_kind = 'account'
                     AND identifier_kind = 'stable_id' AND native_identifier = ?
                     AND recognizer_version = ?""",
                (platform_id, reference.instance_host, reference.native_id, RECOGNIZER_VERSION),
            ).fetchone()[0])
            key = _digest(
                "account", seed_account_id, "same_identity", platform_id,
                reference.instance_host, "account", "stable_id", reference.native_id,
            )
            self.connection.execute(
                """INSERT INTO account_match_candidates (
                       candidate_key, subject_account_id, target_account_id, target_reference_id,
                       relation_kind, score_version, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, 'same_identity', ?, ?, ?)
                   ON CONFLICT(candidate_key) DO UPDATE SET updated_at = excluded.updated_at""",
                (
                    key,
                    seed_account_id,
                    resolved_id,
                    None if resolved_id else reference_id,
                    SCORING_VERSION,
                    observed_at,
                    observed_at,
                ),
            )
            candidate_id = int(self.connection.execute(
                "SELECT account_candidate_id FROM account_match_candidates WHERE candidate_key = ?",
                (key,),
            ).fetchone()[0])
            evidence_digest = _digest(
                INTERPRETER_VERSION,
                key,
                "provider_attribution_url",
                material_digest,
                raw_observation_id,
            )
            self.connection.execute(
                """INSERT INTO match_evidence (
                       evidence_digest, stance, evidence_kind, direction, strength, detector,
                       detector_version, platform_reference_id, observed_at, explanation,
                       components_json
                   ) VALUES (?, 'supports', 'provider_attribution_url', 'subject_to_target',
                             'strong', 'candidate-lookup', ?, ?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                (
                    evidence_digest,
                    INTERPRETER_VERSION,
                    reference_id,
                    observed_at,
                    "A provider attribution record exposes a recognized stable account URL.",
                    json.dumps(
                        {"raw_observation_id": raw_observation_id, "strength_points": 70},
                        sort_keys=True,
                    ),
                ),
            )
            evidence_id = int(self.connection.execute(
                "SELECT evidence_id FROM match_evidence WHERE evidence_digest = ?",
                (evidence_digest,),
            ).fetchone()[0])
            self.connection.execute(
                """INSERT INTO account_candidate_evidence (account_candidate_id, evidence_id)
                   VALUES (?, ?) ON CONFLICT DO NOTHING""",
                (candidate_id, evidence_id),
            )
            score, generation = self.connection.execute(
                """SELECT COALESCE(SUM(CASE e.strength WHEN 'exact' THEN 100
                           WHEN 'strong' THEN 70 WHEN 'moderate' THEN 35 ELSE 10 END), 0), COUNT(*)
                   FROM account_candidate_evidence ce JOIN match_evidence e USING(evidence_id)
                   WHERE ce.account_candidate_id = ? AND e.stance = 'supports'""",
                (candidate_id,),
            ).fetchone()
            self.connection.execute(
                """UPDATE account_match_candidates SET score = ?, score_components_json = ?,
                          evidence_generation = ?, updated_at = ?
                   WHERE account_candidate_id = ?""",
                (
                    score,
                    json.dumps(
                        {"points": score, "supporting_evidence": generation}, sort_keys=True
                    ),
                    generation,
                    observed_at,
                    candidate_id,
                ),
            )
            return reference_id, candidate_id, evidence_id
        return None


def _same_x_post(left: str, right: object) -> bool:
    if not isinstance(right, str):
        return False
    left_ref = recognize_url(left).reference
    right_ref = recognize_url(right).reference
    return bool(
        left_ref
        and right_ref
        and left_ref.platform == right_ref.platform == "x"
        and left_ref.object_kind == right_ref.object_kind == "post"
        and left_ref.native_id == right_ref.native_id
    )
