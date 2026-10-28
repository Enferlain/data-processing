"""Repair replay-stamped facts from the pre-fix reprocess runs (Bead data-processing-3qq).

The 2026-10-08 reprocess runs (before the 8c95810 fix) stamped replay
wall-clock times into the catalog as observation times: duplicate history
rows in post_metadata_observations (6), account_snapshots (1), and
post_tag_observations (172) -- every one an identical-facts twin of an
earlier row -- plus inflated current-projection timestamps on 3 posts,
55 tags, 87 post_tags, 2 accounts, and 3 media occurrences.  Values were
never corrupted; only times lie.

The repair is deterministic: a fact row is replay damage exactly when its
timestamp equals a reprocess run's ``started_at`` AND an identical-facts
row exists at an earlier time.  Damage rows are deleted (trigger surgery
where the audit tier blocks deletes); current-projection fields are
recomputed from the surviving observation history, which the design makes
updatable.  Dry-run by default; ``--apply`` executes in one transaction
and verifies no replay-stamped row remains.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# (table, stamp column, identical-facts twin predicate joining earlier row e)
HISTORY_TABLES: tuple[tuple[str, str, str], ...] = (
    (
        "post_metadata_observations",
        "observed_at",
        """e.post_id = r.post_id
            AND e.score_up IS r.score_up AND e.score_down IS r.score_down
            AND e.score_total IS r.score_total AND e.favorite_count IS r.favorite_count
            AND e.comment_count IS r.comment_count AND e.flag_deleted IS r.flag_deleted
            AND e.flag_pending IS r.flag_pending AND e.flag_flagged IS r.flag_flagged
            AND e.observed_at < r.observed_at""",
    ),
    (
        "account_snapshots",
        "observed_at",
        """e.account_id = r.account_id AND e.snapshot_digest = r.snapshot_digest
            AND e.observed_at < r.observed_at""",
    ),
    (
        "post_tag_observations",
        "observed_at",
        """e.post_tag_id = r.post_tag_id
            AND e.provider_spelling IS r.provider_spelling
            AND e.translated_label IS r.translated_label AND e.position IS r.position
            AND e.native_category IS r.native_category
            AND e.native_category_code IS r.native_category_code
            AND e.observed_at < r.observed_at""",
    ),
)

CURRENT_FIELDS: tuple[tuple[str, str, str], ...] = (
    # (table, column, recompute expression binding row id :row_id)
    (
        "posts",
        "last_seen_at",
        """SELECT MAX(t) FROM (
               SELECT MAX(observed_at) t FROM post_metadata_observations
                WHERE post_id = :row_id
               UNION ALL
               SELECT MAX(observed_at) FROM media_occurrences WHERE post_id = :row_id
               UNION ALL
               SELECT MAX(pto.observed_at) FROM post_tag_observations pto
                 JOIN post_tags pt ON pt.post_tag_id = pto.post_tag_id
                WHERE pt.post_id = :row_id)""",
    ),
    (
        "tags",
        "last_observed_at",
        """SELECT MAX(t) FROM (
               SELECT MAX(observed_at) t FROM tag_observations WHERE tag_id = :row_id
               UNION ALL
               SELECT MAX(pto.observed_at) FROM post_tag_observations pto
                 JOIN post_tags pt ON pt.post_tag_id = pto.post_tag_id
                WHERE pt.tag_id = :row_id)""",
    ),
    (
        "post_tags",
        "last_seen_at",
        """SELECT MAX(observed_at) FROM post_tag_observations
           WHERE post_tag_id = :row_id""",
    ),
    (
        "accounts",
        "last_seen_at",
        """SELECT MAX(observed_at) FROM account_snapshots WHERE account_id = :row_id""",
    ),
)


def _replay_times(connection: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            "SELECT started_at FROM remote_runs WHERE origin_kind = 'reprocess'"
        )
    ]


def _drop_and_remember(connection: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    triggers = [
        (row[0], row[1])
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name = ?",
            (table,),
        )
    ]
    for name, _ in triggers:
        connection.execute(f"DROP TRIGGER {name}")
    return triggers


def plan_and_apply(catalog: Path, *, apply: bool) -> dict[str, object]:
    connection = sqlite3.connect(catalog)
    connection.row_factory = sqlite3.Row
    replay = _replay_times(connection)
    if not replay:
        connection.close()
        return {"catalog": str(catalog), "reprocess_runs": 0, "applied": False}
    marks = ",".join("?" * len(replay))

    deletes: dict[str, list[int]] = {}
    orphans: dict[str, int] = {}
    for table, column, twin in HISTORY_TABLES:
        rows = connection.execute(
            f"""SELECT r.rowid FROM {table} r
                 WHERE r.{column} IN ({marks})
                   AND EXISTS (SELECT 1 FROM {table} e WHERE {twin})""",
            replay,
        ).fetchall()
        deletes[table] = [row[0] for row in rows]
        orphans[table] = connection.execute(
            f"""SELECT COUNT(*) FROM {table} r
                 WHERE r.{column} IN ({marks})
                   AND NOT EXISTS (SELECT 1 FROM {table} e WHERE {twin})""",
            replay,
        ).fetchone()[0]

    # Occurrences carry the replay stamp directly; their retained raw
    # observation kept the original time.
    occurrences = connection.execute(
        f"""SELECT mo.rowid AS occ_rowid, ro.observed_at FROM media_occurrences mo
             JOIN raw_observations ro ON ro.raw_observation_id = mo.raw_observation_id
            WHERE mo.observed_at IN ({marks})""",
        replay,
    ).fetchall()

    current_updates: dict[str, int] = {}
    for table, column, expression in CURRENT_FIELDS:
        stamped = connection.execute(
            f"SELECT rowid AS row_id FROM {table} WHERE {column} IN ({marks})",
            replay,
        ).fetchall()
        changed = 0
        for row in stamped:
            recomputed = connection.execute(expression, {"row_id": row["row_id"]}).fetchone()[0]
            if recomputed is not None:
                changed += 1
        current_updates[f"{table}.{column}"] = changed

    report: dict[str, object] = {
        "catalog": str(catalog),
        "reprocess_runs": len(replay),
        "delete_history_rows": {t: len(ids) for t, ids in deletes.items()},
        "replay_rows_without_earlier_twin": dict(orphans),
        "occurrence_timestamps_from_raw": len(occurrences),
        "current_fields_recomputable": current_updates,
        "applied": False,
    }
    if not apply:
        connection.close()
        return report

    connection.execute("BEGIN IMMEDIATE")
    try:
        if _replay_times(connection) != replay:
            raise SystemExit("reprocess run set changed during planning; re-run")
        for (table, column, twin), _ in zip(HISTORY_TABLES, deletes.values(), strict=True):
            triggers = _drop_and_remember(connection, table)
            connection.execute(
                f"""DELETE FROM {table}
                     WHERE rowid IN (SELECT r.rowid FROM {table} r
                                      WHERE r.{column} IN ({marks})
                                        AND EXISTS (SELECT 1 FROM {table} e WHERE {twin}))""",
                replay,
            )
            for _, sql in triggers:
                connection.execute(sql)
        for row in occurrences:
            connection.execute(
                "UPDATE media_occurrences SET observed_at = ? WHERE rowid = ?",
                (row["observed_at"], row["occ_rowid"]),
            )
        for table, column, expression in CURRENT_FIELDS:
            for row in connection.execute(
                f"SELECT rowid AS row_id FROM {table} WHERE {column} IN ({marks})",
                replay,
            ).fetchall():
                recomputed = connection.execute(expression, {"row_id": row["row_id"]}).fetchone()[0]
                if recomputed is not None:
                    connection.execute(
                        f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                        (recomputed, row["row_id"]),
                    )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SystemExit(f"foreign key violations after repair: {len(violations)}")
        for table, column, _ in HISTORY_TABLES:
            remaining = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({marks})", replay
            ).fetchone()[0]
            if remaining != orphans[table]:
                raise SystemExit(f"replay-stamped rows remain in {table}: {remaining}")
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
    print(json.dumps(plan_and_apply(args.catalog, apply=args.apply), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
