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
)


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
