from dataclasses import replace

import pytest

from cycling_investment_workbench.research.active_search import (
    Arc,
    InvestmentGraph,
    PlanningStandard,
    Turn,
)
from cycling_investment_workbench.research.connector_portfolios import (
    checked_route,
    compare_budgeted_connectors,
    fixed_connector_cost_sensitivity,
    preferred_solutions,
)
from cycling_investment_workbench.research.investment import InvestmentResult


def graph():
    return InvestmentGraph(
        [
            Arc("ab", "ab", "a", "b", 20, 5, 4, "diagnostic-short:1"),
            Arc("bc", "bc", "b", "c", 20, 5, 1),
            Arc("bd", "bd", "b", "d", 20, 5, 1),
        ],
        {"diagnostic-short:1": 5},
    )


def test_connectors_are_charged_once_across_complete_journeys():
    result = compare_budgeted_connectors(
        graph(),
        {"one": (), "two": ()},
        {"one": ("a", "c"), "two": ("a", "d")},
        {"one": 10, "two": 20},
        budget=5,
        standard=PlanningStandard(),
        max_labels=100,
    )
    for solution in result["solutions"]:
        if solution["budget"] == 5:
            assert solution["capital_cost"] == 5
            assert solution["shortConnectorCount"] == 1
            assert solution["served_journeys"] == solution["checkedRouteWitnesses"] == 2
            assert solution["served_weight"] == 30
        else:
            assert solution["served_journeys"] == 0


def test_capped_search_keeps_checked_original_routes():
    network = graph()
    original = network.search("a", "c", budget=5).routes
    result = compare_budgeted_connectors(
        network,
        {"one": original},
        {"one": ("a", "c")},
        {"one": 10},
        budget=5,
        standard=PlanningStandard(),
        max_labels=1,
    )
    assert result["searchStopReasons"] == {"label_limit": 1}
    assert not result["searchComplete"]
    assert result["originalRouteColumnsRetained"] == result["routeColumns"] == 1
    assert result["solutions"][-1]["served_journeys"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("distance_m", 1),
        ("time_s", 1),
        ("capital_cost", 0),
        ("project_ids", frozenset()),
        ("generalized_cost_s", 1),
        ("existing_cycleway_m", 1),
    ],
)
def test_route_checker_rejects_invented_column_metadata(field, value):
    network = graph()
    route = network.search("a", "c", budget=5).routes[0]
    with pytest.raises(ValueError, match="metadata"):
        checked_route(network, replace(route, **{field: value}), ("a", "c"), PlanningStandard(), 40)


def test_route_checker_checks_turns_stress_direction_endpoints_and_time():
    network = graph()
    route = network.search("a", "c", budget=5).routes[0]
    delayed = InvestmentGraph(
        network.arcs.values(), network.projects, {("ab", "bc"): Turn(delay_s=8)}
    )
    delayed_route = delayed.search("a", "c", budget=5).routes[0]
    assert checked_route(delayed, delayed_route, ("a", "c"), PlanningStandard(), 40).time_s == 18
    with pytest.raises(ValueError, match="prohibited"):
        banned = InvestmentGraph(
            network.arcs.values(), network.projects, {("ab", "bc"): Turn(prohibited=True)}
        )
        checked_route(banned, route, ("a", "c"), PlanningStandard(), 40)
    with pytest.raises(ValueError, match="stress gap"):
        untreated = InvestmentGraph(
            [replace(a, project_id=None) for a in network.arcs.values()], {}
        )
        checked_route(untreated, route, ("a", "c"), PlanningStandard(), 40)
    with pytest.raises(ValueError, match="continuous"):
        checked_route(
            network,
            replace(route, arc_ids=tuple(reversed(route.arc_ids))),
            ("a", "c"),
            PlanningStandard(),
            40,
        )
    with pytest.raises(ValueError, match="destination"):
        checked_route(network, route, ("a", "d"), PlanningStandard(), 40)
    with pytest.raises(ValueError, match="planning standard"):
        checked_route(network, route, ("a", "c"), PlanningStandard(maximum_time_s=1), 40)


def test_unpaired_journeys_and_overbudget_seed_routes_are_refused():
    network = graph()
    with pytest.raises(ValueError, match="paired"):
        compare_budgeted_connectors(
            network,
            {},
            {"x": ("a", "c")},
            {},
            budget=5,
            standard=PlanningStandard(),
            max_labels=100,
        )
    with pytest.raises(ValueError, match="comparison budget"):
        compare_budgeted_connectors(
            network,
            {"x": network.search("a", "c", budget=5).routes},
            {"x": ("a", "c")},
            {"x": 1},
            budget=1,
            standard=PlanningStandard(),
            max_labels=100,
        )


def test_search_limits_keep_a_nested_checked_route_pool():
    messages = []
    result = compare_budgeted_connectors(
        graph(),
        {"x": ()},
        {"x": ("a", "c")},
        {"x": 10},
        budget=5,
        standard=PlanningStandard(),
        max_labels=1,
        label_limits=[1, 3, 100],
        fixed_connector_costs=[0, 1],
        progress=messages.append,
    )
    checks = result["searchLimitChecks"]
    assert [c["maxLabelsPerSearch"] for c in checks] == [1, 3, 100]
    assert [c["routeColumns"] for c in checks] == [0, 1, 1]
    assert [c["retainedRouteColumns"] for c in checks] == [0, 0, 1]
    assert checks[0]["searchStopReasons"] == {"label_limit": 1}
    assert checks[-1]["searchComplete"]
    assert result["solutions"] == checks[-1]["solutions"]
    assert len(messages) == 6
    cases = result["fixedConnectorCostSensitivity"]["cases"]
    assert cases[0]["fixedProgrammeAffordable"]
    assert not cases[1]["fixedProgrammeAffordable"]
    assert cases[1]["solutions"][-1]["served_journeys"] == 0


@pytest.mark.parametrize("limits", [[], [0], [2], [1, 1], [1, 0], [1, 2.5], [True]])
def test_invalid_search_limit_sequences_are_refused(limits):
    with pytest.raises(ValueError, match="label limits"):
        compare_budgeted_connectors(
            graph(),
            {},
            {},
            {},
            budget=5,
            standard=PlanningStandard(),
            max_labels=1,
            label_limits=limits,
        )


@pytest.mark.parametrize("allowance", [-1, float("nan"), float("inf")])
def test_invalid_allowances_are_refused_before_searching(allowance):
    with pytest.raises(ValueError, match="allowances"):
        compare_budgeted_connectors(
            graph(),
            {},
            {},
            {},
            budget=5,
            standard=PlanningStandard(),
            max_labels=1,
            fixed_connector_costs=[allowance],
        )
    with pytest.raises(ValueError, match="allowances"):
        fixed_connector_cost_sensitivity(
            {}, {}, {}, budget=5, fixed_costs=[allowance], reference_selected=frozenset()
        )


def test_fixed_allowance_is_charged_once_and_reselection_is_distinct_from_reference():
    network = graph()
    network = InvestmentGraph(
        [*network.arcs.values(), Arc("ac", "ac", "a", "c", 40, 10, 4, "P")],
        {**network.projects, "P": 6},
    )
    routes = {
        name: network.search("a", destination, budget=6).routes
        for name, destination in (("one", "c"), ("two", "d"))
    }
    result = fixed_connector_cost_sensitivity(
        network.projects,
        routes,
        {"one": 10, "two": 20},
        budget=6,
        fixed_costs=[2, 0, 2],
        reference_selected=frozenset({"diagnostic-short:1"}),
    )
    assert [c["fixedAllowancePerConnectorNzd"] for c in result["cases"]] == [0, 2]
    assert result["sameRouteColumns"] and not result["reroutedForEachCostCase"]
    assert result["referenceServedJourneys"] == 2
    original, expensive = result["cases"]
    assert original["solutions"][-1]["served_journeys"] == 2
    assert expensive["fixedProgrammeCostNzd"] == 7  # Not 9: one shared connector, two journeys.
    assert not expensive["fixedProgrammeAffordable"]
    chosen = expensive["solutions"][-1]
    assert chosen["selected"] == ["P"]
    assert chosen["served_journeys"] == chosen["checkedRouteWitnesses"] == 1
    assert chosen["projectOverlapWithReference"] == 0
    assert chosen["shortConnectorCostNzd"] == 0
    assert expensive["affordableRouteColumns"] == 1
    assert network.projects["diagnostic-short:1"] == 5
    assert routes["two"][0].capital_cost == 5


def test_allowance_check_requires_a_known_reference_and_handles_empty_reference():
    with pytest.raises(ValueError, match="unknown projects"):
        fixed_connector_cost_sensitivity(
            {}, {}, {}, budget=1, fixed_costs=[0], reference_selected=frozenset({"missing"})
        )
    result = fixed_connector_cost_sensitivity(
        {}, {}, {}, budget=1, fixed_costs=[0], reference_selected=frozenset()
    )
    assert result["cases"][0]["solutions"][-1]["projectOverlapWithReference"] == 1


def test_preferred_result_keeps_baseline_when_solver_has_less_access_or_higher_cost():
    baseline = {
        "budget": 20,
        "served_weight": 10,
        "capital_cost": 12,
        "selected": ["cheap"],
        "method": "package_greedy",
        "optimal_within_columns": False,
    }
    worse_cost = {**baseline, "capital_cost": 18, "method": "route_packages_milp"}
    worse_access = {**worse_cost, "capital_cost": 8, "served_weight": 9}
    for worse in (worse_cost, worse_access):
        rows = [worse, baseline]
        preferred = preferred_solutions(rows)
        assert preferred == [baseline]
        assert preferred[0] is not baseline
        assert rows[0] == worse  # Raw solver results remain available, not overwritten.
        assert not preferred[0]["optimal_within_columns"]
    better = {**worse_cost, "served_weight": 11}
    assert preferred_solutions([baseline, better]) == [better]
    assert preferred_solutions([]) == []


def test_preferred_result_is_paired_by_budget_and_deterministic_on_ties():
    a = {"budget": 10, "served_weight": 3, "capital_cost": 2, "selected": ["a"], "method": "a"}
    b = {**a, "selected": ["b"]}
    larger = {**a, "budget": 20, "served_weight": 4}
    assert preferred_solutions([b, larger, a]) == [a, larger]
    assert preferred_solutions([a, larger, b]) == [a, larger]


def test_cost_reference_uses_checked_baseline_when_solver_stops_with_a_dearer_tie(monkeypatch):
    from cycling_investment_workbench.research import connector_portfolios

    network = graph()
    network = InvestmentGraph(
        [*network.arcs.values(), Arc("ac", "ac", "a", "c", 40, 10, 4, "P")],
        {**network.projects, "P": 6},
    )

    def limited_solver(costs, routes, weights, *, budget):
        chosen = frozenset({"P"}) if costs["P"] <= budget else frozenset()
        return InvestmentResult(
            chosen,
            costs["P"] if chosen else 0,
            10 if chosen else 0,
            1 if chosen else 0,
            "route_packages_milp",
            False,
            0.5,
        )

    monkeypatch.setattr(connector_portfolios, "choose_investments", limited_solver)
    result = compare_budgeted_connectors(
        network,
        {"x": ()},
        {"x": ("a", "c")},
        {"x": 10},
        budget=6,
        standard=PlanningStandard(),
        max_labels=100,
        fixed_connector_costs=[0, 2],
    )
    assert result["solutions"][-1]["capital_cost"] == 6
    assert result["preferredSolutions"][-1]["capital_cost"] == 5
    sensitivity = result["fixedConnectorCostSensitivity"]
    assert sensitivity["referenceSelected"] == ["diagnostic-short:1"]
    assert sensitivity["cases"][0]["fixedProgrammeCostNzd"] == 5
    assert sensitivity["cases"][1]["fixedProgrammeCostNzd"] == 7
    assert not sensitivity["cases"][1]["fixedProgrammeAffordable"]
