from __future__ import annotations

from pathlib import Path

import pytest

from cycling_investment_workbench.models import Direction, Edge, FacilityType
from cycling_investment_workbench.osm_adapter import (
    EVERYDAY_POI_MAPPING_VERSION,
    GeographicBounds,
    apply_facility_matches,
    classify_destination_tags,
    extract_osm_network,
    match_at_facilities,
)


def _write_osm(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="ciw-fixture">
  <node id="1" lat="-36.8000" lon="174.7000" />
  <node id="2" lat="-36.8000" lon="174.7100" />
  <node id="3" lat="-36.8050" lon="174.7050" />
  <node id="4" lat="-36.7950" lon="174.7050" />
  <node id="5" lat="-36.8000" lon="174.7200" />
  <node id="6" lat="-36.8100" lon="174.7000" />
  <node id="7" lat="-36.8100" lon="174.7100" />
  <node id="20" lat="-36.8030" lon="174.7150" />
  <node id="21" lat="-36.8030" lon="174.7170" />
  <node id="22" lat="-36.8010" lon="174.7170" />
  <node id="23" lat="-36.8010" lon="174.7150" />
  <node id="9" lat="-36.8020" lon="174.7060">
    <tag k="shop" v="supermarket" />
  </node>
  <way id="10">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="residential"/><tag k="oneway" v="yes"/>
    <tag k="maxspeed" v="30"/><tag k="lanes" v="2"/>
  </way>
  <way id="11">
    <nd ref="2"/><nd ref="5"/>
    <tag k="highway" v="residential"/><tag k="oneway" v="yes"/>
    <tag k="cycleway" v="opposite_lane"/>
  </way>
  <way id="12">
    <nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="residential"/><tag k="bridge" v="yes"/>
    <tag k="layer" v="1"/>
  </way>
  <way id="13">
    <nd ref="6"/><nd ref="7"/><tag k="highway" v="footway"/>
  </way>
  <way id="20">
    <nd ref="20"/><nd ref="21"/><nd ref="22"/><nd ref="23"/><nd ref="20"/>
  </way>
  <relation id="30">
    <member type="way" ref="20" role="outer"/>
    <tag k="type" v="multipolygon"/>
    <tag k="amenity" v="hospital"/>
  </relation>
</osm>
""",
        encoding="utf-8",
    )


def test_osm_adapter_preserves_source_layer_direction_access_and_pois(
    tmp_path: Path,
) -> None:
    source = tmp_path / "network.osm"
    _write_osm(source)

    result = extract_osm_network(source)

    by_way = {edge.source_way_id: edge for edge in result.edges}
    assert by_way["10"].direction is Direction.FORWARD
    assert by_way["10"].speed_kph == 30
    assert by_way["10"].lanes == 2
    assert by_way["11"].direction is Direction.BOTH
    assert by_way["12"].bridge
    assert by_way["12"].u == "osm-node-3"
    assert by_way["12"].attributes["layer"] == "1"
    assert "13" not in by_way
    assert result.excluded_way_count == 1
    destinations = {item.id: item for item in result.destinations}
    assert destinations["osm-poi-9"].category == "grocery"
    assert destinations["osm-poi-9"].roles == ("everyday", "employment_proxy")
    assert destinations["osm-poi-9"].source_osm_type == "node"
    assert destinations["osm-poi-relation-30"].category == "health"
    assert destinations["osm-poi-relation-30"].source_osm_type == "relation"
    assert destinations["osm-poi-relation-30"].source_osm_id == "30"
    assert all(item.mapping_version == EVERYDAY_POI_MAPPING_VERSION for item in result.destinations)
    road_nodes = {by_way["10"].u, by_way["10"].v}
    bridge_nodes = {by_way["12"].u, by_way["12"].v}
    assert road_nodes.isdisjoint(bridge_nodes)


def test_osm_adapter_respects_explicit_bounds_and_missing_file(tmp_path: Path) -> None:
    source = tmp_path / "network.osm"
    _write_osm(source)
    outside = GeographicBounds(170, -40, 171, -39)

    result = extract_osm_network(source, bounds=outside)

    assert result.edges == ()
    assert result.destinations == ()
    with pytest.raises(FileNotFoundError):
        extract_osm_network(tmp_path / "missing.osm")


def test_destination_mapping_is_explicit_and_does_not_reuse_commute() -> None:
    assert classify_destination_tags({"amenity": "pharmacy"}) == (
        "health",
        ("everyday", "employment_proxy"),
    )
    assert classify_destination_tags({"office": "government"}) == (
        "employment",
        ("employment_proxy",),
    )
    assert classify_destination_tags({"amenity": "school"}) is None
    assert classify_destination_tags({"landuse": "industrial"}) == (
        "employment",
        ("employment_proxy",),
    )


def test_facility_matching_requires_overlap_bearing_and_structure_compatibility() -> None:
    ordinary = Edge(
        "ordinary",
        "a",
        "b",
        100,
        geometry=((0, 0), (100, 0)),
    )
    bridge = Edge(
        "bridge",
        "c",
        "d",
        100,
        geometry=((0, 10), (100, 10)),
        bridge=True,
    )
    facility = {
        "type": "Feature",
        "id": "facility-1",
        "geometry": {"type": "LineString", "coordinates": [[0, 1], [100, 1]]},
        "properties": {"TYPEOFFACILITY": "Separated cycle lane"},
    }

    matches = match_at_facilities(
        (ordinary, bridge),
        (facility,),
        facility_crs="EPSG:2193",
        maximum_offset_m=3,
    )

    assert len(matches) == 1
    assert matches[0].edge_id == "ordinary"
    assert matches[0].facility is FacilityType.PROTECTED_LANE
    treated = apply_facility_matches((ordinary, bridge), matches)
    assert treated[0].facility is FacilityType.PROTECTED_LANE
    assert treated[0].attributes["matched_facility_id"] == "facility-1:0"
    assert treated[1].facility is FacilityType.MIXED_TRAFFIC


def test_facility_matching_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError, match="parameters"):
        match_at_facilities((), (), maximum_offset_m=-1)
