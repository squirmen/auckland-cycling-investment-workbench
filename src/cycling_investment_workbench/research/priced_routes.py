"""Price-guided route generation: a fast companion to the capped label search.

The label search keeps every non-dominated combination of projects, distance and
time, and stops at a label cap. This generator asks a narrower question many
times: for one price on new capital and one on distance, which single route has
the lowest priced score within the planning standard and the budget? Projects
already in a programme can be priced at zero, so a search looks for routes that
reuse them.

Labels at a junction movement are compared on score, distance and time only, not
on their project sets. With capital unpriced and a budget that does not bind,
that is an exact constrained shortest path. Otherwise it is a heuristic: a
project is paid once, so what a later street costs depends on the path taken to
it, and a label discarded here might have been cheaper, or affordable, further
on. No completeness or optimality is claimed. Every route returned must still
pass the independent route checker.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from heapq import heappop, heappush
from math import inf, isfinite
from time import perf_counter

from .active_search import DEFAULT_STANDARD, EPS, InvestmentGraph, PlanningStandard, RouteOption


@dataclass(frozen=True, slots=True)
class RoutePrice:
    """Seconds of generalized travel cost charged per NZ$ of new capital and per metre."""

    capital_s_per_nzd: float
    distance_s_per_m: float = 0.0

    def __post_init__(self) -> None:
        if any(
            not isfinite(value) or value < 0
            for value in (self.capital_s_per_nzd, self.distance_s_per_m)
        ):
            raise ValueError("route prices must be finite and non-negative")


# From "ignore capital" to "capital decides", each with and without a price on distance.
DEFAULT_PRICES = tuple(
    RoutePrice(capital, distance)
    for distance in (0.0, 1.0)
    for capital in (0.0, 1e-5, 1e-4, 1e-3, 1e-2, 1.0)
)


@dataclass(frozen=True, slots=True)
class PricedSearch:
    route: RouteOption | None
    stop_reason: str
    labels_created: int


@dataclass(slots=True)
class _Label:
    node: str
    incoming: str | None
    mask: int
    distance: float
    time: float
    cost: float
    capital: float
    score: float
    parent: int | None
    arc_id: str | None
    active: bool = True


def priced_route(
    graph: InvestmentGraph,
    origin: str,
    destination: str,
    *,
    budget: float,
    shortest_legal_distance_m: float,
    price: RoutePrice,
    standard: PlanningStandard = DEFAULT_STANDARD,
    funded: frozenset[str] = frozenset(),
    max_labels: int = 200_000,
) -> PricedSearch:
    """Find one route with a low priced score inside the standard and the budget.

    The detour limit uses the supplied shortest legal distance, so a caller can
    hold it equal to the label search's reference. The route's own projects must
    fit the budget. Funded projects are free in the score but still listed as
    requirements of the route.
    """
    if origin not in graph.nodes or destination not in graph.nodes or origin == destination:
        raise ValueError("journey endpoints must be distinct exact graph nodes")
    if not isfinite(budget) or budget < 0 or max_labels < 1:
        raise ValueError("budget and label limit must be valid")
    if not isfinite(shortest_legal_distance_m) or shortest_legal_distance_m <= 0:
        raise ValueError("the shortest legal distance must be positive and finite")
    if funded - graph.projects.keys():
        raise ValueError("funded projects must exist in the graph")
    limit = standard.maximum_stress
    maximum_distance = shortest_legal_distance_m * standard.maximum_detour
    # Bounds over streets that are, or could be made, low-stress. They never exceed the true
    # remaining distance, time or cost of an acceptable route.
    distance_bound = graph.lower_bound(destination, "distance_m", limit)
    time_bound = graph.lower_bound(destination, "time_s", limit)
    cost_bound = graph.lower_bound(destination, "cost_s", limit)
    if (
        distance_bound.get(origin, inf) > maximum_distance + EPS
        or time_bound.get(origin, inf) > standard.maximum_time_s + EPS
    ):
        return PricedSearch(None, "no_route", 0)

    def require(stress, treated, project, mask, capital, priced):
        if stress <= limit:
            return mask, capital, priced
        if not project or treated > limit:
            return None
        bit = graph.bits[project]
        if mask & bit:
            return mask, capital, priced
        cost = graph.projects[project]
        return mask | bit, capital + cost, priced + (0.0 if project in funded else cost)

    labels = [_Label(origin, None, 0, 0.0, 0.0, 0.0, 0.0, 0.0, None, None)]
    priced_capital = [0.0]
    frontiers: defaultdict[tuple[str, str | None], list[int]] = defaultdict(list)
    frontiers[(origin, None)] = [0]
    queue = [(cost_bound[origin] + price.distance_s_per_m * distance_bound[origin], 0)]
    while queue:
        _, index = heappop(queue)
        label = labels[index]
        if not label.active:
            continue
        if label.node == destination:
            arc_ids = []
            cursor = index
            while labels[cursor].parent is not None:
                arc_ids.append(labels[cursor].arc_id)
                cursor = labels[cursor].parent
            ordered = tuple(reversed(arc_ids))
            route = RouteOption(
                ordered,
                graph.ids(label.mask),
                label.distance,
                label.time,
                graph.cost(label.mask),
                sum(graph.arcs[a].distance_m for a in ordered if graph.arcs[a].existing_cycleway),
                label.cost,
            )
            return PricedSearch(route, "route", len(labels))
        for arc in graph.outgoing[label.node]:
            state = require(
                arc.stress,
                arc.treated_stress,
                arc.project_id,
                label.mask,
                label.capital,
                priced_capital[index],
            )
            if state is None:
                continue
            turn = graph.turns.get((label.incoming, arc.id)) if label.incoming else None
            if turn:
                if turn.prohibited:
                    continue
                state = require(turn.stress, turn.treated_stress, turn.project_id, *state)
                if state is None:
                    continue
            mask, capital, priced = state
            distance = label.distance + arc.distance_m
            time = label.time + arc.time_s + (turn.delay_s if turn else 0.0)
            cost = label.cost + arc.cost_s + (turn.cost_s if turn else 0.0)
            if (
                capital > budget + EPS
                or distance + distance_bound.get(arc.v, inf) > maximum_distance + EPS
                or time + time_bound.get(arc.v, inf) > standard.maximum_time_s + EPS
            ):
                continue
            score = cost + price.distance_s_per_m * distance + price.capital_s_per_nzd * priced
            incoming = arc.id if graph.turns and arc.v != destination else None
            key = (arc.v, incoming)
            frontier = frontiers[key]
            if any(
                labels[i].score <= score + EPS
                and labels[i].distance <= distance + EPS
                and labels[i].time <= time + EPS
                for i in frontier
            ):
                continue
            if len(labels) >= max_labels:
                return PricedSearch(None, "label_limit", len(labels))
            remaining = []
            for i in frontier:
                other = labels[i]
                if (
                    score <= other.score + EPS
                    and distance <= other.distance + EPS
                    and time <= other.time + EPS
                ):
                    other.active = False
                else:
                    remaining.append(i)
            new_index = len(labels)
            labels.append(
                _Label(arc.v, incoming, mask, distance, time, cost, capital, score, index, arc.id)
            )
            priced_capital.append(priced)
            frontiers[key] = [*remaining, new_index]
            remaining_score = cost_bound[arc.v] + price.distance_s_per_m * distance_bound[arc.v]
            heappush(queue, (score + remaining_score, new_index))
    return PricedSearch(None, "no_route", len(labels))


def priced_columns(
    graph: InvestmentGraph,
    endpoints: Mapping[str, tuple[str, str]],
    shortest: Mapping[str, float | None],
    *,
    budget: float,
    standard: PlanningStandard,
    prices: Sequence[RoutePrice] = DEFAULT_PRICES,
    funded: frozenset[str] = frozenset(),
    journeys: Sequence[str] | None = None,
    max_labels: int = 200_000,
) -> tuple[dict[str, tuple[RouteOption, ...]], dict]:
    """Run every price for each journey and return the distinct routes found, with counts."""
    started = perf_counter()
    names = list(endpoints) if journeys is None else list(journeys)
    found: dict[str, tuple[RouteOption, ...]] = {}
    reasons: Counter[str] = Counter()
    for name in names:
        reference = shortest[name]
        if reference is None:
            continue
        distinct: dict[tuple[str, ...], RouteOption] = {}
        for price in prices:
            result = priced_route(
                graph,
                *endpoints[name],
                budget=budget,
                shortest_legal_distance_m=reference,
                price=price,
                standard=standard,
                funded=funded,
                max_labels=max_labels,
            )
            reasons[result.stop_reason] += 1
            if result.route is not None:
                distinct[result.route.arc_ids] = result.route
        if distinct:
            found[name] = tuple(distinct.values())
    return found, {
        "journeysSearched": sum(shortest[name] is not None for name in names),
        "searches": sum(reasons.values()),
        "searchStopReasons": dict(sorted(reasons.items())),
        "distinctRoutes": sum(len(rows) for rows in found.values()),
        "searchElapsedS": perf_counter() - started,
    }
