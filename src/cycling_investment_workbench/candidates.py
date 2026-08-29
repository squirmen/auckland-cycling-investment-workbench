"""Exact-edge corridor treatments and continuous cycling demand response."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from math import exp, isfinite, log

from .models import CandidateEvaluation, CorridorCandidate, Edge, FacilityType, ODFlow
from .routing import EdgeCost, shortest_path
from .stress import edge_generalized_cost
from .topology import DirectedTopology


@dataclass(frozen=True, slots=True)
class DemandResponseParameters:
    """Bounded odds elasticity for change in cycling impedance.

    ``cost_elasticity`` is the elasticity of cycling odds with respect to the
    inverse generalized-cost ratio.  It should be estimated locally or varied in
    uncertainty analysis; the default is a neutral scenario value, not a claim.
    """

    cost_elasticity: float = 1.0
    minimum_probability: float = 1e-5

    def __post_init__(self) -> None:
        if self.cost_elasticity < 0 or not isfinite(self.cost_elasticity):
            raise ValueError("cost_elasticity must be finite and non-negative")
        if not 0 < self.minimum_probability < 0.5:
            raise ValueError("minimum_probability must be in (0, 0.5)")


DEFAULT_DEMAND_RESPONSE = DemandResponseParameters()


def continuous_demand_response(
    eligible: float,
    baseline_cycle: float,
    baseline_cost: float,
    treated_cost: float,
    *,
    parameters: DemandResponseParameters = DEFAULT_DEMAND_RESPONSE,
) -> float:
    """Return additional cycling from a smooth, bounded cost-response curve.

    The model is

    ``logit(p1) = logit(p0) + elasticity * log(C0 / C1)``.

    It yields no step discontinuity and no increase when the proposal fails to
    improve generalized cost.  The small probability floor permits analysis of
    disclosure-controlled zero baselines without asserting an exact zero share.
    """

    if eligible < 0 or baseline_cycle < 0 or baseline_cycle > eligible:
        raise ValueError("cycling counts must satisfy 0 <= baseline <= eligible")
    if baseline_cost <= 0 or treated_cost <= 0:
        raise ValueError("route costs must be positive")
    if treated_cost >= baseline_cost or eligible == 0:
        return 0.0
    observed_probability = baseline_cycle / eligible
    p0 = min(
        1.0 - parameters.minimum_probability,
        max(parameters.minimum_probability, observed_probability),
    )
    log_odds = log(p0 / (1.0 - p0))
    log_odds += parameters.cost_elasticity * log(baseline_cost / treated_cost)
    p1 = 1.0 / (1.0 + exp(-log_odds))
    return max(0.0, min(eligible - baseline_cycle, eligible * (p1 - observed_probability)))


def apply_candidate(topology: DirectedTopology, candidate: CorridorCandidate) -> DirectedTopology:
    """Return a treated topology using only the candidate's declared edge IDs."""

    missing = candidate.edge_ids.difference(topology.edges)
    if missing:
        raise KeyError(f"candidate {candidate.id} references unknown edges: {sorted(missing)}")
    replacements: dict[str, Edge] = {}
    for edge_id in candidate.edge_ids:
        edge = topology.edge(edge_id)
        replacements[edge_id] = replace(edge, facility=candidate.treatment)
    return topology.replace_edges(replacements)


def apply_candidates(
    topology: DirectedTopology, candidates: Iterable[CorridorCandidate]
) -> DirectedTopology:
    """Apply several projects cumulatively, rejecting contradictory treatments."""

    result = topology
    treatment_by_edge: dict[str, object] = {}
    for candidate in candidates:
        for edge_id in candidate.edge_ids:
            previous = treatment_by_edge.get(edge_id)
            if previous is not None and previous != candidate.treatment:
                raise ValueError(f"conflicting treatments for edge {edge_id}")
            treatment_by_edge[edge_id] = candidate.treatment
        result = apply_candidate(result, candidate)
    return result


def _default_cost(edge: Edge, reversed: bool) -> float:
    return edge_generalized_cost(edge, reversed=reversed)


def _evaluate_treated_topology(
    topology: DirectedTopology,
    treated: DirectedTopology,
    od_flows: Iterable[ODFlow],
    *,
    evaluation_id: str,
    changed_edge_ids: frozenset[str],
    response: DemandResponseParameters = DEFAULT_DEMAND_RESPONSE,
    cost: EdgeCost = _default_cost,
    use_scenario_baseline: bool = True,
) -> CandidateEvaluation:
    """Evaluate a treated state against the unchanged original network and demand."""

    records = tuple(od_flows)
    if len({od.id for od in records}) != len(records):
        raise ValueError("OD ids must be unique within a candidate evaluation")
    baseline_costs: dict[str, float] = {}
    treated_costs: dict[str, float] = {}
    additions: dict[str, float] = {}
    statuses: dict[str, str] = {}
    for od in sorted(records, key=lambda value: value.id):
        additions[od.id] = 0.0
        if od.origin not in topology.nodes or od.destination not in topology.nodes:
            statuses[od.id] = "baseline_unroutable"
            continue
        baseline_path = shortest_path(topology, od.origin, od.destination, cost=cost)
        treated_path = shortest_path(treated, od.origin, od.destination, cost=cost)
        if baseline_path is None:
            statuses[od.id] = "baseline_unroutable"
            continue
        baseline_costs[od.id] = baseline_path.generalized_cost
        if treated_path is None:
            statuses[od.id] = "treated_unroutable"
            continue
        treated_costs[od.id] = treated_path.generalized_cost
        statuses[od.id] = "evaluated"
        baseline_cycle = od.scenario_cycle if use_scenario_baseline else od.observed_cycle
        if baseline_path.generalized_cost == 0 and treated_path.generalized_cost == 0:
            continue
        additions[od.id] = continuous_demand_response(
            od.eligible,
            baseline_cycle,
            baseline_path.generalized_cost,
            treated_path.generalized_cost,
            parameters=response,
        )
    return CandidateEvaluation(
        candidate_id=evaluation_id,
        changed_edge_ids=changed_edge_ids,
        baseline_cost_by_od=baseline_costs,
        treated_cost_by_od=treated_costs,
        additional_cycle_by_od=additions,
        status_by_od=statuses,
    )


def evaluate_candidate(
    topology: DirectedTopology,
    candidate: CorridorCandidate,
    od_flows: Iterable[ODFlow],
    *,
    response: DemandResponseParameters = DEFAULT_DEMAND_RESPONSE,
    cost: EdgeCost = _default_cost,
    use_scenario_baseline: bool = True,
) -> CandidateEvaluation:
    """Reroute every OD before and after one exact-edge treatment."""

    return _evaluate_treated_topology(
        topology,
        apply_candidate(topology, candidate),
        od_flows,
        evaluation_id=candidate.id,
        changed_edge_ids=frozenset(candidate.edge_ids),
        response=response,
        cost=cost,
        use_scenario_baseline=use_scenario_baseline,
    )


def evaluate_candidate_set(
    topology: DirectedTopology,
    candidates: Iterable[CorridorCandidate],
    od_flows: Iterable[ODFlow],
    *,
    response: DemandResponseParameters = DEFAULT_DEMAND_RESPONSE,
    cost: EdgeCost = _default_cost,
    use_scenario_baseline: bool = True,
) -> CandidateEvaluation:
    """Evaluate a cumulative portfolio once against the original demand state.

    This prevents induced cycling from being reset and counted again at each
    portfolio step.  Overlapping candidate edges are treated only once.
    """

    projects = tuple(candidates)
    if not projects:
        raise ValueError("at least one candidate is required")
    changed_edges = frozenset(edge_id for candidate in projects for edge_id in candidate.edge_ids)
    return _evaluate_treated_topology(
        topology,
        apply_candidates(topology, projects),
        od_flows,
        evaluation_id="portfolio:" + "+".join(candidate.id for candidate in projects),
        changed_edge_ids=changed_edges,
        response=response,
        cost=cost,
        use_scenario_baseline=use_scenario_baseline,
    )


def candidate_edge_overlap(first: CorridorCandidate, second: CorridorCandidate) -> float:
    """Jaccard overlap of declared physical edge memberships."""

    union = first.edge_ids.union(second.edge_ids)
    return len(first.edge_ids.intersection(second.edge_ids)) / len(union)


@dataclass(frozen=True, slots=True)
class CandidateValidation:
    """Topology validation for an exact-edge corridor candidate."""

    valid: bool
    connected: bool
    terminal_nodes: tuple[str, ...]
    branched_nodes: tuple[str, ...]
    unknown_edge_ids: tuple[str, ...]
    issues: tuple[str, ...]


def validate_candidate(
    topology: DirectedTopology,
    candidate: CorridorCandidate,
    *,
    require_simple_path: bool = True,
) -> CandidateValidation:
    """Validate connectedness and unambiguous terminals from exact edge identity."""

    unknown = tuple(sorted(candidate.edge_ids.difference(topology.edges)))
    if unknown:
        return CandidateValidation(
            False,
            False,
            (),
            (),
            unknown,
            ("unknown_edges",),
        )
    neighbours: dict[str, set[str]] = {}
    for edge_id in candidate.edge_ids:
        edge = topology.edge(edge_id)
        neighbours.setdefault(edge.u, set()).add(edge.v)
        neighbours.setdefault(edge.v, set()).add(edge.u)
    seed = min(neighbours)
    stack = [seed]
    visited = {seed}
    while stack:
        node_id = stack.pop()
        for neighbour in neighbours[node_id]:
            if neighbour not in visited:
                visited.add(neighbour)
                stack.append(neighbour)
    connected = len(visited) == len(neighbours)
    terminals = tuple(sorted(node_id for node_id, values in neighbours.items() if len(values) == 1))
    branches = tuple(sorted(node_id for node_id, values in neighbours.items() if len(values) > 2))
    issues: list[str] = []
    if not connected:
        issues.append("disconnected_edge_set")
    if require_simple_path and len(terminals) != 2:
        issues.append("ambiguous_terminals")
    if require_simple_path and branches:
        issues.append("branched_corridor")
    return CandidateValidation(
        valid=not issues,
        connected=connected,
        terminal_nodes=terminals,
        branched_nodes=branches,
        unknown_edge_ids=(),
        issues=tuple(issues),
    )


def generate_exact_edge_candidate(
    topology: DirectedTopology,
    *,
    candidate_id: str,
    edge_ids: Iterable[str],
    capital_cost: float,
    treatment: FacilityType = FacilityType.PROTECTED_LANE,
    name: str = "",
    require_simple_path: bool = True,
) -> CorridorCandidate:
    """Create a candidate only when its declared edge set forms a valid corridor."""

    candidate = CorridorCandidate(
        candidate_id,
        frozenset(edge_ids),
        capital_cost,
        treatment,
        name,
    )
    validation = validate_candidate(topology, candidate, require_simple_path=require_simple_path)
    if not validation.valid:
        raise ValueError(
            f"invalid exact-edge candidate {candidate_id}: {', '.join(validation.issues)}"
        )
    return candidate


def generate_candidate_between_terminals(
    topology: DirectedTopology,
    *,
    candidate_id: str,
    origin: str,
    destination: str,
    capital_cost: float,
    eligible_edge_ids: frozenset[str] | None = None,
    treatment: FacilityType = FacilityType.PROTECTED_LANE,
    name: str = "",
) -> CorridorCandidate:
    """Generate a connected exact-edge corridor between declared terminal nodes."""

    if origin == destination:
        raise ValueError("candidate terminals must be distinct")
    if origin not in topology.nodes or destination not in topology.nodes:
        raise KeyError("candidate terminals must be topology nodes")
    if eligible_edge_ids is None:
        eligible_edge_ids = frozenset(topology.edges)
    unknown = eligible_edge_ids.difference(topology.edges)
    if unknown:
        raise KeyError(f"eligible set contains unknown edges: {sorted(unknown)}")
    eligible_topology = DirectedTopology(
        topology.nodes.values(),
        (topology.edge(edge_id) for edge_id in eligible_edge_ids),
    )

    def physical_cost(edge: Edge, reversed: bool) -> float:
        del reversed
        return edge.length_m

    route = shortest_path(
        eligible_topology,
        origin,
        destination,
        cost=physical_cost,
    )
    if route is None:
        raise ValueError(f"no eligible directed path connects {origin} to {destination}")
    return generate_exact_edge_candidate(
        topology,
        candidate_id=candidate_id,
        edge_ids=route.edge_ids,
        capital_cost=capital_cost,
        treatment=treatment,
        name=name,
    )
