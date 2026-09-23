from itertools import combinations
from random import Random

import pytest

from cycling_investment_workbench.research.active_search import (
    Arc,
    InvestmentGraph,
    PlanningStandard,
    Turn,
)
from cycling_investment_workbench.research.behaviour import (
    ILLUSTRATIVE_PREFERENCES,
    assign_fixed_demand,
    preference_network,
    route_cost,
)


def test_cycleway_detour_survives_dominance_but_never_overrides_hard_limits():
    graph = InvestmentGraph(
        [
            Arc("road", "road", "s", "t", 1000, 240, 2),
            Arc("path1", "path1", "s", "a", 600, 144, 1, existing_cycleway=True),
            Arc("path2", "path2", "a", "t", 600, 144, 1, existing_cycleway=True),
        ],
        {},
    )
    facilities = {"road": "none", "path1": "protected_lane", "path2": "protected_lane"}
    direct = preference_network(graph, facilities, ILLUSTRATIVE_PREFERENCES[0])
    comfort = preference_network(graph, facilities, ILLUSTRATIVE_PREFERENCES[2])
    assert direct.search("s", "t", budget=0, first_only=True).routes[0].arc_ids == ("road",)
    best = comfort.search("s", "t", budget=0, first_only=True).routes[0]
    assert best.arc_ids == ("path1", "path2")
    assert best.time_s == 288  # Preference must not be reported as physical time.
    constrained = comfort.search("s", "t", budget=0, standard=PlanningStandard(2, 1.1, 1800))
    assert constrained.routes[0].arc_ids == ("road",)
    alternatives = comfort.search("s", "t", budget=0).routes
    assert len(alternatives) == 2  # Slower, longer facility route is retained.
    allocation = assign_fixed_demand(comfort, [*alternatives, best], 100)
    assert len(allocation["routes"]) == 2  # A duplicate optimum is not another choice.
    assert sum(p["flow"] for p in allocation["routes"]) == pytest.approx(100)
    assert allocation["assigned"] + allocation["unassigned"] == 100
    assert allocation["additionalCyclists"] is None


def test_materialized_investment_keeps_crossing_constraints_and_discovers_new_routes():
    graph = InvestmentGraph(
        [
            Arc("a", "a", "s", "m", 100, 30, 4, "street"),
            Arc("b", "b", "m", "t", 100, 30, 1),
        ],
        {"street": 5, "crossing": 1},
        {("a", "b"): Turn(4, 20, "crossing")},
    )
    facilities = {a: "none" for a in graph.arcs}
    before = preference_network(graph, facilities, ILLUSTRATIVE_PREFERENCES[1])
    assert not before.search("s", "t", budget=0).routes
    street = preference_network(
        graph, facilities, ILLUSTRATIVE_PREFERENCES[1], frozenset({"street"})
    )
    assert not street.search("s", "t", budget=0).routes
    after = preference_network(
        graph, facilities, ILLUSTRATIVE_PREFERENCES[1], frozenset({"street", "crossing"})
    )
    found = after.search("s", "t", budget=0).routes
    assert found[0].time_s == 80
    assert route_cost(after, found[0].arc_ids) == found[0].generalized_cost_s
    missing = assign_fixed_demand(before, (), 42)
    assigned = assign_fixed_demand(after, found, 42)
    assert missing["unassigned"] == assigned["assigned"] == 42
    assert assigned["additionalCyclists"] is None  # Access does not create demand.


@pytest.mark.parametrize("seed", range(12))
def test_preference_minimum_matches_exhaustive_routes_with_resource_constraints(seed):
    rng = Random(seed)
    arcs = [
        Arc(
            f"{i}-{j}",
            f"{i}-{j}",
            str(i),
            str(j),
            rng.randint(10, 50),
            rng.randint(5, 40),
            rng.choice((1, 2)),
            preference_cost_s=rng.randint(5, 100),
        )
        for i, j in combinations(range(7), 2)
        if j == i + 1 or rng.random() < 0.4
    ]
    graph = InvestmentGraph(arcs, {})
    standard = PlanningStandard(2, 1.8, 100)
    shortest = graph.shortest_legal_distance("0", "6")
    reference = []

    def enumerate_paths(node, distance, time, cost):
        if node == "6":
            if distance <= shortest * 1.8 and time <= 100:
                reference.append(cost)
            return
        for a in graph.outgoing[node]:
            enumerate_paths(a.v, distance + a.distance_m, time + a.time_s, cost + a.cost_s)

    enumerate_paths("0", 0, 0, 0)
    for use_bounds in (True, False):
        result = graph.search(
            "0", "6", budget=0, standard=standard, first_only=True, use_bounds=use_bounds
        )
        assert bool(result.routes) == bool(reference)
        if reference:
            assert result.routes[0].generalized_cost_s == pytest.approx(min(reference))


def test_invalid_preference_or_assignment_input_is_rejected():
    graph = InvestmentGraph([Arc("a", "a", "s", "t", 10, 10, 1)], {})
    with pytest.raises(ValueError, match="classification"):
        preference_network(graph, {"a": "magic_cycleway"}, ILLUSTRATIVE_PREFERENCES[0])
    with pytest.raises(ValueError, match="finite"):
        assign_fixed_demand(graph, (), float("nan"))
    with pytest.raises(ValueError, match="positive"):
        Arc("a", "a", "s", "t", 10, 10, 1, preference_cost_s=-1)


def test_lower_bound_cache_is_bounded_and_recomputation_preserves_route():
    graph = InvestmentGraph(
        [
            Arc("a", "a", "s", "m", 10, 10, 1, preference_cost_s=20),
            Arc("b", "b", "m", "t", 10, 10, 1, preference_cost_s=20),
        ],
        {},
        bound_cache_size=2,
    )
    first = graph.search("s", "t", budget=0).routes
    graph.lower_bound("m", "cost_s")
    graph.lower_bound("m", "distance_m")
    assert len(graph._bounds) == 2
    assert graph.search("s", "t", budget=0).routes == first
    assert len(graph._bounds) == 2


def test_path_overlap_changes_probabilities_without_changing_total_flow():
    graph = InvestmentGraph(
        [
            Arc("shared", "shared", "s", "a", 80, 80, 1),
            Arc("one", "one", "a", "t", 20, 20, 1),
            Arc("two", "two", "a", "t", 20, 20, 1),
            Arc("separate", "separate", "s", "t", 100, 100, 1),
        ],
        {},
    )
    from cycling_investment_workbench.research.active_search import RouteOption

    routes = [
        RouteOption(ids, frozenset(), 100, 100, 0, 0)
        for ids in [("shared", "one"), ("shared", "two"), ("separate",)]
    ]
    result = assign_fixed_demand(graph, routes, 22, cost_scale_per_s=0)
    assert {tuple(p["arcIds"]): p["flow"] for p in result["routes"]} == pytest.approx(
        {
            ("shared", "one"): 6,
            ("shared", "two"): 6,
            ("separate",): 10,
        }
    )
    assert result["arcFlows"]["shared"] == pytest.approx(12)
