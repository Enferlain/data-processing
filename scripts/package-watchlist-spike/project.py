"""Rebuildable package-facts projection over the spike's retained history.

Answers "at least one rebuildable projection" (gh#4) by reusing the kernel's
projection-spec machinery unchanged -- policy slots, canonical digests, and
the as-of evidence cutoff -- over non-media observations.  Current values are
derived at read time (newest observation wins per field, all history kept),
never stored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from media_catalog.database import CatalogDatabase
from media_catalog.projections.spec import (
    AS_OF_ALL_RETAINED,
    POLICY_SLOTS,
    ProjectionSpec,
    canonical_json,
)

SPIKE_VERSION = "package-watchlist-spike-v1"
KIND = "package-facts"
POLICIES = {
    "selection": "packages_with_retained_observations",
    "ordering": "normalized_name ascending",
    "dedup": "none_source_object_identity",
    "preferred_representation": "not_applicable",
    "field_source": "newest_observation_wins_per_field_all_values_retained",
    "url_handling": "no_urls_emitted",
}


def _normalize_as_of(as_of: str) -> str:
    parsed = datetime.fromisoformat(as_of)
    if parsed.tzinfo is None:
        raise ValueError("as-of cutoff requires a timezone")
    # Convert, never relabel: +02:00 wall time must not masquerade as Z.
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build(catalog: Path, *, as_of: str = AS_OF_ALL_RETAINED, out: Path) -> dict:
    with CatalogDatabase(catalog) as database:
        connection = database.connection
        cutoff = (
            "AND julianday(replace(o.observed_at, 'Z', '+00:00')) "
            "<= julianday(replace(?, 'Z', '+00:00'))"
            if as_of != AS_OF_ALL_RETAINED
            else ""
        )
        values = (as_of,) if cutoff else ()
        packages = connection.execute(
            f"""SELECT p.package_id, p.normalized_name FROM spike_packages p
                 WHERE EXISTS (SELECT 1 FROM spike_package_observations o
                                WHERE o.package_id = p.package_id {cutoff})
                 ORDER BY p.normalized_name""",
            values,
        ).fetchall()
        rows = []
        for package in packages:
            observations = connection.execute(
                f"""SELECT o.latest_version, o.yanked_latest, o.summary, o.license,
                           o.requires_python, o.observed_at, o.raw_observation_id
                      FROM spike_package_observations o
                     WHERE o.package_id = ? {cutoff}
                  ORDER BY julianday(replace(o.observed_at, 'Z', '+00:00')),
                           o.package_observation_id""",
                (package["package_id"], *values),
            ).fetchall()
            newest = observations[-1]
            rows.append(
                {
                    "package": str(package["normalized_name"]),
                    "latest_version": newest["latest_version"],
                    "yanked_latest": bool(newest["yanked_latest"]),
                    "summary": newest["summary"],
                    "license": newest["license"],
                    "requires_python": newest["requires_python"],
                    "observed_at": str(newest["observed_at"]),
                    "raw_observation_id": newest["raw_observation_id"],
                    "observation_count": len(observations),
                }
            )
        spec = ProjectionSpec(
            kind=KIND,
            projection_schema_version="package-facts-v1",
            policies=POLICIES,
            tool_version=SPIKE_VERSION,
            source_schema_version=str(connection.execute("PRAGMA user_version").fetchone()[0]),
            as_of=as_of,
        )
    content = "".join(canonical_json(row) + "\n" for row in rows)
    out.write_text(content)
    return {
        "spec": spec.as_dict(),
        "spec_digest": spec.digest(),
        "policy_slots": list(POLICY_SLOTS),
        "rows": len(rows),
        "content_digest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "output": str(out),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("spike-catalog.sqlite3"))
    parser.add_argument("--out", type=Path, default=Path("package-facts.jsonl"))
    parser.add_argument("--as-of", default=AS_OF_ALL_RETAINED)
    args = parser.parse_args(argv)
    as_of = _normalize_as_of(args.as_of) if args.as_of != AS_OF_ALL_RETAINED else args.as_of
    report = build(args.catalog, as_of=as_of, out=args.out)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
