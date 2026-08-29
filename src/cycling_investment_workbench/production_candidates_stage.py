"""Complete exact-edge candidate enumeration for the Auckland network."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import LineString

from .pipeline import ProductionBlocker, StageContext, StageResult
from .provenance import content_hash, read_json, sha256_file, write_json_atomic

CANDIDATE_OUTPUT_SCHEMA_VERSION = 3
_LOW_STRESS_FACILITIES = frozenset({"protected_lane", "shared_path", "quiet_street"})


@dataclass(frozen=True, slots=True)
class CandidateEdge:
    """Compact physical-edge record used by the corridor enumerator."""

    id: str
    u: str
    v: str
    length_m: float
    lts: int
    facility: str

    def __post_init__(self) -> None:
        if not self.id or not self.u or not self.v or self.u == self.v:
            raise ValueError("candidate edge requires distinct identified endpoints")
        if not isfinite(self.length_m) or self.length_m <= 0:
            raise ValueError("candidate edge length must be positive and finite")
        if self.lts not in (1, 2, 3, 4):
            raise ValueError("candidate edge LTS must be in 1..4")


@dataclass(frozen=True, slots=True)
class EdgeTraversal:
    """One exact physical edge in deterministic corridor order."""

    edge_id: str
    from_node: str
    to_node: str
    reversed: bool


@dataclass(frozen=True, slots=True)
class CandidateChain:
    """A connected, unbranched sequence of exact physical edges."""

    traversals: tuple[EdgeTraversal, ...]

    @property
    def origin(self) -> str:
        return self.traversals[0].from_node

    @property
    def destination(self) -> str:
        return self.traversals[-1].to_node

    @property
    def edge_ids(self) -> tuple[str, ...]:
        return tuple(item.edge_id for item in self.traversals)


def is_candidate_gap(edge: CandidateEdge, *, maximum_baseline_lts: int) -> bool:
    """Return whether an edge is an untreated high-stress network gap."""

    return edge.lts > maximum_baseline_lts and edge.facility not in _LOW_STRESS_FACILITIES


def enumerate_nonbranching_chains(
    edges: Iterable[CandidateEdge],
    *,
    maximum_baseline_lts: int = 2,
) -> tuple[tuple[CandidateChain, ...], tuple[CandidateChain, ...]]:
    """Enumerate every maximal high-stress chain exactly once.

    Adjacency is based on source node identities and physical edge IDs.  Degree
    counts therefore include parallel edges and never infer a connection from
    coincident coordinates.  Closed all-degree-two components are returned
    separately because they do not have two unambiguous corridor terminals.
    """

    by_id = {
        edge.id: edge
        for edge in edges
        if is_candidate_gap(edge, maximum_baseline_lts=maximum_baseline_lts)
    }
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in by_id.values():
        adjacency[edge.u].append(edge.id)
        adjacency[edge.v].append(edge.id)
    for edge_ids in adjacency.values():
        edge_ids.sort()

    visited: set[str] = set()

    def walk(
        start_node: str, first_edge_id: str, *, allow_closed_component: bool = False
    ) -> CandidateChain:
        traversals: list[EdgeTraversal] = []
        traversed_nodes = {start_node}
        node = start_node
        edge_id = first_edge_id
        while edge_id not in visited:
            edge = by_id[edge_id]
            if edge.u == node:
                next_node = edge.v
                reversed_edge = False
            elif edge.v == node:
                next_node = edge.u
                reversed_edge = True
            else:  # pragma: no cover - guarded by construction
                raise RuntimeError("corridor walk lost exact edge adjacency")
            traversals.append(EdgeTraversal(edge.id, node, next_node, reversed_edge))
            visited.add(edge.id)
            if len(adjacency[next_node]) != 2:
                break
            following = [item for item in adjacency[next_node] if item != edge.id]
            if len(following) != 1 or following[0] in visited:
                break
            following_edge = by_id[following[0]]
            following_node = following_edge.v if following_edge.u == next_node else following_edge.u
            if following_node in traversed_nodes and not allow_closed_component:
                break
            traversed_nodes.add(next_node)
            node = next_node
            edge_id = following[0]
        return CandidateChain(tuple(traversals))

    chains: list[CandidateChain] = []
    for node in sorted(adjacency):
        if len(adjacency[node]) == 2:
            continue
        chains.extend(walk(node, edge_id) for edge_id in adjacency[node] if edge_id not in visited)

    closed: list[CandidateChain] = []
    for edge_id in sorted(by_id):
        if edge_id in visited:
            continue
        edge = by_id[edge_id]
        start = min(edge.u, edge.v)
        closed.append(walk(start, edge_id, allow_closed_component=True))

    if visited != set(by_id):  # pragma: no cover - defensive invariant
        raise RuntimeError("candidate enumeration did not account for every eligible edge")
    return tuple(chains), tuple(closed)


def split_chain_by_length(
    chain: CandidateChain,
    edges: Mapping[str, CandidateEdge],
    *,
    maximum_length_m: float,
) -> tuple[CandidateChain, ...]:
    """Split a chain at physical edge boundaries, never by segment count."""

    if not isfinite(maximum_length_m) or maximum_length_m <= 0:
        raise ValueError("maximum candidate length must be positive and finite")
    parts: list[CandidateChain] = []
    current: list[EdgeTraversal] = []
    current_length = 0.0
    for traversal in chain.traversals:
        length = edges[traversal.edge_id].length_m
        if length > maximum_length_m:
            if current:
                parts.append(CandidateChain(tuple(current)))
                current = []
                current_length = 0.0
            parts.append(CandidateChain((traversal,)))
            continue
        if current and current_length + length > maximum_length_m:
            parts.append(CandidateChain(tuple(current)))
            current = []
            current_length = 0.0
        current.append(traversal)
        current_length += length
    if current:
        parts.append(CandidateChain(tuple(current)))
    return tuple(parts)


CANDIDATE_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("candidate_id", pa.string()),
        ("origin_node_id", pa.string()),
        ("destination_node_id", pa.string()),
        ("ordered_edge_ids", pa.list_(pa.string())),
        ("edge_count", pa.int32()),
        ("length_m", pa.float64()),
        ("maximum_baseline_lts", pa.int8()),
        ("length_weighted_mean_lts", pa.float64()),
        ("treatment", pa.string()),
        ("primary_road_names", pa.list_(pa.string())),
        ("source_way_ids", pa.list_(pa.string())),
        ("has_bridge", pa.bool_()),
        ("has_tunnel", pa.bool_()),
        ("capital_cost_lower_nzd", pa.float64()),
        ("capital_cost_base_nzd", pa.float64()),
        ("capital_cost_upper_nzd", pa.float64()),
        ("capital_cost_evidence_status", pa.string()),
        ("geometry_wkb", pa.binary()),
        ("crs", pa.string()),
    ]
)

CANDIDATE_EDGE_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("candidate_id", pa.string()),
        ("edge_sequence", pa.int32()),
        ("project_edge_id", pa.string()),
        ("from_node_id", pa.string()),
        ("to_node_id", pa.string()),
        ("reversed", pa.bool_()),
        ("length_m", pa.float64()),
        ("baseline_lts", pa.int8()),
        ("baseline_facility", pa.string()),
        ("baseline_direction", pa.string()),
        ("road_class", pa.string()),
        ("source_way_id", pa.string()),
        ("bridge", pa.bool_()),
        ("tunnel", pa.bool_()),
        ("commute_estimated_observed_cycle", pa.float64()),
        ("commute_estimated_eligible", pa.float64()),
    ]
)

PURPOSE_METRIC_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("candidate_id", pa.string()),
        ("purpose", pa.string()),
        ("estimated_observed_cycle_edge_km", pa.float64()),
        ("estimated_eligible_edge_km", pa.float64()),
        ("peak_edge_observed_cycle", pa.float64()),
        ("peak_edge_eligible", pa.float64()),
        ("minimum_edge_eligible", pa.float64()),
        ("exposed_edge_count", pa.int32()),
    ]
)

EXCLUSION_SCHEMA = pa.schema(
    [
        ("schema_version", pa.int16()),
        ("exclusion_id", pa.string()),
        ("reason", pa.string()),
        ("ordered_edge_ids", pa.list_(pa.string())),
        ("edge_count", pa.int32()),
        ("length_m", pa.float64()),
    ]
)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductionBlocker(
            stage="generate-candidates",
            code="invalid_candidate_configuration",
            message=f"{field} must be a mapping",
            evidence={"field": field},
        )
    return value


def _finite_parameter(
    value: Any, *, field: str, minimum: float = 0.0, strict: bool = False
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductionBlocker(
            stage="generate-candidates",
            code="invalid_candidate_configuration",
            message=f"{field} must be numeric",
            evidence={"field": field, "value": value},
        ) from exc
    if not isfinite(result) or (result <= minimum if strict else result < minimum):
        relation = "greater than" if strict else "at least"
        raise ProductionBlocker(
            stage="generate-candidates",
            code="invalid_candidate_configuration",
            message=f"{field} must be finite and {relation} {minimum}",
            evidence={"field": field, "value": value},
        )
    return result


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    temporary = path.with_name(path.name + ".tmp")
    pq.write_table(
        pa.Table.from_pylist([dict(row) for row in rows], schema=schema),
        temporary,
        compression="zstd",
        use_dictionary=True,
    )
    temporary.replace(path)


def _topology_payload_path(path: Path) -> Path:
    return path / "topology.json" if path.is_dir() else path


def _routes_payload_path(path: Path, filename: str) -> Path:
    return path / filename if path.is_dir() else path.parent / filename


def _edge_geometry(
    traversal: EdgeTraversal,
    edge: Mapping[str, Any],
    nodes: Mapping[str, tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    raw = edge.get("geometry")
    if isinstance(raw, list) and len(raw) >= 2:
        coordinates = tuple((float(item[0]), float(item[1])) for item in raw)
    else:
        coordinates = (nodes[traversal.from_node], nodes[traversal.to_node])
        return coordinates
    return tuple(reversed(coordinates)) if traversal.reversed else coordinates


def _chain_geometry(
    chain: CandidateChain,
    raw_edges: Mapping[str, Mapping[str, Any]],
    nodes: Mapping[str, tuple[float, float]],
) -> bytes:
    coordinates: list[tuple[float, float]] = []
    for traversal in chain.traversals:
        segment = _edge_geometry(traversal, raw_edges[traversal.edge_id], nodes)
        if coordinates and coordinates[-1] == segment[0]:
            coordinates.extend(segment[1:])
        else:
            coordinates.extend(segment)
    if len(coordinates) < 2:
        raise ValueError("candidate geometry requires at least two coordinates")
    return LineString(coordinates).wkb


def _relative_direction(source_direction: str, reversed_traversal: bool) -> str:
    """Express a source bicycle direction relative to exported traversal order."""

    if source_direction == "both":
        return "both"
    if source_direction not in {"forward", "reverse"}:
        raise ValueError(f"unsupported source bicycle direction: {source_direction}")
    if not reversed_traversal:
        return source_direction
    return "reverse" if source_direction == "forward" else "forward"


def _flow_by_purpose(routes_path: Path) -> dict[str, dict[str, tuple[float, float]]]:
    edge_path = _routes_payload_path(routes_path, "edge_flows.parquet")
    manifest_path = _routes_payload_path(routes_path, "manifest.json")
    manifest = read_json(manifest_path)
    purpose = (
        str(manifest.get("purpose", "commute")) if isinstance(manifest, Mapping) else "commute"
    )
    schema_names = set(pq.read_schema(edge_path).names)
    columns = ["project_edge_id", "estimated_observed_cycle", "estimated_eligible"]
    include_purpose = "purpose" in schema_names
    if include_purpose:
        columns.append("purpose")
    result: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    parquet = pq.ParquetFile(edge_path)
    for batch in parquet.iter_batches(batch_size=100_000, columns=columns):
        for row in batch.to_pylist():
            row_purpose = str(row["purpose"]) if include_purpose else purpose
            result[row_purpose][str(row["project_edge_id"])] = (
                float(row["estimated_observed_cycle"]),
                float(row["estimated_eligible"]),
            )
    return dict(result)


def production_candidates_stage(context: StageContext) -> StageResult:
    """Generate all supported high-stress exact-edge corridor candidates."""

    candidate_parameters = _mapping(
        context.config.parameters.get("candidates"), field="parameters.candidates"
    )
    cost_parameters = _mapping(
        candidate_parameters.get("screening_cost"),
        field="parameters.candidates.screening_cost",
    )
    maximum_length_m = _finite_parameter(
        candidate_parameters.get("maximum_length_m"),
        field="candidates.maximum_length_m",
        strict=True,
    )
    minimum_length_m = _finite_parameter(
        candidate_parameters.get("minimum_length_m", 0),
        field="candidates.minimum_length_m",
    )
    maximum_baseline_lts = int(candidate_parameters.get("connectivity_max_lts", 2))
    if maximum_baseline_lts not in (1, 2, 3):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_candidate_configuration",
            message="candidates.connectivity_max_lts must be 1, 2, or 3",
        )
    cost_lower = _finite_parameter(
        cost_parameters.get("lower_nzd_per_m"), field="screening_cost.lower_nzd_per_m"
    )
    cost_base = _finite_parameter(
        cost_parameters.get("base_nzd_per_m"), field="screening_cost.base_nzd_per_m"
    )
    cost_upper = _finite_parameter(
        cost_parameters.get("upper_nzd_per_m"), field="screening_cost.upper_nzd_per_m"
    )
    if not cost_lower <= cost_base <= cost_upper:
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_candidate_configuration",
            message="screening cost rates must satisfy lower <= base <= upper",
        )

    topology_path = context.dependencies["build-topology"]["topology"].path
    routes_path = context.dependencies["assign-routes"]["routes"].path
    payload = read_json(_topology_payload_path(topology_path))
    if not isinstance(payload, Mapping):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_topology_payload",
            message="topology payload must be a JSON object",
        )
    raw_nodes = payload.get("nodes")
    raw_edge_values = payload.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edge_values, list):
        raise ProductionBlocker(
            stage=context.stage.name,
            code="invalid_topology_payload",
            message="topology payload requires node and edge arrays",
        )
    nodes = {
        str(item["id"]): (float(item["x"]), float(item["y"]))
        for item in raw_nodes
        if isinstance(item, Mapping)
    }
    raw_edges = {str(item["id"]): item for item in raw_edge_values if isinstance(item, Mapping)}
    compact_edges = {
        edge_id: CandidateEdge(
            edge_id,
            str(item["u"]),
            str(item["v"]),
            float(item["length_m"]),
            int(item["lts"]),
            str(item["facility"]),
        )
        for edge_id, item in raw_edges.items()
    }
    chains, closed_chains = enumerate_nonbranching_chains(
        compact_edges.values(), maximum_baseline_lts=maximum_baseline_lts
    )
    flow_by_purpose = _flow_by_purpose(routes_path)
    all_flow_edges = {
        edge_id for purpose_values in flow_by_purpose.values() for edge_id in purpose_values
    }

    candidate_rows: list[dict[str, Any]] = []
    candidate_edge_rows: list[dict[str, Any]] = []
    purpose_rows: list[dict[str, Any]] = []
    exclusion_rows: list[dict[str, Any]] = []

    def exclude(reason: str, chain: CandidateChain) -> None:
        edge_ids = chain.edge_ids
        length = sum(compact_edges[edge_id].length_m for edge_id in edge_ids)
        exclusion_rows.append(
            {
                "schema_version": CANDIDATE_OUTPUT_SCHEMA_VERSION,
                "exclusion_id": "exclusion-"
                + content_hash({"reason": reason, "edges": edge_ids})[:16],
                "reason": reason,
                "ordered_edge_ids": list(edge_ids),
                "edge_count": len(edge_ids),
                "length_m": length,
            }
        )

    for chain in closed_chains:
        exclude("closed_component_has_no_unambiguous_terminals", chain)

    for maximal_chain in chains:
        for chain in split_chain_by_length(
            maximal_chain, compact_edges, maximum_length_m=maximum_length_m
        ):
            edge_ids = chain.edge_ids
            edge_values = [compact_edges[edge_id] for edge_id in edge_ids]
            length_m = sum(edge.length_m for edge in edge_values)
            if any(edge.length_m > maximum_length_m for edge in edge_values):
                exclude("single_exact_edge_exceeds_maximum_length", chain)
                continue
            if length_m < minimum_length_m:
                exclude("below_declared_minimum_physical_length", chain)
                continue
            if not any(edge_id in all_flow_edges for edge_id in edge_ids):
                exclude("no_exposure_in_routed_purpose_markets", chain)
                continue
            candidate_id = "candidate-" + content_hash({"ordered_edge_ids": edge_ids})[:16]
            source_edges = [raw_edges[edge_id] for edge_id in edge_ids]
            names = sorted(
                {
                    str(item.get("attributes", {}).get("name", "")).strip()
                    for item in source_edges
                    if isinstance(item.get("attributes"), Mapping)
                    and str(item.get("attributes", {}).get("name", "")).strip()
                }
            )
            way_ids = sorted(
                {str(item["source_way_id"]) for item in source_edges if item.get("source_way_id")}
            )
            candidate_rows.append(
                {
                    "schema_version": CANDIDATE_OUTPUT_SCHEMA_VERSION,
                    "candidate_id": candidate_id,
                    "origin_node_id": chain.origin,
                    "destination_node_id": chain.destination,
                    "ordered_edge_ids": list(edge_ids),
                    "edge_count": len(edge_ids),
                    "length_m": length_m,
                    "maximum_baseline_lts": max(edge.lts for edge in edge_values),
                    "length_weighted_mean_lts": (
                        sum(edge.length_m * edge.lts for edge in edge_values) / length_m
                    ),
                    "treatment": "protected_lane",
                    "primary_road_names": names,
                    "source_way_ids": way_ids,
                    "has_bridge": any(bool(item.get("bridge")) for item in source_edges),
                    "has_tunnel": any(bool(item.get("tunnel")) for item in source_edges),
                    "capital_cost_lower_nzd": length_m * cost_lower,
                    "capital_cost_base_nzd": length_m * cost_base,
                    "capital_cost_upper_nzd": length_m * cost_upper,
                    "capital_cost_evidence_status": str(
                        cost_parameters.get("evidence_status", "provisional_screening_assumption")
                    ),
                    "geometry_wkb": _chain_geometry(chain, raw_edges, nodes),
                    "crs": str(payload.get("crs", context.config.project.crs)),
                }
            )
            for sequence, traversal in enumerate(chain.traversals):
                raw_edge = raw_edges[traversal.edge_id]
                commute_flow = flow_by_purpose.get("commute", {}).get(traversal.edge_id, (0.0, 0.0))
                candidate_edge_rows.append(
                    {
                        "schema_version": CANDIDATE_OUTPUT_SCHEMA_VERSION,
                        "candidate_id": candidate_id,
                        "edge_sequence": sequence,
                        "project_edge_id": traversal.edge_id,
                        "from_node_id": traversal.from_node,
                        "to_node_id": traversal.to_node,
                        "reversed": traversal.reversed,
                        "length_m": float(raw_edge["length_m"]),
                        "baseline_lts": int(raw_edge["lts"]),
                        "baseline_facility": str(raw_edge["facility"]),
                        "baseline_direction": _relative_direction(
                            str(raw_edge.get("direction", "both")),
                            traversal.reversed,
                        ),
                        "road_class": str(raw_edge["road_class"]),
                        "source_way_id": (
                            str(raw_edge["source_way_id"])
                            if raw_edge.get("source_way_id") is not None
                            else None
                        ),
                        "bridge": bool(raw_edge.get("bridge")),
                        "tunnel": bool(raw_edge.get("tunnel")),
                        "commute_estimated_observed_cycle": commute_flow[0],
                        "commute_estimated_eligible": commute_flow[1],
                    }
                )
            for purpose, values in sorted(flow_by_purpose.items()):
                purpose_flows = [values.get(edge_id, (0.0, 0.0)) for edge_id in edge_ids]
                eligible_values = [value[1] for value in purpose_flows]
                purpose_rows.append(
                    {
                        "schema_version": CANDIDATE_OUTPUT_SCHEMA_VERSION,
                        "candidate_id": candidate_id,
                        "purpose": purpose,
                        "estimated_observed_cycle_edge_km": sum(
                            flow[0] * edge.length_m / 1000
                            for flow, edge in zip(purpose_flows, edge_values, strict=True)
                        ),
                        "estimated_eligible_edge_km": sum(
                            flow[1] * edge.length_m / 1000
                            for flow, edge in zip(purpose_flows, edge_values, strict=True)
                        ),
                        "peak_edge_observed_cycle": max(
                            (flow[0] for flow in purpose_flows), default=0.0
                        ),
                        "peak_edge_eligible": max(eligible_values, default=0.0),
                        "minimum_edge_eligible": min(eligible_values, default=0.0),
                        "exposed_edge_count": sum(value > 0 for value in eligible_values),
                    }
                )

    candidate_rows.sort(key=lambda row: str(row["candidate_id"]))
    candidate_edge_rows.sort(key=lambda row: (str(row["candidate_id"]), int(row["edge_sequence"])))
    purpose_rows.sort(key=lambda row: (str(row["candidate_id"]), str(row["purpose"])))
    exclusion_rows.sort(key=lambda row: str(row["exclusion_id"]))
    output_dir = context.artifact_dir / (
        "candidates-"
        + content_hash(
            {
                "topology": context.dependencies["build-topology"]["topology"].sha256,
                "routes": context.dependencies["assign-routes"]["routes"].sha256,
                "parameters": dict(candidate_parameters),
            }
        )[:16]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "candidate_ledger.parquet"
    edge_path = output_dir / "candidate_edge_ledger.parquet"
    purpose_path = output_dir / "candidate_purpose_metrics.parquet"
    exclusion_path = output_dir / "candidate_exclusion_ledger.parquet"
    _write_parquet(candidate_path, candidate_rows, CANDIDATE_SCHEMA)
    _write_parquet(edge_path, candidate_edge_rows, CANDIDATE_EDGE_SCHEMA)
    _write_parquet(purpose_path, purpose_rows, PURPOSE_METRIC_SCHEMA)
    _write_parquet(exclusion_path, exclusion_rows, EXCLUSION_SCHEMA)
    files = {
        path.name: {"size": path.stat().st_size, "sha256": sha256_file(path)}
        for path in (candidate_path, edge_path, purpose_path, exclusion_path)
    }
    manifest_path = output_dir / "manifest.json"
    blockers = []
    if str(cost_parameters.get("evidence_status")) != "authoritative_local_unit_cost":
        blockers.append("capital_unit_cost_evidence_pending")
    if set(flow_by_purpose) != {"commute", "school", "everyday", "transit"}:
        blockers.append("all_four_independent_purpose_route_surfaces_required")
    write_json_atomic(
        manifest_path,
        {
            "schema_version": CANDIDATE_OUTPUT_SCHEMA_VERSION,
            "run_id": context.run_id,
            "method": {
                "enumeration": "complete_maximal_nonbranching_high_stress_physical_edge_chains",
                "source_adjacency": "exact_source_node_and_physical_edge_identity",
                "parallel_edges": "counted_individually_in_node_degree",
                "length_splitting": "physical_edge_boundaries_not_segment_count",
                "closed_components": "excluded_with_reason_no_unambiguous_terminals",
                "demand_filter": "at_least_one_routed_purpose_market_has_positive_edge_exposure",
                "cross_purpose_units_are_not_summed": True,
                "maximum_baseline_lts": maximum_baseline_lts,
                "minimum_length_m": minimum_length_m,
                "maximum_length_m": maximum_length_m,
                "candidate_limit": None,
            },
            "screening_cost": dict(cost_parameters),
            "purposes": sorted(flow_by_purpose),
            "row_counts": {
                "eligible_maximal_chains": len(chains),
                "closed_components": len(closed_chains),
                "candidates": len(candidate_rows),
                "candidate_edges": len(candidate_edge_rows),
                "candidate_purpose_metrics": len(purpose_rows),
                "exclusions": len(exclusion_rows),
            },
            "publication_grade_ready": not blockers,
            "publication_blockers": blockers,
            "files": files,
        },
    )
    return StageResult(
        {"candidates": output_dir},
        {
            "row_counts": {
                "candidates": len(candidate_rows),
                "candidate_edges": len(candidate_edge_rows),
                "candidate_purpose_metrics": len(purpose_rows),
                "candidate_exclusions": len(exclusion_rows),
            }
        },
    )
