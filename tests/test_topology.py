from dataclasses import replace

import pytest

from cycling_investment_workbench.models import Direction, Edge, Node
from cycling_investment_workbench.topology import DirectedTopology


def test_directionality_is_preserved() -> None:
    graph = DirectedTopology(
        (Node("a", 0, 0), Node("b", 1, 0), Node("c", 2, 0)),
        (
            Edge("ab", "a", "b", 1, Direction.FORWARD),
            Edge("bc", "b", "c", 1, Direction.REVERSE),
        ),
    )
    assert [(arc.edge_id, arc.head) for arc in graph.outgoing("a")] == [("ab", "b")]
    assert graph.outgoing("b") == ()
    assert [(arc.edge_id, arc.head) for arc in graph.outgoing("c")] == [("bc", "b")]


def test_coincident_nodes_on_different_layers_are_not_merged() -> None:
    graph = DirectedTopology(
        (
            Node("road_w", -1, 0, 0),
            Node("road_e", 1, 0, 0),
            Node("bridge_s", 0, -1, 1),
            Node("bridge_n", 0, 1, 1),
        ),
        (
            Edge("road", "road_w", "road_e", 2),
            Edge("bridge", "bridge_s", "bridge_n", 2, bridge=True),
        ),
    )
    components = graph.weak_components()
    assert len(components) == 2
    assert {frozenset({"road_w", "road_e"}), frozenset({"bridge_s", "bridge_n"})} == set(components)


def test_component_aware_snapping_and_deterministic_tie_break() -> None:
    graph = DirectedTopology(
        (Node("a", -1, 0), Node("b", 1, 0), Node("z", 100, 0)),
        (Edge("ab", "a", "b", 2),),
    )
    assert graph.snap_node(0, 0, max_distance=2).node_id == "a"
    component = graph.component_by_node()["z"]
    snap = graph.snap_node(99, 0, max_distance=2, eligible_components=frozenset({component}))
    assert snap is not None and snap.node_id == "z"
    assert graph.snap_node(0, 0, max_distance=0.5) is None


def test_replace_edges_requires_exact_identity() -> None:
    nodes = (Node("a", 0, 0), Node("b", 1, 0))
    edge = Edge("ab", "a", "b", 1)
    graph = DirectedTopology(nodes, (edge,))
    replaced = graph.replace_edges({"ab": replace(edge, length_m=2)})
    assert graph.edge("ab").length_m == 1
    assert replaced.edge("ab").length_m == 2
    with pytest.raises(KeyError):
        graph.replace_edges({"missing": edge})


def test_geometry_layer_warning_is_reported() -> None:
    graph = DirectedTopology(
        (Node("a", 0, 0, 0), Node("b", 1, 0, 1)),
        (Edge("ab", "a", "b", 1, geometry=((0, 0), (1, 0))),),
    )
    assert "changes layer" in graph.validate()[0]
