"""Source-identity-preserving OpenStreetMap cycling-network extraction.

The adapter segments ways only at their recorded OSM nodes and never joins
coincident coordinates. Distinct OSM nodes remain disconnected even when their
coordinates coincide, while an explicitly shared OSM node remains connected at
a bridge or tunnel approach. Layer, bridge, and tunnel attributes stay on the
physical edge. Everyday and employment proxy destinations are extracted from a
versioned, explicit tag mapping rather than borrowed from commute demand.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from math import atan2, degrees, isfinite
from pathlib import Path
from typing import Any

import osmium
from pyproj import Transformer
from shapely import make_valid
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import transform as transform_geometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .models import Direction, Edge, FacilityType, Node, RoadClass, polyline_length

EVERYDAY_POI_MAPPING_VERSION = "1.1.0"


@dataclass(frozen=True, slots=True)
class GeographicBounds:
    west: float = 174.25
    south: float = -37.35
    east: float = 175.35
    north: float = -36.05

    def contains(self, longitude: float, latitude: float) -> bool:
        return self.west <= longitude <= self.east and self.south <= latitude <= self.north


_AUCKLAND_BOUNDS = GeographicBounds()


@dataclass(frozen=True, slots=True)
class DestinationPOI:
    id: str
    source_osm_type: str
    source_osm_id: str
    x: float
    y: float
    longitude: float
    latitude: float
    category: str
    roles: tuple[str, ...]
    weight: float
    mapping_version: str = EVERYDAY_POI_MAPPING_VERSION


@dataclass(frozen=True, slots=True)
class OSMExtraction:
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    destinations: tuple[DestinationPOI, ...]
    way_count: int
    excluded_way_count: int
    invalid_location_count: int


@dataclass(frozen=True, slots=True)
class FacilityMatch:
    edge_id: str
    feature_id: str
    facility: FacilityType
    overlap_ratio: float
    bearing_difference_degrees: float


_ALLOWED_HIGHWAYS = frozenset(
    {
        "cycleway",
        "path",
        "footway",
        "pedestrian",
        "steps",
        "track",
        "living_street",
        "residential",
        "service",
        "unclassified",
        "tertiary",
        "tertiary_link",
        "secondary",
        "secondary_link",
        "primary",
        "primary_link",
        "trunk",
        "trunk_link",
    }
)
_BICYCLE_POSITIVE = frozenset({"yes", "designated", "permissive", "destination"})
_BICYCLE_NEGATIVE = frozenset({"no", "private", "use_sidepath"})
_EVERYDAY_AMENITY = {
    "pharmacy": "health",
    "doctors": "health",
    "clinic": "health",
    "hospital": "health",
    "dentist": "health",
    "library": "civic",
    "community_centre": "civic",
    "townhall": "civic",
    "post_office": "civic",
    "bank": "services",
    "marketplace": "grocery",
}
_GROCERY_SHOPS = frozenset({"supermarket", "convenience", "greengrocer", "bakery"})
_RECREATION_LEISURE = frozenset(
    {"fitness_centre", "sports_centre", "park", "playground", "swimming_pool"}
)
_EMPLOYMENT_LANDUSE = frozenset({"commercial", "industrial", "institutional", "retail"})
_EMPLOYMENT_BUILDINGS = frozenset(
    {"civic", "college", "commercial", "hospital", "industrial", "office", "retail", "school"}
)


def _tag_dict(tags: Any) -> dict[str, str]:
    return {tag.k: tag.v for tag in tags}


def _parse_layer(tags: Mapping[str, str]) -> int:
    raw = tags.get("layer")
    if raw is not None:
        try:
            return int(float(raw))
        except ValueError:
            pass
    if tags.get("bridge") not in {None, "no"}:
        return 1
    if tags.get("tunnel") not in {None, "no"}:
        return -1
    return 0


def _cycle_accessible(tags: Mapping[str, str]) -> bool:
    highway = tags.get("highway")
    if highway not in _ALLOWED_HIGHWAYS:
        return False
    bicycle = tags.get("bicycle", "").lower()
    if bicycle in _BICYCLE_NEGATIVE:
        return False
    if highway in {"footway", "pedestrian", "steps"} and bicycle not in _BICYCLE_POSITIVE:
        return False
    access = tags.get("access", "").lower()
    return not (access in {"no", "private"} and bicycle not in _BICYCLE_POSITIVE)


def _direction(tags: Mapping[str, str]) -> Direction:
    bicycle_oneway = tags.get("oneway:bicycle", tags.get("bicycle:oneway", "")).lower()
    if bicycle_oneway in {"no", "0", "false"}:
        return Direction.BOTH
    if bicycle_oneway in {"-1", "reverse"}:
        return Direction.REVERSE
    if bicycle_oneway in {"yes", "1", "true"}:
        return Direction.FORWARD
    if any(
        value.lower().startswith("opposite")
        for key, value in tags.items()
        if key.startswith("cycleway")
    ):
        return Direction.BOTH
    raw = tags.get("oneway", "").lower()
    if raw in {"-1", "reverse"}:
        return Direction.REVERSE
    if raw in {"yes", "1", "true"} or tags.get("junction") == "roundabout":
        return Direction.FORWARD
    return Direction.BOTH


def _road_class(highway: str) -> RoadClass:
    if highway in {"trunk", "trunk_link"}:
        return RoadClass.MOTORWAY
    if highway in {"primary", "primary_link", "secondary", "secondary_link"}:
        return RoadClass.ARTERIAL
    if highway in {"tertiary", "tertiary_link", "unclassified"}:
        return RoadClass.COLLECTOR
    if highway == "service":
        return RoadClass.SERVICE
    if highway in {"cycleway", "path", "footway", "pedestrian", "steps", "track"}:
        return RoadClass.PATH
    return RoadClass.LOCAL


def _facility(tags: Mapping[str, str]) -> FacilityType:
    highway = tags.get("highway", "")
    cycleway_values = " ".join(
        value.lower() for key, value in tags.items() if key.startswith("cycleway")
    )
    if highway in {"cycleway", "path"} and tags.get("bicycle") in _BICYCLE_POSITIVE:
        return FacilityType.SHARED_PATH
    if "track" in cycleway_values or tags.get("separation") in {"kerb", "bollard", "barrier"}:
        return FacilityType.PROTECTED_LANE
    if "lane" in cycleway_values:
        return FacilityType.PAINTED_LANE
    if highway in {"living_street", "cycleway"} or tags.get("cyclestreet") == "yes":
        return FacilityType.QUIET_STREET
    return FacilityType.MIXED_TRAFFIC


def _number(value: str | None, *, integer: bool = False) -> float | int | None:
    if value is None:
        return None
    token = value.split(";")[0].strip().lower()
    multiplier = 1.609344 if "mph" in token else 1.0
    digits = "".join(character for character in token if character.isdigit() or character == ".")
    if not digits:
        return None
    parsed = float(digits) * multiplier
    return round(parsed) if integer else parsed


def classify_destination_tags(tags: Mapping[str, str]) -> tuple[str, tuple[str, ...]] | None:
    """Return the explicit destination category and independent demand roles."""

    amenity = tags.get("amenity", "").lower()
    shop = tags.get("shop", "").lower()
    leisure = tags.get("leisure", "").lower()
    if amenity in _EVERYDAY_AMENITY:
        return _EVERYDAY_AMENITY[amenity], ("everyday", "employment_proxy")
    if shop in _GROCERY_SHOPS:
        return "grocery", ("everyday", "employment_proxy")
    if shop and shop not in {"vacant", "no"}:
        return "retail", ("everyday", "employment_proxy")
    if leisure in _RECREATION_LEISURE:
        return "recreation", ("everyday", "employment_proxy")
    if (
        tags.get("office")
        or tags.get("industrial")
        or tags.get("craft")
        or tags.get("landuse", "").lower() in _EMPLOYMENT_LANDUSE
        or tags.get("building", "").lower() in _EMPLOYMENT_BUILDINGS
    ):
        return "employment", ("employment_proxy",)
    return None


class _AucklandHandler(osmium.SimpleHandler):
    def __init__(self, bounds: GeographicBounds, transformer: Transformer) -> None:
        super().__init__()
        self.bounds = bounds
        self.transformer = transformer
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.destinations: list[DestinationPOI] = []
        self.way_count = 0
        self.excluded_way_count = 0
        self.invalid_location_count = 0

    def node(self, node: Any) -> None:
        if not node.location.valid():
            return
        longitude = float(node.location.lon)
        latitude = float(node.location.lat)
        if not self.bounds.contains(longitude, latitude):
            return
        classified = classify_destination_tags(_tag_dict(node.tags))
        if classified is None:
            return
        category, roles = classified
        x, y = self.transformer.transform(longitude, latitude)
        self.destinations.append(
            DestinationPOI(
                id=f"osm-poi-{node.id}",
                source_osm_type="node",
                source_osm_id=str(node.id),
                x=x,
                y=y,
                longitude=longitude,
                latitude=latitude,
                category=category,
                roles=roles,
                weight=1.0,
            )
        )

    def way(self, way: Any) -> None:
        tags = _tag_dict(way.tags)
        classified = classify_destination_tags(tags)
        accessible = _cycle_accessible(tags)
        if not accessible and classified is None:
            if "highway" in tags:
                self.excluded_way_count += 1
            return
        if not accessible and "highway" in tags:
            self.excluded_way_count += 1
        raw_points: list[tuple[int, float, float]] = []
        for reference in way.nodes:
            if not reference.location.valid():
                self.invalid_location_count += 1
                return
            raw_points.append((int(reference.ref), float(reference.lon), float(reference.lat)))
        if len(raw_points) < 2 or not any(
            self.bounds.contains(longitude, latitude) for _, longitude, latitude in raw_points
        ):
            return
        projected = [
            (node_id, *self.transformer.transform(longitude, latitude))
            for node_id, longitude, latitude in raw_points
        ]
        if classified is not None:
            category, roles = classified
            longitude = sum(point[1] for point in raw_points) / len(raw_points)
            latitude = sum(point[2] for point in raw_points) / len(raw_points)
            x, y = self.transformer.transform(longitude, latitude)
            self.destinations.append(
                DestinationPOI(
                    id=f"osm-poi-way-{way.id}",
                    source_osm_type="way",
                    source_osm_id=str(way.id),
                    x=x,
                    y=y,
                    longitude=longitude,
                    latitude=latitude,
                    category=category,
                    roles=roles,
                    weight=1.0,
                )
            )
        if not accessible:
            return
        self.way_count += 1
        layer = _parse_layer(tags)
        bridge = tags.get("bridge") not in {None, "no"}
        tunnel = tags.get("tunnel") not in {None, "no"}
        highway = tags["highway"]
        for index, ((u_id, ux, uy), (v_id, vx, vy)) in enumerate(pairwise(projected)):
            u = f"osm-node-{u_id}"
            v = f"osm-node-{v_id}"
            if u == v:
                continue
            # Connectivity follows explicit OSM node identity. Layer is an edge
            # attribute: duplicating a shared node at a layer transition would
            # incorrectly sever legitimate bridge and tunnel approaches.
            self.nodes.setdefault(u, Node(u, ux, uy))
            self.nodes.setdefault(v, Node(v, vx, vy))
            geometry = ((ux, uy), (vx, vy))
            length = polyline_length(geometry)
            if not isfinite(length) or length <= 0:
                continue
            self.edges.append(
                Edge(
                    id=f"osm-way-{way.id}-segment-{index}",
                    u=u,
                    v=v,
                    length_m=length,
                    direction=_direction(tags),
                    geometry=geometry,
                    road_class=_road_class(highway),
                    facility=_facility(tags),
                    speed_kph=_number(tags.get("maxspeed")),
                    lanes=_number(tags.get("lanes"), integer=True),
                    source_way_id=str(way.id),
                    bridge=bridge,
                    tunnel=tunnel,
                    attributes={
                        **{
                            key: tags[key]
                            for key in sorted(tags)
                            if key
                            in {
                                "highway",
                                "access",
                                "bicycle",
                                "oneway",
                                "oneway:bicycle",
                                "bicycle:oneway",
                                "cycleway",
                                "cycleway:left",
                                "cycleway:right",
                                "layer",
                                "bridge",
                                "tunnel",
                                "name",
                            }
                        },
                        "parsed_layer": layer,
                    },
                )
            )

    def area(self, area: Any) -> None:
        """Extract classified multipolygon relations at an interior point."""

        if area.from_way():
            return
        classified = classify_destination_tags(_tag_dict(area.tags))
        if classified is None:
            return
        polygons: list[Polygon] = []
        for outer in area.outer_rings():
            shell = [(float(node.lon), float(node.lat)) for node in outer]
            holes = [
                [(float(node.lon), float(node.lat)) for node in inner]
                for inner in area.inner_rings(outer)
            ]
            if len(shell) >= 4:
                polygons.append(Polygon(shell, holes))
        if not polygons:
            return
        geometry = make_valid(unary_union(polygons))
        if geometry.is_empty:
            return
        point = geometry.representative_point()
        longitude = float(point.x)
        latitude = float(point.y)
        if not self.bounds.contains(longitude, latitude):
            return
        category, roles = classified
        x, y = self.transformer.transform(longitude, latitude)
        source_id = str(area.orig_id())
        self.destinations.append(
            DestinationPOI(
                id=f"osm-poi-relation-{source_id}",
                source_osm_type="relation",
                source_osm_id=source_id,
                x=x,
                y=y,
                longitude=longitude,
                latitude=latitude,
                category=category,
                roles=roles,
                weight=1.0,
            )
        )


def extract_osm_network(
    path: str | Path,
    *,
    bounds: GeographicBounds = _AUCKLAND_BOUNDS,
    target_crs: str = "EPSG:2193",
) -> OSMExtraction:
    """Extract the Auckland cycling graph and versioned destinations from OSM."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    handler = _AucklandHandler(bounds, transformer)
    try:
        handler.apply_file(str(source), locations=True, idx="flex_mem")
    except (RuntimeError, OSError) as exc:
        raise ValueError(f"could not parse OSM input {source}: {exc}") from exc
    return OSMExtraction(
        nodes=tuple(sorted(handler.nodes.values(), key=lambda item: item.id)),
        edges=tuple(sorted(handler.edges, key=lambda item: item.id)),
        destinations=tuple(sorted(handler.destinations, key=lambda item: item.id)),
        way_count=handler.way_count,
        excluded_way_count=handler.excluded_way_count,
        invalid_location_count=handler.invalid_location_count,
    )


def _bearing(line: LineString) -> float:
    start = line.coords[0]
    end = line.coords[-1]
    return (degrees(atan2(end[0] - start[0], end[1] - start[1])) + 360.0) % 360.0


def _undirected_bearing_difference(first: float, second: float) -> float:
    difference = abs(first - second) % 180.0
    return min(difference, 180.0 - difference)


def _facility_type(properties: Mapping[str, Any]) -> FacilityType:
    text = " ".join(
        str(properties.get(key, "")) for key in ("TYPEOFFACILITY", "facility_type", "type", "TYPE")
    ).lower()
    if any(token in text for token in ("protected", "separated", "buffered")):
        return FacilityType.PROTECTED_LANE
    if any(token in text for token in ("shared path", "off-road", "off road")):
        return FacilityType.SHARED_PATH
    if any(token in text for token in ("paint", "cycle lane", "shoulder")):
        return FacilityType.PAINTED_LANE
    return FacilityType.MIXED_TRAFFIC


def match_at_facilities(
    edges: Sequence[Edge],
    features: Iterable[Mapping[str, Any]],
    *,
    facility_crs: str = "EPSG:4326",
    target_crs: str = "EPSG:2193",
    maximum_offset_m: float = 20.0,
    minimum_overlap_ratio: float = 0.6,
    maximum_bearing_difference_degrees: float = 30.0,
    require_layer_compatibility: bool = True,
) -> tuple[FacilityMatch, ...]:
    """Conservatively match facilities by overlap, bearing, structure, and layer."""

    if maximum_offset_m < 0 or not 0 <= minimum_overlap_ratio <= 1:
        raise ValueError("facility matching distance/overlap parameters are invalid")
    transformer = Transformer.from_crs(facility_crs, target_crs, always_xy=True)
    prepared: list[tuple[str, LineString, Mapping[str, Any], FacilityType]] = []
    for index, feature in enumerate(features):
        geometry_value = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry_value, Mapping) or not isinstance(properties, Mapping):
            continue
        geometry = shape(geometry_value)
        if geometry.geom_type not in {"LineString", "MultiLineString"} or geometry.is_empty:
            continue
        projected = (
            geometry
            if facility_crs == target_crs
            else transform_geometry(transformer.transform, geometry)
        )
        feature_id = str(
            feature.get("id") or properties.get("OBJECTID") or properties.get("IDENTIFIER") or index
        )
        for part_index, line in enumerate(
            projected.geoms if projected.geom_type == "MultiLineString" else (projected,)
        ):
            prepared.append(
                (f"{feature_id}:{part_index}", line, properties, _facility_type(properties))
            )

    spatial_index = STRtree([item[1] for item in prepared]) if prepared else None

    matches: list[FacilityMatch] = []
    for edge in edges:
        if len(edge.geometry) < 2:
            continue
        edge_line = LineString(edge.geometry)
        edge_bearing = _bearing(edge_line)
        candidates: list[tuple[float, float, str, FacilityType]] = []
        candidate_indices = (
            spatial_index.query(edge_line.buffer(maximum_offset_m))
            if spatial_index is not None
            else ()
        )
        for candidate_index in candidate_indices:
            feature_id, line, properties, facility = prepared[int(candidate_index)]
            if facility is FacilityType.MIXED_TRAFFIC:
                continue
            if require_layer_compatibility:
                raw_layer = properties.get("layer", properties.get("LAYER"))
                try:
                    feature_layer = int(raw_layer) if raw_layer is not None else 0
                except (TypeError, ValueError):
                    continue
                raw_edge_layer = edge.attributes.get("layer", edge.attributes.get("LAYER"))
                try:
                    edge_layer = (
                        int(raw_edge_layer)
                        if raw_edge_layer is not None
                        else 1
                        if edge.bridge
                        else -1
                        if edge.tunnel
                        else 0
                    )
                except (TypeError, ValueError):
                    edge_layer = 1 if edge.bridge else -1 if edge.tunnel else 0
                if feature_layer != edge_layer and (
                    feature_layer != 0 or edge.bridge or edge.tunnel
                ):
                    continue
                structure_text = " ".join(
                    str(properties.get(key, ""))
                    for key in ("bridge", "BRIDGE", "tunnel", "TUNNEL", "STRUCTURE")
                ).lower()
                if edge.bridge and "bridge" not in structure_text and feature_layer == 0:
                    continue
                if edge.tunnel and "tunnel" not in structure_text and feature_layer == 0:
                    continue
            difference = _undirected_bearing_difference(edge_bearing, _bearing(line))
            if difference > maximum_bearing_difference_degrees:
                continue
            overlap = edge_line.intersection(line.buffer(maximum_offset_m)).length
            ratio = min(1.0, overlap / edge.length_m)
            if ratio >= minimum_overlap_ratio:
                candidates.append((ratio, difference, feature_id, facility))
        if candidates:
            ratio, difference, feature_id, facility = min(
                candidates, key=lambda item: (-item[0], item[1], item[2])
            )
            matches.append(FacilityMatch(edge.id, feature_id, facility, ratio, difference))
    return tuple(matches)


def apply_facility_matches(
    edges: Sequence[Edge], matches: Sequence[FacilityMatch]
) -> tuple[Edge, ...]:
    """Return edges updated only by their exact, auditable facility match."""

    by_edge = {match.edge_id: match for match in matches}
    return tuple(
        replace(
            edge,
            facility=by_edge[edge.id].facility,
            attributes={
                **edge.attributes,
                "matched_facility_id": by_edge[edge.id].feature_id,
                "facility_overlap_ratio": by_edge[edge.id].overlap_ratio,
                "facility_bearing_difference_degrees": by_edge[edge.id].bearing_difference_degrees,
            },
        )
        if edge.id in by_edge
        else edge
        for edge in edges
    )
