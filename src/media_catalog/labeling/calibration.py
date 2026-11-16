"""Calibration report from recorded pair labels (bead ``data-processing-4o3``,
change ``add-labeling-audit-stream``).

Per queue signal: label counts by verdict, the same-or-variant share, and a
Wilson score 95% confidence interval for that share — the small-sample
binomial bound the abstention-first triage asked for.  Read-only; computed
from ``pair_labels`` alone.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any

WILSON_Z = 1.959963984540054  # two-sided 95%


def wilson_interval(successes: int, trials: int) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion; None when empty."""
    if trials <= 0:
        return None
    share = successes / trials
    denominator = 1 + WILSON_Z * WILSON_Z / trials
    center = (share + WILSON_Z * WILSON_Z / (2 * trials)) / denominator
    margin = (
        WILSON_Z
        * math.sqrt(share * (1 - share) / trials + WILSON_Z * WILSON_Z / (4 * trials * trials))
        / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def calibration_report(connection: sqlite3.Connection) -> dict[str, Any]:
    """Per-signal verdict counts, same-or-variant rate, and Wilson 95% CI."""
    rows = connection.execute(
        """SELECT queue_signal, verdict, count(*) AS n
             FROM pair_labels
            GROUP BY queue_signal, verdict"""
    ).fetchall()
    families: dict[str, dict[str, int]] = {}
    for row in rows:
        families.setdefault(str(row[0]), {})[str(row[1])] = int(row[2])
    report: dict[str, Any] = {}
    for signal in sorted(families):
        counts = families[signal]
        total = sum(counts.values())
        positive = counts.get("same", 0) + counts.get("variant", 0)
        interval = wilson_interval(positive, total)
        report[signal] = {
            "labels": total,
            "by_verdict": counts,
            "same_or_variant_rate": round(positive / total, 4) if total else None,
            "same_or_variant_ci95": ([round(bound, 4) for bound in interval] if interval else None),
        }
    grand_total = sum(entry["labels"] for entry in report.values())
    return {"families": report, "labels_total": grand_total}
