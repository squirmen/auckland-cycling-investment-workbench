"""Paired, budgeted connector experiments; never a change to published portfolios."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from math import isclose
from time import perf_counter

from .active_search import InvestmentGraph, PlanningStandard, RouteOption
from .investment import choose_investments, greedy_investments


def checked_route(
    graph: InvestmentGraph,
    route: RouteOption,
    endpoints: tuple[str, str],
    standard: PlanningStandard,
    shortest: float,
) -> RouteOption:
    """Independently check a column's exact path, requirements and resource totals."""
    node, destination = endpoints
    required = set()
    distance = time = generalized_cost = existing = 0.0
    previous = None

    def treatment(stress, treated, project):
        if stress > standard.maximum_stress:
            if project is None or treated > standard.maximum_stress:
                raise ValueError("route has an untreated stress gap")
            required.add(project)

    for key in route.arc_ids:
        arc = graph.arcs[key]
        if arc.u != node:
            raise ValueError("route is not a continuous directed path")
        treatment(arc.stress, arc.treated_stress, arc.project_id)
        turn = graph.turns.get((previous, key))
        if turn:
            if turn.prohibited:
                raise ValueError("route uses a prohibited turn")
            treatment(turn.stress, turn.treated_stress, turn.project_id)
            time += turn.delay_s
            generalized_cost += turn.cost_s
        distance += arc.distance_m
        time += arc.time_s
        generalized_cost += arc.cost_s
        existing += arc.distance_m if arc.existing_cycleway else 0
        node, previous = arc.v, key
    if node != destination or not route.arc_ids:
        raise ValueError("route does not reach the declared destination")
    if (
        distance > shortest * standard.maximum_detour + 1e-8
        or time > standard.maximum_time_s + 1e-8
    ):
        raise ValueError("route exceeds the original planning standard")
    cost = sum(graph.projects[p] for p in required)
    if required != route.project_ids or any(
        not isclose(a, b, rel_tol=1e-10, abs_tol=1e-7)
        for a, b in (
            (distance, route.distance_m),
            (time, route.time_s),
            (cost, route.capital_cost),
            (existing, route.existing_cycleway_m),
            (generalized_cost, route.generalized_cost_s),
        )
    ):
        raise ValueError("route column metadata does not match its exact path")
    return route


def compare_budgeted_connectors(
    graph: InvestmentGraph,
    original_routes: Mapping[str, Sequence[RouteOption]],
    endpoints: Mapping[str, tuple[str, str]],
    weights: Mapping[str, float],
    *,
    budget: float,
    standard: PlanningStandard,
    max_labels: int,
) -> dict:
    """Search with connectors, retain checked original routes and compare methods.

    Original columns prevent search truncation from erasing known alternatives.
    All methods receive the same union; optimality is only within that union.
    Every claimed served journey has a checked, fully funded route witness.
    """
    if set(original_routes) != set(endpoints) or set(weights) != set(endpoints):
        raise ValueError("connector comparisons require paired journeys and weights")
    started = perf_counter()
    routes, searches = {}, []
    for name, pair in endpoints.items():
        search = graph.search(*pair, budget=budget, standard=standard, max_labels=max_labels)
        searches.append(search)
        combined = {}
        for route in (*original_routes[name], *search.routes):
            if search.shortest_legal_distance_m is None:
                raise ValueError("route column supplied for disconnected endpoints")
            checked_route(graph, route, pair, standard, search.shortest_legal_distance_m)
            if route.capital_cost > budget + 1e-7:
                raise ValueError("route column exceeds the comparison budget")
            combined[route.arc_ids] = route
        routes[name] = tuple(combined.values())

    used = {p for options in routes.values() for route in options for p in route.project_ids}
    costs = {p: graph.projects[p] for p in sorted(used)}
    solutions = []
    for cap in sorted({0.0, budget / 4, budget / 2, budget}):
        for result in (
            greedy_investments(costs, routes, weights, budget=cap),
            greedy_investments(costs, routes, weights, budget=cap, packages=True),
            choose_investments(costs, routes, weights, budget=cap),
        ):
            witnesses = [
                name
                for name, options in routes.items()
                if any(r.project_ids <= result.selected for r in options)
            ]
            if len(witnesses) != result.served_journeys or not isclose(
                sum(weights[name] for name in witnesses), result.served_weight, abs_tol=1e-7
            ):
                raise ValueError("connector portfolio lacks its claimed route witnesses")
            connectors = {p for p in result.selected if p.startswith("diagnostic-short:")}
            solutions.append(
                {
                    **asdict(result),
                    "selected": sorted(result.selected),
                    "budget": cap,
                    "shortConnectorCount": len(connectors),
                    "shortConnectorCostNzd": sum(costs[p] for p in connectors),
                    "checkedRouteWitnesses": len(witnesses),
                }
            )
    return {
        "status": "budgeted_short_connector_experiment_not_buildability_validation",
        "sameJourneysAndWeights": True,
        "originalRouteColumnsRetained": sum(len(r) for r in original_routes.values()),
        "routeColumns": sum(len(r) for r in routes.values()),
        "journeysWithRouteColumns": sum(bool(r) for r in routes.values()),
        "searchStopReasons": dict(sorted(Counter(s.stop_reason for s in searches).items())),
        "searchComplete": all(s.complete for s in searches),
        "labelsExpanded": sum(s.labels_expanded for s in searches),
        "solutions": solutions,
        "elapsedS": perf_counter() - started,
        "note": "Same crop, demand records, standards and screening cost rate. "
        "Short-chain options are hypothetical, not checked crossing designs. "
        "All methods use the same checked route union, including original columns. "
        "Search caps can omit alternatives. Connected records are not extra cyclists.",
    }
