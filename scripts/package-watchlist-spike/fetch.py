"""Bounded live fetch of PyPI package metadata into spike fixtures.

The second-consumer spike (gh#4) needs one genuinely non-media intake with a
real bounded fetch contract.  This script talks to the public PyPI JSON API
under explicit item/byte/time budgets with typed outcomes, and captures what
it fetched as fixtures so the rest of the spike runs offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://pypi.org/pypi/{name}/json"
USER_AGENT = "data-processing-kernel-spike/0.1 (bounded research fetch)"

# Typed outcomes reuse the kernel run-outcome vocabulary (REMOTE_OUTCOMES);
# every terminal path names one.
# Every terminal path names one; the full kernel outcome vocabulary lives in
# the spike run table's CHECK constraint (intake.py).
OUTCOMES = (
    "success",
    "unavailable",
    "rate_limited",
    "transient_provider",
    "malformed_response",
    "budget_exhausted",
)


def fetch(
    packages: list[str],
    out_dir: Path,
    *,
    item_budget: int,
    byte_budget: int,
    time_budget_seconds: int,
) -> dict:
    started = time.monotonic()
    manifest: list[dict] = []
    bytes_seen = 0
    outcome = "success"
    budget_boundary = None
    for index, name in enumerate(packages, start=1):
        if index > item_budget:
            outcome, budget_boundary = "budget_exhausted", "item"
            break
        if time.monotonic() - started > time_budget_seconds:
            outcome, budget_boundary = "budget_exhausted", "time"
            break
        url = API.format(name=name)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        item_outcome = "success"
        status = None
        body = b""
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            item_outcome = (
                "unavailable"
                if error.code == 404
                else "rate_limited"
                if error.code == 429
                else "malformed_response"
            )
        except (urllib.error.URLError, TimeoutError):
            item_outcome = "transient_provider"
        if item_outcome == "success":
            try:
                document = json.loads(body)
                document["info"]["name"]  # shape probe
            except (ValueError, KeyError, TypeError):
                item_outcome = "malformed_response"
        if item_outcome == "success":
            bytes_seen += len(body)
            if bytes_seen > byte_budget:
                outcome, budget_boundary = "budget_exhausted", "bytes"
                break
            target = out_dir / f"{name}.json"
            target.write_bytes(body)
        manifest.append(
            {
                "package": name,
                "url": url,
                "status_code": status,
                "byte_size": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "outcome": item_outcome,
            }
        )
    report = {
        "declared_budgets": {
            "item": item_budget,
            "bytes": byte_budget,
            "time_seconds": time_budget_seconds,
        },
        "counts": {"items": len(manifest), "bytes": bytes_seen},
        "outcome": outcome,
        "budget_boundary": budget_boundary,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "requests": manifest,
    }
    (out_dir / "fetch-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="+")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "fixtures")
    parser.add_argument("--item-budget", type=int, default=10)
    parser.add_argument("--byte-budget", type=int, default=2_000_000)
    parser.add_argument("--time-budget-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = fetch(
        args.packages,
        args.out_dir,
        item_budget=args.item_budget,
        byte_budget=args.byte_budget,
        time_budget_seconds=args.time_budget_seconds,
    )
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0 if report["outcome"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
