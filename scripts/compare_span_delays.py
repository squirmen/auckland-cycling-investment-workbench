#!/usr/bin/env python3
"""Check like-for-like SPAN delay runs and record their bounded sensitivity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cycling_investment_workbench.provenance import sha256_file, write_json_atomic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("build/effective-network"))
    args = parser.parse_args()
    reports = {
        key: json.loads((args.directory / f"access-{key}.json").read_text())
        for key in ("none", "low", "default", "high")
    }
    baseline = reports["none"]
    scenarios = {}
    for key, report in reports.items():
        for field in ("runId", "sourceHashes", "graph", "sample", "standard", "parameters"):
            if report[field] != baseline[field]:
                raise ValueError(f"{key}: scope changed at {field}")
        if report["assignment"]["totalDemand"] != baseline["assignment"]["totalDemand"]:
            raise ValueError(f"{key}: fixed demand changed")
        if report["ridershipForecast"] is not None:
            raise ValueError("delay sensitivity cannot supply a ridership forecast")
        routes = [r for j in report["journeys"] for r in j["alternatives"]]
        if any(not 0 <= r["intersectionDelayS"] <= r["timeS"] for r in routes):
            raise ValueError(f"{key}: route delay is outside total physical time")
        if key == "none" and any(r["intersectionDelayS"] for r in routes):
            raise ValueError("no-delay reference contains a penalty")
        solutions = [
            {
                k: s[k]
                for k in (
                    "budget",
                    "served_journeys",
                    "served_weight",
                    "capital_cost",
                    "selected",
                    "optimal_within_columns",
                )
            }
            for s in report["solutions"]
            if s["method"] == "route_packages_milp"
        ]
        scenarios[key] = {
            "sha256": sha256_file(args.directory / f"access-{key}.json"),
            "searchComplete": report["searchComplete"],
            "intersectionContext": report["intersectionContext"],
            "baseline": report["baseline"],
            "routesWithDelay": sum(r["intersectionDelayS"] > 0 for r in routes),
            "maximumRouteDelayS": max((r["intersectionDelayS"] for r in routes), default=0),
            "preferenceSearchesComplete": all(
                j["choiceSearchComplete"]
                for p in report["assignment"]["portfolios"]
                for profile in p["profiles"]
                for j in profile["journeys"]
            ),
            "solutions": solutions,
        }
    result = {
        "schemaVersion": "span.delay-comparison.v1",
        "runId": baseline["runId"],
        "scope": {k: baseline[k] for k in ("graph", "sample", "sourceHashes", "standard")},
        "note": "Same native graph, source journeys and weights in every run. "
        "Delay assumptions are unfitted and unmatched crossings are omitted. "
        "Optimisation covers generated routes only; not a citywide ridership forecast.",
        "scenarios": scenarios,
    }
    write_json_atomic(args.directory / "delay-comparison.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
