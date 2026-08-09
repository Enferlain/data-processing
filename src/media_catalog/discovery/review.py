from __future__ import annotations

from typing import Any

from media_catalog.discovery.support import now, parse_match_ref
from media_catalog.records import validate_review_state


class MatchReviewService:
    """Apply candidate review decisions and maintain account identities."""

    def __init__(self, database: Any) -> None:
        self.database = database
        self.connection = database.connection

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
        kind, candidate_id = parse_match_ref(match_ref)
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
                (state, now(), candidate_id, revision),
            )
            if updated.rowcount != 1:
                raise ValueError("stale review: candidate changed concurrently")
            cursor = self.connection.execute(
                f"""INSERT INTO {decision_table}
                    ({id_column}, prior_state, decision, evidence_generation, note, decided_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (candidate_id, row["current_state"], state, generation, note, now()),
            )
            decision_id = int(cursor.lastrowid)
            identity_id = None
            if (
                kind == "account"
                and state == "confirmed"
                and row["relation_kind"] == "same_identity"
            ):
                identity_id = self.confirm_identity(row, candidate_id, decision_id)
            elif (
                kind == "account"
                and row["relation_kind"] == "same_identity"
                and row["current_state"] == "confirmed"
            ):
                self.rebuild_identity_component(
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

    def confirm_identity(self, candidate: Any, candidate_id: int, decision_id: int) -> int:
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
            stable = reference["identifier_kind"] == "stable_id"
            if not stable:
                raise ValueError("target account reference does not expose a stable native ID")
            timestamp = now()
            self.connection.execute(
                """INSERT INTO accounts
                   (platform_id, native_account_id, canonical_url, availability,
                    first_seen_at, last_seen_at)
                   VALUES (?, ?, ?, 'unknown', ?, ?) ON CONFLICT DO NOTHING""",
                (
                    reference["platform_id"],
                    reference["native_identifier"],
                    reference["canonical_target_url"],
                    timestamp,
                    timestamp,
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
                    "INSERT INTO identities (created_at) VALUES (?)", (now(),)
                ).lastrowid
            )
        for account_id in (subject_id, target_id):
            self.connection.execute(
                """INSERT INTO identity_accounts
                   (identity_id, account_id, account_candidate_id, decision_id, added_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_id) DO NOTHING""",
                (identity_id, account_id, candidate_id, decision_id, now()),
            )
        return identity_id

    def rebuild_identity_component(
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
                        "INSERT INTO identities (created_at) VALUES (?)", (now(),)
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
                        now(),
                    ),
                )
        self.connection.execute(
            """DELETE FROM identities WHERE NOT EXISTS (
                   SELECT 1 FROM identity_accounts ia
                   WHERE ia.identity_id = identities.identity_id
               )"""
        )
