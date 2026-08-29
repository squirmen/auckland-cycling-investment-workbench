"""Resumable production routing for independent Auckland purpose markets."""

from __future__ import annotations

import gc
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from .demand import (
    PCT_2020_EBIKE,
    PCT_2020_GO_DUTCH,
    PCT_2020_GOVERNMENT_TARGET,
    CountInterval,
    PCTFeatures,
    ScenarioUnit,
    allocate_additional_scenario,
    pct_probability,
    pct_scenario_counts,
)
from .pipeline import ProductionBlocker, StageContext, StageResult
from .provenance import content_hash, read_json, sha256_file, write_json_atomic
from .r5_routing import (
    ProjectTopologyIndex,
    R5CyclingEngine,
    RouteSample,
    SnapNode,
    path_gradient_metrics,
    select_route_sample,
)

ROUTE_OUTPUT_SCHEMA_VERSION = 3


OD_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("od_id", pa.string()),
        ("source_cell_id", pa.string()),
        ("origin_support_id", pa.string()),
        ("destination_support_id", pa.string()),
        ("purpose", pa.string()),
        ("eligible", pa.float64()),
        ("observed_cycle", pa.float64()),
        ("upstream_selection_probability", pa.float64()),
        ("draw_count", pa.int32()),
        ("total_draws", pa.int32()),
        ("route_sample_selected", pa.bool_()),
        ("route_sample_rank", pa.int32()),
        ("route_stratum_size", pa.int32()),
        ("route_stratum_sample_size", pa.int32()),
        ("route_inclusion_probability", pa.float64()),
        ("analysis_weight", pa.float64()),
        ("weighted_eligible", pa.float64()),
        ("weighted_observed_cycle", pa.float64()),
        ("origin_x", pa.float64()),
        ("origin_y", pa.float64()),
        ("destination_x", pa.float64()),
        ("destination_y", pa.float64()),
        ("origin_node_id", pa.string()),
        ("destination_node_id", pa.string()),
        ("origin_snap_distance_m", pa.float64()),
        ("destination_snap_distance_m", pa.float64()),
        ("origin_component", pa.string()),
        ("destination_component", pa.string()),
        ("origin_layer", pa.int16()),
        ("destination_layer", pa.int16()),
        ("origin_engine_link_distance_m", pa.float64()),
        ("destination_engine_link_distance_m", pa.float64()),
        ("shortest_distance_m", pa.float64()),
        ("shortest_average_absolute_gradient_percent", pa.float64()),
        ("shortest_total_ascent_m", pa.float64()),
        ("status", pa.string()),
        ("failure_reason", pa.string()),
        ("path_ids", pa.list_(pa.string())),
        ("path_probabilities", pa.list_(pa.float64())),
        ("assigned_observed_cycle", pa.float64()),
        ("route_chunk", pa.int32()),
    ]
)

PATH_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("path_id", pa.string()),
        ("od_id", pa.string()),
        ("purpose", pa.string()),
        ("path_index", pa.int16()),
        ("probability", pa.float64()),
        ("generalized_cost", pa.float64()),
        ("length_m", pa.float64()),
        ("shortest_distance_m", pa.float64()),
        ("detour_ratio", pa.float64()),
        ("average_absolute_gradient_percent", pa.float64()),
        ("total_ascent_m", pa.float64()),
        ("total_descent_m", pa.float64()),
        ("r5_edge_ids", pa.list_(pa.int32())),
        ("r5_osm_way_ids", pa.list_(pa.int64())),
        ("project_edge_ids", pa.list_(pa.string())),
        ("project_edge_reversed", pa.list_(pa.bool_())),
    ]
)

PATH_EDGE_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("path_id", pa.string()),
        ("od_id", pa.string()),
        ("purpose", pa.string()),
        ("path_index", pa.int16()),
        ("edge_sequence", pa.int32()),
        ("project_edge_id", pa.string()),
        ("reversed", pa.bool_()),
        ("length_m", pa.float64()),
        ("generalized_cost", pa.float64()),
        ("directed_gradient_ratio", pa.float64()),
        ("path_probability", pa.float64()),
        ("estimated_observed_cycle", pa.float64()),
        ("estimated_eligible", pa.float64()),
    ]
)

EDGE_FLOW_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("project_edge_id", pa.string()),
        ("purpose", pa.string()),
        ("estimated_observed_cycle", pa.float64()),
        ("estimated_eligible", pa.float64()),
        ("path_edge_records", pa.int64()),
    ]
)

SCENARIO_OD_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("scenario_id", pa.string()),
        ("od_id", pa.string()),
        ("purpose", pa.string()),
        ("demand_unit", pa.string()),
        ("analysis_weight", pa.float64()),
        ("weighted_eligible", pa.float64()),
        ("weighted_observed_cycle", pa.float64()),
        ("scenario_cycle", pa.float64()),
        ("additional_cycle", pa.float64()),
        ("pct_probability", pa.float64()),
        ("route_distance_km", pa.float64()),
        ("average_absolute_gradient_percent", pa.float64()),
        ("route_status", pa.string()),
        ("failure_reason", pa.string()),
    ]
)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionBlocker(
            stage="assign-routes",
            code="invalid_routing_configuration",
            message=f"{field} must be a mapping",
            evidence={"field": field},
        )
    return value


def _positive_int(value: Any, *, field: str, allow_none: bool = False) -> int | None:
    if allow_none and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProductionBlocker(
            stage="assign-routes",
            code="invalid_routing_configuration",
            message=f"{field} must be a positive integer" + (" or null" if allow_none else ""),
            evidence={"field": field, "value": value},
        )
    return value


def _finite_float(
    value: Any,
    *,
    field: str,
    minimum: float | None = None,
    strictly_greater: bool = False,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductionBlocker(
            stage="assign-routes",
            code="invalid_routing_configuration",
            message=f"{field} must be numeric",
            evidence={"field": field, "value": value},
        ) from exc
    valid = result == result and result not in {float("inf"), float("-inf")}
    if minimum is not None:
        valid = valid and (result > minimum if strictly_greater else result >= minimum)
    if not valid:
        comparator = ">" if strictly_greater else ">="
        raise ProductionBlocker(
            stage="assign-routes",
            code="invalid_routing_configuration",
            message=f"{field} must be finite and {comparator} {minimum}",
            evidence={"field": field, "value": value},
        )
    return result


def _topology_inputs(path: Path) -> tuple[Mapping[str, Any], Path]:
    if not path.is_dir():
        raise ProductionBlocker(
            stage="assign-routes",
            code="topology_artifact_not_self_contained",
            message="production routing requires the directory-form topology artifact",
            evidence={"topology_artifact": path.name},
        )
    payload = path / "topology.json"
    pbfs = sorted(path.glob("*.osm.pbf"))
    if not payload.is_file() or len(pbfs) != 1:
        raise ProductionBlocker(
            stage="assign-routes",
            code="topology_artifact_incomplete",
            message="topology artifact must contain topology.json and exactly one bounded OSM PBF",
            evidence={"payload_exists": payload.is_file(), "pbf_count": len(pbfs)},
        )
    topology = read_json(payload)
    provenance = topology.get("osm_extract") if isinstance(topology, Mapping) else None
    expected = provenance.get("output_sha256") if isinstance(provenance, Mapping) else None
    actual = sha256_file(pbfs[0])
    if expected != actual:
        raise ProductionBlocker(
            stage="assign-routes",
            code="bounded_osm_hash_mismatch",
            message="bounded OSM PBF does not match topology provenance",
            evidence={"expected_sha256": expected, "actual_sha256": actual},
        )
    return topology, pbfs[0]


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    pq.write_table(
        pa.Table.from_pylist(list(rows), schema=schema),
        temporary,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
    )
    temporary.replace(path)


def _chunk_is_complete(manifest_path: Path, *, identity: str) -> bool:
    if not manifest_path.is_file():
        return False
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError):
        return False
    if not isinstance(manifest, Mapping) or manifest.get("identity") != identity:
        return False
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        return False
    for filename, expected in files.items():
        path = manifest_path.parent / str(filename)
        if not path.is_file() or sha256_file(path) != expected:
            return False
    return True


def _snap_failure_reason(
    topology: ProjectTopologyIndex,
    engine: R5CyclingEngine,
    record: Mapping[str, Any],
    *,
    maximum_distance_m: float,
) -> str:
    origin = topology.snaps_by_component(
        float(record["origin_x"]),
        float(record["origin_y"]),
        maximum_distance_m=maximum_distance_m,
        allowed_node_indices=engine.origin_node_indices,
    )
    destination = topology.snaps_by_component(
        float(record["destination_x"]),
        float(record["destination_y"]),
        maximum_distance_m=maximum_distance_m,
        allowed_node_indices=engine.destination_node_indices,
    )
    if not origin and not destination:
        return "origin_and_destination_outside_reconciled_engine_snap_radius"
    if not origin:
        return "origin_outside_reconciled_engine_snap_radius"
    if not destination:
        return "destination_outside_reconciled_engine_snap_radius"
    if set(origin).intersection(destination):
        return "no_distinct_reconciled_engine_snap_pair_within_radius"
    return "no_shared_reconciled_engine_component_within_snap_radius"


def _base_od_row(
    record: Mapping[str, Any],
    sample: RouteSample,
    *,
    route_chunk: int,
) -> dict[str, Any]:
    eligible = float(record["eligible"])
    observed = float(record["cycle"])
    return {
        "schema_version": ROUTE_OUTPUT_SCHEMA_VERSION,
        "od_id": str(record["id"]),
        "source_cell_id": str(record["source_cell_id"]),
        "origin_support_id": str(record["origin_support_id"]),
        "destination_support_id": str(record["destination_support_id"]),
        "purpose": str(record["purpose"]),
        "eligible": eligible,
        "observed_cycle": observed,
        "upstream_selection_probability": float(record["selection_probability"]),
        "draw_count": int(record["draw_count"]),
        "total_draws": int(record["total_draws"]),
        "route_sample_selected": sample.selected,
        "route_sample_rank": sample.rank,
        "route_stratum_size": sample.stratum_size,
        "route_stratum_sample_size": sample.stratum_sample_size,
        "route_inclusion_probability": sample.inclusion_probability,
        "analysis_weight": sample.analysis_weight if sample.selected else 0.0,
        "weighted_eligible": eligible * sample.analysis_weight if sample.selected else 0.0,
        "weighted_observed_cycle": observed * sample.analysis_weight if sample.selected else 0.0,
        "origin_x": float(record["origin_x"]),
        "origin_y": float(record["origin_y"]),
        "destination_x": float(record["destination_x"]),
        "destination_y": float(record["destination_y"]),
        "origin_node_id": None,
        "destination_node_id": None,
        "origin_snap_distance_m": None,
        "destination_snap_distance_m": None,
        "origin_component": None,
        "destination_component": None,
        "origin_layer": None,
        "destination_layer": None,
        "origin_engine_link_distance_m": None,
        "destination_engine_link_distance_m": None,
        "shortest_distance_m": None,
        "shortest_average_absolute_gradient_percent": None,
        "shortest_total_ascent_m": None,
        "status": "not_selected_probability_sample",
        "failure_reason": None,
        "path_ids": [],
        "path_probabilities": [],
        "assigned_observed_cycle": 0.0,
        "route_chunk": route_chunk,
    }


def _apply_snaps(row: dict[str, Any], origin: SnapNode, destination: SnapNode) -> None:
    row.update(
        {
            "origin_node_id": origin.node_id,
            "destination_node_id": destination.node_id,
            "origin_snap_distance_m": origin.distance_m,
            "destination_snap_distance_m": destination.distance_m,
            "origin_component": origin.component_id,
            "destination_component": destination.component_id,
            "origin_layer": origin.layer,
            "destination_layer": destination.layer,
        }
    )


def _route_chunk(
    records: Sequence[Mapping[str, Any]],
    samples: Mapping[str, RouteSample],
    *,
    chunk_index: int,
    topology: ProjectTopologyIndex,
    engine: R5CyclingEngine,
    parameters: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    od_rows: list[dict[str, Any]] = []
    path_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    maximum_snap = float(parameters["maximum_snap_distance_m"])
    for record in records:
        sample = samples[str(record["id"])]
        row = _base_od_row(record, sample, route_chunk=chunk_index)
        pair = topology.snap_pair(
            float(record["origin_x"]),
            float(record["origin_y"]),
            float(record["destination_x"]),
            float(record["destination_y"]),
            maximum_distance_m=maximum_snap,
            origin_allowed_node_indices=engine.origin_node_indices,
            destination_allowed_node_indices=engine.destination_node_indices,
        )
        if pair is None:
            row["status"] = "unassigned"
            row["failure_reason"] = _snap_failure_reason(
                topology, engine, record, maximum_distance_m=maximum_snap
            )
            od_rows.append(row)
            continue
        origin, destination = pair
        _apply_snaps(row, origin, destination)
        result = engine.route(
            origin,
            destination,
            plausible_paths=int(parameters["plausible_paths"]),
            maximum_cost_ratio=float(parameters["maximum_cost_ratio"]),
            maximum_detour_ratio=float(parameters["maximum_detour_ratio"]),
            maximum_shared_edge_ratio=float(parameters["maximum_shared_edge_ratio"]),
            cost_scale=float(parameters["path_size_logit_cost_scale"]),
            path_size_coefficient=float(parameters["path_size_coefficient"]),
            alternative_penalty_multiplier=float(parameters["alternative_penalty_multiplier"]),
            maximum_alternative_attempts=int(parameters["maximum_alternative_attempts"]),
            engine_link_tolerance_m=float(parameters["engine_link_tolerance_m"]),
        )
        row["origin_engine_link_distance_m"] = result.origin_engine_link_distance_m
        row["destination_engine_link_distance_m"] = result.destination_engine_link_distance_m
        row["shortest_distance_m"] = result.shortest_distance_m
        row["shortest_average_absolute_gradient_percent"] = (
            result.shortest_average_absolute_gradient_percent
        )
        row["shortest_total_ascent_m"] = result.shortest_total_ascent_m
        if result.status != "assigned":
            row["status"] = "unassigned"
            row["failure_reason"] = result.failure_reason
            od_rows.append(row)
            continue
        observed = float(record["cycle"])
        eligible = float(record["eligible"])
        weighted_observed = observed * sample.analysis_weight
        weighted_eligible = eligible * sample.analysis_weight
        path_ids = [
            f"{record['id']}:path:{index}" for index in range(1, len(result.alternatives) + 1)
        ]
        row["status"] = "assigned"
        row["path_ids"] = path_ids
        row["path_probabilities"] = [item.probability for item in result.alternatives]
        row["assigned_observed_cycle"] = weighted_observed
        for path_index, (path_id, alternative) in enumerate(
            zip(path_ids, result.alternatives, strict=True), start=1
        ):
            path = alternative.path
            average_gradient, total_ascent, total_descent = path_gradient_metrics(
                path, topology.segments
            )
            edge_ids = [topology.segments[item.segment_index].edge_id for item in path.traversals]
            path_rows.append(
                {
                    "schema_version": ROUTE_OUTPUT_SCHEMA_VERSION,
                    "path_id": path_id,
                    "od_id": str(record["id"]),
                    "purpose": str(record["purpose"]),
                    "path_index": path_index,
                    "probability": alternative.probability,
                    "generalized_cost": path.generalized_cost,
                    "length_m": path.length_m,
                    "shortest_distance_m": result.shortest_distance_m,
                    "detour_ratio": alternative.detour_ratio,
                    "average_absolute_gradient_percent": average_gradient,
                    "total_ascent_m": total_ascent,
                    "total_descent_m": total_descent,
                    "r5_edge_ids": list(path.r5_edge_ids),
                    "r5_osm_way_ids": list(path.r5_osm_way_ids),
                    "project_edge_ids": edge_ids,
                    "project_edge_reversed": [item.reversed for item in path.traversals],
                }
            )
            for edge_sequence, traversal in enumerate(path.traversals, start=1):
                segment = topology.segments[traversal.segment_index]
                generalized = (
                    segment.generalized_reverse
                    if traversal.reversed
                    else segment.generalized_forward
                )
                edge_rows.append(
                    {
                        "schema_version": ROUTE_OUTPUT_SCHEMA_VERSION,
                        "path_id": path_id,
                        "od_id": str(record["id"]),
                        "purpose": str(record["purpose"]),
                        "path_index": path_index,
                        "edge_sequence": edge_sequence,
                        "project_edge_id": segment.edge_id,
                        "reversed": traversal.reversed,
                        "length_m": segment.length_m,
                        "generalized_cost": generalized,
                        "directed_gradient_ratio": (
                            -segment.gradient_ratio
                            if traversal.reversed
                            else segment.gradient_ratio
                        ),
                        "path_probability": alternative.probability,
                        "estimated_observed_cycle": weighted_observed * alternative.probability,
                        "estimated_eligible": weighted_eligible * alternative.probability,
                    }
                )
        od_rows.append(row)
    return od_rows, path_rows, edge_rows


def _merge_parquet(sources: Sequence[Path], destination: Path, schema: pa.Schema) -> int:
    temporary = destination.with_name(destination.name + ".tmp")
    writer = pq.ParquetWriter(temporary, schema, compression="zstd", use_dictionary=True)
    row_count = 0
    try:
        for source in sources:
            table = pq.read_table(source, schema=schema)
            writer.write_table(table)
            row_count += table.num_rows
    finally:
        writer.close()
    temporary.replace(destination)
    return row_count


def _selected_od_rows(chunk_files: Sequence[Path]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in chunk_files:
        for row in pq.read_table(path, schema=OD_SCHEMA).to_pylist():
            rows[str(row["od_id"])] = row
    return rows


def _write_complete_od_ledger(
    destination: Path,
    records: Sequence[Mapping[str, Any]],
    samples: Mapping[str, RouteSample],
    selected_rows: Mapping[str, Mapping[str, Any]],
    *,
    batch_size: int = 10_000,
) -> int:
    temporary = destination.with_name(destination.name + ".tmp")
    writer = pq.ParquetWriter(temporary, OD_SCHEMA, compression="zstd", use_dictionary=True)
    buffer: list[Mapping[str, Any]] = []
    count = 0
    try:
        for record in sorted(records, key=lambda item: str(item["id"])):
            record_id = str(record["id"])
            sample = samples[record_id]
            row = selected_rows.get(record_id)
            if sample.selected and row is None:
                raise ProductionBlocker(
                    stage="assign-routes",
                    code="routing_chunk_ledger_incomplete",
                    message="a selected OD record has no routed chunk ledger row",
                    evidence={"od_id": record_id},
                )
            buffer.append(row or _base_od_row(record, sample, route_chunk=-1))
            if len(buffer) >= batch_size:
                writer.write_table(pa.Table.from_pylist(buffer, schema=OD_SCHEMA))
                count += len(buffer)
                buffer.clear()
        if buffer:
            writer.write_table(pa.Table.from_pylist(buffer, schema=OD_SCHEMA))
            count += len(buffer)
    finally:
        writer.close()
    temporary.replace(destination)
    return count


def _write_failure_ledger(destination: Path, selected_rows: Mapping[str, Mapping[str, Any]]) -> int:
    failures = [
        row for _, row in sorted(selected_rows.items()) if row.get("status") == "unassigned"
    ]
    _write_parquet(destination, failures, OD_SCHEMA)
    return len(failures)


def _write_edge_flows(destination: Path, path_edge_files: Sequence[Path]) -> tuple[int, int]:
    flows: dict[tuple[str, str], list[float | int]] = defaultdict(lambda: [0.0, 0.0, 0])
    path_edge_count = 0
    for path in path_edge_files:
        table = pq.read_table(
            path,
            columns=[
                "project_edge_id",
                "purpose",
                "estimated_observed_cycle",
                "estimated_eligible",
            ],
        )
        for row in table.to_pylist():
            key = (str(row["purpose"]), str(row["project_edge_id"]))
            values = flows[key]
            values[0] = float(values[0]) + float(row["estimated_observed_cycle"])
            values[1] = float(values[1]) + float(row["estimated_eligible"])
            values[2] = int(values[2]) + 1
            path_edge_count += 1
    rows = [
        {
            "schema_version": ROUTE_OUTPUT_SCHEMA_VERSION,
            "project_edge_id": edge_id,
            "purpose": purpose,
            "estimated_observed_cycle": values[0],
            "estimated_eligible": values[1],
            "path_edge_records": values[2],
        }
        for (purpose, edge_id), values in sorted(flows.items())
    ]
    _write_parquet(destination, rows, EDGE_FLOW_SCHEMA)
    return len(rows), path_edge_count


def _write_zonal_ledger(destination: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise ProductionBlocker(
            stage="assign-routes",
            code="missing_zonal_market_ledger",
            message="prepared demand has no zonal OD market ledger",
        )
    table = pa.Table.from_pylist([dict(row) for row in rows])
    temporary = destination.with_name(destination.name + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=True)
    temporary.replace(destination)


def _write_commute_scenarios(
    destination: Path,
    selected_rows: Mapping[str, Mapping[str, Any]],
    *,
    complete_market_eligible: float,
    complete_market_observed_cycle: float,
    target_share: float,
) -> tuple[int, Mapping[str, Any]]:
    """Write PCT scenarios and an externally denominated 8% sensitivity."""

    if not 0 <= target_share <= 1:
        raise ProductionBlocker(
            stage="assign-routes",
            code="invalid_scenario_configuration",
            message="demand-response target share must be in [0, 1]",
            evidence={"target_share": target_share},
        )
    commute_rows = [row for row in selected_rows.values() if str(row.get("purpose")) == "commute"]
    assigned = [row for row in commute_rows if row.get("status") == "assigned"]
    units = tuple(
        ScenarioUnit(
            str(row["od_id"]),
            float(row["weighted_eligible"]),
            CountInterval(
                float(row["weighted_observed_cycle"]),
                float(row["weighted_observed_cycle"]),
                float(row["weighted_observed_cycle"]),
                "confidentiality_point_estimate_with_route_sample_weight",
            ),
            PCTFeatures(
                float(row["shortest_distance_m"]) / 1000,
                float(row["shortest_average_absolute_gradient_percent"]),
            ),
        )
        for row in sorted(assigned, key=lambda item: str(item["od_id"]))
    )
    by_id = {unit.id: unit for unit in units}
    scenario_counts = {
        "baseline": {unit.id: unit.observed.point for unit in units},
        "government_target": pct_scenario_counts(units, PCT_2020_GOVERNMENT_TARGET),
        "go_dutch": pct_scenario_counts(units, PCT_2020_GO_DUTCH),
        "ebike": pct_scenario_counts(units, PCT_2020_EBIKE),
    }
    requested_additional = max(
        0.0, target_share * complete_market_eligible - complete_market_observed_cycle
    )
    target = allocate_additional_scenario(
        units,
        requested_additional,
        coefficients=PCT_2020_EBIKE,
    )
    scenario_counts["commute_8pct"] = {
        unit.id: unit.observed.point + target.additional_by_od[unit.id] for unit in units
    }
    coefficient_by_scenario = {
        "government_target": PCT_2020_GOVERNMENT_TARGET,
        "go_dutch": PCT_2020_GO_DUTCH,
        "ebike": PCT_2020_EBIKE,
        "commute_8pct": PCT_2020_EBIKE,
    }
    output: list[dict[str, Any]] = []
    for scenario_id in (
        "baseline",
        "government_target",
        "go_dutch",
        "ebike",
        "commute_8pct",
    ):
        for row in sorted(commute_rows, key=lambda item: str(item["od_id"])):
            od_id = str(row["od_id"])
            unit = by_id.get(od_id)
            scenario_cycle = scenario_counts[scenario_id].get(od_id)
            output.append(
                {
                    "schema_version": ROUTE_OUTPUT_SCHEMA_VERSION,
                    "scenario_id": scenario_id,
                    "od_id": od_id,
                    "purpose": "commute",
                    "demand_unit": "weighted_census_main_means_of_travel_to_work_persons",
                    "analysis_weight": float(row["analysis_weight"]),
                    "weighted_eligible": float(row["weighted_eligible"]),
                    "weighted_observed_cycle": float(row["weighted_observed_cycle"]),
                    "scenario_cycle": scenario_cycle,
                    "additional_cycle": (
                        scenario_cycle - float(row["weighted_observed_cycle"])
                        if scenario_cycle is not None
                        else None
                    ),
                    "pct_probability": (
                        pct_probability(unit.features, coefficient_by_scenario[scenario_id])
                        if unit is not None and scenario_id != "baseline"
                        else None
                    ),
                    "route_distance_km": unit.features.distance_km if unit is not None else None,
                    "average_absolute_gradient_percent": (
                        unit.features.gradient_percent if unit is not None else None
                    ),
                    "route_status": str(row["status"]),
                    "failure_reason": row.get("failure_reason"),
                }
            )
    _write_parquet(destination, output, SCENARIO_OD_SCHEMA)
    summaries = {
        scenario_id: {
            "assigned_route_sample_total": sum(values.values()),
            "assigned_route_sample_additional": sum(
                values[unit.id] - unit.observed.point for unit in units
            ),
        }
        for scenario_id, values in scenario_counts.items()
    }
    summaries["commute_8pct"].update(
        {
            "complete_source_market_eligible": complete_market_eligible,
            "complete_source_market_observed_cycle": complete_market_observed_cycle,
            "target_share": target_share,
            "target_additional": target.target_additional,
            "achieved_additional": target.achieved_additional,
            "unallocated": target.unallocated,
            "denominator_not_shrunk_to_routable_sample": True,
        }
    )
    return len(output), summaries


def production_routing_stage(context: StageContext) -> StageResult:
    """Route a declared stratified sample and retain every demand record."""

    routing = _mapping(context.config.parameters.get("routing"), field="parameters.routing")
    sampling = _mapping(routing.get("sampling"), field="parameters.routing.sampling")
    network = _mapping(context.config.parameters.get("network"), field="parameters.network")
    comfort = _mapping(network.get("comfort_impedance"), field="network.comfort_impedance")
    raw_sample_sizes = _mapping(
        sampling.get("records_per_stratum_by_purpose"),
        field="routing.sampling.records_per_stratum_by_purpose",
    )
    expected_purposes = {"commute", "school", "everyday", "transit"}
    if set(raw_sample_sizes) != expected_purposes:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_routing_configuration",
            message="routing sample sizes must declare all four purpose markets exactly",
            evidence={"expected": sorted(expected_purposes), "actual": sorted(raw_sample_sizes)},
        )
    sample_sizes = {
        purpose: _positive_int(
            raw_sample_sizes[purpose],
            field=f"routing.sampling.records_per_stratum_by_purpose.{purpose}",
            allow_none=True,
        )
        for purpose in sorted(expected_purposes)
    }
    seed = sampling.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_routing_configuration",
            message="routing.sampling.seed must be an integer",
            evidence={"value": seed},
        )
    chunk_size = _positive_int(routing.get("chunk_size"), field="routing.chunk_size")
    assert chunk_size is not None
    parameters = {
        "maximum_snap_distance_m": _finite_float(
            network.get("maximum_snap_distance_m"),
            field="network.maximum_snap_distance_m",
            minimum=0,
            strictly_greater=True,
        ),
        "plausible_paths": _positive_int(
            routing.get("plausible_paths"), field="routing.plausible_paths"
        ),
        "maximum_cost_ratio": _finite_float(
            routing.get("maximum_cost_ratio"),
            field="routing.maximum_cost_ratio",
            minimum=1,
        ),
        "maximum_detour_ratio": _finite_float(
            routing.get("maximum_detour_ratio"),
            field="routing.maximum_detour_ratio",
            minimum=1,
        ),
        "maximum_shared_edge_ratio": _finite_float(
            routing.get("maximum_shared_edge_ratio"),
            field="routing.maximum_shared_edge_ratio",
            minimum=0,
        ),
        "path_size_logit_cost_scale": _finite_float(
            routing.get("path_size_logit_cost_scale"),
            field="routing.path_size_logit_cost_scale",
            minimum=0,
        ),
        "path_size_coefficient": _finite_float(
            routing.get("path_size_coefficient"),
            field="routing.path_size_coefficient",
            minimum=0,
        ),
        "alternative_penalty_multiplier": _finite_float(
            routing.get("alternative_penalty_multiplier"),
            field="routing.alternative_penalty_multiplier",
            minimum=1,
            strictly_greater=True,
        ),
        "maximum_alternative_attempts": _positive_int(
            routing.get("maximum_alternative_attempts"),
            field="routing.maximum_alternative_attempts",
        ),
        "engine_link_tolerance_m": _finite_float(
            routing.get("engine_link_tolerance_m"),
            field="routing.engine_link_tolerance_m",
            minimum=0,
        ),
    }
    shared_ratio = float(parameters["maximum_shared_edge_ratio"])
    if shared_ratio > 1:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_routing_configuration",
            message="routing.maximum_shared_edge_ratio must not exceed one",
            evidence={"value": shared_ratio},
        )
    plausible_paths = int(parameters["plausible_paths"])
    alternative_attempts = int(parameters["maximum_alternative_attempts"])
    if alternative_attempts < plausible_paths - 1:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_routing_configuration",
            message=(
                "routing.maximum_alternative_attempts must be at least "
                "routing.plausible_paths minus one"
            ),
            evidence={
                "plausible_paths": plausible_paths,
                "maximum_alternative_attempts": alternative_attempts,
            },
        )

    topology_artifact = context.dependencies["build-topology"]["topology"]
    topology_payload, pbf_path = _topology_inputs(topology_artifact.path)
    identity = content_hash(
        {
            "schema_version": ROUTE_OUTPUT_SCHEMA_VERSION,
            "topology_sha256": topology_artifact.sha256,
            "demand_sha256": context.dependencies["prepare-demand"]["demand"].sha256,
            "routing": routing,
            "network": network,
        }
    )
    work_dir = context.artifact_dir / f"routing-work-{identity[:16]}"
    output_dir = context.artifact_dir / f"routes-{identity[:16]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    topology = ProjectTopologyIndex.from_payload(
        topology_payload,
        comfort_parameters=comfort,
    )
    del topology_payload
    gc.collect()
    maximum_bicycle_lts = _positive_int(
        routing.get("maximum_bicycle_lts"), field="routing.maximum_bicycle_lts"
    )
    if maximum_bicycle_lts not in {1, 2, 3, 4}:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_routing_configuration",
            message="routing.maximum_bicycle_lts must be in 1..4",
            evidence={"value": maximum_bicycle_lts},
        )
    engine = R5CyclingEngine(
        pbf_path,
        topology,
        project_crs=context.config.project.crs,
        bicycle_speed_kph=_finite_float(
            routing.get("bicycle_speed_kph"),
            field="routing.bicycle_speed_kph",
            minimum=0,
            strictly_greater=True,
        ),
        maximum_bicycle_lts=maximum_bicycle_lts,
        unmapped_edge_multiplier=_finite_float(
            routing.get("unmapped_edge_multiplier"),
            field="routing.unmapped_edge_multiplier",
            minimum=1,
        ),
    )

    # Load the large demand JSON only after the raw topology payload has been
    # converted to compact arrays and released. This keeps the peak resident
    # set below the documented full-build memory ceiling.
    demand_payload = read_json(context.dependencies["prepare-demand"]["demand"].path)
    if not isinstance(demand_payload, Mapping):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_prepared_demand",
            message="prepared demand must be a JSON object",
        )
    blockers = demand_payload.get("publication_blockers")
    if isinstance(blockers, list) and blockers:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="prepared_demand_not_publication_grade",
            message="routing cannot proceed while prepared demand has proxy fallbacks",
            evidence={"blockers": blockers},
        )
    commute_records = demand_payload.get("disaggregated_commute_ledger")
    non_commute_records = demand_payload.get("non_commute_purpose_od_ledger")
    zonal_rows = demand_payload.get("zonal_od_ledger")
    if (
        not isinstance(commute_records, list)
        or not isinstance(non_commute_records, list)
        or not isinstance(zonal_rows, list)
    ):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="prepared_demand_ledgers_missing",
            message="prepared demand requires commute, non-commute, and zonal ledgers",
        )
    records = [*commute_records, *non_commute_records]
    purposes = sorted({str(record.get("purpose", "")) for record in records})
    if set(purposes) != expected_purposes:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="incomplete_purpose_markets",
            message="routing requires four independently generated purpose markets",
            evidence={"expected": sorted(expected_purposes), "actual": purposes},
        )
    sample_rows = tuple(
        sample
        for purpose in purposes
        for sample in select_route_sample(
            [record for record in records if str(record["purpose"]) == purpose],
            records_per_stratum=sample_sizes[purpose],
            seed=seed,
        )
    )
    samples = {item.record_id: item for item in sample_rows}
    del sample_rows
    selected = tuple(
        sorted(
            (record for record in records if samples[str(record["id"])].selected),
            key=lambda item: str(item["id"]),
        )
    )

    chunk_od_files: list[Path] = []
    chunk_path_files: list[Path] = []
    chunk_edge_files: list[Path] = []
    for chunk_index, start in enumerate(range(0, len(selected), chunk_size)):
        chunk_records = selected[start : start + chunk_size]
        chunk_identity = content_hash(
            {
                "routing_identity": identity,
                "chunk_index": chunk_index,
                "record_ids": [str(item["id"]) for item in chunk_records],
            }
        )
        prefix = f"chunk-{chunk_index:05d}"
        chunk_manifest = work_dir / f"{prefix}.json"
        od_path = work_dir / f"{prefix}-od.parquet"
        paths_path = work_dir / f"{prefix}-paths.parquet"
        edges_path = work_dir / f"{prefix}-path-edges.parquet"
        if not _chunk_is_complete(chunk_manifest, identity=chunk_identity):
            od_rows, path_rows, edge_rows = _route_chunk(
                chunk_records,
                samples,
                chunk_index=chunk_index,
                topology=topology,
                engine=engine,
                parameters=parameters,
            )
            _write_parquet(od_path, od_rows, OD_SCHEMA)
            _write_parquet(paths_path, path_rows, PATH_SCHEMA)
            _write_parquet(edges_path, edge_rows, PATH_EDGE_SCHEMA)
            write_json_atomic(
                chunk_manifest,
                {
                    "schema_version": 1,
                    "identity": chunk_identity,
                    "row_counts": {
                        "od": len(od_rows),
                        "paths": len(path_rows),
                        "path_edges": len(edge_rows),
                    },
                    "files": {
                        od_path.name: sha256_file(od_path),
                        paths_path.name: sha256_file(paths_path),
                        edges_path.name: sha256_file(edges_path),
                    },
                },
            )
        chunk_od_files.append(od_path)
        chunk_path_files.append(paths_path)
        chunk_edge_files.append(edges_path)

    selected_rows = _selected_od_rows(chunk_od_files)
    od_ledger = output_dir / "od_ledger.parquet"
    path_ledger = output_dir / "path_ledger.parquet"
    path_edge_ledger = output_dir / "path_edge_ledger.parquet"
    edge_flows = output_dir / "edge_flows.parquet"
    failure_ledger = output_dir / "failure_ledger.parquet"
    zonal_ledger = output_dir / "zonal_market_ledger.parquet"
    od_count = _write_complete_od_ledger(od_ledger, records, samples, selected_rows)
    path_count = _merge_parquet(chunk_path_files, path_ledger, PATH_SCHEMA)
    path_edge_count = _merge_parquet(chunk_edge_files, path_edge_ledger, PATH_EDGE_SCHEMA)
    edge_count, aggregated_path_edge_count = _write_edge_flows(edge_flows, chunk_edge_files)
    if path_edge_count != aggregated_path_edge_count:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="path_edge_aggregation_mismatch",
            message="edge-flow aggregation did not consume every path-edge record",
            evidence={
                "ledger_records": path_edge_count,
                "aggregated_records": aggregated_path_edge_count,
            },
        )
    failure_count = _write_failure_ledger(failure_ledger, selected_rows)
    _write_zonal_ledger(zonal_ledger, zonal_rows)

    assigned_rows = [row for row in selected_rows.values() if row["status"] == "assigned"]
    exact_eligible_by_purpose = {
        purpose: sum(
            float(record["eligible"]) for record in records if str(record["purpose"]) == purpose
        )
        for purpose in purposes
    }
    estimated_assigned_by_purpose = {
        purpose: sum(
            float(row["weighted_eligible"])
            for row in assigned_rows
            if str(row["purpose"]) == purpose
        )
        for purpose in purposes
    }
    weighted_attempted_by_purpose = {
        purpose: sum(
            float(row["weighted_eligible"])
            for row in selected_rows.values()
            if str(row["purpose"]) == purpose
        )
        for purpose in purposes
    }
    failure_share_by_purpose = {
        purpose: (
            (weighted_attempted_by_purpose[purpose] - estimated_assigned_by_purpose[purpose])
            / weighted_attempted_by_purpose[purpose]
            if weighted_attempted_by_purpose[purpose] > 0
            else 0.0
        )
        for purpose in purposes
    }
    route_failure_share = failure_share_by_purpose["commute"]
    source_market = demand_payload.get("structural_censoring")
    source_market = (
        source_market.get("unresolved_market_ledger")
        if isinstance(source_market, Mapping)
        else None
    )
    source_market_denominator = (
        float(source_market.get("source_market_total_stated_margin_point", 0))
        if isinstance(source_market, Mapping)
        else 0.0
    )
    source_market_observed_cycle = (
        float(source_market.get("source_market_bicycle_margin_point", 0))
        if isinstance(source_market, Mapping)
        else 0.0
    )
    demand_response = _mapping(
        context.config.parameters.get("demand_response"),
        field="parameters.demand_response",
    )
    target_scenario = _mapping(
        demand_response.get("target_scenario"),
        field="parameters.demand_response.target_scenario",
    )
    target_share = _finite_float(
        target_scenario.get("target_share"),
        field="demand_response.target_scenario.target_share",
        minimum=0,
    )
    if target_share > 1:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_scenario_configuration",
            message="demand-response target share must not exceed one",
        )
    scenario_ledger = output_dir / "scenario_od_ledger.parquet"
    scenario_count, scenario_summaries = _write_commute_scenarios(
        scenario_ledger,
        selected_rows,
        complete_market_eligible=source_market_denominator,
        complete_market_observed_cycle=source_market_observed_cycle,
        target_share=target_share,
    )
    outputs = {
        path.name: {"size": path.stat().st_size, "sha256": sha256_file(path)}
        for path in (
            od_ledger,
            path_ledger,
            path_edge_ledger,
            edge_flows,
            failure_ledger,
            zonal_ledger,
            scenario_ledger,
        )
    }
    manifest_path = output_dir / "manifest.json"
    write_json_atomic(
        manifest_path,
        {
            "schema_version": ROUTE_OUTPUT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "routing_identity": identity,
            "purposes": purposes,
            "markets": {
                "commute": "present_day_observed_cycle_plausibility_case",
                "school": "modelled_enrolment_access_not_observed_cycling",
                "everyday": "person_equivalent_opportunity_access_index_not_daily_trips",
                "transit": "person_equivalent_major_node_access_index_not_patronage",
            },
            "pct_features": {
                "route": "shortest_physical_route_on_same_source_identity_graph",
                "distance_unit": "km",
                "hilliness_unit": "percent",
                "hilliness_definition": ("length_weighted_mean_absolute_edge_gradient_percent"),
                "ascent_unit": "m",
                "source_method": "PCT commuting manual C1 version 1.4r",
                "auckland_terrain_interpretation": (
                    "declared approximation requiring DEM and hilliness sensitivity"
                ),
            },
            "engine": {
                "r5py_version": "1.1.7",
                "r5_release": "7.5.1-r5py",
                "bounded_osm_sha256": sha256_file(pbf_path),
                "mapping_diagnostics": dict(engine.mapping_diagnostics),
            },
            "sampling": {
                "design": "stratified_simple_random_without_replacement",
                "stratum": "purpose_specific_source_cell_id",
                "records_per_stratum_by_purpose": sample_sizes,
                "seed": seed,
                "inverse_probability_weighting": "Horvitz-Thompson",
                "all_records_retained_in_od_ledger": True,
            },
            "parameters": parameters,
            "row_counts": {
                "disaggregated_od": od_count,
                "selected_for_routing": len(selected),
                "assigned_selected_od": len(assigned_rows),
                "routing_failures": failure_count,
                "paths": path_count,
                "path_edges": path_edge_count,
                "edges_with_estimated_flow": edge_count,
                "zonal_market_od": len(zonal_rows),
                "scenario_od": scenario_count,
            },
            "scenario_summaries": scenario_summaries,
            "coverage": {
                "by_purpose": {
                    purpose: {
                        "unit_specific_denominator": exact_eligible_by_purpose[purpose],
                        "weighted_attempted": weighted_attempted_by_purpose[purpose],
                        "estimated_assigned": estimated_assigned_by_purpose[purpose],
                        "estimated_routing_coverage": (
                            estimated_assigned_by_purpose[purpose]
                            / exact_eligible_by_purpose[purpose]
                            if exact_eligible_by_purpose[purpose] > 0
                            else 0.0
                        ),
                        "routing_failure_share_of_weighted_attempted": (
                            failure_share_by_purpose[purpose]
                        ),
                    }
                    for purpose in purposes
                },
                "commute_complete_source_market_denominator": source_market_denominator,
                "commute_estimated_routing_coverage_of_complete_source_market": (
                    estimated_assigned_by_purpose["commute"] / source_market_denominator
                    if source_market_denominator > 0
                    else 0.0
                ),
                "cross_purpose_units_are_not_summed": True,
            },
            "publication_grade_ready": False,
            "publication_blockers": [
                "route_choice_parameter_uncertainty_pending",
                "non_commute_access_market_parameter_uncertainty_pending",
                "terrain_and_pct_hilliness_sensitivity_pending",
                "stratified_manual_route_and_extreme_snap_audit_pending",
            ],
            "files": outputs,
        },
    )
    return StageResult(
        {"routes": output_dir},
        {
            "row_counts": {
                "disaggregated_od": od_count,
                "selected_for_routing": len(selected),
                "assigned_selected_od": len(assigned_rows),
                "paths": path_count,
                "path_edges": path_edge_count,
                "edges_with_estimated_flow": edge_count,
                "scenario_od": scenario_count,
            },
            "routing_failures": failure_count,
            "routing_failure_share": route_failure_share,
        },
    )
