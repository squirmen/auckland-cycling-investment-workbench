"""Access-first investment over complete route requirements, with explicit bounds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix, vstack

from .active_search import RouteOption


@dataclass(frozen=True, slots=True)
class InvestmentResult:
    selected: frozenset[str]
    capital_cost: float
    served_weight: float
    served_journeys: int
    method: str
    optimal_within_columns: bool = False
    relative_gap: float | None = None


def served(
    selected: frozenset[str],
    routes: Mapping[str, Sequence[RouteOption]],
    weights: Mapping[str, float],
) -> tuple[float, int]:
    ids = [
        od
        for od, options in routes.items()
        if any(route.project_ids <= selected for route in options)
    ]
    return sum(weights[od] for od in ids), len(ids)


def choose_investments(
    project_costs: Mapping[str, float],
    routes: Mapping[str, Sequence[RouteOption]],
    weights: Mapping[str, float],
    *,
    budget: float,
    time_limit_s: float = 30,
    exclusive_options: Sequence[frozenset[str]] = (),
) -> InvestmentResult:
    """Maximise served OD weight, then minimise cost without changing access.

    Binary route witnesses require every project on the whole route. Several
    routes or OD markets can share a project; its cost is charged once. This
    master is exact within the supplied route columns when HiGHS proves it.
    Missing columns are not covered by its reported optimization gap.
    """
    if not isfinite(budget) or budget < 0 or not isfinite(time_limit_s) or time_limit_s <= 0:
        raise ValueError("budget and time limit must be valid")
    if set(weights) != set(routes) or any(not isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("every journey needs a finite non-negative weight")
    if any(not isfinite(c) or c < 0 for c in project_costs.values()):
        raise ValueError("project costs must be finite and non-negative")
    projects = sorted(project_costs)
    journeys = sorted(routes)
    columns = [
        (od, ids)
        for od in journeys
        for ids in sorted({r.project_ids for r in routes[od]}, key=lambda x: tuple(sorted(x)))
    ]
    if not columns or not sum(weights.values()):
        return InvestmentResult(frozenset(), 0, 0, 0, "route_packages_milp", True, 0)
    pi = {p: i for i, p in enumerate(projects)}
    ri = len(projects)
    oi = ri + len(columns)
    od_index = {od: oi + i for i, od in enumerate(journeys)}
    constraints: list[tuple[dict[int, float], float, float]] = []
    scale = max(budget, max(project_costs.values(), default=1), 1)
    constraints.append(
        ({pi[p]: c / scale for p, c in project_costs.items()}, -np.inf, budget / scale)
    )
    for index, (_, ids) in enumerate(columns):
        if ids - project_costs.keys():
            raise ValueError("route references unknown project")
        constraints.extend(({ri + index: 1, pi[project]: -1}, -np.inf, 0) for project in ids)
    for od in journeys:
        row = {od_index[od]: 1.0}
        row.update({ri + i: -1.0 for i, (route_od, _) in enumerate(columns) if route_od == od})
        constraints.append((row, -np.inf, 0))
    constraints.extend(({pi[p]: 1 for p in options}, -np.inf, 1) for options in exclusive_options)
    width = oi + len(journeys)
    matrix = lil_matrix((len(constraints), width), dtype=float)
    lower, upper = [], []
    for i, (row, lo, hi) in enumerate(constraints):
        for j, value in row.items():
            matrix[i, j] = value
        lower.append(lo)
        upper.append(hi)
    objective = np.zeros(width)
    total_weight = sum(weights.values())
    for od, index in od_index.items():
        objective[index] = -weights[od] / total_weight
    options = {"time_limit": time_limit_s, "mip_rel_gap": 0.0}
    first = milp(
        objective,
        integrality=np.ones(width),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(matrix.tocsc(), lower, upper),
        options=options,
    )
    if first.x is None:
        raise RuntimeError(f"investment solver returned no feasible incumbent: {first.message}")
    answer = first
    if first.success:
        cost_objective = np.zeros(width)
        for p in projects:
            cost_objective[pi[p]] = project_costs[p] / scale
        second_matrix = vstack([matrix.tocsc(), objective[None, :]], format="csc")
        second = milp(
            cost_objective,
            integrality=np.ones(width),
            bounds=Bounds(0, 1),
            constraints=LinearConstraint(
                second_matrix, [*lower, -np.inf], [*upper, float(first.fun) + 1e-10]
            ),
            options=options,
        )
        if second.x is not None:
            answer = second
    selected = frozenset(p for p in projects if answer.x[pi[p]] > 0.5)
    cost = sum(project_costs[p] for p in selected)
    if cost > budget + 1e-5 or any(len(group & selected) > 1 for group in exclusive_options):
        raise RuntimeError("investment solver incumbent failed budget/options validation")
    weight, count = served(selected, routes, weights)
    # Cost refinement must not sacrifice the achieved primary objective.
    first_selected = frozenset(p for p in projects if first.x[pi[p]] > 0.5)
    if weight + 1e-7 < served(first_selected, routes, weights)[0]:
        selected = first_selected
        cost = sum(project_costs[p] for p in selected)
        weight, count = served(selected, routes, weights)
    gap = getattr(first, "mip_gap", None)
    return InvestmentResult(
        selected,
        cost,
        weight,
        count,
        "route_packages_milp",
        bool(first.success),
        float(gap) if gap is not None else None,
    )


def greedy_investments(
    project_costs: Mapping[str, float],
    routes: Mapping[str, Sequence[RouteOption]],
    weights: Mapping[str, float],
    *,
    budget: float,
    packages: bool = False,
) -> InvestmentResult:
    """Comparable access objective; single-project and route-package baselines."""
    options = {frozenset({p}) for p in project_costs}
    if packages:
        options.update(route.project_ids for values in routes.values() for route in values)
    selected: frozenset[str] = frozenset()
    while True:
        previous = served(selected, routes, weights)[0]
        current_cost = sum(project_costs[p] for p in selected)
        proposals = []
        for option in options:
            addition = option - selected
            if not addition:
                continue
            cost = sum(project_costs[p] for p in addition)
            if cost + current_cost > budget + 1e-8:
                continue
            gain = served(selected | addition, routes, weights)[0] - previous
            if gain > 1e-9:
                proposals.append((gain / max(cost, 1e-12), gain, -cost, tuple(sorted(addition))))
        if not proposals:
            break
        selected |= frozenset(max(proposals)[-1])
    weight, count = served(selected, routes, weights)
    return InvestmentResult(
        selected,
        sum(project_costs[p] for p in selected),
        weight,
        count,
        "package_greedy" if packages else "single_project_greedy",
    )
