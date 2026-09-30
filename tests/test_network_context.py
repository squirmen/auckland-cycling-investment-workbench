from __future__ import annotations

import pytest

from cycling_investment_workbench.network_context import build_network_context, portfolio_groups


def fixture():
    nodes = [{"id": str(i), "x": 1_750_000 + i * 100, "y": 5_920_000} for i in range(8)]
    nodes[7].update(x=nodes[0]["x"], y=nodes[0]["y"])
    topology = {
        "crs": "EPSG:2193",
        "nodes": nodes,
        "edges": [
            {
                "id": "left",
                "u": "0",
                "v": "1",
                "lts": 1,
                "length_m": 100,
                "facility": "shared_path",
            },
            {"id": "right", "u": "3", "v": "4", "lts": 2, "length_m": 100, "facility": "mixed"},
            {"id": "stressful", "u": "1", "v": "3", "lts": 4, "length_m": 200, "facility": "mixed"},
        ],
    }

    def edge(cid, start, end, seq=0, direction="both"):
        return {
            "candidate_id": cid,
            "from_node_id": str(start),
            "to_node_id": str(end),
            "edge_sequence": seq,
            "baseline_direction": direction,
            "length_m": 100,
        }

    edges = [
        edge("bridge", 1, 2),
        edge("bridge", 2, 3, 1),
        edge("extension", 4, 5),
        edge("crossing", 7, 6),
        edge("touch", 5, 6),
    ]
    return topology, edges


def test_contacts_use_exact_nodes_and_groups_are_transitive():
    topology, edges = fixture()
    layer, contexts, metadata = build_network_context(topology, edges)
    assert metadata["edgeCount"] == 2
    assert metadata["componentCount"] == 2
    assert {f["properties"]["kind"] for f in layer["features"]} == {"street", "separated"}
    assert contexts["bridge"]["role"] == "joins_areas"
    assert contexts["bridge"]["componentIds"] == ["0", "3"]
    assert contexts["crossing"]["componentIds"] == []  # Same position, distinct graph node.
    assert contexts["extension"]["role"] == "extends_area"
    assert portfolio_groups(["bridge", "extension", "touch"], contexts) == [
        ["bridge", "extension", "touch"]
    ]
    assert portfolio_groups(["bridge", "crossing"], contexts) == [["bridge"], ["crossing"]]
    assert build_network_context(topology, list(reversed(edges))) == (layer, contexts, metadata)


def test_interior_contacts_and_conflicting_directions_are_retained():
    topology, edges = fixture()
    chain = [
        dict(edges[0], from_node_id="6", to_node_id="1", baseline_direction="forward"),
        dict(edges[1], from_node_id="1", to_node_id="7", baseline_direction="reverse"),
    ]
    _, contexts, _ = build_network_context(topology, chain)
    assert contexts["bridge"]["componentIds"] == ["0"]
    assert [contact["nodeId"] for contact in contexts["bridge"]["contacts"]] == ["1"]
    assert all(endpoint["componentId"] is None for endpoint in contexts["bridge"]["endpoints"])
    assert contexts["bridge"]["direction"] == "mixed"
    assert contexts["bridge"]["role"] == "extends_area"
    chain[1]["from_node_id"] = "2"
    with pytest.raises(ValueError, match="not continuous"):
        build_network_context(topology, chain)
