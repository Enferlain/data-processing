"""Calibrated candidate-scoring policy (bead ``data-processing-vo8``,
change ``add-calibrated-scoring-policy``).

One deterministic recompute shared by every candidate score writer:
each evidence family's weight is its base strength scaled by a calibration
factor derived from the operator's recorded label distribution for the
corresponding labeling signal family.  Families whose labels are majority
``different`` contribute negative weight — same-artist agreement alone is
measured evidence *against* same-work — and evidence kinds that restate one
identity fact compound within their correlation group instead of summing.

Calibration data is the operator's pair labels (2026-11-22 snapshot).
Auto-confirmed ``identical_md5`` rows are excluded (circular: the rule
writes them); that family uses the operator-verified 59/59 calibration
recorded before the auto rule existed.  Rates are Laplace-smoothed
(``(sv+1)/(n+2)``) so thin families cannot swing to the extremes; the
Wilson 95% interval rides along in the score components as the honest
uncertainty record.  Revisit Beta calibration once families pass ~100-200
labels (docs/research/Abstention-First Entity Resolution.md).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from media_catalog.labeling.calibration import wilson_interval

# The canonical strength tier map lives with the policy; discovery.support
# re-exports it for its existing importers.
STRENGTH_SCORES = {"weak": 10, "moderate": 35, "strong": 70, "exact": 100}

SCORING_POLICY_VERSION = "calibrated-evidence-v2"

#: Operator label snapshots per labeling signal family:
#: (same_or_variant labels, different labels).  identical_md5 uses the
#: operator-verified 59/59 measured before the auto-confirm rule (the
#: 18,765 auto rows restate the rule, not the operator).
FAMILY_LABELS: dict[str, tuple[int, int]] = {
    "identical_md5": (59, 0),
    "provider_parent": (196, 35),
    "shared_source_url": (17, 10),
    "shared_external_id": (0, 2),
    "same_artist_tags": (2, 52),
    "same_artist_contrast": (0, 179),
    "pool_member": (27, 82),
}

#: Evidence kind -> labeling signal family whose labels calibrate it.
#: Kinds absent here keep factor 1.0 (behavior unchanged from v1).
KIND_FAMILY: dict[str, str] = {
    "verified_exact_hash": "identical_md5",
    "provider_source_reference": "shared_source_url",
    "shared_stable_external_id": "shared_external_id",
    "same_artist_overlap": "same_artist_tags",
}

#: Evidence-kind sets that restate one identity fact (the artist identity
#: embedded in a source URL): combined multiplicatively, never summed.
CORRELATED_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"provider_source_reference", "same_artist_overlap"}),
)


@dataclass(frozen=True, slots=True)
class FamilyCalibration:
    """The calibration snapshot for one labeling signal family."""

    labels: int
    same_or_variant: int
    rate: float
    ci95: tuple[float, float]

    @property
    def factor(self) -> float:
        """Signed calibration factor in [-1, 1]; negative = majority different."""

        return 2.0 * self.rate - 1.0


def family_calibration(family: str) -> FamilyCalibration:
    """Laplace-smoothed rate and Wilson CI for one signal family."""

    same_or_variant, different = FAMILY_LABELS[family]
    labels = same_or_variant + different
    interval = wilson_interval(same_or_variant, labels)
    assert interval is not None
    rate = (same_or_variant + 1) / (labels + 2)
    return FamilyCalibration(labels, same_or_variant, rate, interval)


def _group_of(kind: str) -> frozenset[str] | None:
    for group in CORRELATED_GROUPS:
        if kind in group:
            return group
    return None


def score_evidence(rows: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    """Score supporting evidence rows under the calibrated policy.

    Each row carries ``evidence_kind`` and ``strength``.  Contributions are
    ``STRENGTH_SCORES[strength] * family factor`` (unmapped kinds factor
    1.0); contributions inside a correlation group compound as
    ``100 * (1 - prod(1 - c/100))``; the total sums groups and standalone
    kinds.  Deterministic: the same rows always score the same.
    """
    per_family: dict[str, dict[str, Any]] = {}
    best_in_group: dict[frozenset[str], dict[str, float]] = {}
    standalone_total = 0.0
    for row in rows:
        kind = str(row["evidence_kind"])
        strength = str(row["strength"])
        base = STRENGTH_SCORES[strength]
        family = KIND_FAMILY.get(kind)
        if family is None:
            contribution = float(base)
            calibration = None
        else:
            calibration = family_calibration(family)
            contribution = base * calibration.factor
        entry = per_family.setdefault(
            kind,
            {
                "count": 0,
                "contribution": 0.0,
                "labels": calibration.labels if calibration else None,
                "rate": round(calibration.rate, 4) if calibration else None,
                "ci95": ([round(bound, 4) for bound in calibration.ci95] if calibration else None),
            },
        )
        entry["count"] += 1
        entry["contribution"] = round(entry["contribution"] + contribution, 4)
        group = _group_of(kind)
        if group is None:
            standalone_total += contribution
        else:
            members = best_in_group.setdefault(group, {})
            previous = members.get(kind)
            members[kind] = contribution if previous is None else max(previous, contribution)

    total = standalone_total
    compounds: list[dict[str, Any]] = []
    for group in sorted(best_in_group, key=sorted):
        members = best_in_group[group]
        # Positive correlated evidence compounds (probabilistic OR) so a
        # restated identity fact is never counted twice; negative members
        # are discounts and apply additively after the compound.
        remainder = 1.0
        for value in members.values():
            if value > 0:
                remainder *= 1.0 - value / 100.0
        compound = 100.0 * (1.0 - remainder) + sum(
            value for value in members.values() if value <= 0
        )
        total += compound
        compounds.append({"group": sorted(group), "compound": round(compound, 4)})
    score = round(total)
    components = {
        "policy_version": SCORING_POLICY_VERSION,
        "points": score,
        "supporting_evidence": len(rows),
        "families": per_family,
        "compounds": compounds,
    }
    return score, json.loads(json.dumps(components))


def score_candidate_evidence(
    connection: Any,
    join_table: str,
    id_column: str,
    candidate_id: int,
) -> tuple[int, str, int]:
    """Score one candidate's supporting evidence under the shared policy.

    Reads the candidate's ``supports``-stance evidence rows through its
    evidence join table and returns ``(score, components_json, generation)``
    for the writer's UPDATE.
    """

    rows = connection.execute(
        f"""SELECT e.evidence_kind, e.strength
              FROM {join_table} ce JOIN match_evidence e ON e.evidence_id = ce.evidence_id
             WHERE ce.{id_column} = ? AND e.stance = 'supports'""",
        (candidate_id,),
    ).fetchall()
    score, components = score_evidence(
        [{"evidence_kind": row[0], "strength": row[1]} for row in rows]
    )
    return score, json.dumps(components, sort_keys=True), len(rows)
