"""Repair pre-0018 anchorless raw-observation duplicates (Bead data-processing-7o0).

Migration 0018 fails loudly on catalogs that already hold anchorless
duplicates (same object kind, native id, and payload bytes under no run or
request anchor).  This script performs the out-of-band surgery the 0018
comment prescribes, under the strict 0018 definition so the migration chain
passes: for every duplicate group keep the earliest observation, re-point
referencing rows to it (update-blocking triggers drop and recreate from
their stored SQL verbatim), delete unreferenced members (the raw-observation
immutability triggers likewise), and verify.  Same-platform folds and
cross-platform folds are reported separately -- the latter fold historical
per-source attestation into the first writer, whose attempt history survives
in the request ledger; migration 0019 scopes anchorless identity to the
source so the cross-platform class never recurs.

Dry-run by default: prints the full plan and changes nothing.  ``--apply``
executes in one transaction and finishes with foreign-key and zero-group
verification.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ANCHORLESS = "import_run_id IS NULL AND remote_run_id IS NULL AND remote_request_id IS NULL"


def _referencing_tables(connection: sqlite3.Connection) -> list[tuple[str, str]]:
    tables = [
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]
    pairs = []
    for table in tables:
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        if "raw_observation_id" in columns and table != "raw_observations":
            pairs.append((table, "raw_observation_id"))
    return pairs


def _groups(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        f"""SELECT object_kind, native_id, raw_payload_id,
                   MIN(raw_observation_id) AS keep_id,
                   COUNT(*) AS members
              FROM raw_observations
             WHERE {ANCHORLESS} AND native_id IS NOT NULL
             GROUP BY object_kind, native_id, raw_payload_id
            HAVING COUNT(*) > 1
            UNION ALL
            SELECT object_kind, NULL, raw_payload_id,
                   MIN(raw_observation_id), COUNT(*)
              FROM raw_observations
             WHERE {ANCHORLESS} AND native_id IS NULL
             GROUP BY object_kind, raw_payload_id
            HAVING COUNT(*) > 1
            ORDER BY keep_id"""
    ).fetchall()
    return [dict(row) for row in rows]


def _triggers_on(connection: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    return [
        (row[0], row[1])
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name = ?",
            (table,),
        )
    ]


def _drop_and_remember(connection: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    triggers = _triggers_on(connection, table)
    for name, _ in triggers:
        connection.execute(f"DROP TRIGGER {name}")
    return triggers


def _recreate(connection: sqlite3.Connection, triggers: list[tuple[str, str]]) -> None:
    for _, sql in triggers:
        connection.execute(sql)


def plan_and_apply(catalog: Path, *, apply: bool) -> dict[str, object]:
    connection = sqlite3.connect(catalog)
    connection.row_factory = sqlite3.Row
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > 18:
        connection.close()
        raise SystemExit(f"catalog is at schema {version}; duplicates live at <= 17")
    groups = _groups(connection)
    referencing = _referencing_tables(connection)
    plan: list[dict[str, object]] = []
    for group in groups:
        members = connection.execute(
            f"""SELECT raw_observation_id, platform_id, object_kind, observed_at
                  FROM raw_observations
                 WHERE {ANCHORLESS} AND object_kind = ? AND native_id IS ?
                   AND raw_payload_id = ?
                 ORDER BY raw_observation_id""",
            (group["object_kind"], group["native_id"], group["raw_payload_id"]),
        ).fetchall()
        keep = dict(members[0])
        for member in members[1:]:
            entry: dict[str, object] = {
                "drop_observation_id": int(member["raw_observation_id"]),
                "keep_observation_id": keep["raw_observation_id"],
                "object_kind": group["object_kind"],
                "fold": (
                    "cross_platform"
                    if member["platform_id"] != keep["platform_id"]
                    else "same_platform"
                ),
                "dropped_observed_at": member["observed_at"],
                "repoints": [],
            }
            for table, column in referencing:
                count = connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                    (member["raw_observation_id"],),
                ).fetchone()[0]
                if count:
                    entry["repoints"].append({"table": table, "rows": int(count)})
            plan.append(entry)
    report: dict[str, object] = {
        "catalog": str(catalog),
        "schema_version": version,
        "groups": len(groups),
        "folds": {
            "same_platform": sum(1 for e in plan if e["fold"] == "same_platform"),
            "cross_platform": sum(1 for e in plan if e["fold"] == "cross_platform"),
        },
        "plan": plan,
        "applied": False,
    }
    if not apply:
        connection.close()
        return report
    connection.execute("BEGIN IMMEDIATE")
    # The plan was computed before the lock; a concurrent writer could have
    # changed the anchorless set in between.  Re-check under the lock and
    # abort loudly rather than apply a stale plan.
    if _groups(connection) != groups:
        connection.rollback()
        connection.close()
        raise SystemExit("anchorless set changed during planning; re-run the repair")
    touched_tables: dict[str, list[tuple[str, str]]] = {}
    try:
        for entry in plan:
            drop_id = entry["drop_observation_id"]
            keep_id = entry["keep_observation_id"]
            for table, column in referencing:
                has_rows = connection.execute(
                    f"SELECT EXISTS(SELECT 1 FROM {table} WHERE {column} = ?)",
                    (drop_id,),
                ).fetchone()[0]
                if not has_rows:
                    continue
                if table not in touched_tables:
                    # Update-blocking audit triggers lift for re-points and
                    # are recreated verbatim at the end.
                    touched_tables[table] = _drop_and_remember(connection, table)
                connection.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                    (keep_id, drop_id),
                )
        raw_triggers = _drop_and_remember(connection, "raw_observations")
        for entry in plan:
            connection.execute(
                "DELETE FROM raw_observations WHERE raw_observation_id = ?",
                (entry["drop_observation_id"],),
            )
        _recreate(connection, raw_triggers)
        for triggers in touched_tables.values():
            _recreate(connection, triggers)
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SystemExit(f"foreign key violations after repair: {len(violations)}")
        remaining = _groups(connection)
        if remaining:
            raise SystemExit(f"duplicate groups remain after repair: {len(remaining)}")
        connection.commit()
    except BaseException:
        connection.rollback()
        connection.close()
        raise
    report["applied"] = True
    connection.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--apply", action="store_true", help="execute the plan (default: dry run)")
    args = parser.parse_args(argv)
    report = plan_and_apply(args.catalog, apply=args.apply)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
