"""Explicit route preferences and conserved assignment on a fixed investment.

Profiles below are engineering sensitivity cases, not estimated Auckland rider
types or CRANC coefficients. Infrastructure preference is a non-negative penalty
in equivalent seconds, separate from physical travel time and hard access rules.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from math import exp, isfinite, log

from .active_search import InvestmentGraph, RouteOption

FACILITIES = ("protected_lane", "shared_path", "painted_lane", "quiet_street", "none")


@dataclass(frozen=True)
class RiderPreference:
    id: str
    label: str
    time_weight: float
    distance_s_per_km: float
    facility_s_per_km: tuple[float, float, float, float, float]
    stress_s_per_km: tuple[float, float, float, float]
    coefficient_status: str = "illustrative_unfitted"

    def __post_init__(self) -> None:
        values = (self.distance_s_per_km, *self.facility_s_per_km, *self.stress_s_per_km)
        if (
            not self.id
            or not self.label
            or not isfinite(self.time_weight)
            or self.time_weight <= 0
            or len(self.facility_s_per_km) != 5
            or len(self.stress_s_per_km) != 4
            or any(not isfinite(x) or x < 0 for x in values)
        ):
            raise ValueError("preferences require identified, finite non-negative penalties")


ILLUSTRATIVE_PREFERENCES = (
    RiderPreference("direct", "Time and distance", 1, 60, (0, 0, 0, 0, 0), (0, 0, 0, 0)),
    RiderPreference(
        "balanced", "Moderate facility preference", 1, 60, (0, 15, 45, 60, 90), (0, 30, 120, 300)
    ),
    RiderPreference(
        "comfort", "Stronger facility preference", 1, 60, (0, 30, 90, 120, 180), (0, 60, 240, 600)
    ),
)


def preference_network(
    graph: InvestmentGraph,
    facilities: Mapping[str, str],
    preference: RiderPreference,
    selected: frozenset[str] = frozenset(),
) -> InvestmentGraph:
    """Resolve investment globally before search; never alter physical times.

    Keep unsuitable arcs in the graph for the shortest-legal-distance reference.
    Hard stress limits still exclude them during forward route search. A street
    upgrade does not lower a separate turn's stress or remove a turn prohibition.
    Unknown facility tags fail closed rather than silently acquiring a benefit.
    """
    if selected - graph.projects.keys():
        raise ValueError("unknown selected project")
    if set(facilities) != set(graph.arcs):
        raise ValueError("every directed arc needs an explicit facility classification")
    if set(facilities.values()) - set(FACILITIES):
        raise ValueError("unknown facility classification")
    arcs = []
    for arc in graph.arcs.values():
        treated = arc.project_id in selected
        stress = arc.treated_stress if treated else arc.stress
        facility = "protected_lane" if treated else facilities[arc.id]
        penalty = (
            (
                preference.distance_s_per_km
                + preference.facility_s_per_km[FACILITIES.index(facility)]
                + preference.stress_s_per_km[stress - 1]
            )
            * arc.distance_m
            / 1000
        )
        arcs.append(
            replace(
                arc,
                stress=stress,
                treated_stress=stress,
                project_id=None,
                preference_cost_s=preference.time_weight * arc.time_s + penalty,
            )
        )
    turns = {
        pair: replace(
            turn,
            stress=turn.treated_stress if turn.project_id in selected else turn.stress,
            project_id=None,
            preference_cost_s=preference.time_weight * turn.delay_s,
        )
        for pair, turn in graph.turns.items()
    }
    return InvestmentGraph(arcs, {}, turns)


def route_cost(graph: InvestmentGraph, arc_ids: tuple[str, ...]) -> float:
    """Evaluate an exact directed route under one materialised network/profile."""
    if not arc_ids or any(a not in graph.arcs for a in arc_ids):
        raise ValueError("route requires known arcs")
    cost = sum(graph.arcs[a].cost_s for a in arc_ids)
    for incoming, outgoing in pairwise(arc_ids):
        if graph.arcs[incoming].v != graph.arcs[outgoing].u:
            raise ValueError("route is discontinuous")
        turn = graph.turns.get((incoming, outgoing))
        if turn and turn.prohibited:
            raise ValueError("route contains a prohibited turn")
        cost += turn.cost_s if turn else 0
    return cost


def assign_fixed_demand(
    graph: InvestmentGraph,
    routes: Sequence[RouteOption],
    demand: float,
    *,
    cost_scale_per_s: float = 0.005,
    path_size_coefficient: float = 1.0,
) -> dict:
    """Path-size logit conditional on supplied feasible routes; conserve people.

    Search one minimum-cost route for each declared preference to construct this
    small choice set. It is not all plausible routes, and these coefficients are
    not fitted. Duplicates cannot inflate demand or split identical alternatives.
    Opposite directions are different arcs. No-route demand stays unassigned.
    """
    if any(not isfinite(v) or v < 0 for v in (demand, cost_scale_per_s, path_size_coefficient)):
        raise ValueError("demand and choice coefficients must be finite and non-negative")
    ids = sorted({r.arc_ids for r in routes})
    costs = [route_cost(graph, route) for route in ids]
    endpoints = {(graph.arcs[r[0]].u, graph.arcs[r[-1]].v) for r in ids}
    if len(endpoints) > 1:
        raise ValueError("assignment routes must belong to the same OD")
    frequency = Counter(a for route in ids for a in set(route))
    factors = [
        sum(graph.arcs[a].distance_m / frequency[a] for a in route)
        / sum(graph.arcs[a].distance_m for a in route)
        for route in ids
    ]
    utilities = [
        -cost_scale_per_s * cost + path_size_coefficient * log(factor)
        for cost, factor in zip(costs, factors, strict=True)
    ]
    weights = [exp(u - max(utilities)) for u in utilities]
    probabilities = [w / sum(weights) for w in weights]
    flows: defaultdict[str, float] = defaultdict(float)
    paths = []
    for route, probability, cost, factor in zip(ids, probabilities, costs, factors, strict=True):
        flow = demand * probability
        for arc_id in route:
            flows[arc_id] += flow
        paths.append(
            {
                "arcIds": list(route),
                "probability": probability,
                "flow": flow,
                "costS": cost,
                "pathSize": factor,
            }
        )
    return {
        "demand": demand,
        "assigned": demand if ids else 0.0,
        "unassigned": 0.0 if ids else demand,
        "expectedCostS": sum(p * c for p, c in zip(probabilities, costs, strict=True))
        if ids
        else None,
        "routes": paths,
        "arcFlows": dict(sorted(flows.items())),
        "additionalCyclists": None,
        "choiceSetStatus": "union_of_profile_optima_not_exhaustive",
    }
