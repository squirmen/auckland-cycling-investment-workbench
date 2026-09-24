#!/usr/bin/env python3
"""Summarise paired area experiments without publishing sampled journey locations."""

import argparse
import json
from pathlib import Path

from cycling_investment_workbench.provenance import sha256_file, write_json_atomic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {p.resolve() for p in args.reports}:
        raise ValueError("summary must not overwrite an input report")
    reports = [(p, json.loads(p.read_text())) for p in args.reports]
    reference = reports[0][1]
    areas = []
    for path, report in reports:
        for key in (
            "runId",
            "radiusM",
            "seed",
            "standard",
            "parameters",
            "implementationHash",
            "experimentScriptHash",
        ):
            if report[key] != reference[key]:
                raise ValueError(f"pilot settings differ: {key}")
        for key in ("topology", "odLedger", "candidateLedger", "scenarioOdLedger"):
            if report["sourceHashes"][key] != reference["sourceHashes"][key]:
                raise ValueError(f"pilot source differs: {key}")
        for key in ("evidenceSha256", "scenario"):
            if report["intersectionContext"][key] != reference["intersectionContext"][key]:
                raise ValueError(f"pilot intersection context differs: {key}")
        gaps = [
            j["allProjectsDiagnostic"]["witnessStressGaps"]
            for j in report["journeys"]
            if j["allProjectsDiagnostic"] and j["allProjectsDiagnostic"]["witnessStressGaps"]
        ]
        areas.append(
            {
                **{
                    key: report[key]
                    for key in (
                        "area",
                        "anchorCandidateId",
                        "centre",
                        "graph",
                        "sample",
                        "cropCoverage",
                        "searchSummary",
                        "elapsedS",
                        "baseline",
                        "searchComplete",
                    )
                },
                "reportSha256": sha256_file(path),
                "solutions": [
                    {
                        key: s[key]
                        for key in (
                            "budget",
                            "method",
                            "selected",
                            "capital_cost",
                            "served_weight",
                            "served_journeys",
                            "optimal_within_columns",
                        )
                    }
                    for s in report["solutions"]
                ],
                "stressGapWitnessCounts": {
                    key: sum(g[key] > 0 for g in gaps)
                    for key in (
                        "untreatedPhysicalEdges",
                        "physicalEdgesStillHighStressAfterTreatment",
                        "turnMovementsStillHighStress",
                    )
                },
            }
        )
    write_json_atomic(
        args.output,
        {
            "status": "bounded_multi_area_screening_not_citywide_validation",
            **{
                key: reference[key]
                for key in (
                    "runId",
                    "radiusM",
                    "seed",
                    "standard",
                    "parameters",
                    "implementationHash",
                    "experimentScriptHash",
                )
            },
            "sourceHashes": {
                key: reference["sourceHashes"][key]
                for key in (
                    "topology",
                    "odLedger",
                    "candidateLedger",
                    "scenarioOdLedger",
                )
            },
            "intersectionEvidenceSha256": reference["intersectionContext"]["evidenceSha256"],
            "areas": areas,
            "limitations": [
                "Same journeys, candidate costs and route columns for methods within each area.",
                "Small bounded samples do not represent all travel in these areas or Auckland.",
                "Some searches hit their caps; optimality is only within generated route columns.",
                "Only previously assigned commute records enter area sampling.",
                "Journeys with an endpoint outside the crop and routes outside it are excluded.",
                "Relaxed-stress witnesses are diagnostic, not acceptable cycling routes.",
                "Witness gap counts count journeys, not unique assets or minimum treatment sets.",
                "No new ridership forecast, measured signal wait or engineering design.",
            ],
        },
    )


if __name__ == "__main__":
    main()
