"""Intake: spike fixtures into a catalog through the kernel surfaces.

The second-consumer spike (gh#4).  This script normalizes the captured PyPI
documents into typed package records while exercising kernel contracts:
source identity through ``platforms``, append-only source reports through
``store_raw``, evidence through the shared ledger, and a bounded run whose
inputs are storage-immutable.  Spike-owned tables (``spike_*``) follow the
kernel immutability tiers and are created here, not in kernel migrations --
that placement is itself one of the spike's findings.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.records import RawRecord
from media_catalog.writer import CatalogWriter

SPIKE_VERSION = "package-watchlist-spike-v1"
SOURCE = "pypi"

# Kernel vocabularies the spike reuses verbatim where it can.
RUN_OUTCOMES = frozenset(
    {
        "success",
        "unavailable",
        "deleted",
        "authentication_required",
        "authorization_denied",
        "rate_limited",
        "transient_provider",
        "malformed_response",
        "budget_exhausted",
        "local_persistence",
    }
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS spike_packages (
    package_id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL REFERENCES platforms(platform_id),
    normalized_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    UNIQUE (platform_id, normalized_name)
);
CREATE TRIGGER IF NOT EXISTS spike_packages_no_update
    BEFORE UPDATE ON spike_packages
BEGIN
    SELECT RAISE(ABORT, 'spike_packages rows are immutable');
END;
CREATE TRIGGER IF NOT EXISTS spike_packages_no_delete
    BEFORE DELETE ON spike_packages
BEGIN
    SELECT RAISE(ABORT, 'spike_packages rows cannot be deleted');
END;
CREATE TABLE IF NOT EXISTS spike_package_observations (
    package_observation_id INTEGER PRIMARY KEY,
    package_id INTEGER NOT NULL REFERENCES spike_packages(package_id),
    observed_at TEXT NOT NULL,
    latest_version TEXT,
    yanked_latest INTEGER,
    summary TEXT,
    license TEXT,
    requires_python TEXT,
    raw_observation_id INTEGER REFERENCES raw_observations(raw_observation_id),
    UNIQUE (package_id, observed_at, raw_observation_id)
);
CREATE TRIGGER IF NOT EXISTS spike_package_observations_no_update
    BEFORE UPDATE ON spike_package_observations
BEGIN
    SELECT RAISE(ABORT, 'spike_package_observations are append-only');
END;
CREATE TRIGGER IF NOT EXISTS spike_package_observations_no_delete
    BEFORE DELETE ON spike_package_observations
BEGIN
    SELECT RAISE(ABORT, 'spike_package_observations are append-only');
END;
-- The bounded run contract, mirrored at spike altitude because the kernel's
-- remote_runs operation vocabulary has no non-media values (finding F2).
CREATE TABLE IF NOT EXISTS spike_runs (
    spike_run_id INTEGER PRIMARY KEY,
    operation TEXT NOT NULL,
    target TEXT NOT NULL,
    item_budget INTEGER NOT NULL,
    byte_budget INTEGER NOT NULL,
    time_budget_seconds INTEGER NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    byte_count INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL CHECK (outcome IN ({outcome_marks})),
    budget_boundary TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TRIGGER IF NOT EXISTS spike_runs_inputs_immutable
    BEFORE UPDATE OF operation, target, item_budget, byte_budget,
                     time_budget_seconds, started_at ON spike_runs
BEGIN
    SELECT RAISE(ABORT, 'spike run inputs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS spike_runs_no_delete
    BEFORE DELETE ON spike_runs
BEGIN
    SELECT RAISE(ABORT, 'spike_runs rows cannot be deleted');
END;
""".format(outcome_marks=", ".join("'" + o + "'" for o in sorted(RUN_OUTCOMES)))


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _package_row(connection: sqlite3.Connection, platform_id: int, name: str, at: str) -> int:
    normalized = normalize_name(name)
    connection.execute(
        "INSERT OR IGNORE INTO spike_packages (platform_id, normalized_name, first_seen_at) "
        "VALUES (?, ?, ?)",
        (platform_id, normalized, at),
    )
    return int(
        connection.execute(
            "SELECT package_id FROM spike_packages WHERE platform_id = ? AND normalized_name = ?",
            (platform_id, normalized),
        ).fetchone()[0]
    )


def intake(catalog: Path, fixtures: Path, *, now: str) -> dict:
    manifest = json.loads((fixtures / "fetch-manifest.json").read_text())
    fetch_report: dict[str, dict] = {entry["package"]: entry for entry in manifest["requests"]}
    budgets = manifest["declared_budgets"]

    with CatalogDatabase(catalog) as database:
        connection = database.connection
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR IGNORE INTO platforms (platform_key, display_name, base_url) "
            "VALUES (?, ?, ?)",
            (SOURCE, "PyPI", "https://pypi.org"),
        )
        platform_id = int(
            connection.execute(
                "SELECT platform_id FROM platforms WHERE platform_key = ?", (SOURCE,)
            ).fetchone()[0]
        )
        # The run row opens with its declared inputs and a provisional
        # outcome; counters, outcome, and finish time advance below and commit
        # once, so no outside reader ever sees a half-finished run.
        connection.execute(
            """INSERT INTO spike_runs (operation, target, item_budget, byte_budget,
                                       time_budget_seconds, outcome, started_at)
               VALUES ('fetch_package', 'watchlist', ?, ?, ?, 'success', ?)""",
            (budgets["item"], budgets["bytes"], budgets["time_seconds"], now),
        )
        run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])

        writer = CatalogWriter(database)
        normalized_rows = 0
        evidence_rows = 0
        for name, entry in sorted(fetch_report.items()):
            observed_at = entry["fetched_at"]
            payload = (fixtures / f"{name}.json").read_bytes()
            # Append-only source report: content-addressed payload plus one
            # observation per (object, payload), exactly as the media adapters.
            raw_observation_id = writer.store_raw(
                RawRecord(
                    payload=payload,
                    media_type="application/json",
                    object_kind="package",
                    native_id=normalize_name(name),
                    observed_at=observed_at,
                    platform=SOURCE,
                    adapter_version=SPIKE_VERSION,
                    schema_version="pypi-json-v1",
                )
            )
            document = json.loads(payload)
            info = document["info"]
            # Evidence through the shared ledger, via the writer's generic
            # evidence insert: the normalization detector that maps the
            # requested name onto the package identity.
            writer.insert_relationship_evidence_row(
                evidence_kind="name_normalization",
                direction="symmetric",
                strength="exact",
                detector="spike-name-normalizer",
                detector_version=SPIKE_VERSION,
                observed_at=observed_at,
                explanation=(
                    f"requested name {name!r} normalizes to the package identity {info['name']!r}"
                ),
                components={"requested": name, "normalized": normalize_name(name)},
            )
            evidence_rows += 1
            package_id = _package_row(connection, platform_id, info["name"], observed_at)
            _record_observation(connection, package_id, info, observed_at, raw_observation_id)
            normalized_rows += 1
            connection.execute(
                "UPDATE spike_runs SET item_count = item_count + 1, "
                "byte_count = byte_count + ? WHERE spike_run_id = ?",
                (len(payload), run_id),
            )

        # A labeled simulated later observation, so the projection can show
        # newest-observation-wins over retained history under an as-of cutoff.
        six_id = _package_row(connection, platform_id, "six", now)
        simulated = {
            "name": "six",
            "version": "1.18.0",
            "yanked": True,
            "yanked_reason": "spike simulation",
            "summary": "Python 2 and 3 compatibility utilities",
            "license": "MIT",
            "requires_python": ">=3.8",
        }
        # Anchorless like the raw reports (no raw pointer): insert only when
        # this anchorless observation is absent, so re-running intake is
        # idempotent -- the same NULL-distinctness hazard F4 describes.
        connection.execute(
            """INSERT INTO spike_package_observations (
                    package_id, observed_at, latest_version, yanked_latest,
                    summary, license, requires_python, raw_observation_id)
                SELECT ?, ?, ?, ?, ?, ?, ?, NULL
                 WHERE NOT EXISTS (SELECT 1 FROM spike_package_observations
                                    WHERE package_id = ? AND observed_at = ?
                                      AND raw_observation_id IS NULL)""",
            (
                six_id,
                now,
                simulated["version"],
                1,
                simulated["summary"],
                simulated["license"],
                simulated["requires_python"],
                six_id,
                now,
            ),
        )
        connection.execute(
            "UPDATE spike_runs SET outcome = 'success', finished_at = ? WHERE spike_run_id = ?",
            (now, run_id),
        )
        connection.commit()
        return {
            "spike_run_id": run_id,
            "platform_id": platform_id,
            "store_raw_calls": normalized_rows,
            "package_rows": normalized_rows,
            "evidence_rows": evidence_rows,
            "simulated_later_observation_for": "six",
        }


def _record_observation(
    connection: sqlite3.Connection,
    package_id: int,
    info: dict,
    observed_at: str,
    raw_observation_id: int | None,
) -> None:
    connection.execute(
        """INSERT OR IGNORE INTO spike_package_observations (
               package_id, observed_at, latest_version, yanked_latest, summary,
               license, requires_python, raw_observation_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            package_id,
            observed_at,
            info.get("version"),
            1 if info.get("yanked") else 0,
            info.get("summary"),
            info.get("license"),
            info.get("requires_python"),
            raw_observation_id,
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("spike-catalog.sqlite3"))
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).parent / "fixtures")
    parser.add_argument("--now", default="2026-10-23T06:00:00Z")
    args = parser.parse_args(argv)
    report = intake(args.catalog, args.fixtures, now=args.now)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
