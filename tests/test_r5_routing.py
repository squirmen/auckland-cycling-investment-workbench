from __future__ import annotations

import pytest

from cycling_investment_workbench.r5_routing import (
    ProjectTopologyIndex,
    ProjectTraversal,
    R5CyclingEngine,
    ReconciledPath,
    RouteSample,
    SnapNode,
    choose_component_compatible_snaps,
    path_gradient_metrics,
    path_size_probabilities,
    select_route_sample,
)

COMFORT = {
    "lts_1": 1.0,
    "lts_2": 1.25,
    "lts_3": 1.8,
    "lts_4": 3.0,
    "uphill_gradient_weight": 4.0,
    "downhill_gradient_weight": 0.5,
    "tunnel_multiplier": 1.25,
    "bridge_multiplier": 1.05,
}


def _topology() -> ProjectTopologyIndex:
    return ProjectTopologyIndex.from_payload(
        {
            "nodes": [
                {"id": "a", "x": 0.0, "y": 0.0, "layer": 0},
                {"id": "b", "x": 10.0, "y": 0.0, "layer": 0},
                {"id": "c", "x": 20.0, "y": 0.0, "layer": 0},
                {"id": "isolated", "x": 0.0, "y": 10.0, "layer": 2},
            ],
            "edges": [
                {
                    "id": "osm-way-10-segment-0",
                    "u": "a",
                    "v": "b",
                    "source_way_id": "10",
                    "length_m": 10.0,
                    "geometry": [[0.0, 0.0], [10.0, 0.0]],
                    "direction": "both",
                    "gradient": 0.0,
                    "lts": 1,
                    "bridge": False,
                    "tunnel": False,
                },
                {
                    "id": "osm-way-10-segment-1",
                    "u": "b",
                    "v": "c",
                    "source_way_id": "10",
                    "length_m": 10.0,
                    "geometry": [[10.0, 0.0], [20.0, 0.0]],
                    "direction": "forward",
                    "gradient": 0.1,
                    "lts": 2,
                    "bridge": False,
                    "tunnel": False,
                },
            ],
        },
        comfort_parameters=COMFORT,
    )


def test_stratified_route_sample_retains_every_record_and_exact_weights() -> None:
    records = [{"id": f"a-{index}", "source_cell_id": "a"} for index in range(4)] + [
        {"id": "b-1", "source_cell_id": "b"}
    ]
    result = select_route_sample(records, records_per_stratum=2, seed=41)

    assert len(result) == len(records)
    assert sum(item.selected for item in result if item.stratum_id == "a") == 2
    assert {
        (item.inclusion_probability, item.analysis_weight)
        for item in result
        if item.stratum_id == "a"
    } == {(0.5, 2.0)}
    assert next(item for item in result if item.stratum_id == "b") == RouteSample(
        "b-1", "b", True, 1, 1, 1.0, 1.0, 1
    )
    assert result == select_route_sample(records, records_per_stratum=2, seed=41)
    assert all(
        item.selected for item in select_route_sample(records, records_per_stratum=None, seed=0)
    )


def test_path_gradient_metrics_are_length_weighted_and_directional() -> None:
    topology = _topology()
    forward = ReconciledPath(
        (),
        (),
        (ProjectTraversal(0, False), ProjectTraversal(1, False)),
        20,
        20,
    )
    reverse = ReconciledPath(
        (),
        (),
        (ProjectTraversal(1, True), ProjectTraversal(0, True)),
        20,
        20,
    )

    assert path_gradient_metrics(forward, topology.segments) == pytest.approx((5, 1, 0))
    assert path_gradient_metrics(reverse, topology.segments) == pytest.approx((5, 0, 1))


def test_route_sample_rejects_duplicate_ids_and_invalid_sample_size() -> None:
    records = [
        {"id": "same", "source_cell_id": "a"},
        {"id": "same", "source_cell_id": "b"},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        select_route_sample(records, records_per_stratum=1, seed=1)
    with pytest.raises(ValueError, match="positive"):
        select_route_sample(records[:1], records_per_stratum=0, seed=1)


def test_project_mapping_honours_bicycle_direction_and_contiguous_trim() -> None:
    topology = _topology()
    forward = topology.map_way_geometry("10", ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)))
    assert forward is not None
    assert [topology.segments[item.segment_index].edge_id for item in forward] == [
        "osm-way-10-segment-0",
        "osm-way-10-segment-1",
    ]
    assert topology.map_way_geometry("10", ((20.0, 0.0), (10.0, 0.0))) is None

    reconciled = topology.trim_and_reconcile(
        (100,),
        (10,),
        (forward,),
        origin_node_index=1,
        destination_node_index=2,
    )
    assert reconciled is not None
    assert [topology.segments[index].edge_id for index in reconciled.project_edge_indices] == [
        "osm-way-10-segment-1"
    ]
    assert reconciled.length_m == pytest.approx(10)
    assert reconciled.generalized_cost == pytest.approx(17.5)


def test_component_aware_snapping_searches_complete_radius() -> None:
    topology = _topology()
    nearest_isolated = topology.nearest_snap(0, 9.5, maximum_distance_m=20)
    assert nearest_isolated is not None and nearest_isolated.node_id == "isolated"

    pair = topology.snap_pair(0, 9.5, 20, 0, maximum_distance_m=20)
    assert pair is not None
    assert pair[0].component_id == pair[1].component_id
    assert pair[0].node_id in {"a", "b"}
    assert pair[1].node_id == "c"
    engine_filtered = topology.snap_pair(
        0,
        9.5,
        20,
        0,
        maximum_distance_m=20,
        origin_allowed_node_indices=frozenset({1}),
        destination_allowed_node_indices=frozenset({2}),
    )
    assert engine_filtered is not None
    assert (engine_filtered[0].node_id, engine_filtered[1].node_id) == ("b", "c")
    assert choose_component_compatible_snaps({}, {}) is None


def test_snap_pair_uses_distinct_nodes_for_short_intrazonal_trip() -> None:
    topology = _topology()

    pair = topology.snap_pair(0.1, 0, 0.2, 0, maximum_distance_m=20)

    assert pair is not None
    assert pair[0].node_id != pair[1].node_id
    assert {pair[0].node_id, pair[1].node_id} == {"a", "b"}


def test_engine_rejects_same_node_as_an_empty_assigned_path() -> None:
    engine = object.__new__(R5CyclingEngine)
    snap = SnapNode(0, "a", "component:a", 0.0, 0.0, 0.0, 0)

    result = engine.route(snap, snap)

    assert result.status == "unassigned"
    assert result.failure_reason == "origin_destination_same_project_node"
    assert result.alternatives == ()


def test_path_size_probabilities_are_normalised_and_overlap_sensitive() -> None:
    topology = _topology()
    direct = topology.map_way_geometry("10", ((0.0, 0.0), (10.0, 0.0), (20.0, 0.0)))
    assert direct is not None
    first = ReconciledPath((1,), (10,), direct, 27.5, 20.0)
    second = ReconciledPath((2,), (10,), direct[:1], 10.0, 10.0)
    probabilities = path_size_probabilities(
        (first, second),
        topology.segments,
        cost_scale=0.01,
        path_size_coefficient=1.0,
    )
    without_overlap_correction = path_size_probabilities(
        (first, second),
        topology.segments,
        cost_scale=0.01,
        path_size_coefficient=0.0,
    )
    assert sum(probabilities) == pytest.approx(1)
    assert probabilities[0] > without_overlap_correction[0]
