from __future__ import annotations

from itertools import combinations
from random import Random

import pytest

from cycling_investment_workbench.research.active_search import (
    Arc,
    InvestmentGraph,
    PlanningStandard,
    Turn,
)
from cycling_investment_workbench.research.connector_portfolios import checked_route
from cycling_investment_workbench.research.priced_routes import (
    DEFAULT_PRICES,
    RoutePrice,
    priced_columns,
    priced_route,
)


def arc(id, u, v, length=1, time=None, stress=1, project=None):
    return Arc(id, id, u, v, length, length if time is None else time, stress, project)


def choice():
    """A short route through a dear project, and a longer one through a cheap project."""
    return InvestmentGraph(
        [
            arc("sa", "s", "a", 1, stress=4, project="dear"),
            arc("at", "a", "t", 1),
            arc("sb", "s", "b", 2, stress=4, project="cheap"),
            arc("bt", "b", "t", 1),
        ],
        {"dear": 100, "cheap": 10},
    )


def search(graph, price, **options):
    options.setdefault("budget", 1000)
    options.setdefault("shortest_legal_distance_m", 2)
    options.setdefault("standard", PlanningStandard(2, 2, 100))
    return priced_route(graph, "s", "t", price=price, **options)


def test_the_capital_price_moves_the_route_from_quickest_to_cheapest():
    graph = choice()
    quick = search(graph, RoutePrice(0))
    assert quick.stop_reason == "route" and quick.route.project_ids == {"dear"}
    assert (quick.route.distance_m, quick.route.capital_cost) == (2, 100)
    # One extra second of travel is worth it once 90 extra dollars cost more than that.
    assert search(graph, RoutePrice(0.01)).route.project_ids == {"dear"}
    thrifty = search(graph, RoutePrice(0.02)).route
    assert thrifty.project_ids == {"cheap"} and thrifty.capital_cost == 10
    assert thrifty.arc_ids == ("sb", "bt") and thrifty.generalized_cost_s == 3


def test_a_funded_project_is_free_in_the_score_but_still_a_requirement():
    graph = choice()
    reused = search(graph, RoutePrice(1), funded=frozenset({"dear"})).route
    assert reused.project_ids == {"dear"} and reused.capital_cost == 100
    # Its own projects must still fit the budget.
    assert search(graph, RoutePrice(0), budget=50).route.project_ids == {"cheap"}
    nothing = search(graph, RoutePrice(0), budget=5)
    assert nothing.route is None and nothing.stop_reason == "no_route"


def test_the_standard_and_the_supplied_reference_distance_are_enforced():
    graph = choice()
    # With a 1.2 detour limit on a 2 m reference, the 3 m route is not acceptable.
    tight = PlanningStandard(2, 1.2, 100)
    assert search(graph, RoutePrice(1), standard=tight).route.project_ids == {"dear"}
    assert search(graph, RoutePrice(1), standard=tight, budget=50).route is None
    assert search(graph, RoutePrice(0), standard=PlanningStandard(2, 2, 1.5)).route is None
    # The caller's reference decides the detour limit, not a fresh shortest path.
    assert search(graph, RoutePrice(1), shortest_legal_distance_m=0.9).route is None


def test_crossings_need_their_own_project_and_banned_turns_are_not_used():
    arcs = [arc("sa", "s", "a", stress=4, project="street"), arc("at", "a", "t")]
    projects = {"street": 1, "crossing": 2}
    graph = InvestmentGraph(arcs, projects, {("sa", "at"): Turn(4, 15, "crossing")})
    route = search(graph, RoutePrice(0.5), budget=3).route
    assert route.project_ids == {"street", "crossing"}
    assert (route.time_s, route.capital_cost) == (17, 3)
    assert search(graph, RoutePrice(0.5), budget=2).route is None
    banned = InvestmentGraph(arcs, projects, {("sa", "at"): Turn(prohibited=True)})
    assert search(banned, RoutePrice(0), budget=3).route is None
    untreatable = InvestmentGraph([arc("st", "s", "t", stress=4)], {})
    assert search(untreatable, RoutePrice(0), shortest_legal_distance_m=1).route is None


def test_a_label_limit_is_reported_and_bad_inputs_are_refused():
    graph = choice()
    limited = search(graph, RoutePrice(0), max_labels=1)
    assert limited.route is None and limited.stop_reason == "label_limit"
    for options in (
        {"budget": -1},
        {"budget": float("nan")},
        {"max_labels": 0},
        {"shortest_legal_distance_m": 0},
        {"shortest_legal_distance_m": float("inf")},
        {"funded": frozenset({"missing"})},
    ):
        with pytest.raises(ValueError):
            search(graph, RoutePrice(0), **options)
    with pytest.raises(ValueError, match="endpoints"):
        priced_route(graph, "s", "s", budget=1, shortest_legal_distance_m=1, price=RoutePrice(0))
    with pytest.raises(ValueError, match="endpoints"):
        priced_route(
            graph, "s", "nowhere", budget=1, shortest_legal_distance_m=1, price=RoutePrice(0)
        )
    for values in ((-1, 0), (0, -1), (float("nan"), 0), (0, float("inf"))):
        with pytest.raises(ValueError, match="prices"):
            RoutePrice(*values)


def random_graph(seed):
    rng = Random(seed)
    arcs = [
        Arc(
            f"{i}-{j}",
            f"{i}-{j}",
            str(i),
            str(j),
            rng.randint(1, 5),
            rng.randint(1, 7),
            rng.choice([1, 3, 4]),
            rng.choice([None, "A", "B", "C"]),
            preference_cost_s=rng.randint(1, 9),
        )
        for i, j in combinations(range(7), 2)
        if j == i + 1 or rng.random() < 0.4
    ]
    turns = {
        (a.id, b.id): Turn(
            stress=rng.choice([1, 4]),
            delay_s=rng.randint(0, 3),
            project_id=rng.choice([None, "A"]),
            prohibited=rng.random() < 0.1,
        )
        for a in arcs
        for b in arcs
        if a.v == b.u
    }
    return InvestmentGraph(arcs, {"A": 2, "B": 3, "C": 4}, turns)


def score(route, price, projects, funded=frozenset()):
    return (
        route.generalized_cost_s
        + price.distance_s_per_m * route.distance_m
        + price.capital_s_per_nzd * sum(projects[p] for p in route.project_ids - funded)
    )


@pytest.mark.parametrize("seed", range(30))
def test_unpriced_capital_and_a_slack_budget_give_the_exact_constrained_optimum(seed):
    graph = random_graph(seed)
    standard = PlanningStandard(2, 2, 25)
    complete = graph.search("0", "6", budget=9, standard=standard, use_bounds=False)
    assert complete.complete
    for price in (RoutePrice(0), RoutePrice(0, 1), RoutePrice(0, 0.3)):
        if complete.shortest_legal_distance_m is None:
            continue
        found = priced_route(
            graph,
            "0",
            "6",
            budget=9,
            shortest_legal_distance_m=complete.shortest_legal_distance_m,
            price=price,
            standard=standard,
        )
        if not complete.routes:
            assert found.route is None and found.stop_reason == "no_route"
            continue
        # A dominated route never scores less than the route that dominates it, so the
        # complete non-dominated set contains the best score.
        best = min(score(route, price, graph.projects) for route in complete.routes)
        assert score(found.route, price, graph.projects) == pytest.approx(best)


@pytest.mark.parametrize("seed", range(30))
def test_priced_routes_are_always_acceptable_and_never_beat_the_true_best_score(seed):
    graph = random_graph(seed)
    standard = PlanningStandard(2, 2, 25)
    rng = Random(1000 + seed)
    budget = rng.choice([2, 3, 5, 9])
    funded = frozenset(rng.sample(sorted(graph.projects), rng.randint(0, 2)))
    complete = graph.search("0", "6", budget=budget, standard=standard, use_bounds=False)
    assert complete.complete
    if complete.shortest_legal_distance_m is None:
        return
    for price in DEFAULT_PRICES:
        found = priced_route(
            graph,
            "0",
            "6",
            budget=budget,
            shortest_legal_distance_m=complete.shortest_legal_distance_m,
            price=price,
            standard=standard,
            funded=funded,
        )
        if found.route is None:
            continue
        # The independent checker recomputes the path, its projects and its totals.
        checked_route(graph, found.route, ("0", "6"), standard, complete.shortest_legal_distance_m)
        assert found.route.capital_cost <= budget
        assert complete.routes, "a priced route exists where the complete search found none"
        best = min(score(route, price, graph.projects, funded) for route in complete.routes)
        assert score(found.route, price, graph.projects, funded) >= best - 1e-9


def test_on_small_graphs_the_priced_search_reaches_the_best_score_in_every_case_tried():
    # An observed property of these 60 graphs, kept as a guard on the heuristic's quality.
    # It is not a guarantee: the next test constructs a miss.
    searches = 0
    for seed in range(60):
        graph = random_graph(seed)
        standard = PlanningStandard(2, 2, 25)
        rng = Random(1000 + seed)
        budget = rng.choice([2, 3, 5, 9])
        funded = frozenset(rng.sample(sorted(graph.projects), rng.randint(0, 2)))
        complete = graph.search("0", "6", budget=budget, standard=standard, use_bounds=False)
        if not complete.routes:
            continue
        for price in DEFAULT_PRICES:
            found = priced_route(
                graph,
                "0",
                "6",
                budget=budget,
                shortest_legal_distance_m=complete.shortest_legal_distance_m,
                price=price,
                standard=standard,
                funded=funded,
            )
            best = min(score(route, price, graph.projects, funded) for route in complete.routes)
            assert score(found.route, price, graph.projects, funded) == pytest.approx(best)
            searches += 1
    assert searches == 420


def test_a_priced_search_can_miss_the_best_score_because_a_project_is_paid_once():
    # Two ways to the middle: through Q, quicker and scoring less so far, or through P.
    # The last street also needs P. The label through P would finish cheaper, but it
    # was dropped at the middle. This is the documented limit of the heuristic.
    graph = InvestmentGraph(
        [
            arc("q", "s", "m", 1, 10, 4, "Q"),
            arc("p1", "s", "m", 1, 12, 4, "P"),
            arc("p2", "m", "t", 1, 1, 4, "P"),
        ],
        {"P": 4, "Q": 5},
    )
    price = RoutePrice(1)
    complete = graph.search("s", "t", budget=100, standard=PlanningStandard(2, 2, 100))
    best = min(complete.routes, key=lambda route: score(route, price, graph.projects))
    assert best.project_ids == {"P"} and score(best, price, graph.projects) == 17
    found = search(graph, price, budget=100).route
    assert found.project_ids == {"P", "Q"} and score(found, price, graph.projects) == 20
    checked_route(graph, found, ("s", "t"), PlanningStandard(2, 2, 100), 2)


def test_columns_are_distinct_counted_and_limited_to_the_journeys_asked_for():
    graph = choice()
    endpoints = {"one": ("s", "t"), "two": ("a", "t"), "cut off": ("t", "s")}
    shortest = {"one": 2.0, "two": 1.0, "cut off": None}
    found, stats = priced_columns(
        graph, endpoints, shortest, budget=1000, standard=PlanningStandard(2, 2, 100)
    )
    assert {name: {r.project_ids for r in rows} for name, rows in found.items()} == {
        "one": {frozenset({"dear"}), frozenset({"cheap"})},
        "two": {frozenset()},
    }
    assert stats["journeysSearched"] == 2
    assert stats["searches"] == 2 * len(DEFAULT_PRICES)
    assert stats["searchStopReasons"] == {"route": 2 * len(DEFAULT_PRICES)}
    assert stats["distinctRoutes"] == 3 and stats["searchElapsedS"] >= 0
    only, stats = priced_columns(
        graph,
        endpoints,
        shortest,
        budget=5,
        standard=PlanningStandard(2, 2, 100),
        prices=[RoutePrice(0)],
        journeys=["one", "cut off"],
    )
    assert only == {}
    assert stats["searchStopReasons"] == {"no_route": 1} and stats["journeysSearched"] == 1
