import pytest

from cycling_investment_workbench.connectivity import (
    PRIORITY_PRESETS,
    greedy_cumulative_sequence,
    pareto_frontier,
    preset_scores,
    weighted_low_stress_connectivity,
)
from cycling_investment_workbench.demo import miniature_city_inputs
from cycling_investment_workbench.models import Edge, FacilityType, Node, ODFlow, RoadClass
from cycling_investment_workbench.topology import DirectedTopology


def test_connectivity_is_demand_weighted() -> None:
    graph = DirectedTopology(
        (Node("a", 0, 0), Node("b", 1, 0), Node("c", 2, 0), Node("x", 10, 0)),
        (
            Edge(
                "ab",
                "a",
                "b",
                1,
                road_class=RoadClass.PATH,
                facility=FacilityType.SHARED_PATH,
            ),
            Edge(
                "bc",
                "b",
                "c",
                1,
                road_class=RoadClass.PATH,
                facility=FacilityType.SHARED_PATH,
            ),
        ),
    )
    ods = (
        ODFlow("connected", "a", "c", 100, scenario_cycle=90),
        ODFlow("disconnected", "a", "x", 100, scenario_cycle=10),
    )
    result = weighted_low_stress_connectivity(graph, ods)
    assert result.score == pytest.approx(0.9)
    assert result.connected_by_od == {"connected": True, "disconnected": False}


def test_sequence_recomputes_cumulative_network() -> None:
    city = miniature_city_inputs()

    def score(graph: DirectedTopology) -> float:
        return weighted_low_stress_connectivity(graph, city.od_flows).score

    steps = greedy_cumulative_sequence(city.topology, city.candidates, score)
    assert [step.candidate_id for step in steps] == ["main_street", "central_crossing"]
    assert steps[1].cumulative_score == pytest.approx(1)
    assert steps[1].marginal_score == pytest.approx(
        steps[1].cumulative_score - steps[0].cumulative_score
    )


def test_pareto_frontier_respects_objective_directions() -> None:
    metrics = {
        "cheap": {"benefit": 5, "cost": 2},
        "strong": {"benefit": 10, "cost": 5},
        "dominated": {"benefit": 4, "cost": 6},
    }
    assert pareto_frontier(metrics, maximise=("benefit",), minimise=("cost",)) == (
        "cheap",
        "strong",
    )


def test_named_preset_is_normalised_and_inspectable() -> None:
    metrics = {
        "a": {"demand": 0, "connectivity": 0, "equity": 0, "value": 0},
        "b": {"demand": 1, "connectivity": 1, "equity": 1, "value": 1},
    }
    scores = preset_scores(metrics, PRIORITY_PRESETS["network"])
    assert scores == pytest.approx({"a": 0, "b": 1})
    assert set(PRIORITY_PRESETS) == {
        "network",
        "equity",
        "school",
        "everyday",
        "transit",
        "appraisal",
    }
