import pytest

from cycling_investment_workbench.models import Direction, Edge, Node, ODFlow, RoutePath
from cycling_investment_workbench.routing import (
    assign_demand,
    k_plausible_paths,
    path_size_factors,
    path_size_logit,
    shortest_path,
)
from cycling_investment_workbench.topology import DirectedTopology


def diamond() -> DirectedTopology:
    return DirectedTopology(
        (
            Node("a", 0, 0),
            Node("b", 1, 1),
            Node("c", 1, -1),
            Node("d", 2, 0),
        ),
        (
            Edge("ab", "a", "b", 1, Direction.FORWARD),
            Edge("bd", "b", "d", 1, Direction.FORWARD),
            Edge("ac", "a", "c", 1.1, Direction.FORWARD),
            Edge("cd", "c", "d", 1.1, Direction.FORWARD),
        ),
    )


def test_shortest_path_honours_one_way_direction() -> None:
    graph = diamond()
    path = shortest_path(graph, "a", "d", cost=lambda edge, reversed: edge.length_m)
    assert path is not None
    assert path.edge_ids == ("ab", "bd")
    assert shortest_path(graph, "d", "a", cost=lambda edge, reversed: edge.length_m) is None


def test_yen_returns_distinct_plausible_paths() -> None:
    graph = diamond()
    paths = k_plausible_paths(
        graph,
        "a",
        "d",
        k=3,
        cost=lambda edge, reversed: edge.length_m,
        max_cost_ratio=1.2,
    )
    assert [path.edge_ids for path in paths] == [("ab", "bd"), ("ac", "cd")]
    probabilities = path_size_logit(paths, graph, cost_scale=1)
    assert sum(probabilities) == pytest.approx(1)
    assert probabilities[0] > probabilities[1]


def test_path_size_penalises_overlapping_alternative() -> None:
    graph = DirectedTopology(
        (Node("a", 0, 0), Node("b", 1, 0), Node("c", 2, 1), Node("d", 2, -1)),
        (
            Edge("ab", "a", "b", 1),
            Edge("bc", "b", "c", 1),
            Edge("bd", "b", "d", 1),
        ),
    )
    paths = (
        RoutePath(("a", "b", "c"), ("ab", "bc"), 2, 2),
        RoutePath(("a", "b", "d"), ("ab", "bd"), 2, 2),
    )
    assert path_size_factors(paths, graph) == pytest.approx((0.75, 0.75))


def test_probabilistic_assignment_conserves_origin_flow() -> None:
    graph = diamond()
    od = ODFlow("od", "a", "d", 20, scenario_cycle=10)
    result = assign_demand(
        graph,
        (od,),
        k=2,
        cost=lambda edge, reversed: edge.length_m,
        cost_scale=1,
    )
    assert not result.unassigned_od_ids
    assert result.edge_flow["ab"] + result.edge_flow["ac"] == pytest.approx(10)
    assert sum(result.probabilities_by_od["od"]) == pytest.approx(1)
    assert result.route_status_by_od["od"].status == "assigned"
    assert result.route_status_by_od["od"].path_ids == ("od:path:1", "od:path:2")


def test_physical_detour_cap_is_independent_of_generalized_cost() -> None:
    graph = DirectedTopology(
        (Node("a", 0, 0), Node("b", 0, 1), Node("c", 2, 1), Node("d", 2, 0)),
        (
            Edge("direct", "a", "d", 2, Direction.FORWARD),
            Edge("ab", "a", "b", 1, Direction.FORWARD),
            Edge("bc", "b", "c", 2, Direction.FORWARD),
            Edge("cd", "c", "d", 1, Direction.FORWARD),
        ),
    )

    def comfort_cost(edge: Edge, reversed: bool) -> float:
        del reversed
        return 100 if edge.id == "direct" else 0.1

    paths = k_plausible_paths(
        graph,
        "a",
        "d",
        cost=comfort_cost,
        max_cost_ratio=2,
        max_detour_ratio=1.5,
    )
    assert [path.edge_ids for path in paths] == [("direct",)]


def test_assignment_ledger_retains_failure_reason_and_components() -> None:
    graph = DirectedTopology(
        (Node("a", 0, 0), Node("b", 1, 0), Node("x", 10, 0), Node("y", 11, 0)),
        (Edge("ab", "a", "b", 1), Edge("xy", "x", "y", 1)),
    )
    result = assign_demand(
        graph,
        (
            ODFlow("disconnected", "a", "x", 10, scenario_cycle=5),
            ODFlow("missing", "a", "outside", 10, scenario_cycle=5),
        ),
    )
    assert result.unassigned_od_ids == ("disconnected", "missing")
    assert result.route_status_by_od["disconnected"].reason == "disconnected_components"
    assert result.route_status_by_od["missing"].reason == "missing_destination"
    assert len(result.od_ledger) == 2
    assert not result.path_ledger


def test_assignment_ledgers_retain_snap_purpose_paths_and_intrazonal_od() -> None:
    graph = diamond()
    ods = (
        ODFlow(
            "routed",
            "a",
            "d",
            20,
            scenario_cycle=10,
            purpose="school",
            origin_snap_distance_m=12.5,
            destination_snap_distance_m=7.25,
        ),
        ODFlow("intrazonal", "a", "a", 5, scenario_cycle=2, purpose="everyday"),
    )
    result = assign_demand(
        graph,
        ods,
        k=2,
        cost=lambda edge, reversed: edge.length_m,
        cost_scale=1,
    )
    routed = result.route_status_by_od["routed"]
    assert routed.purpose == "school"
    assert routed.origin_snap_distance_m == pytest.approx(12.5)
    assert routed.destination_snap_distance_m == pytest.approx(7.25)
    assert len(routed.path_ids) == 2
    assert {path.path_id for path in result.path_ledger if path.od_id == "routed"} == set(
        routed.path_ids
    )
    intrazonal = result.route_status_by_od["intrazonal"]
    assert intrazonal.status == "assigned"
    assert intrazonal.probabilities == (1.0,)
    intrazonal_path = next(path for path in result.path_ledger if path.od_id == "intrazonal")
    assert intrazonal_path.length_m == 0
    assert intrazonal_path.edge_ids == ()


def test_assignment_rejects_duplicate_od_ids_instead_of_overwriting_ledger() -> None:
    with pytest.raises(ValueError, match="OD ids must be unique"):
        assign_demand(
            diamond(),
            (
                ODFlow("duplicate", "a", "d", 10, scenario_cycle=1),
                ODFlow("duplicate", "a", "d", 10, scenario_cycle=2),
            ),
        )
