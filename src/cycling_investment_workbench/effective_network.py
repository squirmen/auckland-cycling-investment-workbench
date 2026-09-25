"""Conservative AT intersection evidence on SPAN's source-identified topology.

No graph edges or connections are inferred here. A site receives delay scenarios
only at an unambiguous at-grade source junction with directed through movements.
All unmatched, complex and competing records remain in the review inventory.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from itertools import pairwise
from math import isfinite
from typing import Any

from pyproj import Transformer
from scipy.spatial import cKDTree

from .research.active_search import Arc, Turn

SOURCE_ID = "at_controlled_intersections"
SOURCE_URL = (
    "https://services2.arcgis.com/JkPEgZJGxhSjYOo0/ArcGIS/rest/services/"
    "RoadingService/FeatureServer/2"
)
NOTE = (
    "AT locations matched to SPAN source junctions. Delay ranges are unfitted "
    "sensitivity assumptions, not observed signal timings. Match status does not "
    "confirm permitted turns, bicycle phases, detection or crossing safety. "
    "The main investment rankings do not include these delays."
)


def directed_ends(edge: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """Use the same arc identities and directions as SPAN's research engine."""
    direction = edge["direction"]
    if direction not in {"both", "forward", "reverse"}:
        raise ValueError(f"unknown direction on {edge['id']}")
    result = []
    if direction in {"both", "forward"}:
        result.append((edge["id"] + ":f", edge["u"], edge["v"]))
    if direction in {"both", "reverse"}:
        result.append((edge["id"] + ":r", edge["v"], edge["u"]))
    return result


def build_intersection_context(
    topology: Mapping[str, Any],
    inventory: Mapping[str, Any],
    *,
    maximum_distance_m: float = 20,
    ambiguity_margin_m: float = 5,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return public points, exact movement records, and native matching counts."""
    if maximum_distance_m <= 0 or ambiguity_margin_m < 0:
        raise ValueError("matching distances must be positive/non-negative")
    if str(topology["crs"]).upper() != "EPSG:2193":
        raise ValueError("intersection matching requires SPAN's metre-based EPSG:2193 graph")
    nodes = {node["id"]: node for node in topology["nodes"]}
    incident: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for edge in topology["edges"]:
        if edge["u"] not in nodes or edge["v"] not in nodes:
            raise ValueError("source edge has an unknown endpoint")
        incident[edge["u"]].append(edge)
        incident[edge["v"]].append(edge)
    # Shape points on a polyline are not enough evidence for a junction match.
    junction_ids = sorted(
        node
        for node, edges in incident.items()
        if len({e["v"] if e["u"] == node else e["u"] for e in edges}) >= 3
    )
    if not junction_ids:
        raise ValueError("source topology has no junctions")
    tree = cKDTree([(nodes[n]["x"], nodes[n]["y"]) for n in junction_ids])
    project = Transformer.from_crs("EPSG:4326", topology["crs"], always_xy=True)
    features, records = [], []
    seen: set[str] = set()
    for feature in inventory["features"]:
        raw = feature["properties"]
        site_id = str(raw["intersection_id"])
        if site_id in seen:
            raise ValueError("duplicate AT intersection identity")
        seen.add(site_id)
        if feature["geometry"]["type"] != "Point":
            raise ValueError("AT intersection geometry must be a point")
        lon, lat = feature["geometry"]["coordinates"][:2]
        if not (isfinite(lon) and isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("invalid intersection coordinate")
        distances, indices = tree.query(project.transform(lon, lat), k=2)
        nearest = float(distances[0])
        second = float(distances[1])
        node_id = junction_ids[int(indices[0])]
        edges = incident[node_id]
        name = str(raw.get("intersection_desc") or "AT intersection")
        context = (name + " " + str(raw.get("intersection_type") or "")).lower()
        status = "matched"
        if nearest > maximum_distance_m:
            status = "no_nearby_junction"
        elif any(term in context for term in ("interchange", "motorway", "ramp", "roundabout")):
            status = "complex_site_review"
        elif second - nearest < ambiguity_margin_m:
            status = "ambiguous_match"
        elif (
            any(
                e["bridge"]
                or e["tunnel"]
                or int(e.get("attributes", {}).get("parsed_layer", 0)) != 0
                for e in edges
            )
            or int(nodes[node_id].get("layer", 0)) != 0
        ):
            status = "structure_review"
        incoming, outgoing = [], []
        for edge in edges:
            for arc_id, u, v in directed_ends(edge):
                if v == node_id:
                    incoming.append((arc_id, u, edge["id"]))
                if u == node_id:
                    outgoing.append((arc_id, v, edge["id"]))
        movements = [
            [a, b]
            for a, origin, first in incoming
            for b, destination, last in outgoing
            if origin != destination and first != last
        ]
        if status == "matched" and not movements:
            status = "no_directed_movements"
        controlled = str(raw.get("controlled") or "").strip().lower() in {"yes", "y", "true", "1"}
        record = {
            "id": site_id,
            "name": name,
            "atSiteNumber": raw.get("intersection_no"),
            "controlled": controlled,
            "matchStatus": status,
            "nodeId": node_id if nearest <= maximum_distance_m else None,
            "matchDistanceM": round(nearest, 2),
            "secondJunctionDistanceM": round(second, 2) if isfinite(second) else None,
            "incidentMaximumLts": max(int(e["lts"]) for e in edges)
            if nearest <= maximum_distance_m
            else None,
            "movementCount": len(movements) if status == "matched" else 0,
            "delayLowS": 20 if controlled else 0,
            "delayS": 45 if controlled else 10,
            "delayHighS": 90 if controlled else 30,
            "delayEvidence": "illustrative_site_default",
        }
        features.append({"type": "Feature", "geometry": feature["geometry"], "properties": record})
        records.append(
            {"siteId": site_id, "nodeId": node_id, "movements": movements, "properties": record}
        )

    # A single junction must never collect two site penalties by accident.
    claims = Counter(r["nodeId"] for r in records if r["properties"]["matchStatus"] == "matched")
    for record in records:
        props = record["properties"]
        if props["matchStatus"] == "matched" and claims[record["nodeId"]] > 1:
            props["matchStatus"] = "competing_sites_review"
            props["movementCount"] = 0
        if props["matchStatus"] != "matched":
            record["movements"] = []
            for key in ("delayLowS", "delayS", "delayHighS"):
                props[key] = None
    statuses = dict(sorted(Counter(f["properties"]["matchStatus"] for f in features).items()))
    matched = [r for r in records if r["movements"]]
    metadata = {
        "version": "1.0.0",
        "method": "unambiguous_at_grade_source_junctions",
        "status": "screening_sensitivity",
        "inventorySites": len(features),
        "matchedSites": len(matched),
        "reviewSites": len(features) - len(matched),
        "directedMovements": sum(len(r["movements"]) for r in matched),
        "maximumDistanceM": maximum_distance_m,
        "ambiguityMarginM": ambiguity_margin_m,
        "counts": statuses,
        "note": NOTE,
    }
    audit = {"schemaVersion": "span.intersections.v1", "metadata": metadata, "sites": matched}
    return {"type": "FeatureCollection", "features": features}, audit, metadata


def turns_for_graph(
    audit: Mapping[str, Any],
    arcs: Sequence[Arc],
    *,
    topology_sha256: str,
    scenario: str = "default",
) -> dict[tuple[str, str], Turn]:
    """Attach delays to topology-consistent SPAN arc pairs in the requested crop."""
    if audit.get("schemaVersion") != "span.intersections.v1":
        raise ValueError("unknown intersection evidence schema")
    if audit.get("topologySha256") != topology_sha256:
        raise ValueError("intersection evidence belongs to a different SPAN topology")
    field = {"low": "delayLowS", "default": "delayS", "high": "delayHighS"}.get(scenario)
    if field is None:
        raise ValueError("unknown delay scenario")
    by_id = {arc.id: arc for arc in arcs}
    turns = {}
    for site in audit["sites"]:
        if site["properties"]["matchStatus"] != "matched":
            raise ValueError("unresolved intersection cannot supply routing delays")
        for incoming, outgoing in site["movements"]:
            if incoming not in by_id or outgoing not in by_id:
                continue  # Cropping legitimately excludes some movements.
            first, last = by_id[incoming], by_id[outgoing]
            if first.v != site["nodeId"] or last.u != site["nodeId"] or first.u == last.v:
                raise ValueError("movement does not meet at the declared source junction")
            key = (incoming, outgoing)
            if key in turns:
                raise ValueError("duplicate intersection delay on one movement")
            # Delay-only sensitivity: site control does not prove a stress level
            # or a permitted signal phase. Existing edge stress remains binding.
            turns[key] = Turn(delay_s=float(site["properties"][field]))
    return turns


def route_delay(arc_ids: Sequence[str], turns: Mapping[tuple[str, str], Turn]) -> float:
    return sum(turns[pair].delay_s for pair in pairwise(arc_ids) if pair in turns)
