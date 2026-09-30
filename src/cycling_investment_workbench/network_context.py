"""Exact-node network context, kept separate from OD accessibility forecasts.

Areas are weakly connected components of the existing low-stress graph. They
describe physical continuity, not directed reachability or acceptable detour.
Geometric simplification is for display only; all contacts use source node IDs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from pyproj import Transformer
from shapely.geometry import MultiLineString, mapping
from shapely.ops import linemerge, transform

CONTEXT_VERSION = "1.0.0"
SEPARATED = frozenset({"protected_lane", "shared_path"})


class Components:
    """Union by size with path compression; labels are assigned separately."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.size: dict[str, int] = {}

    def find(self, node: str) -> str:
        self.parent.setdefault(node, node)
        self.size.setdefault(node, 1)
        root = node
        while self.parent[root] != root:
            root = self.parent[root]
        while node != root:
            parent = self.parent[node]
            self.parent[node] = root
            node = parent
        return root

    def join(self, first: str, second: str) -> None:
        first, second = self.find(first), self.find(second)
        if first == second:
            return
        if self.size[first] < self.size[second]:
            first, second = second, first
        self.parent[second] = first
        self.size[first] += self.size[second]


def build_network_context(
    topology: Mapping[str, Any],
    candidate_edges: Sequence[Mapping[str, Any]],
    *,
    maximum_lts: int = 2,
    simplify_m: float = 2.0,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    """Return display layer, candidate contacts, and auditable context metadata."""

    if maximum_lts not in {1, 2, 3, 4} or simplify_m < 0:
        raise ValueError("invalid network context thresholds")
    nodes = {str(node["id"]): (float(node["x"]), float(node["y"])) for node in topology["nodes"]}
    low = [edge for edge in topology["edges"] if int(edge["lts"]) <= maximum_lts]
    graph = Components()
    for edge in low:
        u, v = str(edge["u"]), str(edge["v"])
        if u not in nodes or v not in nodes:
            raise ValueError(f"low-stress edge has missing node: {edge['id']}")
        graph.join(u, v)
    labels: dict[str, str] = {}
    for node in graph.parent:
        root = graph.find(node)
        labels[root] = min(labels.get(root, node), node)
    component_by_node = {node: labels[graph.find(node)] for node in graph.parent}
    lengths: defaultdict[str, float] = defaultdict(float)
    geometry_by_kind: defaultdict[tuple[str, str], list[list[Any]]] = defaultdict(list)
    for edge in low:
        component = component_by_node[str(edge["u"])]
        lengths[component] += float(edge["length_m"]) / 1_000
        kind = "separated" if edge["facility"] in SEPARATED else "street"
        coordinates = edge.get("geometry") or [nodes[str(edge["u"])], nodes[str(edge["v"])]]
        geometry_by_kind[(component, kind)].append(coordinates)

    transformer = Transformer.from_crs(str(topology["crs"]), "EPSG:4326", always_xy=True)

    def project(x: Any, y: Any, z: Any = None) -> tuple[Any, Any]:
        del z
        lon, lat = transformer.transform(x, y)
        if hasattr(lon, "__iter__"):
            return tuple(round(v, 6) for v in lon), tuple(round(v, 6) for v in lat)
        return round(lon, 6), round(lat, 6)

    features: list[dict[str, Any]] = []
    for (component, kind), lines in sorted(geometry_by_kind.items()):
        # No component is inferred from this merge: topology was resolved above.
        merged = linemerge(MultiLineString(lines))
        parts = list(merged.geoms) if isinstance(merged, MultiLineString) else [merged]
        simplified = [line.simplify(simplify_m, preserve_topology=True) for line in parts]
        for start in range(0, len(simplified), 250):
            geometry = MultiLineString(simplified[start : start + 250])
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(transform(project, geometry)),
                    "properties": {"componentId": component, "kind": kind},
                }
            )

    by_candidate: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    candidates_by_node: defaultdict[str, set[str]] = defaultdict(set)
    for edge in candidate_edges:
        cid = str(edge["candidate_id"])
        by_candidate[cid].append(edge)
        candidates_by_node[str(edge["from_node_id"])].add(cid)
        candidates_by_node[str(edge["to_node_id"])].add(cid)

    contexts: dict[str, dict[str, Any]] = {}
    roles: defaultdict[str, int] = defaultdict(int)
    for cid, raw_edges in sorted(by_candidate.items()):
        edges = sorted(raw_edges, key=lambda edge: int(edge["edge_sequence"]))
        for first, second in pairwise(edges):
            if str(first["to_node_id"]) != str(second["from_node_id"]):
                raise ValueError(f"candidate chain is not continuous: {cid}")
        terminals = [str(edges[0]["from_node_id"]), str(edges[-1]["to_node_id"])]
        corridor_nodes = {
            str(edge[key]) for edge in edges for key in ("from_node_id", "to_node_id")
        }
        contacts = sorted(
            {component_by_node[node] for node in corridor_nodes if node in component_by_node}
        )
        endpoint_components = [component_by_node.get(node) for node in terminals]
        forward = all(edge["baseline_direction"] in {"both", "forward"} for edge in edges)
        reverse = all(edge["baseline_direction"] in {"both", "reverse"} for edge in edges)
        direction = (
            "both"
            if forward and reverse
            else "forward"
            if forward
            else "reverse"
            if reverse
            else "mixed"
        )
        role = (
            "joins_areas"
            if len(contacts) > 1
            else "within_area"
            if all(endpoint_components)
            else "extends_area"
            if contacts
            else "separate"
        )
        roles[role] += 1
        endpoints = []
        for label, node in zip(("A", "B"), terminals, strict=True):
            if node not in nodes:
                raise ValueError(f"candidate terminal has missing node: {cid}:{node}")
            component = component_by_node.get(node)
            endpoints.append(
                {
                    "label": label,
                    "nodeId": node,
                    "coordinates": list(project(*nodes[node])),
                    "componentId": component,
                    "existingKm": lengths[component] if component else 0.0,
                    "touchingCandidateIds": sorted(candidates_by_node[node] - {cid}),
                }
            )
        contexts[cid] = {
            "role": role,
            "lengthKm": sum(float(edge["length_m"]) for edge in edges) / 1_000,
            "direction": direction,
            "componentIds": contacts,
            "contacts": [
                {
                    "nodeId": node,
                    "componentId": component_by_node[node],
                    "coordinates": list(project(*nodes[node])),
                }
                for node in sorted(corridor_nodes)
                if node in component_by_node
            ],
            "existingKm": sum(lengths[component] for component in contacts),
            "endpoints": endpoints,
            "touchingCandidateIds": sorted(
                set().union(*(candidates_by_node[node] for node in corridor_nodes)) - {cid}
            ),
        }
    metadata = {
        "version": CONTEXT_VERSION,
        "method": "weak_components_exact_source_nodes",
        "maximumLts": maximum_lts,
        "displaySimplificationM": simplify_m,
        "edgeCount": len(low),
        "componentCount": len(lengths),
        "lengthKm": sum(lengths.values()),
        "candidateRoles": dict(sorted(roles.items())),
        "note": (
            "Physical continuity only. Direction, crossing quality and OD detour "
            "are not established by sharing an area."
        ),
    }
    return {"type": "FeatureCollection", "features": features}, contexts, metadata


def portfolio_groups(
    candidate_ids: Sequence[str], contexts: Mapping[str, Mapping[str, Any]]
) -> list[list[str]]:
    """Group selected links through existing areas and direct exact-node contacts."""

    graph = Components()
    selected = set(candidate_ids)
    first_by_area: dict[str, str] = {}
    for cid in candidate_ids:
        graph.find(cid)
        context = contexts[cid]
        for component in context["componentIds"]:
            if component in first_by_area:
                graph.join(cid, first_by_area[component])
            else:
                first_by_area[component] = cid
        for other in context["touchingCandidateIds"]:
            if other in selected:
                graph.join(cid, other)
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for cid in candidate_ids:
        groups[graph.find(cid)].append(cid)
    return list(groups.values())
