#!/usr/bin/env python3
"""Audit source-cell leverage without changing source runs, browser data or rankings."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from math import isclose
from pathlib import Path

import pyarrow.parquet as pq
from build_span_context import require_local, verify_ledgers

from cycling_investment_workbench.candidates import DemandResponseParameters
from cycling_investment_workbench.provenance import sha256_file, write_json_atomic
from cycling_investment_workbench.research.stability import (
    grouped_contributions,
    source_cell_influence,
)
from cycling_investment_workbench.route_context import read_commute_market


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--web", type=Path, default=Path("web/public/data"))
    parser.add_argument("--scenario", default="commute_8pct")
    parser.add_argument("--budget", type=float, default=100_000_000)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument(
        "--output", type=Path, default=Path("build/stability/source-cell-influence.json")
    )
    args = parser.parse_args()
    root, web, output = args.run.resolve(), args.web.resolve(), args.output.resolve()
    repository = Path(__file__).resolve().parents[1]
    if (
        output.is_relative_to(root)
        or output.is_relative_to(web)
        or output.is_relative_to(repository / "web")
    ):
        raise ValueError("audit output must be outside the source run and browser tree")
    if not 0 <= args.budget < float("inf") or args.top_k < 1:
        raise ValueError("budget must be finite and non-negative; top-k must be positive")
    require_local(root / "manifest.json")
    manifest = json.loads((root / "manifest.json").read_text())
    browser = json.loads((web / "manifest.json").read_text())
    if browser["runId"] != manifest["run_id"]:
        raise ValueError("browser and source run do not match")
    parameters = json.loads((root / "config.snapshot.json").read_text())["parameters"]

    def artifact(stage: str, name: str) -> Path:
        path = (root / manifest["stages"][stage]["outputs"][name]["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("artifact path escapes source run")
        return path

    routes = artifact("assign-routes", "routes")
    portfolios = artifact("evaluate-portfolios", "portfolios")
    candidates = artifact("generate-candidates", "candidates")
    ledger_groups = (
        (routes, ("od_ledger.parquet", "path_ledger.parquet", "scenario_od_ledger.parquet")),
        (portfolios, ("path_candidate_savings.parquet", "candidate_counterfactuals.parquet")),
        (candidates, ("candidate_ledger.parquet",)),
    )
    print("Verifying source ledgers…", flush=True)
    for folder, names in ledger_groups:
        verify_ledgers(folder, names)
    print("Loading retained commute choices…", flush=True)
    base_choices, affected, activity = read_commute_market(routes, portfolios)
    if args.scenario not in activity or set(activity[args.scenario]) != set(base_choices):
        raise ValueError("scenario must cover every retained commute choice")
    choices = {
        od: replace(choice, baseline_activity=activity[args.scenario][od])
        for od, choice in base_choices.items()
    }
    source_cells = {
        row["od_id"]: row["source_cell_id"]
        for batch in pq.ParquetFile(routes / "od_ledger.parquet").iter_batches(
            columns=["od_id", "source_cell_id"]
        )
        for row in batch.to_pylist()
        if row["od_id"] in choices
    }
    costs = {
        row["candidate_id"]: row["capital_cost_base_nzd"]
        for batch in pq.ParquetFile(candidates / "candidate_ledger.parquet").iter_batches(
            columns=["candidate_id", "capital_cost_base_nzd"]
        )
        for row in batch.to_pylist()
    }
    if set(affected) - costs.keys():
        raise ValueError("route savings reference an unknown candidate")
    candidate_ods = {cid: sorted(affected.get(cid, ())) for cid in costs}
    steps = [
        step
        for step in browser["portfolios"][args.scenario]["network"]
        if step["cumulativeCostNzd"] <= args.budget
    ]
    selected = [step["candidateId"] for step in steps]
    response = DemandResponseParameters(
        parameters["demand_response"]["cost_elasticity"]["mode"],
        parameters["demand_response"]["minimum_probability"],
    )
    cost_scale = parameters["routing"]["path_size_logit_cost_scale"]
    print("Recomputing all standalone contributions and the fixed programme…", flush=True)
    standalone, package = grouped_contributions(
        choices,
        source_cells,
        candidate_ods,
        frozenset(selected),
        cost_scale=cost_scale,
        response=response,
    )
    print("Comparing targeted source-cell deletions…", flush=True)
    report = source_cell_influence(
        standalone,
        package,
        selected,
        source_cells=source_cells,
        eligible={od: choice.eligible for od, choice in choices.items()},
        top_k=args.top_k,
    )
    expected = {
        row["candidate_id"]: row["additional_cycle_users"]
        for batch in pq.ParquetFile(portfolios / "candidate_counterfactuals.parquet").iter_batches()
        for row in batch.to_pylist()
        if row["scenario_id"] == args.scenario
        and row["purpose"] == "commute"
        and row["objective"] == "activity_addition"
    }
    if not expected or set(expected) - standalone.keys():
        raise ValueError("source counterfactual universe does not match")
    for cid, values in standalone.items():
        if not isclose(sum(values.values()), expected.get(cid, 0.0), abs_tol=1e-7, rel_tol=1e-8):
            raise ValueError(f"standalone estimate does not reproduce source result: {cid}")
    programme_expected = steps[-1]["cumulativeObjective"] if steps else 0.0
    programme_cost = steps[-1]["cumulativeCostNzd"] if steps else 0.0
    if not isclose(
        report["fixedProgramme"]["additionalUsualCommuters"],
        programme_expected,
        abs_tol=1e-6,
        rel_tol=1e-8,
    ) or not isclose(sum(costs[cid] for cid in selected), programme_cost, abs_tol=0.01):
        raise ValueError("joint programme estimate or cost does not reproduce browser result")
    files = [root / "manifest.json", root / "config.snapshot.json", web / "manifest.json"]
    files.extend(folder / name for folder, names in ledger_groups for name in names)
    report.update(
        {
            "runId": manifest["run_id"],
            "scenario": args.scenario,
            "budgetNzd": args.budget,
            "programmeCostNzd": programme_cost,
            "baselineReconciliation": {
                "status": "passed",
                "sourceStandaloneRecords": len(expected),
                "candidateUniverseIncludingUnaffected": len(costs),
                "publishedProgrammeJointGain": programme_expected,
            },
            "parameters": {
                "costScale": cost_scale,
                "responseElasticity": response.cost_elasticity,
                "minimumProbability": response.minimum_probability,
                "sourceSampling": parameters["routing"]["sampling"],
            },
            "sourceHashes": {
                (
                    "browserManifest"
                    if path == web / "manifest.json"
                    else "sourceRunManifest"
                    if path == root / "manifest.json"
                    else path.name
                ): sha256_file(path)
                for path in files
            },
            "implementationHashes": {
                "auditScript": sha256_file(Path(__file__)),
                "stability": sha256_file(
                    repository / "src/cycling_investment_workbench/research/stability.py"
                ),
                "portfolioAnalysis": sha256_file(
                    repository / "src/cycling_investment_workbench/portfolio_analysis.py"
                ),
            },
        }
    )
    write_json_atomic(output, report)
    print(
        json.dumps(
            {
                "output": str(output),
                "candidateCount": report["candidateCount"],
                "cases": len(report["cases"]),
                "fixedProgramme": report["fixedProgramme"],
                "minimumTopOverlapShare": min(
                    (case["standaloneTopOverlapShare"] for case in report["cases"]), default=1.0
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
