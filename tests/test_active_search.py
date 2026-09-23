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
from cycling_investment_workbench.research.investment import choose_investments, greedy_investments


def arc(id, u, v, length=1, time=None, stress=1, project=None):
    return Arc(id, id, u, v, length, length if time is None else time, stress, project)


def trap():
    return InvestmentGraph(
        [
            arc("sa", "s", "a", stress=4, project="A"),
            arc("ab", "a", "b"),
            arc("bt", "b", "t", stress=4, project="B"),
            arc("sx", "s", "x", length=4),
            arc("xt", "x", "t", length=4),
            arc("uv", "u", "v", stress=4, project="C"),
        ],
        {"A": 1, "B": 1, "C": 1},
    )


def test_two_gap_route_is_found_and_beats_single_project_greedy():
    graph = trap()
    routes = {
        "main": graph.search("s", "t", budget=2).routes,
        "minor": graph.search("u", "v", budget=2).routes,
    }
    assert len(routes["main"]) == 1
    assert routes["main"][0].project_ids == {"A", "B"}
    weights = {"main": 10, "minor": 1}
    greedy = greedy_investments(graph.projects, routes, weights, budget=2)
    optimum = choose_investments(graph.projects, routes, weights, budget=2)
    assert greedy.selected == {"C"}
    assert optimum.selected == {"A", "B"}
    assert optimum.served_weight == 10 and optimum.optimal_within_columns
    assert graph.search(
        "s", "t", budget=2, selected=optimum.selected, allow_new_projects=False
    ).routes
    assert not graph.search(
        "s", "t", budget=1, selected=frozenset({"A"}), allow_new_projects=False
    ).routes


def test_time_distance_tradeoffs_and_shared_project_cost_are_preserved():
    graph = InvestmentGraph(
        [
            arc("slow1", "s", "a", 1, 5, 3, "P"),
            arc("slow2", "a", "t", 1, 5, 3, "P"),
            arc("fast1", "s", "b", 2, 2, 3, "Q"),
            arc("fast2", "b", "t", 2, 2, 3, "Q"),
        ],
        {"P": 10, "Q": 10},
    )
    result = graph.search("s", "t", budget=10, standard=PlanningStandard(2, 2, 20))
    assert result.complete
    assert {(r.distance_m, r.time_s, r.capital_cost) for r in result.routes} == {
        (2, 10, 10),
        (4, 4, 10),
    }
    fast = graph.search("s", "t", budget=10, standard=PlanningStandard(2, 2, 5))
    assert fast.routes[0].project_ids == {"Q"}
    assert not graph.search("t", "s", budget=10).routes


def test_street_work_does_not_erase_crossing_stress_or_turn_prohibitions():
    arcs = [arc("sa", "s", "a", stress=4, project="street"), arc("at", "a", "t")]
    graph = InvestmentGraph(
        arcs, {"street": 1, "crossing": 2}, {("sa", "at"): Turn(4, 15, "crossing")}
    )
    assert not graph.search("s", "t", budget=1).routes
    route = graph.search("s", "t", budget=3).routes[0]
    assert route.project_ids == {"street", "crossing"} and route.time_s == 17
    banned = InvestmentGraph(arcs, graph.projects, {("sa", "at"): Turn(prohibited=True)})
    assert not banned.search("s", "t", budget=3).routes


def test_lower_bounds_prune_dead_ends_without_changing_the_frontier():
    arcs = [arc("direct", "s", "t", 10)]
    for i in range(100):
        arcs += [arc(f"out{i}", "s", str(i), 1), arc(f"back{i}", str(i), "t", 100)]
    graph = InvestmentGraph(arcs, {})
    fast = graph.search("s", "t", budget=0, use_bounds=True)
    plain = graph.search("s", "t", budget=0, use_bounds=False)
    assert fast.routes == plain.routes
    assert fast.labels_expanded < plain.labels_expanded
    limited = graph.search("s", "t", budget=0, use_bounds=False, max_labels=2)
    assert not limited.complete and limited.stop_reason == "label_limit"


@pytest.mark.parametrize("seed", range(12))
def test_matches_exhaustive_simple_path_feasibility_for_every_small_portfolio(seed):
    rng = Random(seed)
    arcs = []
    for i, j in combinations(range(7), 2):
        if j == i + 1 or rng.random() < 0.35:
            p = rng.choice([None, "A", "B", "C"])
            arcs.append(
                arc(
                    f"{i}-{j}",
                    str(i),
                    str(j),
                    rng.randint(1, 5),
                    rng.randint(1, 7),
                    4 if p else 1,
                    p,
                )
            )
    graph = InvestmentGraph(arcs, {"A": 2, "B": 3, "C": 4})
    standard = PlanningStandard(2, 1.8, 18)
    result = graph.search("0", "6", budget=9, standard=standard)
    assert result.complete
    reference = []

    def enumerate_paths(node, distance, time, projects):
        if node == "6":
            if distance <= result.shortest_legal_distance_m * 1.8 and time <= 18:
                reference.append(projects)
            return
        for a in graph.outgoing[node]:
            enumerate_paths(
                a.v,
                distance + a.distance_m,
                time + a.time_s,
                projects | ({a.project_id} if a.project_id else set()),
            )

    enumerate_paths("0", 0, 0, set())
    for mask in range(8):
        selected = {p for i, p in enumerate("ABC") if mask & (1 << i)}
        assert any(r.project_ids <= selected for r in result.routes) == any(
            r <= selected for r in reference
        )
