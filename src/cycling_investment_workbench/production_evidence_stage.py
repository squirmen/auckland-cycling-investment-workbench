"""Production appraisal, uncertainty, and present-day plausibility evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer
from shapely.geometry import LineString
from shapely.geometry import Point as ShapelyPoint
from shapely.strtree import STRtree

from .appraisal import AppraisalInputs, AppraisalParameters, lifecycle_appraisal
from .models import CounterSite, Direction, Edge, FacilityType, Node, RoadClass
from .pipeline import ProductionBlocker, StageContext, StageResult
from .provenance import content_hash, read_json, sha256_file, write_json_atomic
from .topology import DirectedTopology
from .uncertainty import (
    MATERIAL_UNCERTAINTY_DIMENSIONS,
    ParameterSpec,
    latin_hypercube,
    validate_material_uncertainty_design,
)
from .validation import match_counters

EVIDENCE_OUTPUT_SCHEMA_VERSION = 1

APPRAISAL_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("scenario_id", pa.string()),
        ("candidate_id", pa.string()),
        ("discount_case", pa.string()),
        ("additional_cycle_users", pa.float64()),
        ("annual_cycle_km", pa.float64()),
        ("ebike_share", pa.float64()),
        ("capital_cost_nzd", pa.float64()),
        ("annual_maintenance_nzd", pa.float64()),
        ("renewal_cost_nzd", pa.float64()),
        ("residual_value_nzd", pa.float64()),
        ("full_annual_health_benefit_nzd", pa.float64()),
        ("present_value_benefits_nzd", pa.float64()),
        ("present_value_costs_nzd", pa.float64()),
        ("net_present_value_nzd", pa.float64()),
        ("indicative_bcr", pa.float64()),
        ("price_base_year", pa.int16()),
    ]
)

UNCERTAINTY_PARAMETER_SCHEMA = pa.schema(
    [("schema_version", pa.int16()), ("draw_id", pa.int32())]
    + [(name, pa.float64()) for name in MATERIAL_UNCERTAINTY_DIMENSIONS]
)

UNCERTAINTY_RESULT_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("scenario_id", pa.string()),
        ("draw_id", pa.int32()),
        ("candidate_id", pa.string()),
        ("additional_cycle_users", pa.float64()),
        ("annual_cycle_km", pa.float64()),
        ("present_value_benefits_nzd", pa.float64()),
        ("present_value_costs_nzd", pa.float64()),
        ("net_present_value_nzd", pa.float64()),
        ("indicative_bcr", pa.float64()),
        ("rank", pa.int32()),
        ("top_k_member", pa.bool_()),
        ("pareto_member", pa.bool_()),
    ]
)

EVIDENCE_SUMMARY_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("scenario_id", pa.string()),
        ("candidate_id", pa.string()),
        ("affected_od_count", pa.int32()),
        ("routing_coverage", pa.float64()),
        ("principal_indicative_bcr", pa.float64()),
        ("discount_8pct_indicative_bcr", pa.float64()),
        ("uncertainty_bcr_p05", pa.float64()),
        ("uncertainty_bcr_p50", pa.float64()),
        ("uncertainty_bcr_p95", pa.float64()),
        ("mean_rank", pa.float64()),
        ("top_k_probability", pa.float64()),
        ("frontier_probability", pa.float64()),
        ("cost_evidence_status", pa.string()),
        ("validation_alignment_status", pa.string()),
        ("warnings", pa.list_(pa.string())),
    ]
)

COUNTER_VALIDATION_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("counter_id", pa.string()),
        ("site_name", pa.string()),
        ("observed_daily_all_purpose_cycles", pa.float64()),
        ("predicted_usual_commute_cycle_people", pa.float64()),
        ("matched_edge_id", pa.string()),
        ("match_distance_m", pa.float64()),
        ("bearing_difference_degrees", pa.float64()),
        ("match_basis", pa.string()),
        ("status", pa.string()),
        ("exclusion_reason", pa.string()),
    ]
)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionBlocker(
            stage="appraisal-uncertainty-validation",
            code="invalid_evidence_configuration",
            message=f"{field} must be a mapping",
        )
    return value


def _finite(value: Any, *, field: str, minimum: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductionBlocker(
            stage="appraisal-uncertainty-validation",
            code="invalid_evidence_configuration",
            message=f"{field} must be numeric",
        ) from exc
    if not isfinite(result) or result < minimum:
        raise ProductionBlocker(
            stage="appraisal-uncertainty-validation",
            code="invalid_evidence_configuration",
            message=f"{field} must be finite and at least {minimum}",
        )
    return result


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        result = 0
    else:
        try:
            result = int(value)
        except (TypeError, ValueError):
            result = 0
    if result < 1:
        raise ProductionBlocker(
            stage="appraisal-uncertainty-validation",
            code="invalid_evidence_configuration",
            message=f"{field} must be a positive integer",
        )
    return result


def _artifact_file(path: Path, filename: str) -> Path:
    return path / filename if path.is_dir() else path.parent / filename


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    temporary = path.with_name(path.name + ".tmp")
    pq.write_table(
        pa.Table.from_pylist([dict(row) for row in rows], schema=schema),
        temporary,
        compression="zstd",
        use_dictionary=True,
    )
    temporary.replace(path)


def _appraisal_parameters(
    configuration: Mapping[str, Any], *, discount_rate: float | None = None
) -> AppraisalParameters:
    return AppraisalParameters(
        price_base_year=_positive_int(
            configuration.get("price_base_year"), field="appraisal.price_base_year"
        ),
        discount_rate=discount_rate,
        appraisal_years=_positive_int(
            configuration.get("appraisal_years"), field="appraisal.appraisal_years"
        ),
        ramp_up_years=int(configuration.get("ramp_up_years", 0)),
        conventional_health_per_km=_finite(
            configuration.get("conventional_health_per_km_nzd"),
            field="appraisal.conventional_health_per_km_nzd",
        ),
        ebike_health_per_km=_finite(
            configuration.get("ebike_health_per_km_nzd"),
            field="appraisal.ebike_health_per_km_nzd",
        ),
        conventional_health_cap_per_user=_finite(
            configuration.get("conventional_health_cap_per_user_nzd"),
            field="appraisal.conventional_health_cap_per_user_nzd",
        ),
        ebike_health_cap_per_user=_finite(
            configuration.get("ebike_health_cap_per_user_nzd"),
            field="appraisal.ebike_health_cap_per_user_nzd",
        ),
    )


def _appraisal_inputs(
    metric: Mapping[str, Any],
    configuration: Mapping[str, Any],
    *,
    ebike_share: float,
) -> AppraisalInputs:
    if not 0 <= ebike_share <= 1:
        raise ValueError("e-bike share must be in [0, 1]")
    capital = float(metric["capital_cost_base_nzd"])
    annual_km = float(metric["annual_cycle_km"])
    users = float(metric["additional_cycle_users"])
    maintenance = capital * _finite(
        configuration.get("annual_maintenance_capital_share"),
        field="appraisal.annual_maintenance_capital_share",
    )
    renewal = capital * _finite(
        configuration.get("renewal_capital_share"),
        field="appraisal.renewal_capital_share",
    )
    residual = capital * _finite(
        configuration.get("residual_value_capital_share"),
        field="appraisal.residual_value_capital_share",
    )
    renewal_year = _positive_int(configuration.get("renewal_year"), field="appraisal.renewal_year")
    return AppraisalInputs(
        capital_cost=capital,
        price_base_year=_positive_int(
            configuration.get("price_base_year"), field="appraisal.price_base_year"
        ),
        annual_conventional_cycle_km=annual_km * (1 - ebike_share),
        annual_ebike_cycle_km=annual_km * ebike_share,
        new_conventional_users=users * (1 - ebike_share),
        new_ebike_users=users * ebike_share,
        annual_maintenance_cost=maintenance,
        renewal_costs={renewal_year: renewal},
        residual_value=residual,
    )


def _central_appraisal_rows(
    metrics: Sequence[Mapping[str, Any]], configuration: Mapping[str, Any]
) -> list[dict[str, Any]]:
    ebike_share = _finite(configuration.get("ebike_share"), field="appraisal.ebike_share")
    if ebike_share > 1:
        raise ProductionBlocker(
            stage="appraisal-uncertainty-validation",
            code="invalid_evidence_configuration",
            message="appraisal.ebike_share must not exceed one",
        )
    cases = (
        ("principal_declining_rate", None),
        (
            "mandatory_8pct_sensitivity",
            _finite(
                configuration.get("sensitivity_discount_rate"),
                field="appraisal.sensitivity_discount_rate",
            ),
        ),
    )
    rows: list[dict[str, Any]] = []
    for metric in metrics:
        inputs = _appraisal_inputs(metric, configuration, ebike_share=ebike_share)
        for case_id, discount_rate in cases:
            result = lifecycle_appraisal(
                inputs,
                _appraisal_parameters(configuration, discount_rate=discount_rate),
            )
            rows.append(
                {
                    "schema_version": EVIDENCE_OUTPUT_SCHEMA_VERSION,
                    "scenario_id": str(metric["scenario_id"]),
                    "candidate_id": str(metric["candidate_id"]),
                    "discount_case": case_id,
                    "additional_cycle_users": float(metric["additional_cycle_users"]),
                    "annual_cycle_km": float(metric["annual_cycle_km"]),
                    "ebike_share": ebike_share,
                    "capital_cost_nzd": inputs.capital_cost,
                    "annual_maintenance_nzd": inputs.annual_maintenance_cost,
                    "renewal_cost_nzd": sum(inputs.renewal_costs.values()),
                    "residual_value_nzd": inputs.residual_value,
                    "full_annual_health_benefit_nzd": result.full_annual_health_benefit,
                    "present_value_benefits_nzd": result.present_value_benefits,
                    "present_value_costs_nzd": result.present_value_costs,
                    "net_present_value_nzd": result.net_present_value,
                    "indicative_bcr": result.benefit_cost_ratio,
                    "price_base_year": result.price_base_year,
                }
            )
    return rows


def _parameter_specs(configuration: Mapping[str, Any]) -> tuple[ParameterSpec, ...]:
    raw = configuration.get("parameters")
    if not isinstance(raw, list):
        raise ProductionBlocker(
            stage="appraisal-uncertainty-validation",
            code="invalid_uncertainty_design",
            message="uncertainty.parameters must be a list",
        )
    specs: list[ParameterSpec] = []
    for item in raw:
        current = _mapping(item, field="uncertainty.parameters[]")
        specs.append(
            ParameterSpec(
                str(current.get("name", "")),
                _finite(current.get("lower"), field="uncertainty.parameters[].lower"),
                _finite(current.get("upper"), field="uncertainty.parameters[].upper"),
                str(current.get("distribution", "uniform")),  # type: ignore[arg-type]
                (
                    _finite(current.get("mode"), field="uncertainty.parameters[].mode")
                    if current.get("mode") is not None
                    else None
                ),
            )
        )
    validate_material_uncertainty_design(specs)
    return tuple(specs)


def _discount_factors(rate: float, years: int, ramp_years: int) -> tuple[float, float, list[float]]:
    cumulative = 1.0
    benefit_factor = 0.0
    maintenance_factor = 0.0
    single_payment: list[float] = []
    for year in range(1, years + 1):
        cumulative *= 1 + rate
        discount = 1 / cumulative
        ramp = 1.0 if ramp_years == 0 else min(1.0, year / ramp_years)
        benefit_factor += ramp * discount
        maintenance_factor += discount
        single_payment.append(discount)
    return benefit_factor, maintenance_factor, single_payment


def _pareto_indices(
    benefit: np.ndarray, cost: np.ndarray, candidate_ids: Sequence[str]
) -> np.ndarray:
    order = sorted(
        range(len(candidate_ids)),
        key=lambda index: (float(cost[index]), -float(benefit[index]), candidate_ids[index]),
    )
    selected: list[int] = []
    best_at_cheaper_cost = float("-inf")
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        group_cost = float(cost[order[cursor]])
        while end < len(order) and float(cost[order[end]]) == group_cost:
            end += 1
        group = order[cursor:end]
        group_best = max(float(benefit[index]) for index in group)
        if group_best > best_at_cheaper_cost:
            selected.extend(index for index in group if float(benefit[index]) == group_best)
            best_at_cheaper_cost = group_best
        cursor = end
    return np.asarray(selected, dtype=np.int64)


def _uncertainty_outputs(
    output_dir: Path,
    metrics: Sequence[Mapping[str, Any]],
    appraisal: Mapping[str, Any],
    uncertainty: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], Path, Path]:
    specs = _parameter_specs(uncertainty)
    sample_count = _positive_int(uncertainty.get("sample_count"), field="uncertainty.sample_count")
    seed = _positive_int(uncertainty.get("seed"), field="uncertainty.seed")
    samples = latin_hypercube(specs, sample_count, seed=seed)
    parameter_rows = [
        {
            "schema_version": EVIDENCE_OUTPUT_SCHEMA_VERSION,
            "draw_id": draw_id,
            **sample,
        }
        for draw_id, sample in enumerate(samples, start=1)
    ]
    parameter_path = output_dir / "uncertainty_parameters.parquet"
    _write_parquet(parameter_path, parameter_rows, UNCERTAINTY_PARAMETER_SCHEMA)

    candidate_ids = [str(row["candidate_id"]) for row in metrics]
    scenario_id = str(metrics[0]["scenario_id"])
    users = np.asarray([float(row["additional_cycle_users"]) for row in metrics])
    annual_km = np.asarray([float(row["annual_cycle_km"]) for row in metrics])
    base_cost = np.asarray([float(row["capital_cost_base_nzd"]) for row in metrics])
    years = _positive_int(appraisal.get("appraisal_years"), field="appraisal.appraisal_years")
    ramp_years = int(appraisal.get("ramp_up_years", 0))
    renewal_year = _positive_int(appraisal.get("renewal_year"), field="appraisal.renewal_year")
    maintenance_share = _finite(
        appraisal.get("annual_maintenance_capital_share"),
        field="appraisal.annual_maintenance_capital_share",
    )
    renewal_share = _finite(
        appraisal.get("renewal_capital_share"), field="appraisal.renewal_capital_share"
    )
    residual_share = _finite(
        appraisal.get("residual_value_capital_share"),
        field="appraisal.residual_value_capital_share",
    )
    conventional_value = _finite(
        appraisal.get("conventional_health_per_km_nzd"),
        field="appraisal.conventional_health_per_km_nzd",
    )
    ebike_value = _finite(
        appraisal.get("ebike_health_per_km_nzd"),
        field="appraisal.ebike_health_per_km_nzd",
    )
    conventional_cap = _finite(
        appraisal.get("conventional_health_cap_per_user_nzd"),
        field="appraisal.conventional_health_cap_per_user_nzd",
    )
    ebike_cap = _finite(
        appraisal.get("ebike_health_cap_per_user_nzd"),
        field="appraisal.ebike_health_cap_per_user_nzd",
    )
    top_k = min(
        _positive_int(uncertainty.get("rank_top_k"), field="uncertainty.rank_top_k"),
        len(candidate_ids),
    )
    bcr_values = np.empty((sample_count, len(candidate_ids)), dtype=np.float64)
    rank_total = np.zeros(len(candidate_ids), dtype=np.float64)
    top_k_count = np.zeros(len(candidate_ids), dtype=np.int64)
    frontier_count = np.zeros(len(candidate_ids), dtype=np.int64)
    result_path = output_dir / "candidate_uncertainty_draws.parquet"
    temporary = result_path.with_name(result_path.name + ".tmp")
    writer = pq.ParquetWriter(temporary, UNCERTAINTY_RESULT_SCHEMA, compression="zstd")
    try:
        for draw_index, sample in enumerate(samples):
            demand_factor = (
                sample["suppression_factor"]
                * sample["pct_uptake_factor"]
                * sample["route_choice_factor"]
                * sample["stress_penalty_factor"]
                * sample["topology_coverage_factor"]
                * sample["demand_response_elasticity"]
            )
            draw_users = users * demand_factor
            draw_km = annual_km * demand_factor
            ebike_share = sample["ebike_share"]
            conventional_health = np.minimum(
                draw_km * (1 - ebike_share) * conventional_value,
                draw_users * (1 - ebike_share) * conventional_cap,
            )
            ebike_health = np.minimum(
                draw_km * ebike_share * ebike_value,
                draw_users * ebike_share * ebike_cap,
            )
            annual_benefit = (conventional_health + ebike_health) * sample["benefit_value_factor"]
            benefit_factor, maintenance_factor, single_payment = _discount_factors(
                sample["discount_rate"], years, ramp_years
            )
            capital = base_cost * sample["capital_cost_factor"]
            maintenance = capital * maintenance_share * sample["maintenance_cost_factor"]
            renewal = capital * renewal_share * sample["renewal_cost_factor"]
            residual = capital * residual_share
            pv_benefit = annual_benefit * benefit_factor
            pv_cost = (
                capital
                + maintenance * maintenance_factor
                + renewal * single_payment[renewal_year - 1]
                - residual * single_payment[-1]
            )
            bcr = np.divide(
                pv_benefit,
                pv_cost,
                out=np.full_like(pv_benefit, np.inf),
                where=pv_cost > 0,
            )
            npv = pv_benefit - pv_cost
            order = np.lexsort((np.asarray(candidate_ids), -bcr))
            ranks = np.empty(len(candidate_ids), dtype=np.int32)
            ranks[order] = np.arange(1, len(candidate_ids) + 1, dtype=np.int32)
            frontier = _pareto_indices(draw_users, pv_cost, candidate_ids)
            frontier_flags = np.zeros(len(candidate_ids), dtype=np.bool_)
            frontier_flags[frontier] = True
            top_flags = ranks <= top_k
            bcr_values[draw_index] = bcr
            rank_total += ranks
            top_k_count += top_flags
            frontier_count += frontier_flags
            writer.write_table(
                pa.Table.from_arrays(
                    [
                        pa.array(
                            np.full(len(candidate_ids), EVIDENCE_OUTPUT_SCHEMA_VERSION),
                            type=pa.int16(),
                        ),
                        pa.array([scenario_id] * len(candidate_ids)),
                        pa.array(np.full(len(candidate_ids), draw_index + 1), type=pa.int32()),
                        pa.array(candidate_ids),
                        pa.array(draw_users),
                        pa.array(draw_km),
                        pa.array(pv_benefit),
                        pa.array(pv_cost),
                        pa.array(npv),
                        pa.array(bcr),
                        pa.array(ranks),
                        pa.array(top_flags),
                        pa.array(frontier_flags),
                    ],
                    schema=UNCERTAINTY_RESULT_SCHEMA,
                )
            )
    finally:
        writer.close()
    temporary.replace(result_path)

    summaries = [
        {
            "candidate_id": candidate_id,
            "bcr_p05": float(np.quantile(bcr_values[:, index], 0.05)),
            "bcr_p50": float(np.quantile(bcr_values[:, index], 0.50)),
            "bcr_p95": float(np.quantile(bcr_values[:, index], 0.95)),
            "mean_rank": float(rank_total[index] / sample_count),
            "top_k_probability": float(top_k_count[index] / sample_count),
            "frontier_probability": float(frontier_count[index] / sample_count),
        }
        for index, candidate_id in enumerate(candidate_ids)
    ]
    return summaries, parameter_path, result_path


def _topology_from_payload(path: Path) -> DirectedTopology:
    payload = read_json(_artifact_file(path, "topology.json"))
    nodes = [
        Node(str(row["id"]), float(row["x"]), float(row["y"]), int(row.get("layer", 0)))
        for row in payload["nodes"]
    ]
    edges = [
        Edge(
            id=str(row["id"]),
            u=str(row["u"]),
            v=str(row["v"]),
            length_m=float(row["length_m"]),
            direction=Direction(str(row["direction"])),
            geometry=tuple((float(point[0]), float(point[1])) for point in row["geometry"]),
            road_class=RoadClass(str(row["road_class"])),
            facility=FacilityType(str(row["facility"])),
            source_way_id=str(row.get("source_way_id") or ""),
            bridge=bool(row.get("bridge")),
            tunnel=bool(row.get("tunnel")),
        )
        for row in payload["edges"]
    ]
    return DirectedTopology(nodes, edges)


def _counter_validation(
    context: StageContext,
    route_dir: Path,
    topology_dir: Path,
    configuration: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    location_source = context.sources.get("cycle_counter_locations")
    observation_source = context.sources.get("cycle_counter_observations")
    if (
        not location_source
        or not observation_source
        or not (location_source.usable and observation_source.usable)
    ):
        return [], {
            "status": "unavailable",
            "spatial_match_coverage": 0.0,
            "metrics": None,
            "null_model_metrics": None,
            "reason": "optional_counter_sources_not_available",
        }
    raw_locations = read_json(location_source.path)
    raw_observations = read_json(observation_source.path)
    daily = raw_observations.get("dailyAverages")
    observation_metadata = raw_observations.get("metadata")
    if not isinstance(raw_locations, list) or not isinstance(daily, Mapping):
        raise ProductionBlocker(
            stage="appraisal-uncertainty-validation",
            code="invalid_counter_source",
            message="counter sources do not contain locations and daily averages",
        )
    transformer = Transformer.from_crs("EPSG:4326", context.config.project.crs, always_xy=True)
    site_names: dict[str, str] = {}
    counters: list[CounterSite] = []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw_locations, start=1):
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name not in daily:
            continue
        try:
            x, y = transformer.transform(float(item["lng"]), float(item["lat"]))
            observed = float(daily[name])
        except (KeyError, TypeError, ValueError):
            continue
        counter_id = str(item.get("counter_id") or f"at-counter-{index:03d}")
        if counter_id in site_names:
            raise ProductionBlocker(
                stage="appraisal-uncertainty-validation",
                code="invalid_counter_source",
                message="counter source contains duplicate counter identifiers",
                evidence={"counter_id": counter_id},
            )
        counters.append(CounterSite(counter_id, x, y, observed))
        site_names[counter_id] = name

    topology = _topology_from_payload(topology_dir)
    edge_ids = list(topology.edges)
    geometries = [LineString(topology.edge(edge_id).geometry) for edge_id in edge_ids]
    tree = STRtree(geometries)
    maximum_distance = _finite(
        configuration.get("maximum_counter_match_distance_m"),
        field="validation.maximum_counter_match_distance_m",
    )
    preferred = {
        counter.id: frozenset(
            edge_ids[int(index)]
            for index in tree.query(ShapelyPoint(counter.x, counter.y).buffer(maximum_distance))
        )
        for counter in counters
    }
    matches, unmatched = match_counters(
        counters,
        topology,
        max_distance=maximum_distance,
        preferred_edge_ids=preferred,
    )
    flow_rows = pq.read_table(
        _artifact_file(route_dir, "edge_flows.parquet"),
        filters=[("purpose", "=", "commute")],
        columns=["project_edge_id", "estimated_observed_cycle"],
    ).to_pylist()
    flow = {
        str(row["project_edge_id"]): float(row["estimated_observed_cycle"]) for row in flow_rows
    }
    by_id = {counter.id: counter for counter in counters}
    for counter_id in sorted(by_id):
        counter = by_id[counter_id]
        match = matches.get(counter_id)
        if match is None:
            rows.append(
                {
                    "schema_version": EVIDENCE_OUTPUT_SCHEMA_VERSION,
                    "counter_id": counter_id,
                    "site_name": site_names[counter_id],
                    "observed_daily_all_purpose_cycles": counter.observed,
                    "predicted_usual_commute_cycle_people": None,
                    "matched_edge_id": None,
                    "match_distance_m": None,
                    "bearing_difference_degrees": None,
                    "match_basis": "distance_only_source_has_no_bearing_or_screenline",
                    "status": "unmatched",
                    "exclusion_reason": "no_edge_within_distance_gate",
                }
            )
            continue
        prediction = flow.get(match.edge_id, 0.0)
        rows.append(
            {
                "schema_version": EVIDENCE_OUTPUT_SCHEMA_VERSION,
                "counter_id": counter_id,
                "site_name": site_names[counter_id],
                "observed_daily_all_purpose_cycles": counter.observed,
                "predicted_usual_commute_cycle_people": prediction,
                "matched_edge_id": match.edge_id,
                "match_distance_m": match.distance,
                "bearing_difference_degrees": match.bearing_difference,
                "match_basis": "distance_only_source_has_no_bearing_or_screenline",
                "status": "spatially_matched_incompatible_measure",
                "exclusion_reason": "purpose_and_measure_not_aligned",
            }
        )
    coverage = len(matches) / len(counters) if counters else 0.0
    metadata = observation_metadata if isinstance(observation_metadata, Mapping) else {}
    minimum_pairs = int(configuration.get("minimum_counter_pairs", 0))
    return rows, {
        "status": "plausibility_only_incompatible_measure",
        "counter_records": len(counters),
        "matched_records": len(matches),
        "unmatched_records": len(unmatched),
        "spatial_match_coverage": coverage,
        "minimum_counter_pairs": minimum_pairs,
        "minimum_pair_threshold_met": len(matches) >= minimum_pairs,
        "metrics": None,
        "null_model_metrics": None,
        "spatial_holdout": "not_applicable_without_a_comparable_validation_target",
        "calibration": "none",
        "observation_period": {
            "start": metadata.get("period_start"),
            "end": metadata.get("period_end"),
            "days": metadata.get("observation_days"),
            "label": metadata.get("period_label"),
        },
        "observation_workbook_sha256": metadata.get("workbook_sha256"),
        "coordinate_registry_sha256": metadata.get("coordinate_registry_sha256"),
        "limitations": [
            "counter_source_has_no_direction_bearing_or_screenline",
            "daily_all_purpose_counts_are_not_aligned_to_usual_commute_people",
            "regression_metrics_with_incompatible_units_are_intentionally_not_reported",
            "coordinate_registry_exact_publisher_file_lineage_is_unresolved",
        ],
    }


def production_evidence_stage(context: StageContext) -> StageResult:
    """Produce explicit screening appraisal and evidence profiles."""

    portfolio_dir = context.dependencies["evaluate-portfolios"]["portfolios"].path
    route_dir = context.dependencies["assign-routes"]["routes"].path
    topology_dir = context.dependencies["build-topology"]["topology"].path
    appraisal = _mapping(context.config.parameters.get("appraisal"), field="appraisal")
    uncertainty = _mapping(context.config.parameters.get("uncertainty"), field="uncertainty")
    validation = _mapping(context.config.parameters.get("validation"), field="validation")
    scenario_id = str(appraisal.get("selected_scenario", ""))
    if not scenario_id:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_evidence_configuration",
            message="appraisal.selected_scenario must be declared",
        )
    cost_configuration = _mapping(
        _mapping(context.config.parameters.get("candidates"), field="candidates").get(
            "screening_cost"
        ),
        field="candidates.screening_cost",
    )
    if int(cost_configuration.get("price_base_year", -1)) != int(
        appraisal.get("price_base_year", -2)
    ):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="appraisal_price_base_mismatch",
            message="candidate costs and benefit values must use one declared price base",
        )
    table = pq.read_table(
        _artifact_file(portfolio_dir, "candidate_counterfactuals.parquet"),
        filters=[
            ("scenario_id", "=", scenario_id),
            ("purpose", "=", "commute"),
            ("objective", "=", "activity_addition"),
        ],
    )
    metrics = [
        row
        for row in table.to_pylist()
        if row["additional_cycle_users"] is not None
        and float(row["additional_cycle_users"]) > 0
        and row["annual_cycle_km"] is not None
        and float(row["annual_cycle_km"]) > 0
    ]
    if not metrics:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="no_appraisable_candidates",
            message="selected scenario has no positive commute counterfactuals",
            evidence={"scenario_id": scenario_id},
        )
    output_dir = context.artifact_dir / (
        "evidence-"
        + content_hash(
            {
                "portfolio": context.dependencies["evaluate-portfolios"]["portfolios"].sha256,
                "routes": context.dependencies["assign-routes"]["routes"].sha256,
                "topology": context.dependencies["build-topology"]["topology"].sha256,
                "appraisal": dict(appraisal),
                "uncertainty": dict(uncertainty),
                "validation": dict(validation),
            }
        )[:16]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    appraisal_rows = _central_appraisal_rows(metrics, appraisal)
    appraisal_path = output_dir / "candidate_appraisal.parquet"
    _write_parquet(appraisal_path, appraisal_rows, APPRAISAL_SCHEMA)
    uncertainty_summaries, parameter_path, result_path = _uncertainty_outputs(
        output_dir, metrics, appraisal, uncertainty
    )
    counter_rows, validation_summary = _counter_validation(
        context, route_dir, topology_dir, validation
    )
    counter_path = output_dir / "counter_validation.parquet"
    _write_parquet(counter_path, counter_rows, COUNTER_VALIDATION_SCHEMA)

    route_manifest = read_json(_artifact_file(route_dir, "manifest.json"))
    routing_coverage = float(
        route_manifest.get("coverage", {}).get(
            "commute_estimated_routing_coverage_of_complete_source_market", 0.0
        )
    )
    appraisal_lookup = {
        (str(row["candidate_id"]), str(row["discount_case"])): float(row["indicative_bcr"])
        for row in appraisal_rows
    }
    uncertainty_lookup = {str(row["candidate_id"]): row for row in uncertainty_summaries}
    metric_lookup = {str(row["candidate_id"]): row for row in metrics}
    warnings = [
        "indicative_screening_bcr_not_business_case_bcr",
        "provisional_corridor_unit_cost_range",
        "fixed_retained_route_choice_set_pending_full_network_reroute_check",
        "uncertainty_distributions_require_local_evidence_review",
        "counter_validation_is_spatial_plausibility_only",
    ]
    summary_rows = []
    for candidate_id in sorted(metric_lookup):
        sampled = uncertainty_lookup[candidate_id]
        summary_rows.append(
            {
                "schema_version": EVIDENCE_OUTPUT_SCHEMA_VERSION,
                "scenario_id": scenario_id,
                "candidate_id": candidate_id,
                "affected_od_count": int(metric_lookup[candidate_id]["affected_od_count"]),
                "routing_coverage": routing_coverage,
                "principal_indicative_bcr": appraisal_lookup[
                    (candidate_id, "principal_declining_rate")
                ],
                "discount_8pct_indicative_bcr": appraisal_lookup[
                    (candidate_id, "mandatory_8pct_sensitivity")
                ],
                "uncertainty_bcr_p05": sampled["bcr_p05"],
                "uncertainty_bcr_p50": sampled["bcr_p50"],
                "uncertainty_bcr_p95": sampled["bcr_p95"],
                "mean_rank": sampled["mean_rank"],
                "top_k_probability": sampled["top_k_probability"],
                "frontier_probability": sampled["frontier_probability"],
                "cost_evidence_status": str(cost_configuration.get("evidence_status")),
                "validation_alignment_status": str(validation_summary["status"]),
                "warnings": warnings,
            }
        )
    summary_path = output_dir / "candidate_evidence_profiles.parquet"
    _write_parquet(summary_path, summary_rows, EVIDENCE_SUMMARY_SCHEMA)
    files = {
        path.name: {"size": path.stat().st_size, "sha256": sha256_file(path)}
        for path in (
            appraisal_path,
            parameter_path,
            result_path,
            counter_path,
            summary_path,
        )
    }
    manifest_path = output_dir / "manifest.json"
    blockers = [
        "full_network_low_stress_reroute_check_pending",
        "authoritative_local_capital_maintenance_and_renewal_costs_pending",
        "mbcm_2025_price_update_factor_not_applied_to_2021_screening_base",
        "uncertainty_priors_require_local_and_literature_evidence_review",
        "counter_purpose_direction_and_screenline_alignment_unresolved",
        "stratified_manual_audits_pending",
    ]
    write_json_atomic(
        manifest_path,
        {
            "schema_version": EVIDENCE_OUTPUT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "scenario_id": scenario_id,
            "appraisal": {
                "standard": appraisal["standard"],
                "interpretation": "indicative_lifecycle_screening_bcr_not_business_case_bcr",
                "price_base_year": appraisal["price_base_year"],
                "principal_discount_schedule": appraisal["non_commercial_discount_schedule"],
                "mandatory_sensitivity_discount_rate": appraisal["sensitivity_discount_rate"],
                "benefit_scope": "capped_conventional_and_ebike_health_only",
                "excluded_unquantified_benefits": [
                    "crash_reduction",
                    "vehicle_operating_cost",
                    "travel_time",
                    "emissions",
                    "comfort",
                ],
            },
            "uncertainty": {
                "method": uncertainty["method"],
                "sample_count": uncertainty["sample_count"],
                "seed": uncertainty["seed"],
                "dimensions": list(MATERIAL_UNCERTAINTY_DIMENSIONS),
                "iid_od_bootstrap": False,
                "interpretation": "conditional_parameter_ensemble_not_confidence_interval",
            },
            "validation": validation_summary,
            "row_counts": {
                "appraisal_cases": len(appraisal_rows),
                "uncertainty_parameter_draws": int(uncertainty["sample_count"]),
                "candidate_uncertainty_draws": len(metrics) * int(uncertainty["sample_count"]),
                "candidate_evidence_profiles": len(summary_rows),
                "counter_records": len(counter_rows),
            },
            "publication_grade_ready": False,
            "publication_blockers": blockers,
            "files": files,
        },
    )
    return StageResult(
        {"evidence": output_dir},
        {
            "row_counts": {
                "appraisal_cases": len(appraisal_rows),
                "candidate_evidence_profiles": len(summary_rows),
                "counter_records": len(counter_rows),
            },
            "sample_count": int(uncertainty["sample_count"]),
            "validation_coverage": float(validation_summary["spatial_match_coverage"]),
        },
    )
