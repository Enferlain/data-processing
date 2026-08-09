from __future__ import annotations

from typing import Any

from media_catalog.discovery.support import parse_match_ref, public_url
from media_catalog.records import validate_review_state


class DiscoveryQueries:
    """Read-only link and match queries used by the catalog CLI."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

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
                       p.platform_key, pr.instance_host, pr.object_kind, pr.identifier_kind,
                       pr.native_identifier,
                       pr.canonical_target_url
                FROM link_observations lo JOIN external_links el USING (external_link_id)
                LEFT JOIN external_link_references elr USING (external_link_id)
                LEFT JOIN platform_references pr USING (platform_reference_id)
                LEFT JOIN platforms p ON p.platform_id = pr.platform_id
                {where} ORDER BY lo.link_observation_id""",
            parameters,
        )
        results = [dict(row) for row in rows]
        for item in results:
            for field in ("original_url", "canonical_url", "canonical_target_url"):
                if item[field] is not None:
                    item[field] = public_url(str(item[field]))
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
        kind, candidate_id = parse_match_ref(match_ref)
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
