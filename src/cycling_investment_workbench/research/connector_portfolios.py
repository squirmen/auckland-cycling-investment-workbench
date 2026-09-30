"""Paired, budgeted connector experiments; never a change to published portfolios."""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from itertools import pairwise
from math import isclose, isfinite
from time import perf_counter

from .active_search import InvestmentGraph, PlanningStandard, RouteOption
from .investment import InvestmentResult, choose_investments, greedy_investments, served
from .priced_routes import DEFAULT_PRICES, RoutePrice, priced_columns


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


def _solution_row(
    result: InvestmentResult,
    project_costs: Mapping[str, float],
    routes: Mapping[str, Sequence[RouteOption]],
    weights: Mapping[str, float],
    cap: float,
) -> dict:
    """Check a package's claimed journeys against complete route witnesses and describe it."""
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
    return {
        **asdict(result),
        "selected": sorted(result.selected),
        "budget": cap,
        "shortConnectorCount": len(connectors),
        "shortConnectorCostNzd": sum(project_costs[p] for p in connectors),
        "checkedRouteWitnesses": len(witnesses),
    }


def _solve_columns(
    project_costs: Mapping[str, float],
    routes: Mapping[str, Sequence[RouteOption]],
    weights: Mapping[str, float],
    budgets: Sequence[float],
) -> list[dict]:
    used = {p for options in routes.values() for route in options for p in route.project_ids}
    costs = {p: project_costs[p] for p in sorted(used)}
    return [
        _solution_row(result, costs, routes, weights, cap)
        for cap in budgets
        for result in (
            greedy_investments(costs, routes, weights, budget=cap),
            greedy_investments(costs, routes, weights, budget=cap, packages=True),
            choose_investments(costs, routes, weights, budget=cap),
        )
    ]


def _retained(
    earlier: Sequence[dict],
    stage: str,
    project_costs: Mapping[str, float],
    routes: Mapping[str, Sequence[RouteOption]],
    weights: Mapping[str, float],
) -> list[dict]:
    """Re-evaluate an earlier stage's preferred packages on a larger route pool.

    A package that was affordable stays affordable, and more routes can only
    connect more journeys with it. Keeping it as a candidate means a time-limited
    solver or a greedy pass cannot make a later stage look worse than an earlier one.
    """
    rows = []
    for solution in earlier:
        selected = frozenset(solution["selected"])
        weight, count = served(selected, routes, weights)
        result = InvestmentResult(
            selected, solution["capital_cost"], weight, count, solution["method"]
        )
        row = _solution_row(result, project_costs, routes, weights, solution["budget"])
        rows.append({**row, "retainedFrom": solution.get("retainedFrom", stage)})
    return rows


def priced_route_generation(
    graph: InvestmentGraph,
    routes: Mapping[str, Sequence[RouteOption]],
    endpoints: Mapping[str, tuple[str, str]],
    shortest: Mapping[str, float | None],
    weights: Mapping[str, float],
    *,
    budget: float,
    standard: PlanningStandard,
    label_stage: Mapping,
    prices: Sequence[RoutePrice] = DEFAULT_PRICES,
    rounds: int = 3,
    max_labels: int = 200_000,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Add price-guided routes to the checked label-search pool and re-solve in stages.

    Stage one is the label search as supplied. Stage two adds one route per price
    for every journey. Stage three repeats for the journeys the current package
    leaves unconnected, with that package's projects priced at zero, until a round
    adds nothing, leaves the package unchanged, or reaches the round limit. Every
    added route passes the same independent checker as the label-search columns,
    and every method sees the same pool at each stage. Nothing here proves the
    pool is complete.
    """
    if type(rounds) is not int or rounds < 0:
        raise ValueError("priced rounds must be a non-negative whole number")
    started = perf_counter()
    budgets = sorted({0.0, budget / 4, budget / 2, budget})
    pool = {name: {route.arc_ids: route for route in rows} for name, rows in routes.items()}

    def columns() -> dict[str, tuple[RouteOption, ...]]:
        return {name: tuple(rows.values()) for name, rows in pool.items()}

    def add(found: Mapping[str, Sequence[RouteOption]]) -> int:
        added = 0
        for name, rows in found.items():
            for route in rows:
                checked_route(graph, route, endpoints[name], standard, shortest[name])
                if route.capital_cost > budget + 1e-7:
                    raise ValueError("priced route exceeds the comparison budget")
                if route.arc_ids not in pool[name]:
                    pool[name][route.arc_ids] = route
                    added += 1
        return added

    def size() -> dict:
        return {
            "routeColumns": sum(len(rows) for rows in pool.values()),
            "journeysWithRouteColumns": sum(bool(rows) for rows in pool.values()),
        }

    def at_budget(solutions: Sequence[dict]) -> dict:
        return next(s for s in preferred_solutions(solutions) if s["budget"] == budget)

    def pool_summary() -> dict:
        """How many journeys have a route at all, by the capital of their cheapest one."""
        cheapest = [
            min((route.capital_cost for route in rows.values()), default=None)
            for rows in pool.values()
        ]
        with_route = [value for value in cheapest if value is not None]
        return {
            "journeys": len(pool),
            "disconnected": sum(shortest[name] is None for name in pool),
            "withoutRoute": sum(
                shortest[name] is not None and not rows for name, rows in pool.items()
            ),
            "connectedWithoutProjects": sum(value <= 1e-7 for value in with_route),
            "cheapestRouteUpToQuarterBudget": sum(
                1e-7 < value <= budget / 4 for value in with_route
            ),
            "cheapestRouteUpToHalfBudget": sum(
                budget / 4 < value <= budget / 2 for value in with_route
            ),
            "cheapestRouteUpToBudget": sum(budget / 2 < value for value in with_route),
        }

    label_pool = pool_summary()

    stages = [
        {
            "stage": "label_search",
            **size(),
            "solutions": label_stage["solutions"],
            "preferredSolutions": label_stage["preferredSolutions"],
            # Searching and solving together, as for the later stages.
            "elapsedS": label_stage.get("elapsedS"),
        }
    ]
    if progress:
        progress(f"Priced routes: {len(prices)} prices for each journey…")
    stage_started = perf_counter()
    found, stats = priced_columns(
        graph,
        endpoints,
        shortest,
        budget=budget,
        standard=standard,
        prices=prices,
        max_labels=max_labels,
    )
    added = add(found)
    current = columns()
    solutions = [
        *_solve_columns(graph.projects, current, weights, budgets),
        *_retained(
            stages[0]["preferredSolutions"], "label_search", graph.projects, current, weights
        ),
    ]
    stages.append(
        {
            "stage": "priced_paths",
            **stats,
            "newRouteColumns": added,
            **size(),
            "solutions": solutions,
            "preferredSolutions": preferred_solutions(solutions),
            "elapsedS": perf_counter() - stage_started,
        }
    )
    if progress:
        progress(f"Priced routes: {added} new routes; {stats['searchStopReasons']}")
    stage_started = perf_counter()
    round_rows = []
    reference = at_budget(solutions)
    stopped = "round_limit"
    for number in range(1, rounds + 1):
        funded = frozenset(reference["selected"])
        unserved = [
            name
            for name, rows in pool.items()
            if shortest[name] is not None
            and not any(route.project_ids <= funded for route in rows.values())
        ]
        found, stats = priced_columns(
            graph,
            endpoints,
            shortest,
            budget=budget,
            standard=standard,
            prices=prices,
            funded=funded,
            journeys=unserved,
            max_labels=max_labels,
        )
        added = add(found)
        row = {
            "round": number,
            "fundedProjects": len(funded),
            "unconnectedJourneys": len(unserved),
            **stats,
            "newRouteColumns": added,
        }
        round_rows.append(row)
        if progress:
            progress(f"Priced round {number}: {added} new routes for {len(unserved)} journeys")
        if not added:
            stopped = "no_new_routes"
            break
        current = columns()
        # The package being improved stays a candidate, named for the stage it came from.
        origin = "priced_paths" if number == 1 else "priced_rounds"
        reference = at_budget(
            [
                *_solve_columns(graph.projects, current, weights, [budget]),
                *_retained([reference], origin, graph.projects, current, weights),
            ]
        )
        row["preferredServedWeight"] = reference["served_weight"]
        row["preferredServedJourneys"] = reference["served_journeys"]
        row["preferredCapitalCost"] = reference["capital_cost"]
        if frozenset(reference["selected"]) == funded:
            # The same package would price the same searches and find the same routes.
            stopped = "package_unchanged"
            break
    if any(row["newRouteColumns"] for row in round_rows):
        current = columns()
        kept: dict[tuple, dict] = {}
        for row in (
            *_retained(
                stages[1]["preferredSolutions"], "priced_paths", graph.projects, current, weights
            ),
            *_retained([reference], "priced_rounds", graph.projects, current, weights),
        ):
            # One row per package and budget, named for the earliest stage that found it.
            kept.setdefault((row["budget"], tuple(row["selected"])), row)
        solutions = [*_solve_columns(graph.projects, current, weights, budgets), *kept.values()]
    stages.append(
        {
            "stage": "priced_rounds",
            "rounds": round_rows,
            "stopped": stopped,
            "newRouteColumns": sum(row["newRouteColumns"] for row in round_rows),
            **size(),
            "solutions": solutions,
            "preferredSolutions": preferred_solutions(solutions),
            "elapsedS": perf_counter() - stage_started,
        }
    )
    before = at_budget(stages[0]["preferredSolutions"])
    after = at_budget(stages[-1]["preferredSolutions"])
    package = frozenset(after["selected"])
    # For each journey the package leaves unconnected: the least extra capital any of its
    # routes in the pool would need. The pool is not complete, so the true figure may be lower.
    additions = sorted(
        min(sum(graph.projects[p] for p in route.project_ids - package) for route in rows.values())
        for rows in pool.values()
        if rows and not any(route.project_ids <= package for route in rows.values())
    )
    return {
        "status": "heuristic_route_generation_without_completeness_or_optimality_proof",
        "budget": budget,
        "prices": [asdict(price) for price in prices],
        "roundLimit": rounds,
        "maxLabelsPerPricedSearch": max_labels,
        "boundStrategy": "treatable_streets",
        "stages": stages,
        "labelSearchRoutePool": label_pool,
        "routePool": pool_summary(),
        "nextJourney": {
            "unconnectedWithRoute": len(additions),
            "remainingBudgetNzd": budget - after["capital_cost"],
            "cheapestAdditionNzd": additions[0] if additions else None,
        },
        "change": {
            "servedWeight": after["served_weight"] - before["served_weight"],
            "servedJourneys": after["served_journeys"] - before["served_journeys"],
            "capitalCost": after["capital_cost"] - before["capital_cost"],
            "routeColumns": stages[-1]["routeColumns"] - stages[0]["routeColumns"],
        },
        "elapsedS": perf_counter() - started,
        "note": "One label per junction movement, score and resources only: a heuristic, not a "
        "complete search. Priced routes join the checked label-search pool; nothing is removed. "
        "Each later stage also keeps the earlier preferred package as a candidate, so a stage "
        "cannot report less access than the one before. Same journeys, weights, standards, "
        "budget and provisional costs. Connected records are not extra cyclists.",
    }


def fixed_connector_cost_sensitivity(
    project_costs: Mapping[str, float],
    routes: Mapping[str, Sequence[RouteOption]],
    weights: Mapping[str, float],
    *,
    budget: float,
    fixed_costs: Sequence[float],
    reference_selected: frozenset[str],
) -> dict:
    """Reprice shared short projects on fixed route columns, not engineered crossings.

    Nonnegative allowances cannot make an originally over-budget path affordable.
    Capped route generation may still have omitted alternatives that matter after
    repricing. This is conditional sensitivity, not a cost estimate or rerouting.
    """
    if any(not isfinite(value) or value < 0 for value in fixed_costs):
        raise ValueError("connector allowances must be finite and non-negative")
    if reference_selected - project_costs.keys():
        raise ValueError("reference programme contains unknown projects")
    reference_weight, reference_count = served(reference_selected, routes, weights)
    cases = []
    for allowance in sorted({0.0, *fixed_costs}):
        costs = {
            p: value + (allowance if p.startswith("diagnostic-short:") else 0)
            for p, value in project_costs.items()
        }
        repriced = {
            name: tuple(replace(r, capital_cost=sum(costs[p] for p in r.project_ids)) for r in rows)
            for name, rows in routes.items()
        }
        solutions = _solve_columns(costs, repriced, weights, [budget])
        for solution in solutions:
            chosen = frozenset(solution["selected"])
            union = chosen | reference_selected
            solution["projectOverlapWithReference"] = (
                len(chosen & reference_selected) / len(union) if union else 1.0
            )
        reference_cost = sum(costs[p] for p in reference_selected)
        cases.append(
            {
                "fixedAllowancePerConnectorNzd": allowance,
                "fixedProgrammeCostNzd": reference_cost,
                "fixedProgrammeAffordable": reference_cost <= budget + 1e-7,
                "affordableRouteColumns": sum(
                    r.capital_cost <= budget + 1e-7 for rs in repriced.values() for r in rs
                ),
                "solutions": solutions,
                "preferredSolutions": preferred_solutions(solutions),
            }
        )
    return {
        "status": "hypothetical_fixed_connector_allowances_not_crossing_cost_estimates",
        "budget": budget,
        "sameRouteColumns": True,
        "reroutedForEachCostCase": False,
        "referenceSelected": sorted(reference_selected),
        "referenceServedWeight": reference_weight,
        "referenceServedJourneys": reference_count,
        "routeColumns": sum(len(rows) for rows in routes.values()),
        "cases": cases,
        "note": "One allowance per selected short-chain project, shared across journeys. "
        "Not per physical crossing: several chains may touch one junction. Geometry, stress, "
        "delays and route columns stay fixed. No engineering or AT cost evidence is implied. "
        "Reoptimised results are conditional on the capped route pool; an unaffordable fixed "
        "reference programme is not reported as a deliverable programme.",
    }


def preferred_solutions(solutions: Sequence[dict]) -> list[dict]:
    """Keep the best checked result per budget without disguising its method.

    A time-limited MILP can return less access or a dearer equal-access package
    than a baseline. Preserve all raw method results; select by achieved weight,
    then cost, with deterministic ties. This supplies no new optimality proof.
    """
    return [
        min(
            (s for s in solutions if s["budget"] == budget),
            key=lambda s: (
                -s["served_weight"],
                s["capital_cost"],
                tuple(s["selected"]),
                s["method"],
            ),
        ).copy()
        for budget in sorted({s["budget"] for s in solutions})
    ]


def compare_budgeted_connectors(
    graph: InvestmentGraph,
    original_routes: Mapping[str, Sequence[RouteOption]],
    endpoints: Mapping[str, tuple[str, str]],
    weights: Mapping[str, float],
    *,
    budget: float,
    standard: PlanningStandard,
    max_labels: int,
    label_limits: Sequence[int] | None = None,
    fixed_connector_costs: Sequence[float] = (),
    stress_aware_bounds: bool = False,
    priced_routes: bool = False,
    priced_rounds: int = 3,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Search nested route unions with paired inputs and explicit truncation.

    Original columns and earlier-cap columns remain available at larger caps.
    Every method sees the same checked union at each step. A solver's proof is
    conditional on that union; unchanged objective values alone are not evidence
    that capped route generation has converged.
    """
    if set(original_routes) != set(endpoints) or set(weights) != set(endpoints):
        raise ValueError("connector comparisons require paired journeys and weights")
    limits = tuple(label_limits) if label_limits is not None else (max_labels,)
    if (
        not limits
        or limits[0] != max_labels
        or any(type(limit) is not int or limit < 1 for limit in limits)
        or any(a >= b for a, b in pairwise(limits))
    ):
        raise ValueError("connector label limits must increase from the original positive cap")
    if any(not isfinite(value) or value < 0 for value in fixed_connector_costs):
        raise ValueError("connector allowances must be finite and non-negative")
    started = perf_counter()
    routes = {name: tuple(rows) for name, rows in original_routes.items()}
    shortest: dict[str, float | None] = {}
    checks = []
    for limit in limits:
        if progress:
            progress(f"Connector search: {limit:,} labels per journey…")
        step_started = perf_counter()
        retained = sum(len(rows) for rows in routes.values())
        searches = []
        for name, pair in endpoints.items():
            search = graph.search(
                *pair,
                budget=budget,
                standard=standard,
                max_labels=limit,
                stress_aware_bounds=stress_aware_bounds,
            )
            searches.append(search)
            shortest[name] = search.shortest_legal_distance_m
            combined = {}
            for route in (*routes[name], *search.routes):
                if search.shortest_legal_distance_m is None:
                    raise ValueError("route column supplied for disconnected endpoints")
                checked_route(graph, route, pair, standard, search.shortest_legal_distance_m)
                if route.capital_cost > budget + 1e-7:
                    raise ValueError("route column exceeds the comparison budget")
                combined[route.arc_ids] = route
            routes[name] = tuple(combined.values())
        solutions = _solve_columns(
            graph.projects, routes, weights, sorted({0.0, budget / 4, budget / 2, budget})
        )
        checks.append(
            {
                "maxLabelsPerSearch": limit,
                "retainedRouteColumns": retained,
                "routeColumns": sum(len(rows) for rows in routes.values()),
                "journeysWithRouteColumns": sum(bool(rows) for rows in routes.values()),
                "searchStopReasons": dict(sorted(Counter(s.stop_reason for s in searches).items())),
                "searchComplete": all(s.complete for s in searches),
                "labelsExpanded": sum(s.labels_expanded for s in searches),
                "solutions": solutions,
                "preferredSolutions": preferred_solutions(solutions),
                "elapsedS": perf_counter() - step_started,
            }
        )
        if progress:
            progress(
                f"Connector search at {limit:,}: {checks[-1]['routeColumns']} retained routes; "
                f"{checks[-1]['searchStopReasons']}"
            )
    final = checks[-1]
    sensitivity = None
    if fixed_connector_costs:
        reference = next(s for s in final["preferredSolutions"] if s["budget"] == budget)
        sensitivity = fixed_connector_cost_sensitivity(
            graph.projects,
            routes,
            weights,
            budget=budget,
            fixed_costs=fixed_connector_costs,
            reference_selected=frozenset(reference["selected"]),
        )
    priced = None
    if priced_routes:
        # A separate block: the label-search results above are reported unchanged.
        priced = priced_route_generation(
            graph,
            routes,
            endpoints,
            shortest,
            weights,
            budget=budget,
            standard=standard,
            label_stage=final,
            rounds=priced_rounds,
            progress=progress,
        )
    return {
        **final,
        "status": "budgeted_short_connector_experiment_not_buildability_validation",
        "sameJourneysAndWeights": True,
        "boundStrategy": "treatable_streets" if stress_aware_bounds else "all_legal_streets",
        "originalRouteColumnsRetained": sum(len(r) for r in original_routes.values()),
        "searchLimitChecks": checks,
        "fixedConnectorCostSensitivity": sensitivity,
        "pricedRouteGeneration": priced,
        "elapsedS": perf_counter() - started,
        "note": "Same crop, demand records, standards and screening cost rate. "
        "Short-chain options are hypothetical, not checked crossing designs. "
        "All methods use the same checked route union, including original columns. "
        "Preferred solutions select the greatest checked weight, then least cost, among "
        "the three methods at each budget; raw method outcomes remain separate. "
        "Search caps can omit alternatives. Connected records are not extra cyclists.",
    }
