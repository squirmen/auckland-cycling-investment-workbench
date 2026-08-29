"""Deterministic cycling routing with plausible alternatives and path-size logit.

Alternative generation uses Yen's loopless k-shortest-path algorithm (Yen, 1971,
*Management Science*, 17(11), 712-716).  Choice probabilities include the
path-size correction described by Ben-Akiva and Bierlaire (1999), which prevents
near-duplicate routes from receiving independent-alternative weight.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import pairwise
from math import exp, isfinite, log
from typing import Literal

from .models import Edge, ODFlow, RoutePath
from .stress import edge_generalized_cost
from .topology import DirectedTopology, Traversal

EdgeCost = Callable[[Edge, bool], float]


def _default_cost(edge: Edge, reversed: bool) -> float:
    return edge_generalized_cost(edge, reversed=reversed)


def _physical_length_cost(edge: Edge, reversed: bool) -> float:
    del reversed
    return edge.length_m


def _traversal_between(topology: DirectedTopology, tail: str, head: str, edge_id: str) -> Traversal:
    for traversal in topology.outgoing(tail):
        if traversal.head == head and traversal.edge_id == edge_id:
            return traversal
    raise ValueError(f"route uses forbidden traversal {tail}->{head} on {edge_id}")


def route_cost(
    topology: DirectedTopology,
    nodes: Sequence[str],
    edge_ids: Sequence[str],
    *,
    cost: EdgeCost = _default_cost,
) -> tuple[float, float]:
    """Calculate generalized cost and physical length for a specified route."""

    if len(nodes) != len(edge_ids) + 1:
        raise ValueError("route nodes and edges are inconsistent")
    generalized = 0.0
    length = 0.0
    for (tail, head), edge_id in zip(pairwise(nodes), edge_ids, strict=True):
        traversal = _traversal_between(topology, tail, head, edge_id)
        edge = topology.edge(edge_id)
        value = cost(edge, traversal.reversed)
        if value < 0 or not isfinite(value):
            raise ValueError(f"invalid cost for edge {edge_id}")
        generalized += value
        length += edge.length_m
    return generalized, length


def shortest_path(
    topology: DirectedTopology,
    origin: str,
    destination: str,
    *,
    cost: EdgeCost = _default_cost,
    banned_nodes: frozenset[str] = frozenset(),
    banned_traversals: frozenset[str] = frozenset(),
    max_cost: float | None = None,
) -> RoutePath | None:
    """Return a minimum-cost directed path, or ``None`` when disconnected."""

    if origin not in topology.nodes or destination not in topology.nodes:
        raise KeyError("origin and destination must be topology nodes")
    if origin in banned_nodes or destination in banned_nodes:
        return None
    if origin == destination:
        return RoutePath((origin,), (), 0.0, 0.0)

    distance: dict[str, float] = {origin: 0.0}
    signature: dict[str, tuple[str, ...]] = {origin: ()}
    predecessor: dict[str, tuple[str, Traversal]] = {}
    queue: list[tuple[float, tuple[str, ...], str]] = [(0.0, (), origin)]
    while queue:
        accumulated, path_signature, node_id = heappop(queue)
        if accumulated != distance.get(node_id) or path_signature != signature.get(node_id):
            continue
        if node_id == destination:
            break
        for traversal in topology.outgoing(node_id):
            if traversal.id in banned_traversals or traversal.head in banned_nodes:
                continue
            edge = topology.edge(traversal.edge_id)
            step = cost(edge, traversal.reversed)
            if step < 0 or not isfinite(step):
                raise ValueError(f"edge cost must be finite and non-negative: {edge.id}")
            candidate = accumulated + step
            if max_cost is not None and candidate > max_cost:
                continue
            candidate_signature = (*path_signature, traversal.id)
            known = distance.get(traversal.head)
            if (
                known is None
                or candidate < known - 1e-12
                or (
                    abs(candidate - known) <= 1e-12
                    and candidate_signature < signature[traversal.head]
                )
            ):
                distance[traversal.head] = candidate
                signature[traversal.head] = candidate_signature
                predecessor[traversal.head] = (node_id, traversal)
                heappush(queue, (candidate, candidate_signature, traversal.head))

    if destination not in distance:
        return None
    reverse_nodes = [destination]
    reverse_edges: list[str] = []
    cursor = destination
    while cursor != origin:
        previous, traversal = predecessor[cursor]
        reverse_edges.append(traversal.edge_id)
        reverse_nodes.append(previous)
        cursor = previous
    nodes = tuple(reversed(reverse_nodes))
    edge_ids = tuple(reversed(reverse_edges))
    generalized, length = route_cost(topology, nodes, edge_ids, cost=cost)
    return RoutePath(nodes, edge_ids, generalized, length)


def _shared_length_ratio(path: RoutePath, other: RoutePath, topology: DirectedTopology) -> float:
    if path.length_m <= 0:
        return 1.0
    shared = set(path.edge_ids).intersection(other.edge_ids)
    return sum(topology.edge(edge_id).length_m for edge_id in shared) / path.length_m


def k_plausible_paths(
    topology: DirectedTopology,
    origin: str,
    destination: str,
    *,
    k: int = 5,
    cost: EdgeCost = _default_cost,
    max_cost_ratio: float = 1.5,
    max_detour_ratio: float = 1.5,
    max_shared_edge_ratio: float = 0.95,
) -> tuple[RoutePath, ...]:
    """Generate loopless routes within cost and physical-distance tolerances.

    Physical detour is measured against the shortest-distance feasible directed
    path, independently of the comfort/generalized-cost objective.
    """

    if k < 1:
        raise ValueError("k must be positive")
    if max_cost_ratio < 1:
        raise ValueError("max_cost_ratio must be at least one")
    if max_detour_ratio < 1:
        raise ValueError("max_detour_ratio must be at least one")
    if not 0 <= max_shared_edge_ratio <= 1:
        raise ValueError("max_shared_edge_ratio must be in [0, 1]")
    shortest_distance = shortest_path(topology, origin, destination, cost=_physical_length_cost)
    if shortest_distance is None:
        return ()
    maximum_length = shortest_distance.length_m * max_detour_ratio
    first = shortest_path(topology, origin, destination, cost=cost)
    if first is None:
        return ()
    if first.length_m > maximum_length + 1e-9:
        generalized, length = route_cost(
            topology,
            shortest_distance.nodes,
            shortest_distance.edge_ids,
            cost=cost,
        )
        first = RoutePath(
            shortest_distance.nodes,
            shortest_distance.edge_ids,
            generalized,
            length,
        )
    accepted = [first]
    candidate_heap: list[tuple[float, tuple[str, ...], tuple[str, ...], RoutePath]] = []
    queued: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()

    while len(accepted) < k:
        previous = accepted[-1]
        for spur_index in range(len(previous.nodes) - 1):
            root_nodes = previous.nodes[: spur_index + 1]
            root_edges = previous.edge_ids[:spur_index]
            banned_arcs: set[str] = set()
            for path in accepted:
                if (
                    path.nodes[: spur_index + 1] == root_nodes
                    and path.edge_ids[:spur_index] == root_edges
                    and spur_index < len(path.edge_ids)
                ):
                    traversal = _traversal_between(
                        topology,
                        path.nodes[spur_index],
                        path.nodes[spur_index + 1],
                        path.edge_ids[spur_index],
                    )
                    banned_arcs.add(traversal.id)
            spur = shortest_path(
                topology,
                root_nodes[-1],
                destination,
                cost=cost,
                banned_nodes=frozenset(root_nodes[:-1]),
                banned_traversals=frozenset(banned_arcs),
                max_cost=first.generalized_cost * max_cost_ratio,
            )
            if spur is None:
                continue
            total_nodes = root_nodes[:-1] + spur.nodes
            total_edges = root_edges + spur.edge_ids
            key = (total_nodes, total_edges)
            if key in queued or any((p.nodes, p.edge_ids) == key for p in accepted):
                continue
            generalized, length = route_cost(topology, total_nodes, total_edges, cost=cost)
            if generalized > first.generalized_cost * max_cost_ratio + 1e-9:
                continue
            if length > maximum_length + 1e-9:
                continue
            candidate = RoutePath(total_nodes, total_edges, generalized, length)
            queued.add(key)
            heappush(candidate_heap, (generalized, total_edges, total_nodes, candidate))

        selected: RoutePath | None = None
        while candidate_heap:
            _, _, _, option = heappop(candidate_heap)
            if all(
                _shared_length_ratio(option, chosen, topology) <= max_shared_edge_ratio
                for chosen in accepted
            ):
                selected = option
                break
        if selected is None:
            break
        accepted.append(selected)
    return tuple(accepted)


def path_size_factors(paths: Sequence[RoutePath], topology: DirectedTopology) -> tuple[float, ...]:
    """Compute path-size factors in ``(0, 1]`` for overlapping alternatives."""

    if not paths:
        return ()
    frequency: dict[str, int] = {}
    for path in paths:
        for edge_id in set(path.edge_ids):
            frequency[edge_id] = frequency.get(edge_id, 0) + 1
    factors: list[float] = []
    for path in paths:
        if path.length_m <= 0:
            factors.append(1.0)
            continue
        value = sum(
            (topology.edge(edge_id).length_m / path.length_m) / frequency[edge_id]
            for edge_id in path.edge_ids
        )
        factors.append(min(1.0, max(value, 1e-12)))
    return tuple(factors)


def path_size_logit(
    paths: Sequence[RoutePath],
    topology: DirectedTopology,
    *,
    cost_scale: float = 0.002,
    path_size_coefficient: float = 1.0,
) -> tuple[float, ...]:
    """Return normalised route-choice probabilities with overlap correction."""

    if cost_scale < 0 or path_size_coefficient < 0:
        raise ValueError("logit parameters must be non-negative")
    if not paths:
        return ()
    factors = path_size_factors(paths, topology)
    utilities = [
        -cost_scale * path.generalized_cost + path_size_coefficient * log(factor)
        for path, factor in zip(paths, factors, strict=True)
    ]
    maximum = max(utilities)
    weights = [exp(value - maximum) for value in utilities]
    total = sum(weights)
    return tuple(value / total for value in weights)


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    """Probabilistic edge assignment and auditable OD route sets."""

    edge_flow: Mapping[str, float]
    paths_by_od: Mapping[str, tuple[RoutePath, ...]]
    probabilities_by_od: Mapping[str, tuple[float, ...]]
    unassigned_od_ids: tuple[str, ...]
    route_status_by_od: Mapping[str, RouteStatus]
    path_ledger: tuple[PathLedgerRecord, ...]

    @property
    def od_ledger(self) -> tuple[RouteStatus, ...]:
        """Every input OD relation in stable identifier order."""

        return tuple(self.route_status_by_od[key] for key in sorted(self.route_status_by_od))


@dataclass(frozen=True, slots=True)
class RouteStatus:
    """Complete route ledger entry for one OD relation."""

    od_id: str
    origin: str
    destination: str
    purpose: str
    eligible: float
    observed_cycle: float
    scenario_cycle: float
    analysis_weight: float
    assigned_demand: float
    origin_snap_distance_m: float
    destination_snap_distance_m: float
    status: Literal["assigned", "unassigned"]
    reason: str | None
    origin_component: str | None
    destination_component: str | None
    path_ids: tuple[str, ...]
    probabilities: tuple[float, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a portable, schema-ready OD ledger record."""

        return {
            "od_id": self.od_id,
            "origin": self.origin,
            "destination": self.destination,
            "purpose": self.purpose,
            "eligible": self.eligible,
            "observed_cycle": self.observed_cycle,
            "scenario_cycle": self.scenario_cycle,
            "analysis_weight": self.analysis_weight,
            "assigned_demand": self.assigned_demand,
            "origin_snap_distance_m": self.origin_snap_distance_m,
            "destination_snap_distance_m": self.destination_snap_distance_m,
            "origin_component": self.origin_component,
            "destination_component": self.destination_component,
            "status": self.status,
            "failure_reason": self.reason,
            "path_ids": list(self.path_ids),
            "probabilities": list(self.probabilities),
        }


@dataclass(frozen=True, slots=True)
class PathLedgerRecord:
    """One plausible route and its probability for a retained OD record."""

    path_id: str
    od_id: str
    path_index: int
    probability: float
    generalized_cost: float
    length_m: float
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "path_id": self.path_id,
            "od_id": self.od_id,
            "path_index": self.path_index,
            "probability": self.probability,
            "generalized_cost": self.generalized_cost,
            "length_m": self.length_m,
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
        }


def assign_demand(
    topology: DirectedTopology,
    od_flows: Iterable[ODFlow],
    *,
    demand: Callable[[ODFlow], float] = lambda od: od.scenario_cycle,
    k: int = 5,
    cost: EdgeCost = _default_cost,
    max_cost_ratio: float = 1.5,
    max_detour_ratio: float = 1.5,
    max_shared_edge_ratio: float = 0.95,
    cost_scale: float = 0.002,
    path_size_coefficient: float = 1.0,
) -> AssignmentResult:
    """Assign OD cycling continuously across plausible paths."""

    od_records = tuple(od_flows)
    if len({od.id for od in od_records}) != len(od_records):
        raise ValueError("OD ids must be unique within an assignment")
    edge_flow = {edge_id: 0.0 for edge_id in topology.edges}
    paths_by_od: dict[str, tuple[RoutePath, ...]] = {}
    probabilities_by_od: dict[str, tuple[float, ...]] = {}
    unassigned: list[str] = []
    route_status: dict[str, RouteStatus] = {}
    path_ledger: list[PathLedgerRecord] = []
    component_by_node = topology.component_by_node()
    for od in sorted(od_records, key=lambda value: value.id):
        amount = demand(od)
        if amount < 0 or not isfinite(amount):
            raise ValueError(f"invalid demand for {od.id}")
        origin_component = component_by_node.get(od.origin)
        destination_component = component_by_node.get(od.destination)
        if origin_component is None or destination_component is None:
            missing = (
                "missing_origin_and_destination"
                if origin_component is None and destination_component is None
                else "missing_origin"
                if origin_component is None
                else "missing_destination"
            )
            unassigned.append(od.id)
            route_status[od.id] = RouteStatus(
                od.id,
                od.origin,
                od.destination,
                od.purpose,
                od.eligible,
                od.observed_cycle,
                od.scenario_cycle,
                od.weight,
                amount,
                od.origin_snap_distance_m,
                od.destination_snap_distance_m,
                "unassigned",
                missing,
                origin_component,
                destination_component,
                (),
                (),
            )
            continue
        paths = k_plausible_paths(
            topology,
            od.origin,
            od.destination,
            k=k,
            cost=cost,
            max_cost_ratio=max_cost_ratio,
            max_detour_ratio=max_detour_ratio,
            max_shared_edge_ratio=max_shared_edge_ratio,
        )
        if not paths:
            unassigned.append(od.id)
            reason = (
                "disconnected_components"
                if origin_component != destination_component
                else "no_plausible_directed_path"
            )
            route_status[od.id] = RouteStatus(
                od.id,
                od.origin,
                od.destination,
                od.purpose,
                od.eligible,
                od.observed_cycle,
                od.scenario_cycle,
                od.weight,
                amount,
                od.origin_snap_distance_m,
                od.destination_snap_distance_m,
                "unassigned",
                reason,
                origin_component,
                destination_component,
                (),
                (),
            )
            continue
        probabilities = path_size_logit(
            paths,
            topology,
            cost_scale=cost_scale,
            path_size_coefficient=path_size_coefficient,
        )
        for path, probability in zip(paths, probabilities, strict=True):
            for edge_id in path.edge_ids:
                edge_flow[edge_id] += amount * probability
        paths_by_od[od.id] = paths
        probabilities_by_od[od.id] = probabilities
        path_ids = tuple(f"{od.id}:path:{index}" for index in range(1, len(paths) + 1))
        path_ledger.extend(
            PathLedgerRecord(
                path_id,
                od.id,
                index,
                probability,
                path.generalized_cost,
                path.length_m,
                path.nodes,
                path.edge_ids,
            )
            for index, (path_id, path, probability) in enumerate(
                zip(path_ids, paths, probabilities, strict=True), start=1
            )
        )
        route_status[od.id] = RouteStatus(
            od.id,
            od.origin,
            od.destination,
            od.purpose,
            od.eligible,
            od.observed_cycle,
            od.scenario_cycle,
            od.weight,
            amount,
            od.origin_snap_distance_m,
            od.destination_snap_distance_m,
            "assigned",
            None,
            origin_component,
            destination_component,
            path_ids,
            probabilities,
        )
    return AssignmentResult(
        edge_flow=edge_flow,
        paths_by_od=paths_by_od,
        probabilities_by_od=probabilities_by_od,
        unassigned_od_ids=tuple(unassigned),
        route_status_by_od=route_status,
        path_ledger=tuple(path_ledger),
    )
