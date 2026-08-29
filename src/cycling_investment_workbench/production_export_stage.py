"""Adapters from versioned Auckland ledgers to the public browser contract."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pyproj import Transformer
from shapely import from_wkb
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import substring, transform

from . import __version__
from .exports import PURPOSE_IDS, SCENARIO_IDS, export_web_payload, load_web_payload
from .pipeline import ProductionBlocker, StageContext, StageResult
from .provenance import content_hash, read_json, write_json_atomic

_COMMUTE_PURPOSES = frozenset({"network", "appraisal"})
_ACCESS_PURPOSES = frozenset({"school", "everyday", "transit"})
_INCLUDED_PUBLIC_SOURCE_IDS = frozenset(
    {
        "stats_nz_journey_to_work",
        "stats_nz_sa2_transport_margins",
        "stats_nz_sa1_geography",
        "stats_nz_sa2_geography",
        "stats_nz_auckland_boundary",
        "educationcounts_schools_auckland",
        "stats_nz_business_demography_sa2_2024",
        "geofabrik_new_zealand_osm",
        "auckland_transport_cycle_network",
        "linz_auckland_dem",
        "linz_auckland_dem_manifest",
    }
)


def _artifact_file(path: Path, filename: str) -> Path:
    return path / filename if path.is_dir() else path.parent / filename


def _table_rows(
    path: Path, filename: str, *, columns: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    return pq.read_table(_artifact_file(path, filename), columns=columns).to_pylist()


def _feature_collection(features: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [dict(feature) for feature in features]}


def _run_metadata(context: StageContext) -> tuple[str, str]:
    manifest_path = context.run_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        if isinstance(manifest, Mapping):
            config = manifest.get("config")
            created = manifest.get("created_at")
            if isinstance(config, Mapping) and isinstance(config.get("sha256"), str):
                generated = str(created) if isinstance(created, str) else "1970-01-01T00:00:00Z"
                return str(config["sha256"]), generated
    return content_hash(context.config.to_dict()), "1970-01-01T00:00:00Z"


def _source_rights(context: StageContext) -> tuple[list[dict[str, str]], list[str]]:
    decisions: list[dict[str, str]] = []
    attributions: list[str] = []
    for source in context.config.sources:
        include = source.id in _INCLUDED_PUBLIC_SOURCE_IDS and source.redistribution == "permitted"
        decisions.append(
            {
                "sourceId": source.id,
                "redistribution": source.redistribution,
                "decision": "include" if include else "exclude",
                "reason": (
                    "used by a derived public layer under registered reuse terms"
                    if include
                    else (
                        "not exposed because it is unused or its redistribution terms are "
                        "unresolved"
                    )
                ),
            }
        )
        if include and source.attribution not in attributions:
            attributions.append(source.attribution)
    return decisions, attributions


def _coverage_by_purpose(route_manifest: Mapping[str, Any]) -> dict[str, float]:
    coverage = route_manifest.get("coverage")
    by_purpose = coverage.get("by_purpose") if isinstance(coverage, Mapping) else None
    result: dict[str, float] = {}
    if isinstance(by_purpose, Mapping):
        for purpose in ("commute", "school", "everyday", "transit"):
            item = by_purpose.get(purpose)
            if isinstance(item, Mapping):
                result[purpose] = max(
                    0.0, min(1.0, float(item.get("estimated_routing_coverage", 0.0)))
                )
    if "commute" not in result and isinstance(coverage, Mapping):
        result["commute"] = max(
            0.0,
            min(
                1.0,
                float(
                    coverage.get(
                        "commute_estimated_routing_coverage_of_complete_source_market",
                        coverage.get("estimated_routing_coverage_of_complete_source_market", 0.0),
                    )
                ),
            ),
        )
    return {
        purpose: result.get(purpose, 0.0)
        for purpose in ("commute", "school", "everyday", "transit")
    }


def _activity_totals(route_manifest: Mapping[str, Any]) -> dict[tuple[str, str], float]:
    coverage = route_manifest.get("coverage")
    by_purpose = coverage.get("by_purpose") if isinstance(coverage, Mapping) else None
    denominators: dict[str, float] = {}
    if isinstance(by_purpose, Mapping):
        for purpose in ("school", "everyday", "transit"):
            value = by_purpose.get(purpose)
            if isinstance(value, Mapping):
                denominators[purpose] = float(value.get("unit_specific_denominator", 0.0))
    scenarios = route_manifest.get("scenario_summaries")
    result: dict[tuple[str, str], float] = {}
    for scenario in SCENARIO_IDS:
        scenario_summary = scenarios.get(scenario) if isinstance(scenarios, Mapping) else None
        commute = (
            float(scenario_summary.get("assigned_route_sample_total", 0.0))
            if isinstance(scenario_summary, Mapping)
            else 0.0
        )
        result[(scenario, "network")] = commute
        result[(scenario, "appraisal")] = commute
        result[(scenario, "equity")] = 0.0
        for purpose in _ACCESS_PURPOSES:
            result[(scenario, purpose)] = denominators.get(purpose, 0.0)
    return result


def _metric_warning(*values: str) -> list[str]:
    return [value for value in values if value]


def _unavailable_metric(
    *, capital_cost: float, lifecycle_cost: float, route_coverage: float, warning: str
) -> dict[str, Any]:
    return {
        "available": False,
        "capitalCostNzd": capital_cost,
        "lifecycleCostNzd": lifecycle_cost,
        "objectiveValue": None,
        "objectiveUnit": "not available",
        "additionalCycleUsers": None,
        "annualBikeKmDelta": None,
        "odLowStressShareDelta": None,
        "bcrP5": None,
        "bcrP50": None,
        "bcrP95": None,
        "routeCoverage": route_coverage,
        "meanRank": None,
        "topKProbability": None,
        "frontierProbability": None,
        "warnings": [warning],
    }


def _candidate_metrics(
    candidate_id: str,
    capital_cost: float,
    *,
    counterfactuals: Mapping[tuple[str, str, str], Mapping[str, Any]],
    evidence: Mapping[str, Mapping[str, Any]],
    lifecycle_costs: Mapping[str, float],
    coverage: Mapping[str, float],
    evidence_scenario: str,
    transit_public: bool,
    appraisal_public: bool,
) -> dict[str, dict[str, dict[str, Any]]]:
    lifecycle_cost = lifecycle_costs.get(candidate_id, capital_cost)
    sampled = evidence.get(candidate_id)

    def evidence_fields(scenario: str) -> dict[str, Any]:
        if sampled is None or scenario != evidence_scenario:
            return {
                "bcrP5": None,
                "bcrP50": None,
                "bcrP95": None,
                "meanRank": None,
                "topKProbability": None,
                "frontierProbability": None,
            }
        return {
            "bcrP5": float(sampled["uncertainty_bcr_p05"]) if appraisal_public else None,
            "bcrP50": float(sampled["uncertainty_bcr_p50"]) if appraisal_public else None,
            "bcrP95": float(sampled["uncertainty_bcr_p95"]) if appraisal_public else None,
            "meanRank": float(sampled["mean_rank"]),
            "topKProbability": float(sampled["top_k_probability"]),
            "frontierProbability": float(sampled["frontier_probability"]),
        }

    output: dict[str, dict[str, dict[str, Any]]] = {}
    for scenario in SCENARIO_IDS:
        by_purpose: dict[str, dict[str, Any]] = {}
        commute = counterfactuals.get((scenario, "commute", candidate_id))
        if commute is None:
            by_purpose["network"] = _unavailable_metric(
                capital_cost=capital_cost,
                lifecycle_cost=lifecycle_cost,
                route_coverage=coverage["commute"],
                warning="No routed commute market intersects this candidate.",
            )
        else:
            by_purpose["network"] = {
                "available": True,
                "capitalCostNzd": capital_cost,
                "lifecycleCostNzd": lifecycle_cost,
                "objectiveValue": float(commute["objective_value"]),
                "objectiveUnit": "additional usual commute cyclists",
                "additionalCycleUsers": float(commute["additional_cycle_users"]),
                "annualBikeKmDelta": float(commute["annual_cycle_km"]),
                "odLowStressShareDelta": None,
                **evidence_fields(scenario),
                "routeCoverage": coverage["commute"],
                "warnings": _metric_warning(
                    "CIW OD low-stress connectivity requires the pending full-network reroute.",
                    "Lifecycle cost falls back to capital cost where no appraisable demand "
                    "response exists."
                    if candidate_id not in lifecycle_costs
                    else "",
                ),
            }

        by_purpose["equity"] = _unavailable_metric(
            capital_cost=capital_cost,
            lifecycle_cost=lifecycle_cost,
            route_coverage=coverage["commute"],
            warning="Equity scoring is withheld until NZDep redistribution terms are resolved.",
        )

        for purpose in ("school", "everyday", "transit"):
            route_coverage = coverage[purpose]
            if purpose == "transit" and not transit_public:
                by_purpose[purpose] = _unavailable_metric(
                    capital_cost=capital_cost,
                    lifecycle_cost=lifecycle_cost,
                    route_coverage=route_coverage,
                    warning=(
                        "Transit access scoring is withheld from the public build pending "
                        "source rights."
                    ),
                )
                continue
            access = counterfactuals.get(("access_baseline", purpose, candidate_id))
            if access is None:
                by_purpose[purpose] = _unavailable_metric(
                    capital_cost=capital_cost,
                    lifecycle_cost=lifecycle_cost,
                    route_coverage=route_coverage,
                    warning=f"No routed {purpose} market intersects this candidate.",
                )
                continue
            by_purpose[purpose] = {
                "available": True,
                "capitalCostNzd": capital_cost,
                "lifecycleCostNzd": lifecycle_cost,
                "objectiveValue": float(access["objective_value"]),
                "objectiveUnit": "person-equivalent impedance improvement",
                "additionalCycleUsers": None,
                "annualBikeKmDelta": None,
                "odLowStressShareDelta": None,
                "bcrP5": None,
                "bcrP50": None,
                "bcrP95": None,
                "routeCoverage": route_coverage,
                "meanRank": None,
                "topKProbability": None,
                "frontierProbability": None,
                "warnings": [
                    "This independent access market is scenario-invariant and is not a "
                    "daily trip forecast."
                ],
            }

        if not appraisal_public:
            by_purpose["appraisal"] = _unavailable_metric(
                capital_cost=capital_cost,
                lifecycle_cost=lifecycle_cost,
                route_coverage=coverage["commute"],
                warning="Appraisal is withheld until release-specific inputs pass review.",
            )
        elif sampled is None or scenario != evidence_scenario:
            by_purpose["appraisal"] = _unavailable_metric(
                capital_cost=capital_cost,
                lifecycle_cost=lifecycle_cost,
                route_coverage=coverage["commute"],
                warning=(
                    "Indicative appraisal is available only for the declared "
                    f"{evidence_scenario} scenario."
                ),
            )
        else:
            by_purpose["appraisal"] = {
                "available": True,
                "capitalCostNzd": capital_cost,
                "lifecycleCostNzd": lifecycle_cost,
                "objectiveValue": float(sampled["uncertainty_bcr_p50"]),
                "objectiveUnit": "indicative BCR",
                "additionalCycleUsers": (
                    float(commute["additional_cycle_users"]) if commute is not None else None
                ),
                "annualBikeKmDelta": (
                    float(commute["annual_cycle_km"]) if commute is not None else None
                ),
                "odLowStressShareDelta": None,
                **evidence_fields(scenario),
                "routeCoverage": coverage["commute"],
                "warnings": [
                    "Indicative screening BCR; it is not a business-case BCR.",
                    *[str(value) for value in sampled.get("warnings", [])],
                ],
            }
        output[scenario] = by_purpose
    return output


def _portfolio_manifest(
    rows: Sequence[Mapping[str, Any]],
    metric_lookup: Mapping[tuple[str, str, str], Mapping[str, Any]],
    *,
    transit_public: bool,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    by_analysis: defaultdict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_analysis[(str(row["scenario_id"]), str(row["preset"]))].append(row)
    output: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for scenario in SCENARIO_IDS:
        by_purpose: dict[str, list[dict[str, Any]]] = {}
        for browser_purpose in PURPOSE_IDS:
            if browser_purpose in {"equity", "appraisal"}:
                by_purpose[browser_purpose] = []
                continue
            if browser_purpose == "transit" and not transit_public:
                by_purpose[browser_purpose] = []
                continue
            source_scenario = scenario if browser_purpose == "network" else "access_baseline"
            source_preset = browser_purpose
            objective_unit = (
                "additional usual commute cyclists"
                if browser_purpose == "network"
                else "person-equivalent impedance improvement"
            )
            steps: list[dict[str, Any]] = []
            for row in sorted(
                by_analysis.get((source_scenario, source_preset), []),
                key=lambda item: int(item["rank"]),
            ):
                candidate_id = str(row["candidate_id"])
                metric = metric_lookup.get(
                    (
                        source_scenario,
                        "commute" if browser_purpose == "network" else browser_purpose,
                        candidate_id,
                    )
                )
                steps.append(
                    {
                        "candidateId": candidate_id,
                        "step": int(row["rank"]),
                        "cumulativeCostNzd": float(row["cumulative_cost_nzd"]),
                        "marginalObjective": float(row["marginal_objective"]),
                        "cumulativeObjective": float(row["cumulative_objective"]),
                        "objectiveUnit": objective_unit,
                        "paretoMember": bool(metric["pareto_member"]) if metric else False,
                    }
                )
            by_purpose[browser_purpose] = steps
        output[scenario] = by_purpose
    return output


def _candidate_and_network_layers(
    candidate_rows: Sequence[Mapping[str, Any]],
    edge_rows: Sequence[Mapping[str, Any]],
    *,
    metrics: Mapping[str, Mapping[str, dict[str, dict[str, dict[str, Any]]]]],
    project_crs: str,
    edge_cost_per_m: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    transformer = Transformer.from_crs(project_crs, "EPSG:4326", always_xy=True)
    edges_by_candidate: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in edge_rows:
        edges_by_candidate[str(row["candidate_id"])].append(row)
    candidate_features: list[dict[str, Any]] = []
    network_features: list[dict[str, Any]] = []
    for row in sorted(candidate_rows, key=lambda item: str(item["candidate_id"])):
        candidate_id = str(row["candidate_id"])
        geometry = from_wkb(row["geometry_wkb"])
        if not isinstance(geometry, LineString):
            raise ProductionBlocker(
                stage="export-outputs",
                code="invalid_candidate_geometry",
                message="candidate geometry must be a LineString",
                evidence={"candidate_id": candidate_id},
            )
        browser_geometry = transform(transformer.transform, geometry)
        candidate_edges = sorted(
            edges_by_candidate.get(candidate_id, []), key=lambda item: int(item["edge_sequence"])
        )
        edge_ids = [str(item["project_edge_id"]) for item in candidate_edges]
        if edge_ids != [str(value) for value in row["ordered_edge_ids"]]:
            raise ProductionBlocker(
                stage="export-outputs",
                code="candidate_edge_order_mismatch",
                message="candidate geometry and exact-edge ledger are not aligned",
                evidence={"candidate_id": candidate_id},
            )
        names = [
            str(value).strip() for value in row.get("primary_road_names", []) if str(value).strip()
        ]
        title = " / ".join(names[:2]) if names else f"Candidate {candidate_id}"
        candidate_features.append(
            {
                "type": "Feature",
                "geometry": mapping(browser_geometry),
                "properties": {
                    "candidateId": candidate_id,
                    "name": title,
                    "purposeOrigins": ["network", "school", "everyday", "transit", "appraisal"],
                    "edgeIds": edge_ids,
                    "facilityType": "protected cycleway screening treatment",
                    "programmeStatus": "unprogrammed",
                    "rationale": (
                        f"Connected exact-edge high-stress gap; baseline maximum LTS "
                        f"{int(row['maximum_baseline_lts'])}."
                    ),
                    "metrics": metrics[candidate_id],
                },
            }
        )

        total_edge_length = sum(float(item["length_m"]) for item in candidate_edges)
        cursor = 0.0
        for edge in candidate_edges:
            edge_length = float(edge["length_m"])
            start = geometry.length * cursor / total_edge_length
            cursor += edge_length
            end = geometry.length * cursor / total_edge_length
            segment = substring(geometry, start, end)
            if not isinstance(segment, LineString) or len(segment.coords) < 2:
                raise ProductionBlocker(
                    stage="export-outputs",
                    code="invalid_candidate_edge_geometry",
                    message=(
                        "an exact candidate edge could not be segmented from its corridor geometry"
                    ),
                    evidence={"candidate_id": candidate_id, "edge_id": edge["project_edge_id"]},
                )
            browser_segment = transform(transformer.transform, segment)
            network_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(browser_segment),
                    "properties": {
                        "edgeId": str(edge["project_edge_id"]),
                        "u": str(edge["from_node_id"]),
                        "v": str(edge["to_node_id"]),
                        "direction": str(edge["baseline_direction"]),
                        "protected": str(edge["baseline_facility"])
                        in {
                            "protected_lane",
                            "shared_path",
                            "quiet_street",
                        },
                        "lengthKm": edge_length / 1_000,
                        "capitalCostNzd": edge_length * edge_cost_per_m,
                        "dailyTripsPotential": float(edge["commute_estimated_observed_cycle"]),
                        "odLowStressSharePotential": 0.0,
                        "baselineLts": int(edge["baseline_lts"]),
                        "candidateId": candidate_id,
                    },
                }
            )
    if len({feature["properties"]["edgeId"] for feature in network_features}) != len(
        network_features
    ):
        raise ProductionBlocker(
            stage="export-outputs",
            code="duplicate_public_network_edge",
            message="candidate exact-edge partition contains a duplicate edge identifier",
        )
    return _feature_collection(candidate_features), _feature_collection(network_features)


def _cell_layer(route_dir: Path, *, project_crs: str) -> dict[str, Any]:
    od_rows = _table_rows(
        route_dir,
        "od_ledger.parquet",
        columns=[
            "od_id",
            "origin_support_id",
            "purpose",
            "weighted_eligible",
            "origin_x",
            "origin_y",
            "status",
        ],
    )
    scenario_rows = _table_rows(
        route_dir,
        "scenario_od_ledger.parquet",
        columns=["scenario_id", "od_id", "scenario_cycle"],
    )
    commute = {
        (str(row["scenario_id"]), str(row["od_id"])): float(row["scenario_cycle"])
        for row in scenario_rows
        if row["scenario_cycle"] is not None
    }
    coordinates: dict[str, tuple[float, float]] = {}
    totals: defaultdict[tuple[str, str, str], float] = defaultdict(float)
    for row in od_rows:
        if str(row["status"]) != "assigned":
            continue
        support = str(row["origin_support_id"])
        purpose = str(row["purpose"])
        coordinates[support] = (float(row["origin_x"]), float(row["origin_y"]))
        if purpose == "commute":
            for scenario in SCENARIO_IDS:
                totals[(support, scenario, "network")] += commute.get(
                    (scenario, str(row["od_id"])), 0.0
                )
                totals[(support, scenario, "appraisal")] += commute.get(
                    (scenario, str(row["od_id"])), 0.0
                )
        elif purpose in _ACCESS_PURPOSES:
            for scenario in SCENARIO_IDS:
                totals[(support, scenario, purpose)] += float(row["weighted_eligible"])
    maxima: defaultdict[tuple[str, str], float] = defaultdict(float)
    for (_, scenario, purpose), value in totals.items():
        maxima[(scenario, purpose)] = max(maxima[(scenario, purpose)], value)
    transformer = Transformer.from_crs(project_crs, "EPSG:4326", always_xy=True)
    features: list[dict[str, Any]] = []
    half_width_m = 175.0
    for support, (x, y) in sorted(coordinates.items()):
        polygon = Polygon(
            [
                (x - half_width_m, y - half_width_m),
                (x + half_width_m, y - half_width_m),
                (x + half_width_m, y + half_width_m),
                (x - half_width_m, y + half_width_m),
                (x - half_width_m, y - half_width_m),
            ]
        )
        values: dict[str, dict[str, float]] = {}
        for scenario in SCENARIO_IDS:
            purpose_values: dict[str, float] = {}
            for purpose in PURPOSE_IDS:
                maximum = maxima[(scenario, purpose)]
                purpose_values[purpose] = (
                    totals[(support, scenario, purpose)] / maximum if maximum > 0 else 0.0
                )
            values[scenario] = purpose_values
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(transform(transformer.transform, polygon)),
                "properties": {
                    "cellId": support,
                    "representation": "350_m_visualisation_square_around_routed_origin_support",
                    "values": values,
                },
            }
        )
    return _feature_collection(features)


def build_production_web_payload(context: StageContext) -> dict[str, Any]:
    """Build a rights-filtered research snapshot from canonical stage ledgers."""

    route_dir = context.dependencies["assign-routes"]["routes"].path
    candidate_dir = context.dependencies["generate-candidates"]["candidates"].path
    portfolio_dir = context.dependencies["evaluate-portfolios"]["portfolios"].path
    evidence_dir = context.dependencies["appraisal-uncertainty-validation"]["evidence"].path
    route_manifest = read_json(_artifact_file(route_dir, "manifest.json"))
    evidence_manifest = read_json(_artifact_file(evidence_dir, "manifest.json"))
    if not isinstance(route_manifest, Mapping) or not isinstance(evidence_manifest, Mapping):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_export_dependency_manifest",
            message="route and evidence manifests must be JSON objects",
        )
    coverage = _coverage_by_purpose(route_manifest)
    candidate_rows = _table_rows(candidate_dir, "candidate_ledger.parquet")
    edge_rows = _table_rows(candidate_dir, "candidate_edge_ledger.parquet")
    counterfactual_rows = _table_rows(portfolio_dir, "candidate_counterfactuals.parquet")
    portfolio_rows = _table_rows(portfolio_dir, "portfolio_steps.parquet")
    evidence_rows = _table_rows(evidence_dir, "candidate_evidence_profiles.parquet")
    appraisal_rows = _table_rows(evidence_dir, "candidate_appraisal.parquet")
    counterfactuals = {
        (str(row["scenario_id"]), str(row["purpose"]), str(row["candidate_id"])): row
        for row in counterfactual_rows
    }
    evidence = {str(row["candidate_id"]): row for row in evidence_rows}
    lifecycle_costs = {
        str(row["candidate_id"]): float(row["present_value_costs_nzd"])
        for row in appraisal_rows
        if str(row["discount_case"]) == "principal_declining_rate"
    }
    evidence_scenario = str(evidence_manifest.get("scenario_id", "commute_8pct"))
    source_by_id = {source.id: source for source in context.config.sources}
    transit_public = (
        source_by_id.get("major_transit_nodes") is not None
        and source_by_id["major_transit_nodes"].redistribution == "permitted"
    )
    metrics = {
        str(row["candidate_id"]): _candidate_metrics(
            str(row["candidate_id"]),
            float(row["capital_cost_base_nzd"]),
            counterfactuals=counterfactuals,
            evidence=evidence,
            lifecycle_costs=lifecycle_costs,
            coverage=coverage,
            evidence_scenario=evidence_scenario,
            transit_public=transit_public,
            appraisal_public=False,
        )
        for row in candidate_rows
    }
    cost_configuration = context.config.parameters["candidates"]["screening_cost"]
    candidates, network = _candidate_and_network_layers(
        candidate_rows,
        edge_rows,
        metrics=metrics,
        project_crs=context.config.project.crs,
        edge_cost_per_m=float(cost_configuration["base_nzd_per_m"]),
    )
    portfolios = _portfolio_manifest(portfolio_rows, counterfactuals, transit_public=transit_public)
    activity = _activity_totals(route_manifest)
    maximum_lts = int(context.config.parameters["candidates"]["connectivity_max_lts"])
    maximum_detour = float(context.config.parameters["candidates"]["maximum_detour_ratio"])
    candidate_count = len(candidate_rows)
    summaries: dict[str, dict[str, dict[str, Any]]] = {}
    for scenario in SCENARIO_IDS:
        by_purpose: dict[str, dict[str, Any]] = {}
        for purpose in PURPOSE_IDS:
            route_purpose = "commute" if purpose in _COMMUTE_PURPOSES | {"equity"} else purpose
            warning = "CIW OD low-stress connectivity requires the pending full-network reroute."
            if purpose == "equity":
                warning = "Equity output is unavailable pending redistribution-rights resolution."
            elif purpose == "transit" and not transit_public:
                warning = "Transit output is withheld from the public build pending source rights."
            elif purpose == "appraisal" and scenario != evidence_scenario:
                warning = f"Appraisal is available only for {evidence_scenario}."
            by_purpose[purpose] = {
                "purpose": purpose,
                "activityValue": activity[(scenario, purpose)],
                "activityUnit": {
                    "network": "weighted usual commute cyclists",
                    "appraisal": "weighted usual commute cyclists",
                    "equity": "unavailable",
                    "school": "modelled enrolment access units",
                    "everyday": "person-equivalent opportunity access units",
                    "transit": "person-equivalent major-node access units",
                }[purpose],
                "odLowStressShare": None,
                "odLowStressConnectedWeight": None,
                "odLowStressDenominatorWeight": None,
                "routingCoverage": coverage[route_purpose],
                "maximumLts": maximum_lts,
                "maximumDetourRatio": maximum_detour,
                "candidateCount": candidate_count,
                "validationCoverage": None,
                "warnings": [warning],
            }
        summaries[scenario] = by_purpose

    config_sha256, generated_at = _run_metadata(context)
    decisions, attributions = _source_rights(context)
    included = {decision["sourceId"] for decision in decisions if decision["decision"] == "include"}
    cell_sources = sorted(included & {"stats_nz_sa1_geography"})
    network_sources = sorted(
        included
        & {
            "geofabrik_new_zealand_osm",
            "auckland_transport_cycle_network",
            "linz_auckland_dem",
            "linz_auckland_dem_manifest",
        }
    )
    candidate_sources = sorted(included)
    max_budget = float(context.config.parameters["portfolios"]["maximum_precomputed_budget_nzd"])
    default_budget = min(100_000_000.0, max_budget)
    manifest = {
        "schemaVersion": "2.0.0",
        "modelVersion": __version__,
        "configSha256": config_sha256,
        "runId": context.run_id,
        "generatedAtUtc": generated_at,
        "title": "Auckland Cycling Investment Workbench",
        "dataStatus": "research_snapshot",
        "dataStatusLabel": "Auckland research snapshot; release blockers remain",
        "defaultScenario": "commute_8pct",
        "defaultPurpose": "network",
        "defaultBudgetNzd": default_budget,
        "maxBudgetNzd": max_budget,
        "scenarios": [
            {
                "id": "baseline",
                "label": "Present-day baseline",
                "description": (
                    "Present-day usual commute cycling estimate used as the validation case."
                ),
            },
            {
                "id": "government_target",
                "label": "PCT government target",
                "description": "Published PCT government-target commute propensity scenario.",
            },
            {
                "id": "go_dutch",
                "label": "PCT Go Dutch",
                "description": "Published PCT Go Dutch commute propensity scenario.",
            },
            {
                "id": "ebike",
                "label": "PCT e-bike",
                "description": "Published PCT e-bike commute propensity scenario.",
            },
            {
                "id": "commute_8pct",
                "label": "8% commute sensitivity",
                "description": (
                    "Explicit CIW sensitivity allocating an 8% commute cycling target; "
                    "not TERP modelling."
                ),
            },
        ],
        "purposes": [
            {
                "id": "network",
                "label": "Network",
                "description": "Commute counterfactual over the retained plausible-path market.",
                "objectiveLabel": "Additional usual commute cyclists",
            },
            {
                "id": "equity",
                "label": "Equity",
                "description": (
                    "Reserved for a rights-cleared deprivation-weighted accessibility analysis."
                ),
                "objectiveLabel": "Equity-weighted accessibility",
            },
            {
                "id": "school",
                "label": "School",
                "description": "Independent population-to-school enrolment access market.",
                "objectiveLabel": "School access impedance improvement",
            },
            {
                "id": "everyday",
                "label": "Everyday",
                "description": "Independent access market for everyday OSM destinations.",
                "objectiveLabel": "Everyday access impedance improvement",
            },
            {
                "id": "transit",
                "label": "Transit",
                "description": (
                    "Independent major-transit-node access market, withheld where rights "
                    "are unresolved."
                ),
                "objectiveLabel": "Transit access impedance improvement",
            },
            {
                "id": "appraisal",
                "label": "Appraisal",
                "description": "Indicative MBCM-aligned lifecycle health-benefit screen.",
                "objectiveLabel": "Indicative median BCR",
            },
        ],
        "summaries": summaries,
        "portfolios": portfolios,
        "validation": {
            "periodLabel": "Public counter layer withheld pending source-lineage resolution",
            "counterCount": 0,
            "matchedCount": 0,
            "coverage": 0.0,
            "purposeAlignment": (
                "No public calibration; local counters are a plausibility check only"
            ),
        },
        "capabilities": {
            "equity": "rights_blocked",
            "appraisal": "withheld",
            "sketchEvaluation": "requires_pipeline_evaluation",
        },
        "limitations": [
            "Full-network CIW OD low-stress connectivity recomputation is pending.",
            (
                "The browser network contains exact candidate edges, not the complete Auckland "
                "cycling graph."
            ),
            (
                "Origin cells are 350 m visualisation squares around routed supports, not "
                "statistical boundaries."
            ),
            "The Appraisal cumulative portfolio is withheld pending joint portfolio appraisal.",
            "Capital, maintenance, renewal, and uncertainty inputs require local evidence review.",
            (
                "Counter, equity, programme, transit, and safety outputs are excluded where "
                "rights or lineage are unresolved."
            ),
        ],
        "layers": [
            {
                "id": "cells",
                "label": "Routed origin demand surface",
                "url": "./data/cells.geojson",
                "sha256": "0" * 64,
                "defaultVisible": True,
                "optional": False,
                "licence": "Stats NZ data under CC BY 4.0; derived support visualisation",
                "sourceIds": cell_sources,
            },
            {
                "id": "network",
                "label": "Exact candidate-edge graph",
                "url": "./data/network.geojson",
                "sha256": "0" * 64,
                "defaultVisible": False,
                "optional": False,
                "licence": "Derived from OpenStreetMap ODbL and attributed public inputs",
                "sourceIds": network_sources,
            },
            {
                "id": "candidates",
                "label": "Candidate corridors",
                "url": "./data/candidates.geojson",
                "sha256": "0" * 64,
                "defaultVisible": True,
                "optional": False,
                "licence": "Derived analytical output; underlying sources retain their licences",
                "sourceIds": candidate_sources,
            },
            {
                "id": "programmes",
                "label": "Planned and funded programmes (withheld)",
                "url": "./data/programmes.geojson",
                "sha256": "0" * 64,
                "defaultVisible": False,
                "optional": True,
                "licence": "No source included pending rights verification",
                "sourceIds": [],
            },
            {
                "id": "counters",
                "label": "Validation counters (withheld)",
                "url": "./data/counters.geojson",
                "sha256": "0" * 64,
                "defaultVisible": False,
                "optional": True,
                "licence": "No source included pending lineage verification",
                "sourceIds": [],
            },
        ],
        "attribution": attributions,
        "methodologyUrl": "./documentation/methodology.md",
        "sourceDecisions": decisions,
    }
    return {
        "manifest": manifest,
        "layers": {
            "cells": _cell_layer(route_dir, project_crs=context.config.project.crs),
            "network": network,
            "candidates": candidates,
            "programmes": _feature_collection([]),
            "counters": _feature_collection([]),
        },
    }


def production_export_outputs_stage(context: StageContext) -> StageResult:
    payload = build_production_web_payload(context)
    destination = context.artifact_dir / "web-payload.json"
    write_json_atomic(destination, payload)
    layers = payload["layers"]
    return StageResult(
        {"web_payload": destination},
        {
            "row_counts": {
                "features": sum(len(layer["features"]) for layer in layers.values()),
                "layers": len(layers),
            }
        },
    )


def production_export_web_stage(context: StageContext) -> StageResult:
    payload = load_web_payload(context.dependencies["export-outputs"]["web_payload"].path)
    result = export_web_payload(
        payload,
        export_config=context.config.export,
        output_dir=context.artifact_dir / "data",
        source_specs=context.config.sources,
    )
    outputs: dict[str, Path] = {"web_manifest": result.manifest.path}
    outputs.update({layer_id: digest.path for layer_id, digest in result.layers.items()})
    return StageResult(
        outputs,
        {
            "row_counts": {
                "layers": len(result.layers),
                "bytes": result.manifest.size + sum(item.size for item in result.layers.values()),
            }
        },
    )
