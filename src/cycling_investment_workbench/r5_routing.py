"""Pinned R5 routing adapter with exact CIW-edge reconciliation.

R5 supplies fast bicycle routing and preserves OSM way identities.  The CIW
topology remains authoritative for source-identified nodes, physical-edge layer,
bicycle direction, stress, terrain, and exact segment identifiers. Every accepted R5
path is therefore reconciled to a contiguous sequence of CIW directed edges;
paths that cannot be reconciled fail closed instead of falling back to geometry
buffers or parallel edges.

The import of :mod:`r5py` is deliberately deferred until an engine is created.
Pure sampling, probability, and topology-reconciliation tests can run without a
JVM.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from math import exp, hypot, isfinite, log
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree


class R5RoutingError(RuntimeError):
    """Raised when the pinned routing engine or its inputs are unusable."""


@dataclass(frozen=True, slots=True)
class RouteSample:
    """Declared inclusion result for one disaggregated OD record."""

    record_id: str
    stratum_id: str
    selected: bool
    stratum_size: int
    stratum_sample_size: int
    inclusion_probability: float
    analysis_weight: float
    rank: int


def select_route_sample(
    records: Sequence[Mapping[str, Any]],
    *,
    records_per_stratum: int | None,
    seed: int,
) -> tuple[RouteSample, ...]:
    """Select stable SRS strata while retaining a ledger row for every record.

    The rank is a SHA-256 ordering of ``seed``, stratum, and record identity.
    Selecting the first ``m`` records is equivalent to simple random sampling
    without replacement under a deterministic seeded random permutation.  The
    returned inverse-probability weight is the exact Horvitz--Thompson weight.
    ``None`` selects the complete input.
    """

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("routing sample seed must be an integer")
    if records_per_stratum is not None and records_per_stratum < 1:
        raise ValueError("records_per_stratum must be positive or None")
    grouped: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for record in records:
        record_id = str(record.get("id", "")).strip()
        stratum_id = str(record.get("source_cell_id", "")).strip()
        if not record_id or not stratum_id:
            raise ValueError("routing records require id and source_cell_id")
        if record_id in seen:
            raise ValueError(f"duplicate routing record id: {record_id}")
        seen.add(record_id)
        grouped[stratum_id].append(record_id)

    result: list[RouteSample] = []
    for stratum_id in sorted(grouped):
        record_ids = grouped[stratum_id]
        ordered = sorted(
            record_ids,
            key=lambda record_id: (
                sha256(f"{seed}\0{stratum_id}\0{record_id}".encode()).digest(),
                record_id,
            ),
        )
        size = len(ordered)
        sample_size = size if records_per_stratum is None else min(size, records_per_stratum)
        inclusion_probability = sample_size / size
        weight = size / sample_size
        for rank, record_id in enumerate(ordered, start=1):
            result.append(
                RouteSample(
                    record_id=record_id,
                    stratum_id=stratum_id,
                    selected=rank <= sample_size,
                    stratum_size=size,
                    stratum_sample_size=sample_size,
                    inclusion_probability=inclusion_probability,
                    analysis_weight=weight,
                    rank=rank,
                )
            )
    return tuple(sorted(result, key=lambda item: item.record_id))


@dataclass(frozen=True, slots=True)
class SnapNode:
    node_index: int
    node_id: str
    component_id: str
    distance_m: float
    x: float
    y: float
    layer: int


def choose_component_compatible_snaps(
    origins: Mapping[str, SnapNode],
    destinations: Mapping[str, SnapNode],
) -> tuple[SnapNode, SnapNode] | None:
    """Choose the nearest deterministic pair in a shared weak component."""

    common = set(origins).intersection(destinations)
    if not common:
        return None
    options = ((origins[key], destinations[key]) for key in common)
    return min(
        options,
        key=lambda pair: (
            pair[0].distance_m + pair[1].distance_m,
            max(pair[0].distance_m, pair[1].distance_m),
            pair[0].node_id,
            pair[1].node_id,
        ),
    )


@dataclass(frozen=True, slots=True)
class ProjectSegment:
    edge_id: str
    u_index: int
    v_index: int
    source_way_id: str
    length_m: float
    generalized_forward: float
    generalized_reverse: float
    gradient_ratio: float
    allows_forward: bool
    allows_reverse: bool


@dataclass(frozen=True, slots=True)
class ProjectTraversal:
    segment_index: int
    reversed: bool


@dataclass(frozen=True, slots=True)
class ReconciledPath:
    r5_edge_ids: tuple[int, ...]
    r5_osm_way_ids: tuple[int, ...]
    traversals: tuple[ProjectTraversal, ...]
    generalized_cost: float
    length_m: float

    @property
    def project_edge_indices(self) -> tuple[int, ...]:
        return tuple(item.segment_index for item in self.traversals)


@dataclass(frozen=True, slots=True)
class RouteAlternative:
    path: ReconciledPath
    probability: float
    detour_ratio: float


@dataclass(frozen=True, slots=True)
class R5RouteResult:
    status: Literal["assigned", "unassigned"]
    failure_reason: str | None
    origin_engine_link_distance_m: float | None
    destination_engine_link_distance_m: float | None
    shortest_distance_m: float | None
    alternatives: tuple[RouteAlternative, ...]
    shortest_average_absolute_gradient_percent: float | None = None
    shortest_total_ascent_m: float | None = None


def path_gradient_metrics(
    path: ReconciledPath, segments: Sequence[ProjectSegment]
) -> tuple[float, float, float]:
    """Return mean absolute gradient percent, ascent, and descent.

    Mean absolute gradient is a length-weighted route statistic.  It is the
    declared CIW approximation to the PCT/CycleStreets average slope and is
    symmetric by direction; ascent and descent retain the actual traversal.
    """

    if path.length_m <= 0:
        return 0.0, 0.0, 0.0
    absolute_rise = 0.0
    ascent = 0.0
    descent = 0.0
    for traversal in path.traversals:
        segment = segments[traversal.segment_index]
        directed_gradient = (
            -segment.gradient_ratio if traversal.reversed else segment.gradient_ratio
        )
        rise = directed_gradient * segment.length_m
        absolute_rise += abs(rise)
        ascent += max(0.0, rise)
        descent += max(0.0, -rise)
    return 100.0 * absolute_rise / path.length_m, ascent, descent


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = np.arange(size, dtype=np.int32)
        self.weight = np.ones(size, dtype=np.int32)
        self.minimum = np.arange(size, dtype=np.int32)

    def find(self, item: int) -> int:
        parent = self.parent
        cursor = item
        while int(parent[cursor]) != cursor:
            parent[cursor] = parent[int(parent[cursor])]
            cursor = int(parent[cursor])
        return cursor

    def union(self, first: int, second: int) -> None:
        left = self.find(first)
        right = self.find(second)
        if left == right:
            return
        if int(self.weight[left]) < int(self.weight[right]):
            left, right = right, left
        self.parent[right] = left
        self.weight[left] += self.weight[right]
        self.minimum[left] = min(int(self.minimum[left]), int(self.minimum[right]))

    def stable_components(self) -> np.ndarray:
        components = np.empty(len(self.parent), dtype=np.int32)
        for index in range(len(self.parent)):
            root = self.find(index)
            components[index] = self.minimum[root]
        return components


def _finite_number(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise R5RoutingError(f"topology edge has invalid {field}") from exc
    if not isfinite(number):
        raise R5RoutingError(f"topology edge has non-finite {field}")
    return number


def _edge_generalized_costs(
    edge: Mapping[str, Any], comfort: Mapping[str, Any]
) -> tuple[float, float]:
    length = _finite_number(edge.get("length_m"), field="length_m")
    if length <= 0:
        raise R5RoutingError("topology edge length must be positive")
    lts = int(edge.get("lts", 4))
    if lts not in {1, 2, 3, 4}:
        raise R5RoutingError("topology edge LTS must be in 1..4")
    stress = tuple(float(comfort[f"lts_{index}"]) for index in range(1, 5))
    uphill = float(comfort["uphill_gradient_weight"])
    downhill = float(comfort["downhill_gradient_weight"])
    tunnel = float(comfort["tunnel_multiplier"])
    bridge = float(comfort["bridge_multiplier"])
    gradient = _finite_number(edge.get("gradient", 0), field="gradient")
    structure = (tunnel if bool(edge.get("tunnel")) else 1.0) * (
        bridge if bool(edge.get("bridge")) else 1.0
    )

    def cost(directed_gradient: float) -> float:
        grade = 1 + uphill * max(0.0, directed_gradient) + downhill * max(0.0, -directed_gradient)
        return length * stress[lts - 1] * grade * structure

    return cost(gradient), cost(-gradient)


class ProjectTopologyIndex:
    """Memory-conscious index of authoritative CIW nodes and directed segments."""

    # R5 stores OSM coordinates in fixed 1e-7 degrees, producing about a
    # centimetre of projected displacement. Sequence matching (rather than
    # rounded coordinate identity) preserves legitimate sub-decimetre segments.
    coordinate_tolerance_m = 0.025

    def __init__(
        self,
        *,
        node_ids: tuple[str, ...],
        coordinates: np.ndarray,
        layers: np.ndarray,
        components: np.ndarray,
        segments: tuple[ProjectSegment, ...],
        segment_sequences_by_way: Mapping[str, tuple[int, ...]],
    ) -> None:
        self.node_ids = node_ids
        self.coordinates = coordinates
        self.layers = layers
        self.components = components
        self.segments = segments
        self.segment_sequences_by_way = segment_sequences_by_way
        self._tree = cKDTree(coordinates)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        comfort_parameters: Mapping[str, Any],
    ) -> ProjectTopologyIndex:
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges")
        if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
            raise R5RoutingError("topology payload requires node and edge arrays")
        node_ids: list[str] = []
        coordinates = np.empty((len(raw_nodes), 2), dtype=np.float64)
        layers = np.empty(len(raw_nodes), dtype=np.int16)
        node_index: dict[str, int] = {}
        for index, item in enumerate(raw_nodes):
            if not isinstance(item, Mapping):
                raise R5RoutingError("topology node must be an object")
            node_id = str(item.get("id", ""))
            if not node_id or node_id in node_index:
                raise R5RoutingError(f"invalid or duplicate topology node: {node_id!r}")
            node_ids.append(node_id)
            node_index[node_id] = index
            coordinates[index] = (float(item["x"]), float(item["y"]))
            layers[index] = int(item.get("layer", 0))

        union_find = _UnionFind(len(node_ids))
        segments: list[ProjectSegment] = []
        sequences: dict[str, list[tuple[int, int]]] = defaultdict(list)

        for item in raw_edges:
            if not isinstance(item, Mapping):
                raise R5RoutingError("topology edge must be an object")
            edge_id = str(item.get("id", ""))
            way_id = str(item.get("source_way_id", ""))
            u_id = str(item.get("u", ""))
            v_id = str(item.get("v", ""))
            geometry = item.get("geometry")
            if not edge_id or not way_id or u_id not in node_index or v_id not in node_index:
                raise R5RoutingError(f"topology edge has invalid identity: {edge_id!r}")
            if not isinstance(geometry, list) or len(geometry) < 2:
                raise R5RoutingError(f"topology edge has invalid geometry: {edge_id}")
            u_index = node_index[u_id]
            v_index = node_index[v_id]
            union_find.union(u_index, v_index)
            forward_cost, reverse_cost = _edge_generalized_costs(item, comfort_parameters)
            segment_index = len(segments)
            segment = ProjectSegment(
                edge_id=edge_id,
                u_index=u_index,
                v_index=v_index,
                source_way_id=way_id,
                length_m=float(item["length_m"]),
                generalized_forward=forward_cost,
                generalized_reverse=reverse_cost,
                gradient_ratio=_finite_number(item.get("gradient", 0), field="gradient"),
                allows_forward=str(item.get("direction", "both")) in {"both", "forward"},
                allows_reverse=str(item.get("direction", "both")) in {"both", "reverse"},
            )
            segments.append(segment)
            direction = str(item.get("direction", "both"))
            if direction not in {"both", "forward", "reverse"}:
                raise R5RoutingError(f"topology edge has invalid direction: {edge_id}")
            try:
                sequence_index = int(edge_id.rsplit("-segment-", 1)[1])
            except (IndexError, ValueError) as exc:
                raise R5RoutingError(f"edge lacks stable OSM segment index: {edge_id}") from exc
            sequences[way_id].append((sequence_index, segment_index))

        del node_index
        return cls(
            node_ids=tuple(node_ids),
            coordinates=coordinates,
            layers=layers,
            components=union_find.stable_components(),
            segments=tuple(segments),
            segment_sequences_by_way={
                way_id: tuple(
                    segment_index for _, segment_index in sorted(sequence, key=lambda item: item[0])
                )
                for way_id, sequence in sequences.items()
            },
        )

    def _component_id(self, node_index: int) -> str:
        return f"component:{self.node_ids[int(self.components[node_index])]}"

    def nearest_snap(self, x: float, y: float, *, maximum_distance_m: float) -> SnapNode | None:
        distance, raw_index = self._tree.query((x, y), k=1, distance_upper_bound=maximum_distance_m)
        if not isfinite(float(distance)) or int(raw_index) >= len(self.node_ids):
            return None
        index = int(raw_index)
        return SnapNode(
            index,
            self.node_ids[index],
            self._component_id(index),
            float(distance),
            float(self.coordinates[index, 0]),
            float(self.coordinates[index, 1]),
            int(self.layers[index]),
        )

    def snaps_by_component(
        self,
        x: float,
        y: float,
        *,
        maximum_distance_m: float,
        allowed_node_indices: frozenset[int] | None = None,
    ) -> Mapping[str, SnapNode]:
        return {
            component_id: candidates[0]
            for component_id, candidates in self._snap_candidates_by_component(
                x,
                y,
                maximum_distance_m=maximum_distance_m,
                allowed_node_indices=allowed_node_indices,
                candidates_per_component=1,
            ).items()
        }

    def _snap_candidates_by_component(
        self,
        x: float,
        y: float,
        *,
        maximum_distance_m: float,
        allowed_node_indices: frozenset[int] | None,
        candidates_per_component: int,
    ) -> Mapping[str, tuple[SnapNode, ...]]:
        """Return the nearest few deterministic nodes in every component."""

        if candidates_per_component < 1:
            raise ValueError("candidates_per_component must be positive")
        indices = self._tree.query_ball_point((x, y), maximum_distance_m)
        result: dict[str, list[SnapNode]] = defaultdict(list)
        for index in indices:
            if allowed_node_indices is not None and index not in allowed_node_indices:
                continue
            distance = hypot(
                float(self.coordinates[index, 0]) - x,
                float(self.coordinates[index, 1]) - y,
            )
            component_id = self._component_id(index)
            candidate = SnapNode(
                index,
                self.node_ids[index],
                component_id,
                distance,
                float(self.coordinates[index, 0]),
                float(self.coordinates[index, 1]),
                int(self.layers[index]),
            )
            options = result[component_id]
            options.append(candidate)
            options.sort(key=lambda item: (item.distance_m, item.node_id))
            del options[candidates_per_component:]
        return {key: tuple(value) for key, value in result.items()}

    def snap_pair(
        self,
        origin_x: float,
        origin_y: float,
        destination_x: float,
        destination_y: float,
        *,
        maximum_distance_m: float,
        origin_allowed_node_indices: frozenset[int] | None = None,
        destination_allowed_node_indices: frozenset[int] | None = None,
    ) -> tuple[SnapNode, SnapNode] | None:
        origins = self._snap_candidates_by_component(
            origin_x,
            origin_y,
            maximum_distance_m=maximum_distance_m,
            allowed_node_indices=origin_allowed_node_indices,
            candidates_per_component=2,
        )
        destinations = self._snap_candidates_by_component(
            destination_x,
            destination_y,
            maximum_distance_m=maximum_distance_m,
            allowed_node_indices=destination_allowed_node_indices,
            candidates_per_component=2,
        )
        options = (
            (origin, destination)
            for component_id in set(origins).intersection(destinations)
            for origin in origins[component_id]
            for destination in destinations[component_id]
            if origin.node_index != destination.node_index
        )
        return min(
            options,
            key=lambda pair: (
                pair[0].distance_m + pair[1].distance_m,
                max(pair[0].distance_m, pair[1].distance_m),
                pair[0].component_id,
                pair[0].node_id,
                pair[1].node_id,
            ),
            default=None,
        )

    def map_way_geometry(
        self,
        source_way_id: str,
        projected_coordinates: Sequence[tuple[float, float]],
    ) -> tuple[ProjectTraversal, ...] | None:
        sequence = self.segment_sequences_by_way.get(source_way_id)
        if sequence is None or len(projected_coordinates) < 2:
            return None
        node_sequence = (
            self.segments[sequence[0]].u_index,
            *(self.segments[index].v_index for index in sequence),
        )
        point_count = len(projected_coordinates)
        if point_count > len(node_sequence):
            return None

        def close(node_index: int, point: tuple[float, float]) -> bool:
            return (
                hypot(
                    float(self.coordinates[node_index, 0]) - point[0],
                    float(self.coordinates[node_index, 1]) - point[1],
                )
                <= self.coordinate_tolerance_m
            )

        for start in range(len(node_sequence) - point_count + 1):
            stop = start + point_count
            forward_nodes = node_sequence[start:stop]
            if all(
                close(node_index, point)
                for node_index, point in zip(forward_nodes, projected_coordinates, strict=True)
            ):
                selected = sequence[start : stop - 1]
                if all(self.segments[index].allows_forward for index in selected):
                    return tuple(ProjectTraversal(index, False) for index in selected)
            reverse_nodes = tuple(reversed(forward_nodes))
            if all(
                close(node_index, point)
                for node_index, point in zip(reverse_nodes, projected_coordinates, strict=True)
            ):
                selected = tuple(reversed(sequence[start : stop - 1]))
                if all(self.segments[index].allows_reverse for index in selected):
                    return tuple(ProjectTraversal(index, True) for index in selected)
        return None

    def trim_and_reconcile(
        self,
        r5_edge_ids: Sequence[int],
        r5_osm_way_ids: Sequence[int],
        mapped_edges: Sequence[Sequence[ProjectTraversal] | None],
        *,
        origin_node_index: int,
        destination_node_index: int,
    ) -> ReconciledPath | None:
        if not (
            len(r5_edge_ids) == len(r5_osm_way_ids) == len(mapped_edges)
            and all(item is not None for item in mapped_edges)
        ):
            return None
        flattened = tuple(item for group in mapped_edges for item in group or ())
        if origin_node_index == destination_node_index and not flattened:
            return ReconciledPath(tuple(r5_edge_ids), tuple(r5_osm_way_ids), (), 0.0, 0.0)

        def endpoints(traversal: ProjectTraversal) -> tuple[int, int]:
            segment = self.segments[traversal.segment_index]
            return (
                (segment.v_index, segment.u_index)
                if traversal.reversed
                else (segment.u_index, segment.v_index)
            )

        candidates: list[tuple[int, int]] = []
        for start, traversal in enumerate(flattened):
            tail, _ = endpoints(traversal)
            if tail != origin_node_index:
                continue
            cursor = tail
            for end in range(start, len(flattened)):
                next_tail, head = endpoints(flattened[end])
                if next_tail != cursor:
                    break
                cursor = head
                if cursor == destination_node_index:
                    candidates.append((start, end))
                    break
        if not candidates:
            return None
        start, end = min(candidates, key=lambda pair: (pair[1] - pair[0], pair))
        traversals = flattened[start : end + 1]
        generalized = 0.0
        length = 0.0
        for traversal in traversals:
            segment = self.segments[traversal.segment_index]
            length += segment.length_m
            generalized += (
                segment.generalized_reverse if traversal.reversed else segment.generalized_forward
            )
        return ReconciledPath(
            tuple(r5_edge_ids),
            tuple(r5_osm_way_ids),
            traversals,
            generalized,
            length,
        )

    def reconciliation_failure_reason(
        self,
        mapped_edges: Sequence[Sequence[ProjectTraversal] | None],
        *,
        origin_node_index: int,
        destination_node_index: int,
    ) -> str:
        """Classify why an R5 path cannot become one contiguous CIW path."""

        if any(item is None for item in mapped_edges):
            return "r5_path_contains_non_authoritative_edge"
        flattened = tuple(item for group in mapped_edges for item in group or ())

        def endpoints(traversal: ProjectTraversal) -> tuple[int, int]:
            segment = self.segments[traversal.segment_index]
            return (
                (segment.v_index, segment.u_index)
                if traversal.reversed
                else (segment.u_index, segment.v_index)
            )

        directed = tuple(endpoints(item) for item in flattened)
        if not any(tail == origin_node_index for tail, _ in directed):
            return "r5_path_does_not_start_at_project_snap"
        if not any(head == destination_node_index for _, head in directed):
            return "r5_path_does_not_end_at_project_snap"
        for first, second in pairwise(directed):
            if first[1] == second[0]:
                continue
            first_xy = self.coordinates[first[1]]
            second_xy = self.coordinates[second[0]]
            separation = hypot(
                float(first_xy[0]) - float(second_xy[0]),
                float(first_xy[1]) - float(second_xy[1]),
            )
            if separation <= self.coordinate_tolerance_m:
                return "r5_false_connection_between_distinct_coincident_osm_nodes"
            return "r5_project_topology_discontinuity"
        return "r5_reconciliation_failed"


def path_size_probabilities(
    paths: Sequence[ReconciledPath],
    segments: Sequence[ProjectSegment],
    *,
    cost_scale: float,
    path_size_coefficient: float,
) -> tuple[float, ...]:
    """Return path-size-logit probabilities on exact CIW physical edges."""

    if cost_scale < 0 or path_size_coefficient < 0:
        raise ValueError("path-size logit parameters must be non-negative")
    if not paths:
        return ()
    frequency: dict[int, int] = defaultdict(int)
    for path in paths:
        for edge_index in set(path.project_edge_indices):
            frequency[edge_index] += 1
    factors: list[float] = []
    for path in paths:
        if path.length_m <= 0:
            factors.append(1.0)
            continue
        factor = sum(
            (segments[index].length_m / path.length_m) / frequency[index]
            for index in path.project_edge_indices
        )
        factors.append(min(1.0, max(factor, 1e-12)))
    utilities = [
        -cost_scale * path.generalized_cost + path_size_coefficient * log(factor)
        for path, factor in zip(paths, factors, strict=True)
    ]
    maximum = max(utilities)
    weights = [exp(value - maximum) for value in utilities]
    total = sum(weights)
    return tuple(value / total for value in weights)


def _shared_edge_ratio(
    first: ReconciledPath,
    second: ReconciledPath,
    segments: Sequence[ProjectSegment],
) -> float:
    if first.length_m <= 0:
        return 1.0
    shared = set(first.project_edge_indices).intersection(second.project_edge_indices)
    return sum(segments[index].length_m for index in shared) / first.length_m


class R5CyclingEngine:
    """One pinned R5 network with CIW comfort factors and exact-edge auditing."""

    def __init__(
        self,
        pbf_path: str | Path,
        topology: ProjectTopologyIndex,
        *,
        project_crs: str,
        bicycle_speed_kph: float = 15.0,
        maximum_bicycle_lts: int = 4,
        unmapped_edge_multiplier: float = 3.0,
    ) -> None:
        if bicycle_speed_kph <= 0:
            raise ValueError("bicycle_speed_kph must be positive")
        if maximum_bicycle_lts not in {1, 2, 3, 4}:
            raise ValueError("maximum_bicycle_lts must be in 1..4")
        if unmapped_edge_multiplier < 1:
            raise ValueError("unmapped_edge_multiplier must be at least one")
        source = Path(pbf_path)
        if not source.is_file() or source.suffix.lower() != ".pbf":
            raise R5RoutingError("R5 routing requires a readable bounded .osm.pbf input")

        try:
            import r5py
            from r5py import TransportMode
            from r5py.r5.regional_task import RegionalTask
        except Exception as exc:  # pragma: no cover - runtime installation boundary
            raise R5RoutingError(f"could not initialise pinned r5py runtime: {exc}") from exc
        try:
            import com.conveyal.r5  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - runtime installation boundary
            raise R5RoutingError(f"could not load pinned R5 classes: {exc}") from exc

        self._java = com.conveyal.r5
        self._transport_mode = TransportMode
        self.topology = topology
        self.network = r5py.TransportNetwork(source)
        self.request = RegionalTask(
            self.network,
            transport_modes=[TransportMode.BICYCLE],
            speed_cycling=bicycle_speed_kph,
            max_bicycle_traffic_stress=maximum_bicycle_lts,
        )
        self._from_wgs84 = Transformer.from_crs("EPSG:4326", project_crs, always_xy=True)
        self._edge_store = self.network._transport_network.streetLayer.edgeStore
        self._traversal_times = com.conveyal.r5.streets.EdgeTraversalTimes.createNeutral(
            self._edge_store
        )
        self._edge_store.edgeTraversalTimes = self._traversal_times
        self._base_factors = np.full(self._edge_store.nEdges(), unmapped_edge_multiplier)
        self._mapping_cache: dict[int, tuple[int, tuple[ProjectTraversal, ...] | None]] = {}
        self.mapping_diagnostics = self._apply_project_costs(unmapped_edge_multiplier)

    def _edge_mapping(self, edge_index: int) -> tuple[int, tuple[ProjectTraversal, ...] | None]:
        cached = self._mapping_cache.get(edge_index)
        if cached is not None:
            return cached
        edge = self._edge_store.getCursor(edge_index)
        way_id = int(edge.getOSMID())
        coordinates = edge.getGeometry().getCoordinates()
        longitudes = [float(item.x) for item in coordinates]
        latitudes = [float(item.y) for item in coordinates]
        xs, ys = self._from_wgs84.transform(longitudes, latitudes)
        mapped = self.topology.map_way_geometry(str(way_id), tuple(zip(xs, ys, strict=True)))
        result = (way_id, mapped)
        self._mapping_cache[edge_index] = result
        return result

    def _apply_project_costs(self, unmapped_edge_multiplier: float) -> Mapping[str, int]:
        mapped_count = 0
        unmapped_count = 0
        originally_non_bicycle_count = 0
        enabled_from_project_count = 0
        origin_vertices: dict[int, set[int]] = defaultdict(set)
        destination_vertices: dict[int, set[int]] = defaultdict(set)
        for edge_index in range(self._edge_store.nEdges()):
            edge = self._edge_store.getCursor(edge_index)
            originally_bicycle = edge.allowsStreetMode(self._java.profile.StreetMode.BICYCLE)
            if not originally_bicycle:
                originally_non_bicycle_count += 1
            _, mapped = self._edge_mapping(edge_index)
            if mapped:
                first = mapped[0]
                last = mapped[-1]
                first_segment = self.topology.segments[first.segment_index]
                last_segment = self.topology.segments[last.segment_index]
                project_origin = first_segment.v_index if first.reversed else first_segment.u_index
                project_destination = (
                    last_segment.u_index if last.reversed else last_segment.v_index
                )
                origin_vertices[project_origin].add(int(edge.getFromVertex()))
                destination_vertices[project_destination].add(int(edge.getToVertex()))
                length = sum(self.topology.segments[item.segment_index].length_m for item in mapped)
                generalized = sum(
                    (
                        self.topology.segments[item.segment_index].generalized_reverse
                        if item.reversed
                        else self.topology.segments[item.segment_index].generalized_forward
                    )
                    for item in mapped
                )
                factor = generalized / length if length > 0 else unmapped_edge_multiplier
                mapped_count += 1
                if not originally_bicycle:
                    edge.allowStreetMode(self._java.profile.StreetMode.BICYCLE)
                    enabled_from_project_count += 1
            else:
                factor = unmapped_edge_multiplier
                unmapped_count += 1
                # The CIW graph is authoritative for cycling access and
                # direction. Leaving an unmatched R5 bicycle edge merely
                # penalised can still make an unreconcilable route optimal.
                # R5 otherwise falls back to walking a bicycle when its bike
                # flag is cleared, so pedestrian permission must also be
                # removed from this engine-local copy.
                edge.clearFlag(self._java.streets.EdgeStore.EdgeFlag.ALLOWS_BIKE)
                edge.clearFlag(self._java.streets.EdgeStore.EdgeFlag.ALLOWS_PEDESTRIAN)
            self._base_factors[edge_index] = factor
            self._traversal_times.setBikeTimeFactor(edge_index, factor)
        self._origin_vertex_by_node = {
            node_index: next(iter(vertices))
            for node_index, vertices in origin_vertices.items()
            if len(vertices) == 1
        }
        self._destination_vertex_by_node = {
            node_index: next(iter(vertices))
            for node_index, vertices in destination_vertices.items()
            if len(vertices) == 1
        }
        self.origin_node_indices = frozenset(self._origin_vertex_by_node)
        self.destination_node_indices = frozenset(self._destination_vertex_by_node)
        return {
            "r5_directed_edges": int(self._edge_store.nEdges()),
            "mapped_r5_directed_edges": mapped_count,
            "unmapped_r5_directed_edges": unmapped_count,
            "originally_non_bicycle_r5_directed_edges": originally_non_bicycle_count,
            "enabled_from_authoritative_project_graph": enabled_from_project_count,
            "project_nodes_usable_as_r5_origins": len(self.origin_node_indices),
            "project_nodes_usable_as_r5_destinations": len(self.destination_node_indices),
            "ambiguous_project_origin_vertices_excluded": sum(
                len(vertices) != 1 for vertices in origin_vertices.values()
            ),
            "ambiguous_project_destination_vertices_excluded": sum(
                len(vertices) != 1 for vertices in destination_vertices.values()
            ),
        }

    def _raw_path(
        self,
        origin: SnapNode,
        destination: SnapNode,
        *,
        distance_objective: bool = False,
    ) -> tuple[ReconciledPath | None, float | None, float | None, str | None]:
        router = self._java.streets.StreetRouter(self.network.street_layer)
        router.profileRequest = self.request
        router.streetMode = self._transport_mode.BICYCLE
        if distance_objective:
            router.quantityToMinimize = (
                self._java.streets.StreetRouter.State.RoutingVariable.DISTANCE_MILLIMETERS
            )
        origin_vertex = self._origin_vertex_by_node.get(origin.node_index)
        destination_vertex = self._destination_vertex_by_node.get(destination.node_index)
        if origin_vertex is None:
            return None, None, None, "r5_origin_vertex_missing"
        if destination_vertex is None:
            return None, 0.0, None, "r5_destination_vertex_missing"
        router.setOrigin(origin_vertex)
        router.toVertex = destination_vertex
        router.route()
        try:
            state = router.getStateAtVertex(destination_vertex)
            if state is None:
                return None, 0.0, 0.0, "r5_no_directed_path"
            street_path = self._java.profile.StreetPath(state, self.network, False)
            r5_edges = tuple(int(item) for item in street_path.getEdges())
        except Exception:
            return None, 0.0, 0.0, "r5_path_extraction_failed"
        way_ids: list[int] = []
        mappings: list[tuple[ProjectTraversal, ...] | None] = []
        for edge_index in r5_edges:
            way_id, mapped = self._edge_mapping(edge_index)
            way_ids.append(way_id)
            mappings.append(mapped)
        reconciled = self.topology.trim_and_reconcile(
            r5_edges,
            way_ids,
            mappings,
            origin_node_index=origin.node_index,
            destination_node_index=destination.node_index,
        )
        failure = (
            None
            if reconciled is not None
            else self.topology.reconciliation_failure_reason(
                mappings,
                origin_node_index=origin.node_index,
                destination_node_index=destination.node_index,
            )
        )
        return reconciled, 0.0, 0.0, failure

    def route(
        self,
        origin: SnapNode,
        destination: SnapNode,
        *,
        plausible_paths: int = 5,
        maximum_cost_ratio: float = 1.5,
        maximum_detour_ratio: float = 1.5,
        maximum_shared_edge_ratio: float = 0.95,
        cost_scale: float = 0.002,
        path_size_coefficient: float = 1.0,
        alternative_penalty_multiplier: float = 2.0,
        maximum_alternative_attempts: int = 20,
        engine_link_tolerance_m: float = 1.0,
    ) -> R5RouteResult:
        if plausible_paths < 1:
            raise ValueError("plausible_paths must be positive")
        if min(maximum_cost_ratio, maximum_detour_ratio) < 1:
            raise ValueError("cost and detour ratios must be at least one")
        if not 0 <= maximum_shared_edge_ratio <= 1:
            raise ValueError("maximum_shared_edge_ratio must be in [0, 1]")
        if alternative_penalty_multiplier <= 1:
            raise ValueError("alternative_penalty_multiplier must exceed one")
        if maximum_alternative_attempts < plausible_paths - 1:
            raise ValueError("maximum_alternative_attempts cannot be smaller than k - 1")
        if origin.node_index == destination.node_index:
            return R5RouteResult(
                "unassigned",
                "origin_destination_same_project_node",
                0.0,
                0.0,
                None,
                (),
            )

        shortest, origin_link, destination_link, shortest_failure = self._raw_path(
            origin, destination, distance_objective=True
        )
        if origin_link is None:
            return R5RouteResult("unassigned", "r5_origin_link_failed", None, None, None, ())
        if destination_link is None:
            return R5RouteResult(
                "unassigned", "r5_destination_link_failed", origin_link, None, None, ()
            )
        if origin_link > engine_link_tolerance_m or destination_link > engine_link_tolerance_m:
            return R5RouteResult(
                "unassigned",
                "r5_project_snap_mismatch",
                origin_link,
                destination_link,
                None,
                (),
            )
        if shortest is None:
            return R5RouteResult(
                "unassigned",
                shortest_failure or "no_reconciled_shortest_distance_path",
                origin_link,
                destination_link,
                None,
                (),
            )
        shortest_distance = shortest.length_m
        shortest_gradient, shortest_ascent, _ = path_gradient_metrics(
            shortest, self.topology.segments
        )
        base, _, _, base_failure = self._raw_path(origin, destination)
        if base is None:
            return R5RouteResult(
                "unassigned",
                base_failure or "no_reconciled_comfort_path",
                origin_link,
                destination_link,
                shortest_distance,
                (),
            )
        if base.length_m > shortest_distance * maximum_detour_ratio + 1e-9:
            base = shortest
        accepted = [base]
        signatures = {base.project_edge_indices}
        penalised_frequency: dict[int, int] = defaultdict(int)
        for edge_index in base.r5_edge_ids:
            penalised_frequency[edge_index] += 1

        attempts = 0
        while len(accepted) < plausible_paths and attempts < maximum_alternative_attempts:
            attempts += 1
            changed: list[int] = []
            for edge_index, frequency in penalised_frequency.items():
                factor = float(self._base_factors[edge_index]) * (
                    alternative_penalty_multiplier**frequency
                )
                self._traversal_times.setBikeTimeFactor(edge_index, factor)
                changed.append(edge_index)
            try:
                candidate, _, _, _ = self._raw_path(origin, destination)
            finally:
                for edge_index in changed:
                    self._traversal_times.setBikeTimeFactor(
                        edge_index, float(self._base_factors[edge_index])
                    )
            if candidate is None:
                break
            for edge_index in candidate.r5_edge_ids:
                penalised_frequency[edge_index] += 1
            signature = candidate.project_edge_indices
            if signature in signatures:
                continue
            signatures.add(signature)
            if candidate.generalized_cost > base.generalized_cost * maximum_cost_ratio + 1e-9:
                continue
            if candidate.length_m > shortest_distance * maximum_detour_ratio + 1e-9:
                continue
            if any(
                _shared_edge_ratio(candidate, existing, self.topology.segments)
                > maximum_shared_edge_ratio
                for existing in accepted
            ):
                continue
            accepted.append(candidate)

        probabilities = path_size_probabilities(
            accepted,
            self.topology.segments,
            cost_scale=cost_scale,
            path_size_coefficient=path_size_coefficient,
        )
        alternatives = tuple(
            RouteAlternative(
                path,
                probability,
                path.length_m / shortest_distance if shortest_distance > 0 else 1.0,
            )
            for path, probability in zip(accepted, probabilities, strict=True)
        )
        return R5RouteResult(
            "assigned",
            None,
            origin_link,
            destination_link,
            shortest_distance,
            alternatives,
            shortest_gradient,
            shortest_ascent,
        )
