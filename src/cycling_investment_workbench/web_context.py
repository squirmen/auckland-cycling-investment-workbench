"""Attach reproducible network and route-use context to an Auckland export."""

from __future__ import annotations

import gc
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .candidates import DemandResponseParameters
from .network_context import build_network_context
from .provenance import content_hash, read_json, sha256_file
from .route_context import build_route_context, read_commute_market


def add_web_context(
    payload: dict[str, Any],
    *,
    topology_path: Path,
    candidate_edges: Sequence[Mapping[str, Any]],
    route_dir: Path,
    portfolio_dir: Path,
    parameters: Mapping[str, Any],
) -> None:
    """Enrich in memory; callers export only after every calculation succeeds."""

    maximum_lts = int(parameters["candidates"]["connectivity_max_lts"])
    topology = read_json(topology_path)
    existing, contexts, metadata = build_network_context(
        topology, candidate_edges, maximum_lts=maximum_lts
    )
    del topology
    gc.collect()
    manifest = payload["manifest"]
    choices, candidate_ods, activities = read_commute_market(route_dir, portfolio_dir)
    demand = parameters["demand_response"]
    usage, packages = build_route_context(
        choices,
        candidate_ods,
        activities,
        manifest["portfolios"],
        contexts,
        cost_scale=float(parameters["routing"]["path_size_logit_cost_scale"]),
        response=DemandResponseParameters(
            cost_elasticity=float(demand["cost_elasticity"]["mode"]),
            minimum_probability=float(demand["minimum_probability"]),
        ),
    )
    for feature in payload["layers"]["candidates"]["features"]:
        properties = feature["properties"]
        cid = properties["candidateId"]
        properties["networkContext"] = contexts[cid]
        properties["commuteRouteUse"] = usage[cid]

    source_files = [
        topology_path,
        route_dir / "manifest.json",
        route_dir / "od_ledger.parquet",
        route_dir / "scenario_od_ledger.parquet",
        route_dir / "path_ledger.parquet",
        portfolio_dir / "path_candidate_savings.parquet",
    ]
    metadata["sourceFiles"] = {path.name: sha256_file(path) for path in source_files}
    metadata["sourceFiles"]["candidate_edges_canonical"] = content_hash(candidate_edges)
    metadata["sourceFiles"]["parameters_canonical"] = content_hash(parameters)
    metadata["implementationSha256"] = content_hash(
        {
            filename: sha256_file(Path(__file__).with_name(filename))
            for filename in ("network_context.py", "route_context.py", "web_context.py")
        }
    )
    metadata["packages"] = packages
    metadata["routeUseNote"] = (
        "Usual cycle commuters allocated across retained routes; each traveller is counted "
        "at most once per portfolio or package. Package uptake is evaluated independently "
        "against the scenario baseline and must not be summed across packages."
    )
    manifest["networkContext"] = metadata
    routes = read_json(route_dir / "manifest.json")
    coverage = routes.get("coverage", {})
    internal = coverage.get("by_purpose", {}).get("commute", {})
    scenario = routes.get("scenario_summaries", {})
    manifest["demandContext"] = {
        "routedBaselineUsers": scenario.get("baseline", {}).get("assigned_route_sample_total"),
        "sourceMarginUsers": scenario.get("commute_8pct", {}).get(
            "complete_source_market_observed_cycle"
        ),
        "routedEligible": internal.get("estimated_assigned"),
        "internalEligible": internal.get("unit_specific_denominator"),
        "sourceEligible": coverage.get("commute_complete_source_market_denominator"),
        "internalCoverage": internal.get("estimated_routing_coverage"),
        "sourceCoverage": coverage.get(
            "commute_estimated_routing_coverage_of_complete_source_market"
        ),
        "capitalCostPerKm": float(parameters["candidates"]["screening_cost"]["base_nzd_per_m"])
        * 1_000,
        "note": (
            "Suppressed bicycle cells use the lower bound. Internal OD and full-origin "
            "margins have different coverage; they are not interchangeable totals."
        ),
    }
    manifest["title"] = "SPAN: Spending Priorities for Active Networks"
    manifest["limitations"] = [
        note
        for note in manifest["limitations"]
        if "browser network contains exact candidate edges" not in note.lower()
    ]
    manifest["limitations"].append(metadata["note"])
    network = next(layer for layer in manifest["layers"] if layer["id"] == "network")
    for layer in manifest["layers"]:
        if layer["id"] in {"cells", "candidates"}:
            layer["defaultVisible"] = False
    manifest["layers"] = [layer for layer in manifest["layers"] if layer["id"] != "existing"]
    manifest["layers"].append(
        {
            "id": "existing",
            "label": "Existing low-stress streets and paths",
            "url": "./data/existing.geojson",
            "sha256": "0" * 64,
            "defaultVisible": True,
            "optional": False,
            "licence": network["licence"],
            "sourceIds": network["sourceIds"],
        }
    )
    payload["layers"]["existing"] = existing
