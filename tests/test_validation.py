import pytest

from cycling_investment_workbench.models import CounterSite, Edge, Node
from cycling_investment_workbench.topology import DirectedTopology
from cycling_investment_workbench.validation import (
    aggregate_site_counts,
    match_counters,
    regression_metrics,
)


def crossing_graph() -> DirectedTopology:
    return DirectedTopology(
        (
            Node("w", -100, 0),
            Node("e", 100, 0),
            Node("s", 0, -100),
            Node("n", 0, 100),
        ),
        (
            Edge("horizontal", "w", "e", 200, geometry=((-100, 0), (100, 0))),
            Edge("vertical", "s", "n", 200, geometry=((0, -100), (0, 100))),
        ),
    )


def test_counter_match_uses_full_geometry_and_bearing() -> None:
    graph = crossing_graph()
    counters = (
        CounterSite("near_end", 90, 5, 10, 90),
        CounterSite("crossing", 1, 1, 10, 0),
    )
    matches, unmatched = match_counters(counters, graph, max_distance=10, max_bearing_difference=20)
    assert not unmatched
    assert matches["near_end"].edge_id == "horizontal"
    assert matches["crossing"].edge_id == "vertical"


def test_directional_counter_records_reverse_traversal() -> None:
    graph = crossing_graph()
    counter = CounterSite("westbound", 0, 1, 10, 270, bidirectional=False)
    matches, _ = match_counters((counter,), graph, max_distance=5)
    assert matches["westbound"].edge_id == "horizontal"
    assert matches["westbound"].traversal_direction == "reverse"


def test_preferred_exact_association_is_enforced() -> None:
    graph = crossing_graph()
    counter = CounterSite("site", 0, 0, 10)
    matches, _ = match_counters(
        (counter,), graph, preferred_edge_ids={"site": frozenset({"vertical"})}
    )
    assert matches["site"].edge_id == "vertical"


def test_validation_metrics_distinguish_prediction_from_association() -> None:
    perfect = regression_metrics([1, 2, 3], [1, 2, 3], total_reference_count=6)
    assert perfect.coverage == 0.5
    assert perfect.mae == 0
    assert perfect.r_squared == pytest.approx(1)
    assert perfect.calibration_slope == pytest.approx(1)
    poor = regression_metrics([1, 2, 3], [10, 10, 10])
    assert poor.r_squared is not None and poor.r_squared < 0
    assert poor.calibration_slope is None


def test_site_aggregation_prevents_direction_double_count_confusion() -> None:
    values = aggregate_site_counts(
        {"northbound": 10, "southbound": 15, "other": 4},
        {"northbound": "main", "southbound": "main", "other": "other"},
    )
    assert values == {"main": 25, "other": 4}
