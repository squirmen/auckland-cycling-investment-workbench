#!/usr/bin/env python3
"""Reproducible local access-first pilot; never rewrites the published model.

Samples existing commute OD records in a declared circle around a chosen project.
Searches every retained directed street in that circle; all complete candidate
projects in the circle are eligible. Crop/sampling/label limits are disclosed.
"""

from __future__ import annotations

import argparse
import gc
import json
import resource
import sys
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from math import exp, hypot, isfinite
from pathlib import Path
from time import perf_counter

import pyarrow.parquet as pq
from build_span_context import require_local, verify_ledgers
from pyproj import Transformer
from shapely import from_wkb

from cycling_investment_workbench.effective_network import route_delay, turns_for_graph
from cycling_investment_workbench.provenance import content_hash, sha256_file, write_json_atomic
from cycling_investment_workbench.research.active_search import (
    Arc,
    InvestmentGraph,
    PlanningStandard,
)
from cycling_investment_workbench.research.behaviour import (
    ILLUSTRATIVE_PREFERENCES,
    assign_fixed_demand,
    preference_network,
)
from cycling_investment_workbench.research.connector_portfolios import compare_budgeted_connectors
from cycling_investment_workbench.research.gaps import (
    all_projects_check,
    candidate_coverage_reasons,
    diagnose_route_gap,
    with_short_connector_diagnostic,
)
from cycling_investment_workbench.research.investment import (
    choose_investments,
    greedy_investments,
    served,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/pilots/access-experiment.json"))
    parser.add_argument("--anchor-candidate", default="candidate-93dcb500489db8cd")
    parser.add_argument("--area-label", help="Human-readable area label; defaults to anchor roads")
    parser.add_argument("--radius-m", type=float, default=4000)
    parser.add_argument("--sample-size", type=int, default=169)
    parser.add_argument("--budget-m", type=float, default=20)
    parser.add_argument("--max-labels", type=int, default=15000)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--intersections", type=Path, help="SPAN native intersection audit")
    parser.add_argument("--delay-scenario", choices=("low", "default", "high"), default="default")
    parser.add_argument(
        "--test-short-connectors",
        action="store_true",
        help="Diagnostic only: test all projects plus complete short excluded chains; "
        "does not add them to the budgeted portfolio",
    )
    parser.add_argument(
        "--budget-short-connectors",
        action="store_true",
        help="Also compare budgeted hypothetical connectors on the same sampled journeys; "
        "kept separate from the original portfolio and browser data",
    )
    args = parser.parse_args()
    if (
        not isfinite(args.radius_m)
        or args.radius_m <= 0
        or not isfinite(args.budget_m)
        or args.budget_m <= 0
        or args.sample_size < 1
        or args.max_labels < 1
    ):
        raise ValueError("pilot bounds must be positive")
    root = args.run.resolve()
    if args.output.resolve().is_relative_to(root):
        raise ValueError("research output must be outside the immutable source run")
    manifest = json.loads((root / "manifest.json").read_text())

    def artifact(stage, name):
        path = (root / manifest["stages"][stage]["outputs"][name]["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("artifact escapes run")
        return path

    candidate_dir = artifact("generate-candidates", "candidates")
    route_dir = artifact("assign-routes", "routes")
    topology_file = artifact("build-topology", "topology") / "topology.json"
    for path in [
        topology_file,
        candidate_dir / "candidate_ledger.parquet",
        route_dir / "od_ledger.parquet",
    ]:
        require_local(path)
    verify_ledgers(
        candidate_dir, ("candidate_ledger.parquet", "candidate_exclusion_ledger.parquet")
    )
    verify_ledgers(route_dir, ("od_ledger.parquet", "scenario_od_ledger.parquet"))
    candidates = pq.ParquetFile(candidate_dir / "candidate_ledger.parquet").read().to_pylist()
    exclusions = (
        pq.ParquetFile(candidate_dir / "candidate_exclusion_ledger.parquet").read().to_pylist()
    )
    anchor = next((c for c in candidates if c["candidate_id"] == args.anchor_candidate), None)
    if anchor is None:
        raise ValueError("anchor candidate does not exist in the source run")
    area_label = (
        args.area_label or " / ".join(anchor["primary_road_names"]) or args.anchor_candidate
    )
    centre = from_wkb(anchor["geometry_wkb"]).centroid
    started = perf_counter()
    print("Loading source topology and defining the declared pilot area…", flush=True)
    topology = json.loads(topology_file.read_text())
    nodes = {
        n["id"]: n
        for n in topology["nodes"]
        if hypot(n["x"] - centre.x, n["y"] - centre.y) <= args.radius_m
    }
    edges = [e for e in topology["edges"] if e["u"] in nodes and e["v"] in nodes]
    edge_ids = {e["id"] for e in edges}
    untreated_reasons = candidate_coverage_reasons(edge_ids, candidates, exclusions)
    candidate_coverage = {
        "untreatedHighStressEdgesByReason": dict(
            sorted(
                Counter(
                    untreated_reasons[e["id"]]
                    for e in edges
                    if e["lts"] > 2 and e["id"] in untreated_reasons
                ).items()
            )
        ),
        "note": "Counts of distinct physical edges in the crop, not journeys or buildable "
        "projects. Source exclusions are read from the checked original ledger. "
        "Unlisted edges are not assigned an inferred exclusion reason.",
    }
    candidates = [c for c in candidates if set(c["ordered_edge_ids"]) <= edge_ids]
    by_edge = {}
    for candidate in candidates:
        for edge in candidate["ordered_edge_ids"]:
            if edge in by_edge:
                raise ValueError("pilot requires disjoint physical project assets")
            by_edge[edge] = candidate["candidate_id"]
    costs = {c["candidate_id"]: c["capital_cost_base_nzd"] for c in candidates}
    arcs = []
    for edge in edges:
        for reverse, permitted in [
            (False, edge["direction"] in {"both", "forward"}),
            (True, edge["direction"] in {"both", "reverse"}),
        ]:
            if not permitted:
                continue
            grade = float(edge["gradient"]) * (-1 if reverse else 1)
            # Transparent engineering time sensitivity, not a fitted speed model.
            speed_mps = 15 / 3.6 * exp(-3 * max(grade, 0))
            arcs.append(
                Arc(
                    edge["id"] + (":r" if reverse else ":f"),
                    edge["id"],
                    edge["v"] if reverse else edge["u"],
                    edge["u"] if reverse else edge["v"],
                    edge["length_m"],
                    edge["length_m"] / speed_mps,
                    int(edge["lts"]),
                    by_edge.get(edge["id"]),
                    max(1, int(edge["intersection_stress"])),
                    edge["facility"] in {"protected_lane", "shared_path"},
                )
            )
    intersection_context = None
    turns = {}
    if args.intersections:
        evidence = json.loads(args.intersections.read_text())
        if evidence.get("runId") != manifest["run_id"]:
            raise ValueError("intersection evidence belongs to another SPAN run")
        turns = turns_for_graph(
            evidence,
            arcs,
            topology_sha256=sha256_file(topology_file),
            scenario=args.delay_scenario,
        )
        delayed_incoming = {pair[0] for pair in turns}
        intersection_context = {
            "scenario": args.delay_scenario,
            "matchedSitesCitywide": evidence["metadata"]["matchedSites"],
            "sitesInCrop": len({a.v for a in arcs if a.id in delayed_incoming}),
            "directedMovementsInCrop": len(turns),
            "evidenceSha256": sha256_file(args.intersections),
            "note": evidence["metadata"]["note"],
        }
    graph = InvestmentGraph(arcs, costs, turns)
    connector_graph = None
    connector_context = None
    if args.test_short_connectors or args.budget_short_connectors:
        candidate_manifest = json.loads((candidate_dir / "manifest.json").read_text())
        cost_per_m = candidate_manifest["screening_cost"]["base_nzd_per_m"]
        connector_graph = with_short_connector_diagnostic(graph, exclusions, cost_per_m=cost_per_m)
        connector_context = {
            "additionalProjects": len(connector_graph.projects) - len(graph.projects),
            "additionalScreeningCostNzd": sum(connector_graph.projects.values())
            - sum(graph.projects.values()),
            "screeningCostPerM": cost_per_m,
            "sourceMinimumLengthM": candidate_manifest["method"]["minimum_length_m"],
            "sourceCandidateManifestSha256": sha256_file(candidate_dir / "manifest.json"),
            "note": "All projects plus complete in-crop chains excluded for minimum length "
            "are funded hypothetically. Original stress, time, detour, turn and crop rules "
            "remain. This tests coverage, not affordability, buildability or optimal investment. "
            "The budgeted portfolio and its assignments are unchanged.",
        }
    facility_by_edge = {e["id"]: e["facility"] for e in edges}
    facility_aliases = {
        "none": "none",
        "mixed_traffic": "none",
        "protected_lane": "protected_lane",
        "shared_path": "shared_path",
        "painted_lane": "painted_lane",
        "quiet_street": "quiet_street",
    }
    unknown_facilities = set(facility_by_edge.values()) - facility_aliases.keys()
    if unknown_facilities:
        raise ValueError(f"Unmapped source facilities: {sorted(unknown_facilities)}")
    facilities = {a.id: facility_aliases[facility_by_edge[a.edge_id]] for a in arcs}
    del topology
    gc.collect()
    ods = (
        pq.ParquetFile(route_dir / "od_ledger.parquet")
        .read(
            columns=[
                "od_id",
                "purpose",
                "status",
                "route_sample_selected",
                "origin_node_id",
                "destination_node_id",
                "weighted_eligible",
                "weighted_observed_cycle",
            ],
        )
        .to_pylist()
    )
    assigned_commutes = [
        od for od in ods if od["purpose"] == "commute" and od["status"] == "assigned"
    ]
    coverage = {
        "assignedCommuteRecordsCitywide": len(assigned_commutes),
        "sourceSelectedUnassignedCommuteRecords": sum(
            od["purpose"] == "commute"
            and od["route_sample_selected"]
            and od["status"] == "unassigned"
            for od in ods
        ),
        "bothEndpointsInCrop": sum(
            od["origin_node_id"] in graph.nodes and od["destination_node_id"] in graph.nodes
            for od in assigned_commutes
        ),
        "oneEndpointOutsideCrop": sum(
            (od["origin_node_id"] in graph.nodes) != (od["destination_node_id"] in graph.nodes)
            for od in assigned_commutes
        ),
        "bothEndpointsOutsideCrop": sum(
            od["origin_node_id"] not in graph.nodes and od["destination_node_id"] not in graph.nodes
            for od in assigned_commutes
        ),
        "note": "Endpoint coverage among previously assigned commute records. "
        "An in-crop disconnected search is not proof of citywide disconnection.",
    }
    eligible_ods = [
        od
        for od in ods
        if od["purpose"] == "commute"
        and od["status"] == "assigned"
        and od["origin_node_id"] in graph.nodes
        and od["destination_node_id"] in graph.nodes
        and od["origin_node_id"] != od["destination_node_id"]
        and od["weighted_eligible"] > 0
    ]
    eligible_ods.sort(key=lambda od: sha256(f"{args.seed}:{od['od_id']}".encode()).hexdigest())
    sample = eligible_ods[: args.sample_size]
    if not sample:
        raise ValueError("no source commute ODs fit the declared pilot area")
    standard = PlanningStandard(2, 1.5, 1800)
    budget = args.budget_m * 1e6
    searches, routes, weights = {}, {}, {}
    full_treatment_checks = {}
    for i, od in enumerate(sample):
        label = f"Journey {i + 1}"
        result = graph.search(
            od["origin_node_id"],
            od["destination_node_id"],
            budget=budget,
            standard=standard,
            max_labels=args.max_labels,
        )
        searches[label], routes[label], weights[label] = (
            result,
            result.routes,
            od["weighted_eligible"],
        )
        if not result.routes:
            full_treatment_checks[label] = diagnose_route_gap(
                graph,
                od["origin_node_id"],
                od["destination_node_id"],
                standard=standard,
                max_labels=args.max_labels,
                untreated_reasons=untreated_reasons,
            )
            if connector_graph is not None and not full_treatment_checks[label]["routeFound"]:
                full_treatment_checks[label]["shortConnectorCheck"] = all_projects_check(
                    connector_graph,
                    od["origin_node_id"],
                    od["destination_node_id"],
                    standard=standard,
                    max_labels=args.max_labels,
                )
        print(
            f"{label}: {len(result.routes)} routes; "
            f"{result.labels_expanded} expansions; {result.stop_reason}",
            flush=True,
        )
    print("Solving shared project budgets and verifying complete route witnesses…", flush=True)
    budgets = sorted({0.0, budget / 4, budget / 2, budget})
    solutions = []
    for value in budgets:
        solutions.extend(
            {**asdict(result), "selected": sorted(result.selected), "budget": value}
            for result in [
                greedy_investments(costs, routes, weights, budget=value),
                greedy_investments(costs, routes, weights, budget=value, packages=True),
                choose_investments(costs, routes, weights, budget=value),
            ]
        )
    final = next(
        s for s in solutions if s["budget"] == budget and s["method"] == "route_packages_milp"
    )
    selected = frozenset(final["selected"])
    budgeted_connectors = None
    if args.budget_short_connectors:
        print("Comparing budgeted short connectors on the same journeys and standards…", flush=True)
        budgeted_connectors = compare_budgeted_connectors(
            connector_graph,
            routes,
            {
                f"Journey {i + 1}": (od["origin_node_id"], od["destination_node_id"])
                for i, od in enumerate(sample)
            },
            weights,
            budget=budget,
            standard=standard,
            max_labels=args.max_labels,
        )
    transform = Transformer.from_crs("EPSG:2193", "EPSG:4326", always_xy=True)
    edge_lookup = {e["id"]: e for e in edges}

    def coordinates(edge, reverse=False):
        coords = edge.get("geometry") or [
            [nodes[edge["u"]]["x"], nodes[edge["u"]]["y"]],
            [nodes[edge["v"]]["x"], nodes[edge["v"]]["y"]],
        ]
        return [
            [round(x, 6), round(y, 6)]
            for x, y in (
                transform.transform(*point) for point in (reversed(coords) if reverse else coords)
            )
        ]

    def exported_route(option, selected_projects):
        return {
            "projectIds": sorted(
                {graph.arcs[a].project_id for a in option.arc_ids} & set(selected_projects)
            ),
            "distanceM": option.distance_m,
            "timeS": option.time_s,
            "intersectionDelayS": route_delay(option.arc_ids, graph.turns),
            "generalizedCostS": option.generalized_cost_s,
            "capitalCost": sum(
                costs[p]
                for p in {graph.arcs[a].project_id for a in option.arc_ids} & set(selected_projects)
            ),
            "existingCyclewayM": option.existing_cycleway_m,
            "segments": [
                {
                    "edgeId": graph.arcs[a].edge_id,
                    "projectId": graph.arcs[a].project_id
                    if graph.arcs[a].project_id in selected_projects
                    else None,
                    "existingCycleway": graph.arcs[a].existing_cycleway,
                    "coordinates": coordinates(
                        edge_lookup[graph.arcs[a].edge_id], a.endswith(":r")
                    ),
                }
                for a in option.arc_ids
            ],
        }

    scenario_rows = (
        pq.ParquetFile(route_dir / "scenario_od_ledger.parquet")
        .read(columns=["od_id", "scenario_id", "scenario_cycle"])
        .to_pylist()
    )
    cycle_demand = {
        r["od_id"]: r["scenario_cycle"] for r in scenario_rows if r["scenario_id"] == "commute_8pct"
    }
    assignment_portfolios = []
    for s in solutions:
        s["assignmentKey"] = content_hash(s["selected"])
    for key, selection in sorted({s["assignmentKey"]: s["selected"] for s in solutions}.items()):
        print(
            f"Fresh preference routing and conserved assignment: {len(selection)} projects…",
            flush=True,
        )
        networks = {
            p.id: preference_network(graph, facilities, p, frozenset(selection))
            for p in ILLUSTRATIVE_PREFERENCES
        }
        profile_results = {
            p.id: {"profileId": p.id, "assigned": 0.0, "unassigned": 0.0, "journeys": []}
            for p in ILLUSTRATIVE_PREFERENCES
        }
        for i, od in enumerate(sample):
            results = {
                pid: network.search(
                    od["origin_node_id"],
                    od["destination_node_id"],
                    budget=0,
                    standard=standard,
                    max_labels=args.max_labels,
                    first_only=True,
                )
                for pid, network in networks.items()
            }
            # Each optimum supplies a plausible alternative; the union is explicitly limited.
            options = {r.routes[0].arc_ids: r.routes[0] for r in results.values() if r.routes}
            for pid, network in networks.items():
                allocation = assign_fixed_demand(
                    network, list(options.values()), cycle_demand[od["od_id"]]
                )
                out = profile_results[pid]
                out["assigned"] += allocation["assigned"]
                out["unassigned"] += allocation["unassigned"]
                out["journeys"].append(
                    {
                        "name": f"Journey {i + 1}",
                        "demand": allocation["demand"],
                        "assigned": allocation["assigned"],
                        "unassigned": allocation["unassigned"],
                        "searchOptimal": results[pid].stop_reason != "label_limit",
                        "choiceSearchComplete": all(
                            r.stop_reason != "label_limit" for r in results.values()
                        ),
                        "stopReason": results[pid].stop_reason,
                        "labelsExpanded": results[pid].labels_expanded,
                        "searchElapsedS": results[pid].elapsed_s,
                        "alternatives": [
                            {
                                **exported_route(options[tuple(r["arcIds"])], selection),
                                "generalizedCostS": r["costS"],
                                "probability": r["probability"],
                                "flow": r["flow"],
                                "pathSize": r["pathSize"],
                            }
                            for r in allocation["routes"]
                        ],
                    }
                )
        assignment_portfolios.append(
            {"key": key, "selected": selection, "profiles": list(profile_results.values())}
        )
        del networks

    journeys = []
    for i, od in enumerate(sample):
        name = f"Journey {i + 1}"
        result = searches[name]
        feasible = [r for r in result.routes if r.project_ids <= selected]
        if feasible:
            check = graph.search(
                od["origin_node_id"],
                od["destination_node_id"],
                budget=budget,
                selected=selected,
                allow_new_projects=False,
                standard=standard,
                max_labels=args.max_labels,
                first_only=True,
            )
            if not check.routes:
                raise ValueError("portfolio route failed independent rerouting")
        alternatives = [
            {
                "projectIds": sorted(option.project_ids),
                "distanceM": option.distance_m,
                "timeS": option.time_s,
                "intersectionDelayS": route_delay(option.arc_ids, graph.turns),
                "capitalCost": option.capital_cost,
                "existingCyclewayM": option.existing_cycleway_m,
                "segments": [
                    {
                        "edgeId": graph.arcs[a].edge_id,
                        "projectId": graph.arcs[a].project_id if graph.arcs[a].stress > 2 else None,
                        "existingCycleway": graph.arcs[a].existing_cycleway,
                        "coordinates": coordinates(
                            edge_lookup[graph.arcs[a].edge_id], a.endswith(":r")
                        ),
                    }
                    for a in option.arc_ids
                ],
            }
            for option in result.routes
        ]
        journeys.append(
            {
                "name": name,
                "weight": weights[name],
                "baselineFeasible": any(not r.project_ids for r in result.routes),
                "shortestLegalDistanceM": result.shortest_legal_distance_m,
                "searchComplete": result.complete,
                "stopReason": result.stop_reason,
                "labelsExpanded": result.labels_expanded,
                "elapsedS": result.elapsed_s,
                "allProjectsDiagnostic": full_treatment_checks.get(name),
                "alternatives": alternatives,
            }
        )
    used = set().union(*(r.project_ids for values in routes.values() for r in values))
    projects = [
        {
            "id": c["candidate_id"],
            "name": " / ".join(c["primary_road_names"]) or "Unnamed street",
            "cost": costs[c["candidate_id"]],
            "lengthM": c["length_m"],
            "treatment": "protected_lane",
            "costStatus": "provisional",
            "coordinates": [
                [round(x, 6), round(y, 6)]
                for x, y in (
                    transform.transform(*point) for point in from_wkb(c["geometry_wkb"]).coords
                )
            ],
        }
        for c in candidates
        if c["candidate_id"] in used
    ]
    elapsed = perf_counter() - started
    implementation = Path("src/cycling_investment_workbench/research")
    report = {
        "schemaVersion": "1.0.0",
        "status": "local_research_pilot",
        "runId": manifest["run_id"],
        "title": "Complete journeys before extra cycling",
        "area": area_label,
        "anchorCandidateId": args.anchor_candidate,
        "centre": list(transform.transform(centre.x, centre.y)),
        "radiusM": args.radius_m,
        "seed": args.seed,
        "standard": asdict(standard),
        "budget": budget,
        "graph": {"nodes": len(graph.nodes), "directedArcs": len(arcs), "projects": len(costs)},
        "intersectionContext": intersection_context,
        "sample": {
            "selected": len(sample),
            "eligibleWithinArea": len(eligible_ods),
            "weightedDemand": sum(weights.values()),
            "citywideRepresentative": False,
        },
        "cropCoverage": coverage,
        "candidateCoverage": candidate_coverage,
        "shortConnectorDiagnostic": connector_context,
        "budgetedConnectorComparison": budgeted_connectors,
        "searchSummary": {
            "stopReasons": dict(sorted(Counter(r.stop_reason for r in searches.values()).items())),
            "labelsExpanded": sum(r.labels_expanded for r in searches.values()),
            "searchElapsedS": sum(r.elapsed_s for r in searches.values()),
            "allProjectsDiagnostics": {
                "testedNoRouteJourneys": len(full_treatment_checks),
                "routeFound": sum(r["routeFound"] for r in full_treatment_checks.values()),
                "conclusiveNoRoute": sum(
                    r["conclusiveNoRoute"] for r in full_treatment_checks.values()
                ),
                "labelLimit": sum(
                    r["stopReason"] == "label_limit" for r in full_treatment_checks.values()
                ),
                "stressRelaxedWitnessFound": sum(
                    r["stressRelaxedWitnessFound"] is True for r in full_treatment_checks.values()
                ),
                "stressRelaxedLabelLimit": sum(
                    r["stressRelaxedStopReason"] == "label_limit"
                    for r in full_treatment_checks.values()
                ),
                "note": "Diagnostic only: every in-crop modelled project funded, "
                "with unchanged stress/time/detour standards and crossing assumptions. "
                "Not a proposed or affordable programme.",
            },
            "peakProcessRssMiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (1024**2 if sys.platform == "darwin" else 1024),
        },
        "sourceHashes": {
            "topology": sha256_file(topology_file),
            "odLedger": sha256_file(route_dir / "od_ledger.parquet"),
            "candidateLedger": sha256_file(candidate_dir / "candidate_ledger.parquet"),
            "candidateExclusionLedger": sha256_file(
                candidate_dir / "candidate_exclusion_ledger.parquet"
            ),
            "scenarioOdLedger": sha256_file(route_dir / "scenario_od_ledger.parquet"),
            "origins": content_hash(sorted(od["origin_node_id"] for od in sample)),
            "originWeights": content_hash(
                sorted((od["origin_node_id"], od["weighted_eligible"]) for od in sample)
            ),
        },
        "implementationHash": content_hash(
            {p.name: sha256_file(p) for p in sorted(implementation.glob("*.py"))}
        ),
        "experimentScriptHash": sha256_file(Path(__file__)),
        "parameters": {
            "sampleSizeRequested": args.sample_size,
            "maxLabelsPerSearch": args.max_labels,
            "testShortConnectors": args.test_short_connectors,
            "budgetShortConnectors": args.budget_short_connectors,
            "protectedCostSource": "candidate_ledger.capital_cost_base_nzd",
            "flatSpeedKph": 15,
            "uphillExponent": 3,
        },
        "searchComplete": all(r.complete for r in searches.values()),
        "elapsedS": elapsed,
        "baseline": {
            "weight": served(frozenset(), routes, weights)[0],
            "journeys": served(frozenset(), routes, weights)[1],
        },
        "solutions": solutions,
        "journeys": journeys,
        "projects": projects,
        "assignment": {
            "status": "fixed_demand_illustrative_preferences",
            "scenarioId": "commute_8pct",
            "demandUnit": "usual_cycle_commuters",
            "totalDemand": sum(cycle_demand[od["od_id"]] for od in sample),
            "profileSharesEstimated": False,
            "profiles": [asdict(p) for p in ILLUSTRATIVE_PREFERENCES],
            "choiceSet": "Union of one minimum-cost route per preference; not exhaustive.",
            "costScalePerS": 0.005,
            "pathSizeCoefficient": 1.0,
            "portfolios": assignment_portfolios,
            "additionalCyclists": None,
        },
        "ridershipForecast": None,
        "crancStatus": "integration_reserved_not_computed",
        "limitations": [
            "A local graph crop and deterministic OD sample; "
            "not an Auckland forecast or recommendation.",
            "Weights retain source OD expansion factors "
            "without an additional pilot sampling expansion.",
            "Complete means LTS ≤ 2, distance ≤ 1.5 times the shortest legal route "
            "and time ≤ 30 minutes.",
            "Time assumes 15 km/h on flat ground with a declared uphill penalty; "
            "it is not calibrated.",
            "Street treatment retains recorded intersection stress. "
            + (
                "Matched SPAN junctions include illustrative "
                + args.delay_scenario
                + " crossing-delay assumptions. Signal phases and legal-turn evidence "
                "remain unavailable."
                if args.intersections
                else "Movement-specific turning evidence is unavailable in this pilot."
            ),
            "Only complete source candidate projects in the crop are eligible; "
            "prices are provisional protected-lane estimates.",
            "Search caps can omit routes. Solver optimality applies to generated routes, "
            "not unsearched possibilities.",
            "No induced-ridership, crash-reduction or benefit-cost forecast "
            "is produced by this experiment.",
            "Preference cases are unfitted sensitivities, not estimated rider types or CRANC "
            "profiles. Each independently assigns the same fixed 8% scenario demand. "
            "Do not add these cases together.",
            "Assignment uses the union of the three preference optima with a path-overlap "
            "correction. It is conditional on this limited choice set. No-route demand is "
            "reported as unassigned rather than removed or labelled new cyclists.",
        ],
    }
    write_json_atomic(args.output, report)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sample": report["sample"],
                "searchComplete": report["searchComplete"],
                "final": final,
                "elapsedS": elapsed,
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
