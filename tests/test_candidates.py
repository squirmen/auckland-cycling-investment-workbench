import pytest

from cycling_investment_workbench.candidates import (
    DemandResponseParameters,
    apply_candidate,
    candidate_edge_overlap,
    continuous_demand_response,
    evaluate_candidate,
    evaluate_candidate_set,
    generate_candidate_between_terminals,
    generate_exact_edge_candidate,
    validate_candidate,
)
from cycling_investment_workbench.models import (
    CorridorCandidate,
    Edge,
    FacilityType,
    Node,
    ODFlow,
    RoadClass,
)
from cycling_investment_workbench.topology import DirectedTopology


def simple_graph() -> DirectedTopology:
    return DirectedTopology(
        (Node("a", 0, 0), Node("b", 1, 0), Node("c", 2, 0)),
        (
            Edge(
                "ab",
                "a",
                "b",
                100,
                road_class=RoadClass.ARTERIAL,
                facility=FacilityType.MIXED_TRAFFIC,
                speed_kph=50,
                lanes=4,
                traffic_volume=15_000,
            ),
            Edge(
                "bc",
                "b",
                "c",
                100,
                road_class=RoadClass.ARTERIAL,
                facility=FacilityType.MIXED_TRAFFIC,
                speed_kph=50,
                lanes=4,
                traffic_volume=15_000,
            ),
        ),
    )


def test_candidate_changes_only_exact_declared_edges() -> None:
    graph = simple_graph()
    candidate = CorridorCandidate("one", frozenset({"ab"}), 100)
    treated = apply_candidate(graph, candidate)
    assert treated.edge("ab").facility is FacilityType.PROTECTED_LANE
    assert treated.edge("bc") == graph.edge("bc")
    with pytest.raises(KeyError):
        apply_candidate(graph, CorridorCandidate("bad", frozenset({"missing"}), 1))


def test_continuous_response_has_no_threshold_jump_and_is_bounded() -> None:
    tiny = continuous_demand_response(100, 10, 100, 99.99)
    larger = continuous_demand_response(100, 10, 100, 80)
    assert 0 < tiny < larger < 90
    assert continuous_demand_response(100, 10, 100, 100) == 0
    assert continuous_demand_response(100, 10, 100, 110) == 0


def test_elasticity_controls_response() -> None:
    low = continuous_demand_response(100, 10, 100, 75, parameters=DemandResponseParameters(0.5))
    high = continuous_demand_response(100, 10, 100, 75, parameters=DemandResponseParameters(2.0))
    assert high > low > 0


def test_candidate_evaluation_reroutes_before_and_after() -> None:
    graph = simple_graph()
    candidate = CorridorCandidate("corridor", frozenset({"ab", "bc"}), 1_000)
    od = ODFlow("od", "a", "c", 100, observed_cycle=10, scenario_cycle=20)
    evaluation = evaluate_candidate(graph, candidate, (od,))
    assert evaluation.changed_edge_ids == frozenset({"ab", "bc"})
    assert evaluation.treated_cost_by_od["od"] < evaluation.baseline_cost_by_od["od"]
    assert evaluation.additional_cycle_by_od["od"] > 0


def test_candidate_overlap_uses_edge_ids_not_buffers() -> None:
    first = CorridorCandidate("a", frozenset({"1", "2"}), 1)
    second = CorridorCandidate("b", frozenset({"2", "3"}), 1)
    assert candidate_edge_overlap(first, second) == pytest.approx(1 / 3)


def test_exact_edge_generation_validates_connectedness_and_terminals() -> None:
    graph = simple_graph()
    candidate = generate_exact_edge_candidate(
        graph,
        candidate_id="line",
        edge_ids=("ab", "bc"),
        capital_cost=1,
    )
    validation = validate_candidate(graph, candidate)
    assert validation.valid
    assert validation.terminal_nodes == ("a", "c")


def test_disconnected_and_branched_edge_sets_are_rejected() -> None:
    graph = DirectedTopology(
        (Node("a", 0, 0), Node("b", 1, 0), Node("c", 2, 0), Node("d", 1, 1)),
        (
            Edge("ab", "a", "b", 1),
            Edge("bc", "b", "c", 1),
            Edge("bd", "b", "d", 1),
            Edge("cd", "c", "d", 1),
        ),
    )
    with pytest.raises(ValueError, match="branched_corridor"):
        generate_exact_edge_candidate(
            graph,
            candidate_id="branch",
            edge_ids=("ab", "bc", "bd"),
            capital_cost=1,
        )
    disconnected = CorridorCandidate("split", frozenset({"ab", "cd"}), 1)
    assert "disconnected_edge_set" in validate_candidate(graph, disconnected).issues


def test_terminal_generation_returns_auditable_exact_path() -> None:
    graph = simple_graph()
    candidate = generate_candidate_between_terminals(
        graph,
        candidate_id="generated",
        origin="a",
        destination="c",
        capital_cost=50,
    )
    assert candidate.edge_ids == frozenset({"ab", "bc"})


def test_cumulative_evaluation_does_not_double_count_overlapping_projects() -> None:
    graph = simple_graph()
    first = CorridorCandidate("first", frozenset({"ab"}), 100)
    overlapping = CorridorCandidate("overlap", frozenset({"ab", "bc"}), 200)
    od = ODFlow("od", "a", "c", 100, observed_cycle=10, scenario_cycle=20)
    first_result = evaluate_candidate_set(graph, (first,), (od,))
    portfolio_result = evaluate_candidate_set(graph, (first, overlapping), (od,))
    overlap_alone = evaluate_candidate(graph, overlapping, (od,))
    assert portfolio_result.changed_edge_ids == frozenset({"ab", "bc"})
    assert portfolio_result.additional_cycle_trips >= first_result.additional_cycle_trips
    assert portfolio_result.additional_cycle_trips == pytest.approx(
        overlap_alone.additional_cycle_trips
    )
    assert portfolio_result.additional_cycle_trips < (
        first_result.additional_cycle_trips + overlap_alone.additional_cycle_trips
    )


def test_candidate_evaluation_retains_unroutable_and_intrazonal_od_status() -> None:
    graph = simple_graph()
    candidate = CorridorCandidate("corridor", frozenset({"ab", "bc"}), 1_000)
    evaluation = evaluate_candidate(
        graph,
        candidate,
        (
            ODFlow("valid", "a", "c", 10, scenario_cycle=2),
            ODFlow("missing", "a", "outside", 10, scenario_cycle=2),
            ODFlow("intrazonal", "a", "a", 10, scenario_cycle=2),
        ),
    )
    assert evaluation.status_by_od == {
        "intrazonal": "evaluated",
        "missing": "baseline_unroutable",
        "valid": "evaluated",
    }
    assert set(evaluation.additional_cycle_by_od) == {
        "valid",
        "missing",
        "intrazonal",
    }
    assert evaluation.additional_cycle_by_od["missing"] == 0
    assert evaluation.additional_cycle_by_od["intrazonal"] == 0
