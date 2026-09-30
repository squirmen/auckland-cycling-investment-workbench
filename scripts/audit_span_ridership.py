#!/usr/bin/env python3
"""Reconcile browser ridership with counterfactual results, without inflating demand.

This is an aggregate accounting audit, not a recalibration or an OD rerun.
Reports source hashes, rank distribution, affected OD counts and calendar units.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from math import isclose
from pathlib import Path

import pyarrow.parquet as pq
from build_span_context import verify_ledgers

from cycling_investment_workbench.candidates import DemandResponseParameters
from cycling_investment_workbench.provenance import sha256_file, write_json_atomic
from cycling_investment_workbench.research.demand_diagnostics import diagnose_candidate
from cycling_investment_workbench.route_context import read_commute_market


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--web", type=Path, default=Path("web/public/data"))
    parser.add_argument("--market-run", type=Path, help="Optional stable copy for OD recomputation")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("documentation/audit/span-ridership-audit.json"),
    )
    args = parser.parse_args()
    run = args.run.resolve()
    manifest = json.loads((run / "manifest.json").read_text())
    web = json.loads((args.web / "manifest.json").read_text())
    if web["runId"] != manifest["run_id"]:
        raise ValueError("browser and source run do not match")
    candidates_file = args.web / "candidates.geojson"
    digest = sha256_file(candidates_file)
    declared = next(layer for layer in web["layers"] if layer["id"] == "candidates")
    if digest != declared["sha256"]:
        raise ValueError("candidate browser layer fails its manifest checksum")
    candidates = {
        f["properties"]["candidateId"]: f["properties"]
        for f in json.loads(candidates_file.read_text())["features"]
    }
    relative = manifest["stages"]["evaluate-portfolios"]["outputs"]["portfolios"]["path"]
    counter_file = (run / relative / "candidate_counterfactuals.parquet").resolve()
    if not counter_file.is_relative_to(run):
        raise ValueError("counterfactual path escapes source run")
    counter = {
        (row["scenario_id"], row["candidate_id"]): row
        for batch in pq.ParquetFile(counter_file).iter_batches()
        for row in batch.to_pylist()
        if row["purpose"] == "commute" and row["objective"] == "activity_addition"
    }
    for (scenario, cid), row in counter.items():
        value = candidates[cid]["metrics"][scenario]["network"]["additionalCycleUsers"]
        if value is None or not isclose(value, row["additional_cycle_users"], abs_tol=1e-8):
            raise ValueError(f"browser/source rider estimate differs: {scenario}:{cid}")
        use = candidates[cid].get("commuteRouteUse", {}).get(scenario)
        if use and not isclose(value, use["additional"], abs_tol=1e-8):
            raise ValueError(f"route-use uptake and ranking differ: {scenario}:{cid}")
    parameters = json.loads((run / "config.snapshot.json").read_text())["parameters"]
    appraisal = parameters["appraisal"]
    calendar = {
        "daysPerYear": appraisal["commute_operating_days_per_year"],
        "legsPerDay": appraisal["commute_legs_per_day"],
    }
    multiplier = calendar["daysPerYear"] * calendar["legsPerDay"]
    scenario = "commute_8pct"
    ranked = sorted(
        candidates.values(),
        key=lambda c: (
            -(c["metrics"][scenario]["network"]["additionalCycleUsers"] or 0),
            c["candidateId"],
        ),
    )
    values = sorted(c["metrics"][scenario]["network"]["additionalCycleUsers"] or 0 for c in ranked)
    top = []
    for c in ranked[:12]:
        cid = c["candidateId"]
        use = c["commuteRouteUse"][scenario]
        top.append(
            {
                "candidateId": cid,
                "name": c["name"],
                "additionalUsualCommuters": use["additional"],
                "routeUsersBefore": use["before"],
                "routeUsersAfter": use["after"],
                "affectedOdRecords": counter[(scenario, cid)]["affected_od_count"],
                "annualAdditionalJourneyEquivalent": use["additional"] * multiplier,
                "annualRouteUserJourneyEquivalent": use["after"] * multiplier,
                "baselineRouteUsers": c["commuteRouteUse"]["baseline"]["before"],
            }
        )
    steps = [s for s in web["portfolios"][scenario]["network"] if s["cumulativeCostNzd"] <= 100e6]
    last = steps[-1]
    report = {
        "status": "aggregate_accounting_passed_not_demand_validation",
        "runId": web["runId"],
        "scenario": scenario,
        "sourceHashes": {
            "browserManifest": sha256_file(args.web / "manifest.json"),
            "browserCandidates": digest,
            "counterfactualLedger": sha256_file(counter_file),
            "configuration": sha256_file(run / "config.snapshot.json"),
        },
        "matchedScenarioCandidateRecords": len(counter),
        "candidateCount": len(ranked),
        "positiveAdditionalEstimates": sum(v > 0 for v in values),
        "distribution": {
            f"p{q}": values[int(q / 100 * (len(values) - 1))] for q in (50, 90, 95, 99, 100)
        },
        "calendarAssumptions": calendar,
        "topStandaloneCandidates": top,
        "programme100m": {
            "links": len(steps),
            "capitalCost": last["cumulativeCostNzd"],
            "additionalUsualCommuters": last["cumulativeObjective"],
            "routeUsersAfter": last["routeUsersAfter"],
            "annualAdditionalJourneyEquivalent": last["cumulativeObjective"] * multiplier,
            "annualRouteUserJourneyEquivalent": last["routeUsersAfter"] * multiplier,
        },
        "demandContext": web.get("demandContext"),
        "limitations": [
            "Agreement with stored source results does not validate the demand model.",
            "Annual/monthly equivalents reuse people with an assumed commuting frequency; "
            "they do not add unique riders, purposes or measured traffic.",
            "Return journeys are assumed; reverse routes are not separately assigned.",
            "Affected OD records are sampled, weighted model records, not observed riders.",
            "Confidentiality and new-route sensitivities are not rerun by this audit. "
            "OD response sensitivities are included only when odDiagnostics is present.",
        ],
    }
    if args.market_run:
        market_root = args.market_run.resolve()
        if sha256_file(market_root / "manifest.json") != sha256_file(run / "manifest.json"):
            raise ValueError("copied run manifest differs from source")
        routes = market_root / manifest["stages"]["assign-routes"]["outputs"]["routes"]["path"]
        portfolios = market_root / relative
        verify_ledgers(
            routes, ("od_ledger.parquet", "scenario_od_ledger.parquet", "path_ledger.parquet")
        )
        verify_ledgers(portfolios, ("path_candidate_savings.parquet",))
        choices, affected, activity = read_commute_market(routes, portfolios)
        response = DemandResponseParameters(
            parameters["demand_response"]["cost_elasticity"]["mode"],
            parameters["demand_response"]["minimum_probability"],
        )
        diagnostics = {
            "runId": web["runId"],
            "scenario": scenario,
            "candidateLayerSha256": digest,
            "status": "exploratory_sensitivity_not_confidence_interval",
            "commuteRecordsPerStratum": parameters["routing"]["sampling"][
                "records_per_stratum_by_purpose"
            ]["commute"],
            "sourceHashes": {
                p.name: sha256_file(p)
                for p in [
                    routes / "od_ledger.parquet",
                    routes / "path_ledger.parquet",
                    routes / "scenario_od_ledger.parquet",
                    portfolios / "path_candidate_savings.parquet",
                ]
            },
            "candidates": [
                diagnose_candidate(
                    row["candidateId"],
                    [
                        replace(choices[od], baseline_activity=activity[scenario][od])
                        for od in sorted(affected[row["candidateId"]])
                    ],
                    cost_scale=parameters["routing"]["path_size_logit_cost_scale"],
                    response=response,
                    expected_additional=row["additionalUsualCommuters"],
                )
                for row in top
            ],
        }
        report["odDiagnostics"] = diagnostics
        write_json_atomic(args.web / "ridership-diagnostics.json", diagnostics)
    write_json_atomic(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "matched": len(counter),
                "top": top[0],
                "programme": report["programme100m"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
