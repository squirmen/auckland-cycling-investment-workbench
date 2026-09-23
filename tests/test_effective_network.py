from copy import deepcopy

import pytest
from pyproj import Transformer

from cycling_investment_workbench.effective_network import (
    build_intersection_context,
    directed_ends,
    route_delay,
    turns_for_graph,
)
from cycling_investment_workbench.research.active_search import (
    Arc,
    InvestmentGraph,
    PlanningStandard,
)


def fixture():
    x, y = 1757000, 5920000
    nodes = [
        {"id": name, "x": x + dx, "y": y + dy, "layer": 0}
        for name, dx, dy in [
            ("west", -100, 0),
            ("centre", 0, 0),
            ("east", 100, 0),
            ("north", 0, 100),
        ]
    ]
    edges = [
        {
            "id": key,
            "u": u,
            "v": v,
            "length_m": 100,
            "direction": direction,
            "bridge": False,
            "tunnel": False,
            "attributes": {},
            "lts": 1,
        }
        for key, u, v, direction in [
            ("a", "west", "centre", "forward"),
            ("b", "centre", "east", "both"),
            ("c", "centre", "north", "both"),
        ]
    ]
    lon, lat = Transformer.from_crs("EPSG:2193", "EPSG:4326", always_xy=True).transform(x, y)
    inventory = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "intersection_id": 7,
                    "intersection_desc": "Test crossing",
                    "controlled": "Yes",
                },
            }
        ],
    }
    return {"crs": "EPSG:2193", "nodes": nodes, "edges": edges}, inventory


def make_arcs(topology):
    return [
        Arc(a, e["id"], u, v, 100, 24, 1) for e in topology["edges"] for a, u, v in directed_ends(e)
    ]


def test_native_turns_respect_direction_and_add_delay_without_modifying_edges():
    topology, inventory = fixture()
    original = deepcopy(topology)
    layer, audit, summary = build_intersection_context(topology, inventory)
    assert topology == original
    assert summary["matchedSites"] == 1
    assert summary["directedMovements"] == 4
    assert layer["features"][0]["properties"]["nodeId"] == "centre"
    audit["topologySha256"] = "native"
    arcs = make_arcs(topology)
    turns = turns_for_graph(audit, arcs, topology_sha256="native")
    assert ("a:f", "b:f") in turns
    assert not any("a:r" in pair for pair in turns)
    assert ("b:r", "b:f") not in turns
    baseline = InvestmentGraph(arcs, {}).search("west", "east", budget=0).routes[0]
    delayed = InvestmentGraph(arcs, {}, turns).search("west", "east", budget=0).routes[0]
    assert delayed.arc_ids == baseline.arc_ids
    assert delayed.time_s - baseline.time_s == route_delay(delayed.arc_ids, turns) == 45
    assert not InvestmentGraph(arcs, {}, turns).search("east", "west", budget=0).routes
    assert (
        not InvestmentGraph(arcs, {}, turns)
        .search("west", "east", budget=0, standard=PlanningStandard(maximum_time_s=60))
        .routes
    )


@pytest.mark.parametrize(
    "condition", ["bridge", "tunnel", "layer", "ambiguous", "duplicate", "complex", "distant"]
)
def test_unresolved_sites_cannot_inject_delay(condition):
    topology, inventory = fixture()
    if condition in {"bridge", "tunnel"}:
        topology["edges"][0][condition] = True
    elif condition == "layer":
        topology["edges"][0]["attributes"]["parsed_layer"] = 1
    elif condition == "ambiguous":
        extra = deepcopy(topology)
        for node in extra["nodes"]:
            node["id"] += "2"
            node["x"] += 1
        for edge in extra["edges"]:
            for key in ("id", "u", "v"):
                edge[key] += "2"
        topology["nodes"] += extra["nodes"]
        topology["edges"] += extra["edges"]
    elif condition == "duplicate":
        extra = deepcopy(inventory["features"][0])
        extra["properties"]["intersection_id"] = 8
        inventory["features"].append(extra)
    elif condition == "complex":
        inventory["features"][0]["properties"]["intersection_type"] = "State Highway Interchange"
    elif condition == "distant":
        inventory["features"][0]["geometry"]["coordinates"][0] += 0.01
    layer, audit, metadata = build_intersection_context(topology, inventory)
    assert not audit["sites"]
    assert metadata["matchedSites"] == 0
    assert all(f["properties"]["delayS"] is None for f in layer["features"])


def test_stale_and_corrupted_evidence_is_rejected():
    topology, inventory = fixture()
    _, audit, _ = build_intersection_context(topology, inventory)
    audit["topologySha256"] = "native"
    arcs = make_arcs(topology)
    with pytest.raises(ValueError, match="different SPAN topology"):
        turns_for_graph(audit, arcs, topology_sha256="other")
    audit["sites"][0]["nodeId"] = "wrong"
    with pytest.raises(ValueError, match="declared source junction"):
        turns_for_graph(audit, arcs, topology_sha256="native")


def test_zero_delay_reproduces_reference_and_crop_cannot_add_arcs():
    topology, inventory = fixture()
    inventory["features"][0]["properties"]["controlled"] = "N"
    _, audit, _ = build_intersection_context(topology, inventory)
    audit["topologySha256"] = "native"
    arcs = make_arcs(topology)
    turns = turns_for_graph(audit, arcs, topology_sha256="native", scenario="low")
    reference = InvestmentGraph(arcs, {}).search("west", "east", budget=0).routes[0]
    zero = InvestmentGraph(arcs, {}, turns).search("west", "east", budget=0).routes[0]
    assert (zero.arc_ids, zero.time_s, zero.distance_m) == (
        reference.arc_ids,
        reference.time_s,
        reference.distance_m,
    )
    assert not turns_for_graph(audit, arcs[:1], topology_sha256="native")
    with pytest.raises(ValueError, match="unknown delay scenario"):
        turns_for_graph(audit, arcs, topology_sha256="native", scenario="measured")
