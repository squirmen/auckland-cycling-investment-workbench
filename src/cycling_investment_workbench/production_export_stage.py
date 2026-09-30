"""Adapters from versioned Auckland ledgers to the public browser contract."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pyproj import Transformer
from shapely import from_wkb
from shapely.geometry import LineString, MultiLineString, Polygon, mapping, shape
from shapely.ops import substring, transform
from shapely.strtree import STRtree

from . import __version__
from .exports import PURPOSE_IDS, SCENARIO_IDS, export_web_payload, load_web_payload
from .pipeline import ProductionBlocker, StageContext, StageResult
from .provenance import content_hash, read_json, write_json_atomic
from .web_context import add_web_context

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
        "nzdep2023_sa1",
        "at_gtfs_schedule_2026_09_01",
        "major_transit_nodes",
        "auckland_transport_future_connect",
        "auckland_transport_rltp",
        "cycle_counter_locations",
        "cycle_counter_observations",
        "crash_safety_aggregate",
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


def _activity_totals(
    route_manifest: Mapping[str, Any], portfolio_manifest: Mapping[str, Any]
) -> dict[tuple[str, str], float]:
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
        equity = portfolio_manifest.get("equity")
        equity_activity = equity.get("scenario_activity") if isinstance(equity, Mapping) else None
        result[(scenario, "equity")] = (
            float(equity_activity.get(scenario, 0.0))
            if isinstance(equity_activity, Mapping)
            else 0.0
        )
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
    equity_public: bool,
    appraisal_public: bool,
) -> dict[str, dict[str, dict[str, Any]]]:
    lifecycle_cost = lifecycle_costs.get(candidate_id, capital_cost)
    sampled = evidence.get(candidate_id)

    def evidence_fields(scenario: str, *, include_bcr: bool) -> dict[str, Any]:
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
            "bcrP5": (
                float(sampled["uncertainty_bcr_p05"]) if appraisal_public and include_bcr else None
            ),
            "bcrP50": (
                float(sampled["uncertainty_bcr_p50"]) if appraisal_public and include_bcr else None
            ),
            "bcrP95": (
                float(sampled["uncertainty_bcr_p95"]) if appraisal_public and include_bcr else None
            ),
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
                **evidence_fields(scenario, include_bcr=False),
                "routeCoverage": coverage["commute"],
                "warnings": _metric_warning(
                    "Full-network CIW OD low-stress connectivity is reserved for separate "
                    "research integration.",
                    "Lifecycle cost falls back to capital cost where no appraisable demand "
                    "response exists."
                    if candidate_id not in lifecycle_costs
                    else "",
                ),
            }

        equity = counterfactuals.get((scenario, "equity", candidate_id))
        if not equity_public:
            by_purpose["equity"] = _unavailable_metric(
                capital_cost=capital_cost,
                lifecycle_cost=lifecycle_cost,
                route_coverage=coverage["commute"],
                warning=(
                    "The equity subgroup lens is unavailable without the registered NZDep source."
                ),
            )
        elif equity is None:
            by_purpose["equity"] = _unavailable_metric(
                capital_cost=capital_cost,
                lifecycle_cost=lifecycle_cost,
                route_coverage=coverage["commute"],
                warning=(
                    "No routed high-deprivation-origin commute market intersects this candidate."
                ),
            )
        else:
            by_purpose["equity"] = {
                "available": True,
                "capitalCostNzd": capital_cost,
                "lifecycleCostNzd": lifecycle_cost,
                "objectiveValue": float(equity["objective_value"]),
                "objectiveUnit": "additional usual commuters from NZDep decile 8-10 origins",
                "additionalCycleUsers": float(equity["additional_cycle_users"]),
                "annualBikeKmDelta": float(equity["annual_cycle_km"]),
                "odLowStressShareDelta": None,
                "bcrP5": None,
                "bcrP50": None,
                "bcrP95": None,
                "routeCoverage": coverage["commute"],
                "meanRank": None,
                "topKProbability": None,
                "frontierProbability": None,
                "warnings": [
                    "Distributional subgroup lens; not a causal equity effect or welfare weight.",
                    "Full-network CIW OD low-stress connectivity is reserved for separate "
                    "research integration.",
                ],
            }

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
                **evidence_fields(scenario, include_bcr=True),
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
    equity_public: bool,
    appraisal_scenario: str,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    by_analysis: defaultdict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_analysis[(str(row["scenario_id"]), str(row["preset"]))].append(row)
    output: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for scenario in SCENARIO_IDS:
        by_purpose: dict[str, list[dict[str, Any]]] = {}
        for browser_purpose in PURPOSE_IDS:
            if browser_purpose == "appraisal" and scenario != appraisal_scenario:
                by_purpose[browser_purpose] = []
                continue
            if browser_purpose == "equity" and not equity_public:
                by_purpose[browser_purpose] = []
                continue
            if browser_purpose == "transit" and not transit_public:
                by_purpose[browser_purpose] = []
                continue
            source_scenario = (
                scenario
                if browser_purpose in {"network", "equity", "appraisal"}
                else "access_baseline"
            )
            source_preset = browser_purpose
            objective_unit = (
                "additional usual commute cyclists"
                if browser_purpose == "network"
                else (
                    "additional usual commuters from NZDep decile 8-10 origins"
                    if browser_purpose == "equity"
                    else (
                        "additional usual commute cyclists (appraisal prescreen)"
                        if browser_purpose == "appraisal"
                        else "person-equivalent impedance improvement"
                    )
                )
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
                        (
                            "commute"
                            if browser_purpose in {"network", "appraisal"}
                            else browser_purpose
                        ),
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
    programme_geometries: Sequence[LineString | MultiLineString] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    transformer = Transformer.from_crs(project_crs, "EPSG:4326", always_xy=True)
    edges_by_candidate: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in edge_rows:
        edges_by_candidate[str(row["candidate_id"])].append(row)
    candidate_features: list[dict[str, Any]] = []
    network_features: list[dict[str, Any]] = []
    programme_tree = STRtree(programme_geometries) if programme_geometries else None
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
        programme_status = "unprogrammed"
        if programme_tree is not None and geometry.length > 0:
            nearby = programme_tree.query(geometry.buffer(20.0))
            if any(
                geometry.intersection(programme_geometries[int(index)].buffer(20.0)).length
                / geometry.length
                >= 0.25
                for index in nearby
            ):
                programme_status = "aligned"
        candidate_features.append(
            {
                "type": "Feature",
                "geometry": mapping(browser_geometry),
                "properties": {
                    "candidateId": candidate_id,
                    "name": title,
                    "purposeOrigins": [
                        "network",
                        "equity",
                        "school",
                        "everyday",
                        "transit",
                        "appraisal",
                    ],
                    "edgeIds": edge_ids,
                    "facilityType": "protected cycleway screening treatment",
                    "programmeStatus": programme_status,
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


def _permitted_source_path(context: StageContext, source_id: str) -> Path | None:
    spec = next((source for source in context.config.sources if source.id == source_id), None)
    record = context.sources.get(source_id)
    if spec is None or spec.redistribution != "permitted" or record is None or not record.usable:
        return None
    return record.path


def _programme_layer(
    context: StageContext, *, project_crs: str
) -> tuple[dict[str, Any], list[LineString | MultiLineString]]:
    transformer = Transformer.from_crs("EPSG:4326", project_crs, always_xy=True)
    features: list[dict[str, Any]] = []
    project_geometries: list[LineString | MultiLineString] = []
    source_definitions = (
        ("auckland_transport_future_connect", "strategic"),
        ("auckland_transport_rltp", "rltp"),
    )
    for source_id, source_type in source_definitions:
        source_path = _permitted_source_path(context, source_id)
        if source_path is None:
            continue
        payload = read_json(source_path)
        raw_features = payload.get("features") if isinstance(payload, Mapping) else None
        if not isinstance(raw_features, list):
            raise ProductionBlocker(
                stage="export-outputs",
                code="invalid_programme_source",
                message=f"{source_id} must be a GeoJSON FeatureCollection",
            )
        for index, raw_feature in enumerate(raw_features):
            if not isinstance(raw_feature, Mapping):
                continue
            raw_geometry = raw_feature.get("geometry")
            properties = raw_feature.get("properties")
            if not isinstance(raw_geometry, Mapping) or not isinstance(properties, Mapping):
                continue
            geometry = shape(raw_geometry)
            if not isinstance(geometry, LineString | MultiLineString) or geometry.is_empty:
                continue
            project_geometry = transform(transformer.transform, geometry)
            project_geometries.append(project_geometry)
            if source_type == "strategic":
                name = str(properties.get("street_name") or "Future Connect cycle network")
                status = "strategic"
                description = "Future Connect strategic cycle-network alignment"
                programme_id = f"future-connect-{properties.get('OBJECTID', index)}"
            else:
                name = str(properties.get("Title") or "RLTP active-modes project")
                extent = str(properties.get("extent") or "planned").strip().lower()
                status = "committed" if extent == "committed" else "planned"
                description = str(properties.get("description") or "RLTP active-modes project")
                programme_id = f"rltp-{properties.get('RLTP_ID', index)}"
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": {
                        "programmeId": programme_id,
                        "name": name,
                        "status": status,
                        "description": description,
                        "sourceId": source_id,
                        "programmeVersion": (
                            "Future Connect 2024-2034"
                            if source_type == "strategic"
                            else str(properties.get("RLTPVersion") or "RLTP 2024-2034")
                        ),
                    },
                }
            )
    return _feature_collection(features), project_geometries


def _counter_layer(
    context: StageContext,
    evidence_dir: Path,
    evidence_manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    location_path = _permitted_source_path(context, "cycle_counter_locations")
    observation_path = _permitted_source_path(context, "cycle_counter_observations")
    if location_path is None or observation_path is None:
        return _feature_collection([]), {
            "periodLabel": "Counter source unavailable",
            "counterCount": 0,
            "matchedCount": 0,
            "coverage": 0.0,
            "purposeAlignment": "No calibration; counter comparison is a plausibility check only",
            "status": "unavailable",
        }
    locations = read_json(location_path)
    observations = read_json(observation_path)
    if not isinstance(locations, list) or not isinstance(observations, Mapping):
        raise ProductionBlocker(
            stage="export-outputs",
            code="invalid_counter_source",
            message="counter locations and observations have invalid public adapter schemas",
        )
    evidence_rows = _table_rows(evidence_dir, "counter_validation.parquet")
    evidence_by_id = {str(row["counter_id"]): row for row in evidence_rows}
    daily = observations.get("dailyAverages")
    metadata = observations.get("metadata")
    if not isinstance(daily, Mapping) or not isinstance(metadata, Mapping):
        raise ProductionBlocker(
            stage="export-outputs",
            code="invalid_counter_source",
            message="counter observations must include daily averages and metadata",
        )
    features: list[dict[str, Any]] = []
    matched = 0
    for item in locations:
        if not isinstance(item, Mapping):
            continue
        counter_id = str(item.get("counter_id", ""))
        site_name = str(item.get("name", ""))
        row = evidence_by_id.get(counter_id)
        status = str(row.get("status")) if row is not None else "not_evaluated"
        if status == "spatially_matched_incompatible_measure":
            matched += 1
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(item["lng"]), float(item["lat"])],
                },
                "properties": {
                    "counterId": counter_id,
                    "siteName": site_name,
                    "observedDaily": float(daily[site_name]),
                    "status": status,
                    "matchDistanceM": (
                        float(row["match_distance_m"])
                        if row is not None and row.get("match_distance_m") is not None
                        else None
                    ),
                    "coordinateBasis": "approximate project-maintained site point",
                    "measure": "daily all-purpose cycle movements",
                    "periodLabel": str(metadata.get("period_label", "July 2026")),
                },
            }
        )
    validation = evidence_manifest.get("validation")
    validation_mapping = validation if isinstance(validation, Mapping) else {}
    return _feature_collection(features), {
        "periodLabel": str(metadata.get("period_label", "July 2026")),
        "counterCount": len(features),
        "matchedCount": matched,
        "coverage": matched / len(features) if features else 0.0,
        "purposeAlignment": (
            "Spatial plausibility only: daily all-purpose movements are not usual-commute people"
        ),
        "status": str(validation_mapping.get("status", "plausibility_only")),
    }


def _safety_layer(context: StageContext) -> dict[str, Any]:
    source_path = _permitted_source_path(context, "crash_safety_aggregate")
    if source_path is None:
        return _feature_collection([])
    payload = read_json(source_path)
    features = payload.get("features") if isinstance(payload, Mapping) else None
    if not isinstance(features, list):
        raise ProductionBlocker(
            stage="export-outputs",
            code="invalid_safety_source",
            message="safety aggregate must be a GeoJSON FeatureCollection",
        )
    return _feature_collection([feature for feature in features if isinstance(feature, Mapping)])


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
    portfolio_manifest_path = _artifact_file(portfolio_dir, "manifest.json")
    portfolio_manifest = (
        read_json(portfolio_manifest_path) if portfolio_manifest_path.is_file() else {}
    )
    if not isinstance(portfolio_manifest, Mapping):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_export_dependency_manifest",
            message="portfolio manifest must be a JSON object",
        )
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
    transit_public = _permitted_source_path(context, "major_transit_nodes") is not None
    equity_public = _permitted_source_path(context, "nzdep2023_sa1") is not None
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
            equity_public=equity_public,
            appraisal_public=True,
        )
        for row in candidate_rows
    }
    cost_configuration = context.config.parameters["candidates"]["screening_cost"]
    programmes, programme_geometries = _programme_layer(
        context, project_crs=context.config.project.crs
    )
    counters, validation = _counter_layer(context, evidence_dir, evidence_manifest)
    safety = _safety_layer(context)
    candidates, network = _candidate_and_network_layers(
        candidate_rows,
        edge_rows,
        metrics=metrics,
        project_crs=context.config.project.crs,
        edge_cost_per_m=float(cost_configuration["base_nzd_per_m"]),
        programme_geometries=programme_geometries,
    )
    portfolios = _portfolio_manifest(
        portfolio_rows,
        counterfactuals,
        transit_public=transit_public,
        equity_public=equity_public,
        appraisal_scenario=evidence_scenario,
    )
    activity = _activity_totals(route_manifest, portfolio_manifest)
    maximum_lts = int(context.config.parameters["candidates"]["connectivity_max_lts"])
    maximum_detour = float(context.config.parameters["candidates"]["maximum_detour_ratio"])
    candidate_count = len(candidate_rows)
    summaries: dict[str, dict[str, dict[str, Any]]] = {}
    for scenario in SCENARIO_IDS:
        by_purpose: dict[str, dict[str, Any]] = {}
        for purpose in PURPOSE_IDS:
            route_purpose = "commute" if purpose in _COMMUTE_PURPOSES | {"equity"} else purpose
            warning = (
                "Full-network CIW OD low-stress connectivity is reserved for separate "
                "research integration."
            )
            if purpose == "equity":
                warning = (
                    "Distributional subgroup lens for NZDep2023 deciles 8-10; not a causal "
                    "equity effect or welfare weight."
                    if equity_public
                    else "The equity subgroup lens is unavailable without the registered source."
                )
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
                    "equity": "weighted usual commuters from NZDep decile 8-10 origins",
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
                    "Distributional lens for additional usual commute cyclists originating in "
                    "NZDep2023 deciles 8-10."
                ),
                "objectiveLabel": "Additional cyclists from high-deprivation origins",
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
                    "Independent access market to rail, ferry, named interchange, and busiest "
                    "bus nodes in the declared AT GTFS service day."
                ),
                "objectiveLabel": "Transit access impedance improvement",
            },
            {
                "id": "appraisal",
                "label": "Appraisal",
                "description": (
                    "Research-only MBCM v1.7.5-aligned lifecycle health-benefit screen with "
                    "provisional cost ranges."
                ),
                "objectiveLabel": "Indicative median BCR",
            },
        ],
        "summaries": summaries,
        "portfolios": portfolios,
        "validation": validation,
        "capabilities": {
            "equity": "available" if equity_public else "unavailable",
            "appraisal": "research_only",
            "sketchEvaluation": "requires_pipeline_evaluation",
        },
        "limitations": [
            (
                "Full-network CIW OD low-stress connectivity is intentionally reserved for "
                "separate research integration. No Auckland point estimate is reported."
            ),
            (
                "The browser network contains exact candidate edges, not the complete Auckland "
                "cycling graph."
            ),
            (
                "Origin cells are 350 m visualisation squares around routed supports, not "
                "statistical boundaries."
            ),
            (
                "Indicative BCRs are research-only candidate screens using provisional capital, "
                "maintenance, renewal, and uncertainty inputs; they are not business-case BCRs."
            ),
            (
                "The Appraisal sequence uses commute activity improvement per cost; candidate "
                "BCRs are not summed into a cumulative portfolio BCR."
            ),
            (
                "Counter comparisons are spatial plausibility checks only; their daily all-purpose "
                "measure is not calibrated against usual-commute people."
            ),
            "Safety cells show police-reported crash counts without cycling-exposure adjustment.",
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
                "label": "Future Connect and RLTP active-mode programmes",
                "url": "./data/programmes.geojson",
                "sha256": "0" * 64,
                "defaultVisible": False,
                "optional": True,
                "licence": "Auckland Transport open data under CC BY 4.0",
                "sourceIds": sorted(
                    included & {"auckland_transport_future_connect", "auckland_transport_rltp"}
                ),
            },
            {
                "id": "counters",
                "label": "July 2026 cycle-count plausibility sites",
                "url": "./data/counters.geojson",
                "sha256": "0" * 64,
                "defaultVisible": False,
                "optional": True,
                "licence": (
                    "AT observations under CC BY 4.0; approximate site points maintained by CIW"
                ),
                "sourceIds": sorted(
                    included & {"cycle_counter_locations", "cycle_counter_observations"}
                ),
            },
            {
                "id": "safety",
                "label": "Cycle-involved crash context, 2016-2025",
                "url": "./data/safety.geojson",
                "sha256": "0" * 64,
                "defaultVisible": False,
                "optional": True,
                "licence": (
                    "Disclosure-safe derived aggregate from NZTA CAS open data; raw rows excluded"
                ),
                "sourceIds": sorted(included & {"crash_safety_aggregate"}),
            },
        ],
        "attribution": attributions,
        "methodologyUrl": "./documentation/methodology.md",
        "sourceDecisions": decisions,
    }
    payload = {
        "manifest": manifest,
        "layers": {
            "cells": _cell_layer(route_dir, project_crs=context.config.project.crs),
            "network": network,
            "candidates": candidates,
            "programmes": programmes,
            "counters": counters,
            "safety": safety,
        },
    }
    if "build-topology" in context.dependencies:
        add_web_context(
            payload,
            topology_path=_artifact_file(
                context.dependencies["build-topology"]["topology"].path, "topology.json"
            ),
            candidate_edges=edge_rows,
            route_dir=route_dir,
            portfolio_dir=portfolio_dir,
            parameters=context.config.parameters,
        )
    return payload


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
