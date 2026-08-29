"""Demand-weighted low-stress connectivity and transparent prioritisation.

The connectivity statistic here is deliberately named an OD low-stress
connectivity share.  It should not be compared with city-level NCI products that
use different destinations, grids, weights, or stress rules.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from .candidates import apply_candidate
from .models import CorridorCandidate, Edge, ODFlow, SequenceStep
from .routing import shortest_path
from .stress import StressInputs, level_of_traffic_stress
from .topology import DirectedTopology


@dataclass(frozen=True, slots=True)
class ConnectivityResult:
    """Demand-weighted OD low-stress connectivity result."""

    score: float
    connected_weight: float
    total_weight: float
    connected_by_od: Mapping[str, bool]
    all_network_distance_by_od: Mapping[str, float | None]
    low_stress_distance_by_od: Mapping[str, float | None]


def weighted_low_stress_connectivity(
    topology: DirectedTopology,
    od_flows: Iterable[ODFlow],
    *,
    max_lts: int = 2,
    detour_ratio: float = 1.5,
    demand: Callable[[ODFlow], float] = lambda od: od.scenario_cycle * od.weight,
) -> ConnectivityResult:
    """Calculate weighted share connected by a tolerably direct low-stress route."""

    if max_lts not in (1, 2, 3, 4):
        raise ValueError("max_lts must be in 1..4")
    if detour_ratio < 1:
        raise ValueError("detour_ratio must be at least one")
    low_stress_edges = [
        edge
        for edge in topology.edges.values()
        if level_of_traffic_stress(StressInputs.from_edge(edge)).level <= max_lts
    ]
    low_stress = DirectedTopology(topology.nodes.values(), low_stress_edges)

    def distance_cost(edge: Edge, reversed: bool) -> float:
        del reversed
        return edge.length_m

    connected: dict[str, bool] = {}
    all_distances: dict[str, float | None] = {}
    low_distances: dict[str, float | None] = {}
    total_weight = 0.0
    connected_weight = 0.0
    for od in sorted(od_flows, key=lambda value: value.id):
        weight = demand(od)
        if weight < 0 or not isfinite(weight):
            raise ValueError(f"invalid connectivity weight for {od.id}")
        total_weight += weight
        all_path = shortest_path(topology, od.origin, od.destination, cost=distance_cost)
        low_path = shortest_path(low_stress, od.origin, od.destination, cost=distance_cost)
        all_distance = all_path.length_m if all_path is not None else None
        low_distance = low_path.length_m if low_path is not None else None
        is_connected = (
            all_distance is not None
            and low_distance is not None
            and (all_distance == 0 or low_distance <= detour_ratio * all_distance + 1e-9)
        )
        all_distances[od.id] = all_distance
        low_distances[od.id] = low_distance
        connected[od.id] = is_connected
        if is_connected:
            connected_weight += weight
    score = connected_weight / total_weight if total_weight > 0 else 0.0
    return ConnectivityResult(
        score,
        connected_weight,
        total_weight,
        connected,
        all_distances,
        low_distances,
    )


ScoreFunction = Callable[[DirectedTopology], float]


def greedy_cumulative_sequence(
    topology: DirectedTopology,
    candidates: Sequence[CorridorCandidate],
    score_function: ScoreFunction,
    *,
    budget: float | None = None,
    score_per_cost: bool = True,
) -> tuple[SequenceStep, ...]:
    """Greedily sequence projects, recomputing the full network after every pick.

    This captures complementarity: a project's marginal effect is calculated on
    the network containing all prior selections, rather than by unioning static
    baseline coverage sets.
    """

    if budget is not None and budget < 0:
        raise ValueError("budget must be non-negative")
    if len({candidate.id for candidate in candidates}) != len(candidates):
        raise ValueError("candidate ids must be unique")
    current_topology = topology
    current_score = score_function(current_topology)
    remaining = {candidate.id: candidate for candidate in candidates}
    chosen: list[str] = []
    spent = 0.0
    steps: list[SequenceStep] = []

    while remaining:
        options: list[tuple[float, float, str, CorridorCandidate, DirectedTopology, float]] = []
        for candidate in remaining.values():
            if budget is not None and spent + candidate.capital_cost > budget + 1e-9:
                continue
            treated = apply_candidate(current_topology, candidate)
            score = score_function(treated)
            marginal = score - current_score
            denominator = candidate.capital_cost if candidate.capital_cost > 0 else 1e-12
            selection_value = marginal / denominator if score_per_cost else marginal
            options.append((selection_value, marginal, candidate.id, candidate, treated, score))
        if not options:
            break
        selection_value, marginal, _, candidate, treated, score = max(
            options,
            key=lambda option: (option[0], option[1], -option[3].capital_cost, option[2]),
        )
        if marginal <= 1e-12:
            break
        chosen.append(candidate.id)
        spent += candidate.capital_cost
        steps.append(
            SequenceStep(
                rank=len(steps) + 1,
                candidate_id=candidate.id,
                cumulative_candidate_ids=tuple(chosen),
                marginal_score=marginal,
                cumulative_score=score,
                cumulative_cost=spent,
            )
        )
        current_topology = treated
        current_score = score
        del remaining[candidate.id]
    return tuple(steps)


@dataclass(frozen=True, slots=True)
class PriorityPreset:
    """Named, inspectable weights for normalised candidate indicators."""

    name: str
    weights: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.weights or any(value < 0 for value in self.weights.values()):
            raise ValueError("preset weights must be non-negative and non-empty")
        if sum(self.weights.values()) <= 0:
            raise ValueError("at least one preset weight must be positive")


PRIORITY_PRESETS: Mapping[str, PriorityPreset] = {
    "network": PriorityPreset(
        "network", {"demand": 0.25, "connectivity": 0.60, "equity": 0.10, "value": 0.05}
    ),
    "equity": PriorityPreset(
        "equity", {"demand": 0.15, "connectivity": 0.20, "equity": 0.55, "value": 0.10}
    ),
    "school": PriorityPreset(
        "school", {"demand": 0.15, "connectivity": 0.20, "school": 0.55, "value": 0.10}
    ),
    "everyday": PriorityPreset(
        "everyday",
        {"demand": 0.15, "connectivity": 0.20, "everyday": 0.55, "value": 0.10},
    ),
    "transit": PriorityPreset(
        "transit", {"demand": 0.15, "connectivity": 0.20, "transit": 0.55, "value": 0.10}
    ),
    "appraisal": PriorityPreset(
        "appraisal", {"demand": 0.15, "connectivity": 0.10, "equity": 0.05, "value": 0.70}
    ),
}


def preset_scores(
    metrics: Mapping[str, Mapping[str, float]], preset: PriorityPreset
) -> Mapping[str, float]:
    """Min-max normalise declared indicators and apply a named weight set."""

    if not metrics:
        return {}
    ids = sorted(metrics)
    missing = {
        metric
        for metric in preset.weights
        if any(metric not in metrics[candidate_id] for candidate_id in ids)
    }
    if missing:
        raise KeyError(f"missing preset metrics: {sorted(missing)}")
    bounds = {
        metric: (
            min(metrics[candidate_id][metric] for candidate_id in ids),
            max(metrics[candidate_id][metric] for candidate_id in ids),
        )
        for metric in preset.weights
    }
    weight_total = sum(preset.weights.values())
    result: dict[str, float] = {}
    for candidate_id in ids:
        score = 0.0
        for metric, weight in preset.weights.items():
            lower, upper = bounds[metric]
            normalised = (
                0.5 if upper == lower else (metrics[candidate_id][metric] - lower) / (upper - lower)
            )
            score += weight * normalised
        result[candidate_id] = score / weight_total
    return result


def pareto_frontier(
    metrics: Mapping[str, Mapping[str, float]],
    *,
    maximise: Sequence[str],
    minimise: Sequence[str] = (),
) -> tuple[str, ...]:
    """Return non-dominated candidate IDs for explicitly directed objectives."""

    objectives = tuple(maximise) + tuple(minimise)
    if not objectives:
        raise ValueError("at least one objective is required")
    for candidate_id, values in metrics.items():
        missing = set(objectives).difference(values)
        if missing:
            raise KeyError(f"{candidate_id} is missing objectives: {sorted(missing)}")

    def no_worse(a: str, b: str, objective: str) -> bool:
        if objective in maximise:
            return metrics[a][objective] >= metrics[b][objective]
        return metrics[a][objective] <= metrics[b][objective]

    def strictly_better(a: str, b: str, objective: str) -> bool:
        if objective in maximise:
            return metrics[a][objective] > metrics[b][objective]
        return metrics[a][objective] < metrics[b][objective]

    frontier: list[str] = []
    for candidate_id in sorted(metrics):
        dominated = any(
            other != candidate_id
            and all(no_worse(other, candidate_id, objective) for objective in objectives)
            and any(strictly_better(other, candidate_id, objective) for objective in objectives)
            for other in metrics
        )
        if not dominated:
            frontier.append(candidate_id)
    return tuple(frontier)
