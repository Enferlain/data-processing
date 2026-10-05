"""Measure matching signals over fetched spike fixtures.

Reads the manifest, locates fixture bytes fetched by fetch.py, and computes
per-pair signals — exact hash equality, perceptual-hash Hamming distance at
sizes 8 and 16, dimensions, aspect closeness, and chronology where both sides
carry a declared creation time. Outputs pairs.jsonl (one record per pair) and
report.json (per-class distance distributions and a threshold sweep with
true/false-positive rates against the class labels, plus exact-byte
collisions across fixtures as the same-bytes evidence).

Research tooling only: similarity measurement lives here, not in the catalog
package — catalog hashes are identification metadata, and no metric or
threshold establishes identity, authorship, same-work, source direction, or
preferred quality.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from PIL import Image
from seeds import POSITIVE_CLASSES
from signals import (
    aspect_ratio,
    aspect_ratio_close,
    hamming_distance,
    hashes_equal,
    phashes_from_image,
    same_dimensions,
)

SWEEP_MAX = 32


def _fixture_map(fixtures_dir: Path) -> dict[str, Path]:
    return {path.stem: path for path in sorted(fixtures_dir.iterdir()) if path.is_file()}


def _measure_fixture(path: Path) -> dict[str, Any] | None:
    data = path.read_bytes()
    with Image.open(path) as image:
        image.seek(0)
        image.load()
        hashes = phashes_from_image(image)
        width, height = image.size
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "md5": hashlib.md5(data).hexdigest(),
        "phash8": hashes[8],
        "phash16": hashes[16],
        "width": width,
        "height": height,
    }


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _distribution(values: list[int]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "min": min(values),
        "p50": statistics.median(values),
        "max": max(values),
    }


def _sweep(
    pairs: list[dict[str, Any]], field: str, positives: set[str], negatives: set[str]
) -> list[dict[str, Any]]:
    sweep = []
    for threshold in range(SWEEP_MAX + 1):
        tp = sum(1 for p in pairs if p["class"] in positives and p[field] <= threshold)
        fn = sum(1 for p in pairs if p["class"] in positives and p[field] > threshold)
        fp = sum(1 for p in pairs if p["class"] in negatives and p[field] <= threshold)
        tn = sum(1 for p in pairs if p["class"] in negatives and p[field] > threshold)
        sweep.append(
            {
                "threshold": threshold,
                "true_positives": tp,
                "false_negatives": fn,
                "false_positives": fp,
                "true_negatives": tn,
                "true_positive_rate": round(tp / (tp + fn), 4) if tp + fn else None,
                "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None,
            }
        )
    return sweep


def measure(
    manifest_path: Path,
    fixtures_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {str(entry["key"]): entry for entry in manifest.get("entries", [])}
    fixtures = _fixture_map(fixtures_dir)

    measured: dict[str, dict[str, Any]] = {}
    for key in entries:
        path = fixtures.get(key.replace(":", "_"))
        if path is None:
            continue
        record = _measure_fixture(path)
        if record is not None:
            measured[key] = record

    pair_records: list[dict[str, Any]] = []
    for pair in manifest.get("pairs", []):
        first = str(pair["a"])
        second = str(pair["b"])
        if first not in measured or second not in measured:
            continue
        left, right = measured[first], measured[second]
        left_time = _parse_time(entries[first].get("declared_created_at"))
        right_time = _parse_time(entries[second].get("declared_created_at"))
        pair_records.append(
            {
                "class": pair["class"],
                "group": pair["group"],
                "a": first,
                "b": second,
                "sha256_equal": hashes_equal(left["sha256"], right["sha256"]),
                "md5_equal": hashes_equal(left["md5"], right["md5"]),
                "distance8": hamming_distance(left["phash8"], right["phash8"]),
                "distance16": hamming_distance(left["phash16"], right["phash16"]),
                "same_dimensions": same_dimensions(
                    left["width"], left["height"], right["width"], right["height"]
                ),
                "aspect_close": aspect_ratio_close(
                    aspect_ratio(left["width"], left["height"]),
                    aspect_ratio(right["width"], right["height"]),
                ),
                "created_delta_seconds": (
                    (right_time - left_time).total_seconds()
                    if left_time is not None and right_time is not None
                    else None
                ),
            }
        )

    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in pair_records:
        by_class[record["class"]].append(record)

    class_reports = {
        name: {
            "pairs": len(records),
            "sha256_equal": sum(1 for r in records if r["sha256_equal"]),
            "same_dimensions": sum(1 for r in records if r["same_dimensions"]),
            "distance8": _distribution([r["distance8"] for r in records]),
            "distance16": _distribution([r["distance16"] for r in records]),
        }
        for name, records in sorted(by_class.items())
    }

    positives = {c for c in POSITIVE_CLASSES if c in by_class}
    negatives = set(by_class) - positives

    sha_groups: dict[str, list[str]] = defaultdict(list)
    for key, record in measured.items():
        sha_groups[record["sha256"]].append(key)
    byte_collisions = {sha: keys for sha, keys in sha_groups.items() if len(keys) > 1}

    report = {
        "manifest": manifest_path.name,
        "fixtures_measured": len(measured),
        "fixtures_missing": sorted(set(entries) - set(measured)),
        "pairs_measured": len(pair_records),
        "positive_classes": sorted(positives),
        "negative_classes": sorted(negatives),
        "classes": class_reports,
        "exact_byte_collisions": byte_collisions,
        "sweep_distance8": _sweep(pair_records, "distance8", positives, negatives),
        "sweep_distance16": _sweep(pair_records, "distance16", positives, negatives),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "pairs.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in pair_records),
        encoding="utf-8",
    )
    (output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest", type=Path, default=Path("private-exports/matching-spike/manifest.json")
    )
    parser.add_argument(
        "--fixtures-dir", type=Path, default=Path("private-exports/matching-spike/fixtures/")
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("private-exports/matching-spike/results/")
    )
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    report = measure(arguments.manifest, arguments.fixtures_dir, arguments.output_dir)
    if arguments.json:
        print(
            json.dumps(
                {
                    "fixtures_measured": report["fixtures_measured"],
                    "pairs_measured": report["pairs_measured"],
                    "classes": {
                        name: body["distance8"] for name, body in report["classes"].items()
                    },
                },
                indent=2,
            )
        )
    else:
        print(f"measure: fixtures={report['fixtures_measured']} pairs={report['pairs_measured']}")
        print(f"results: {arguments.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
