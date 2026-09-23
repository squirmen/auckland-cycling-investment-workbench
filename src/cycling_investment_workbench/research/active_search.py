"""Budget-aware Pareto search over exact directed streets and project sets.

Every returned route passes a stress threshold and explicit distance/time
bounds after its required projects are built. Investment is paid once per
project, including when a route traverses several of its edges. Reverse
distance/time bounds accelerate search without changing its feasible set.

This combines established label-setting, A* bounds and fixed-charge resource
accounting. It is an experimental implementation, not a claimed new theorem.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from heapq import heappop, heappush
from math import inf, isfinite
from time import perf_counter

EPS = 1e-8


@dataclass(frozen=True, slots=True)
class Arc:
    id: str
    edge_id: str
    u: str
    v: str
    distance_m: float
    time_s: float
    stress: int
    project_id: str | None = None
    treated_stress: int = 1
    existing_cycleway: bool = False
    preference_cost_s: float | None = None

    def __post_init__(self) -> None:
        if not all((self.id, self.edge_id, self.u, self.v)) or self.u == self.v:
            raise ValueError("arc needs distinct source endpoints and identifiers")
        if any(not isfinite(v) or v <= 0 for v in (self.distance_m, self.time_s)):
            raise ValueError("arc distance and time must be positive and finite")
        if self.stress not in range(1, 5) or not 1 <= self.treated_stress <= self.stress:
            raise ValueError("arc stress must be in 1..4; treatment cannot worsen it")
        if self.preference_cost_s is not None and (
            not isfinite(self.preference_cost_s) or self.preference_cost_s <= 0
        ):
            raise ValueError("preference cost must be positive and finite")

    @property
    def cost_s(self) -> float:
        return self.time_s if self.preference_cost_s is None else self.preference_cost_s


@dataclass(frozen=True, slots=True)
class Turn:
    """Optional movement-specific crossing evidence, separate from street work."""

    stress: int = 1
    delay_s: float = 0.0
    project_id: str | None = None
    treated_stress: int = 1
    prohibited: bool = False
    preference_cost_s: float | None = None

    def __post_init__(self) -> None:
        if self.stress not in range(1, 5) or not 1 <= self.treated_stress <= self.stress:
            raise ValueError("turn stress must be in 1..4")
        if not isfinite(self.delay_s) or self.delay_s < 0:
            raise ValueError("turn delay must be finite and non-negative")
        if self.preference_cost_s is not None and (
            not isfinite(self.preference_cost_s) or self.preference_cost_s < 0
        ):
            raise ValueError("turn preference cost must be finite and non-negative")

    @property
    def cost_s(self) -> float:
        return self.delay_s if self.preference_cost_s is None else self.preference_cost_s


@dataclass(frozen=True, slots=True)
class PlanningStandard:
    maximum_stress: int = 2
    maximum_detour: float = 1.5
    maximum_time_s: float = 1800

    def __post_init__(self) -> None:
        if self.maximum_stress not in range(1, 5):
            raise ValueError("stress threshold must be in 1..4")
        if not isfinite(self.maximum_detour) or self.maximum_detour < 1:
            raise ValueError("detour ratio must be finite and at least one")
        if not isfinite(self.maximum_time_s) or self.maximum_time_s <= 0:
            raise ValueError("time limit must be positive and finite")


@dataclass(frozen=True, slots=True)
class RouteOption:
    arc_ids: tuple[str, ...]
    project_ids: frozenset[str]
    distance_m: float
    time_s: float
    capital_cost: float
    existing_cycleway_m: float
    generalized_cost_s: float = 0.0


DEFAULT_STANDARD = PlanningStandard()


@dataclass(frozen=True, slots=True)
class SearchResult:
    routes: tuple[RouteOption, ...]
    complete: bool
    stop_reason: str
    labels_created: int
    labels_expanded: int
    bound_pruned: int
    dominance_pruned: int
    elapsed_s: float
    shortest_legal_distance_m: float | None


@dataclass(slots=True)
class _Label:
    node: str
    incoming: str | None
    mask: int
    distance: float
    time: float
    cost: float
    parent: int | None
    arc_id: str | None
    active: bool = True


class InvestmentGraph:
    """Multigraph with fixed-charge project identities and reusable lower bounds."""

    def __init__(
        self,
        arcs: Iterable[Arc],
        project_costs: Mapping[str, float],
        turns: Mapping[tuple[str, str], Turn] | None = None,
        *,
        bound_cache_size: int = 32,
    ) -> None:
        self.arcs: dict[str, Arc] = {}
        self.outgoing: defaultdict[str, list[Arc]] = defaultdict(list)
        self.incoming: defaultdict[str, list[Arc]] = defaultdict(list)
        self.projects = dict(sorted(project_costs.items()))
        if any(not key or not isfinite(cost) or cost < 0 for key, cost in self.projects.items()):
            raise ValueError("projects need identifiers and finite non-negative costs")
        self.bits = {key: 1 << i for i, key in enumerate(self.projects)}
        self.turns = dict(turns or {})
        self.nodes: set[str] = set()
        for arc in sorted(arcs, key=lambda item: item.id):
            if arc.id in self.arcs or (arc.project_id and arc.project_id not in self.projects):
                raise ValueError("duplicate arc or unknown project")
            self.arcs[arc.id] = arc
            self.outgoing[arc.u].append(arc)
            self.incoming[arc.v].append(arc)
            self.nodes.update((arc.u, arc.v))
        for (incoming, outgoing), turn in self.turns.items():
            if incoming not in self.arcs or outgoing not in self.arcs:
                raise ValueError("turn references unknown arcs")
            if self.arcs[incoming].v != self.arcs[outgoing].u:
                raise ValueError("turn arcs do not meet at a source junction")
            if turn.project_id and turn.project_id not in self.projects:
                raise ValueError("turn references unknown project")
        if bound_cache_size < 1:
            raise ValueError("bound cache size must be positive")
        self.bound_cache_size = bound_cache_size
        self._bounds: OrderedDict[tuple[str, str], dict[str, float]] = OrderedDict()
        self._cost_is_time = all(a.cost_s == a.time_s for a in self.arcs.values())
        self._costs = {0: 0.0}

    def mask(self, ids: Iterable[str]) -> int:
        value = 0
        for project_id in ids:
            value |= self.bits[project_id]
        return value

    def ids(self, mask: int) -> frozenset[str]:
        return frozenset(key for key, bit in self.bits.items() if mask & bit)

    def cost(self, mask: int) -> float:
        if mask not in self._costs:
            self._costs[mask] = sum(self.projects[key] for key in self.ids(mask))
        return self._costs[mask]

    def lower_bound(self, destination: str, term: str) -> dict[str, float]:
        """Optimistic reverse Dijkstra: all legal arcs, ignoring stress/turn delays.

        Ignoring turn bans only weakens this bound. It cannot falsely declare
        a prohibited movement feasible; those are checked during forward search.
        """
        if term not in {"distance_m", "time_s", "cost_s"}:
            raise ValueError("unknown lower-bound resource")
        if term == "cost_s" and self._cost_is_time:
            term = "time_s"
        key = (destination, term)
        if key not in self._bounds:
            values = {destination: 0.0}
            queue = [(0.0, destination)]
            while queue:
                cost, node = heappop(queue)
                if cost != values[node]:
                    continue
                for arc in self.incoming[node]:
                    value = cost + getattr(arc, term)
                    if value < values.get(arc.u, inf):
                        values[arc.u] = value
                        heappush(queue, (value, arc.u))
            self._bounds[key] = values
            while len(self._bounds) > self.bound_cache_size:
                self._bounds.popitem(last=False)
        self._bounds.move_to_end(key)
        return self._bounds[key]

    def search(
        self,
        origin: str,
        destination: str,
        *,
        budget: float,
        standard: PlanningStandard = DEFAULT_STANDARD,
        selected: frozenset[str] = frozenset(),
        allow_new_projects: bool = True,
        max_labels: int = 50_000,
        use_bounds: bool = True,
        first_only: bool = False,
    ) -> SearchResult:
        """Return nondominated feasible routes, with an explicit truncation flag.

        Dominance requires a subset of projects AND no greater distance/time.
        Generalized preference cost is a further dominance dimension, so a
        longer, slower but more attractive facility route is not discarded.
        Equal-cost but different project sets are retained: their sharing with
        other journeys can change the best programme. There is no weighted sum
        that silently exchanges distance, time, stress or capital cost.
        """
        start = perf_counter()
        if origin not in self.nodes or destination not in self.nodes:
            raise ValueError("journey endpoints must be exact graph nodes")
        if not isfinite(budget) or budget < 0 or max_labels < 1:
            raise ValueError("budget and label limit must be valid")
        initial = self.mask(selected)
        if self.cost(initial) > budget + EPS:
            raise ValueError("selected projects exceed budget")
        distance_bound = self.lower_bound(destination, "distance_m")
        time_bound = self.lower_bound(destination, "time_s") if use_bounds else {}
        cost_bound = self.lower_bound(destination, "cost_s") if use_bounds else {}
        shortest = self.shortest_legal_distance(origin, destination)
        labels = [_Label(origin, None, initial, 0.0, 0.0, 0.0, None, None)]
        frontiers: defaultdict[tuple[str, str | None], list[int]] = defaultdict(list)
        frontiers[(origin, None)] = [0]
        queue = [(cost_bound.get(origin, 0.0), 0.0, 0)]
        expanded = bound_pruned = dominated = 0
        complete, reason = True, "exhausted"

        def required(stress: int, treated: int, project: str | None, mask: int) -> int | None:
            if stress <= standard.maximum_stress:
                return mask
            if not project or treated > standard.maximum_stress:
                return None
            bit = self.bits[project]
            return mask | bit if allow_new_projects or mask & bit else None

        if shortest is None:
            return SearchResult((), True, "disconnected", 1, 0, 0, 0, perf_counter() - start, None)
        maximum_distance = shortest * standard.maximum_detour
        while queue:
            _, _, index = heappop(queue)
            label = labels[index]
            if not label.active:
                continue
            if label.node == destination:
                if first_only:
                    complete, reason = False, "feasible_witness"
                    break
                continue
            expanded += 1
            for arc in self.outgoing[label.node]:
                mask = required(arc.stress, arc.treated_stress, arc.project_id, label.mask)
                if mask is None:
                    continue
                turn = self.turns.get((label.incoming, arc.id)) if label.incoming else None
                if turn:
                    if turn.prohibited:
                        continue
                    mask = required(turn.stress, turn.treated_stress, turn.project_id, mask)
                    if mask is None:
                        continue
                distance = label.distance + arc.distance_m
                time = label.time + arc.time_s + (turn.delay_s if turn else 0.0)
                cost = label.cost + arc.cost_s + (turn.cost_s if turn else 0.0)
                remaining_distance = distance_bound.get(arc.v, inf) if use_bounds else 0.0
                remaining_time = time_bound.get(arc.v, inf) if use_bounds else 0.0
                if (
                    self.cost(mask) > budget + EPS
                    or distance + remaining_distance > maximum_distance + EPS
                    or time + remaining_time > standard.maximum_time_s + EPS
                ):
                    bound_pruned += 1
                    continue
                incoming = arc.id if self.turns and arc.v != destination else None
                key = (arc.v, incoming)
                frontier = frontiers[key]
                if any(
                    labels[i].mask & mask == labels[i].mask
                    and labels[i].distance <= distance + EPS
                    and labels[i].time <= time + EPS
                    and labels[i].cost <= cost + EPS
                    for i in frontier
                ):
                    dominated += 1
                    continue
                if len(labels) >= max_labels:
                    complete, reason = False, "label_limit"
                    queue.clear()
                    break
                remaining = []
                for i in frontier:
                    other = labels[i]
                    if (
                        mask & other.mask == mask
                        and distance <= other.distance + EPS
                        and time <= other.time + EPS
                        and cost <= other.cost + EPS
                    ):
                        other.active = False
                    else:
                        remaining.append(i)
                new_index = len(labels)
                labels.append(_Label(arc.v, incoming, mask, distance, time, cost, index, arc.id))
                frontiers[key] = [*remaining, new_index]
                heappush(queue, (cost + cost_bound.get(arc.v, 0.0), distance, new_index))

        options = []
        for index in frontiers[(destination, None)]:
            label = labels[index]
            arc_ids = []
            cursor = index
            while labels[cursor].parent is not None:
                arc_ids.append(labels[cursor].arc_id)
                cursor = labels[cursor].parent
            ordered = tuple(reversed(arc_ids))
            options.append(
                RouteOption(
                    ordered,
                    self.ids(label.mask),
                    label.distance,
                    label.time,
                    self.cost(label.mask),
                    sum(self.arcs[a].distance_m for a in ordered if self.arcs[a].existing_cycleway),
                    label.cost,
                )
            )
        options.sort(
            key=lambda r: (r.capital_cost, r.generalized_cost_s, r.time_s, r.distance_m, r.arc_ids)
        )
        return SearchResult(
            tuple(options),
            complete,
            reason,
            len(labels),
            expanded,
            bound_pruned,
            dominated,
            perf_counter() - start,
            shortest,
        )

    def shortest_legal_distance(self, origin: str, destination: str) -> float | None:
        if not self.turns:
            return self.lower_bound(destination, "distance_m").get(origin)
        queue = [(0.0, origin, "")]
        distances = {(origin, ""): 0.0}
        while queue:
            distance, node, previous = heappop(queue)
            if distance != distances[(node, previous)]:
                continue
            if node == destination:
                return distance
            for arc in self.outgoing[node]:
                turn = self.turns.get((previous, arc.id))
                if turn and turn.prohibited:
                    continue
                value = distance + arc.distance_m
                key = (arc.v, arc.id)
                if value < distances.get(key, inf):
                    distances[key] = value
                    heappush(queue, (value, arc.v, arc.id))
        return None
