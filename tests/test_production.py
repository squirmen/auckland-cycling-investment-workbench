from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from cycling_investment_workbench.config import PipelineStageConfig, load_config
from cycling_investment_workbench.osm_adapter import DestinationPOI
from cycling_investment_workbench.pipeline import (
    ProductionBlocker,
    StageContext,
)
from cycling_investment_workbench.production import (
    _employment_supports,
    _sa1_supports,
    build_auckland_topology_stage,
    prepare_auckland_demand_stage,
    prepare_zonal_commute_demand,
)
from cycling_investment_workbench.production_routing_stage import production_routing_stage
from cycling_investment_workbench.provenance import hash_path, sha256_file
from cycling_investment_workbench.sources import SourceRecord

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _margin(code: str = "a") -> dict[str, object]:
    return {
        "SA22023_V1_00": code,
        "VAR_2_780": 6,
        "VAR_2_786": 30,
        "VAR_2_822": 3,
        "VAR_2_828": 20,
    }


def test_zonal_preparation_retains_outbound_and_treats_margins_as_soft_evidence() -> None:
    rows = [
        {
            "SA22023_V1_00_usual_residence_address": "a",
            "SA22023_V1_00_workplace_address": "a",
            "2023_Bicycle": "3",
            "2023_Total_stated": "20",
        },
        {
            "SA22023_V1_00_usual_residence_address": "a",
            "SA22023_V1_00_workplace_address": "outside-auckland",
            "2023_Bicycle": "-999",
            "2023_Total_stated": "-999",
        },
        {
            "SA22023_V1_00_usual_residence_address": "outside-auckland",
            "SA22023_V1_00_workplace_address": "a",
            "2023_Bicycle": "3",
            "2023_Total_stated": "10",
        },
    ]

    prepared = prepare_zonal_commute_demand(rows, [_margin()], {"a"})

    assert len(prepared.cells) == 2
    assert prepared.internal_od_count == 1
    assert prepared.outbound_or_special_od_count == 1
    assert prepared.excluded_non_auckland_origin_rows == 1
    assert prepared.suppressed_cycle_cells == 1
    assert prepared.suppressed_eligible_cells == 1
    outbound = next(cell for cell in prepared.cells if cell.destination_zone == "outside-auckland")
    assert outbound.eligible_interval.lower == 0
    assert outbound.eligible_interval.upper == 5
    assert prepared.cycle_point_by_od[outbound.id] == 0
    assert sum(prepared.cycle_point_by_od.values()) == pytest.approx(3)
    assert all(not item.hard_constraint_applied for item in prepared.margin_evidence)
    origin_total = next(
        item
        for item in prepared.margin_evidence
        if item.metric == "total_stated" and item.universe.startswith("all_auckland")
    )
    assert origin_total.margin_point == 30
    assert origin_total.row_point == pytest.approx(22.5)
    assert origin_total.intervals_overlap is False


def test_zonal_preparation_rejects_duplicate_or_empty_auckland_ledger() -> None:
    row = {
        "SA22023_V1_00_usual_residence_address": "a",
        "SA22023_V1_00_workplace_address": "a",
        "2023_Bicycle": "0",
        "2023_Total_stated": "3",
    }
    with pytest.raises(ValueError, match="duplicate"):
        prepare_zonal_commute_demand([row, row], [_margin()], {"a"})
    with pytest.raises(ValueError, match="no Auckland-origin"):
        prepare_zonal_commute_demand([], [_margin()], {"a"})


def test_missing_employment_support_is_retained_as_unresolved_not_centroid() -> None:
    poi = DestinationPOI(
        "poi-a",
        "node",
        "1",
        1.0,
        2.0,
        174.7,
        -36.8,
        "employment",
        ("employment_proxy",),
        1.0,
    )

    supports, unresolved = _employment_supports(
        {"a": [poi]},
        [
            {"SA22023_V1_00": "a", "ec2024": 100},
            {"SA22023_V1_00": "b", "ec2024": 80},
        ],
        {"a", "b"},
    )

    assert {item.zone_id for item in supports} == {"a"}
    assert unresolved == ("b",)
    assert all("fallback" not in item.source for item in supports)


def test_production_blocker_is_machine_readable() -> None:
    blocker = ProductionBlocker(
        stage="assign-routes",
        code="test_blocker",
        message="cannot proceed",
        evidence={"records": 3},
    )

    payload = json.loads(str(blocker))

    assert payload == {
        "code": "test_blocker",
        "evidence": {"records": 3},
        "message": "cannot proceed",
        "stage": "assign-routes",
        "type": "production_blocker",
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _record(source_id: str, path: Path) -> SourceRecord:
    return SourceRecord(
        source_id,
        path,
        True,
        "available",
        path.stat().st_size,
        sha256_file(path),
        None,
    )


def _stage_context(
    tmp_path: Path,
    *,
    stage_name: str,
    sources: dict[str, SourceRecord],
    dependencies=None,
) -> StageContext:
    config = load_config(PROJECT_ROOT / "configs/auckland.yml")
    parameters = copy.deepcopy(config.parameters)
    parameters["validation"]["source_regression_minimum_records"] = {
        source_id: 1 for source_id in sources
    }
    parameters["demand"]["disaggregation"].update({"samples_per_od": 2, "seed": 17})
    parameters["demand"]["purpose_markets"]["school"].update({"samples_per_school": 2, "seed": 17})
    parameters["demand"]["purpose_markets"]["everyday"]["category_weights"] = {"grocery": 1}
    config = replace(
        config,
        root_dir=tmp_path,
        parameters=parameters,
        sources=tuple(replace(source, expected_record_count=None) for source in config.sources),
    )
    run_dir = tmp_path / "runs" / "run-fixture"
    run_dir.mkdir(parents=True, exist_ok=True)
    return StageContext(
        config=config,
        run_id="run-fixture",
        run_dir=run_dir,
        stage=PipelineStageConfig(stage_name, "test", (), {"profile": "fixture"}),
        sources=sources,
        dependencies=dependencies or {},
    )


def _write_stage_fixture(tmp_path: Path) -> dict[str, SourceRecord]:
    osm = tmp_path / "sources" / "auckland.osm"
    osm.parent.mkdir(parents=True)
    osm.write_text(
        """<osm version="0.6" generator="ciw-fixture">
<node id="1" lat="-36.800" lon="174.700"><tag k="shop" v="supermarket"/></node>
<node id="2" lat="-36.800" lon="174.720"><tag k="office" v="yes"/></node>
<way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>
</osm>""",
        encoding="utf-8",
    )
    at = tmp_path / "sources" / "at.geojson"
    _write_json(
        at,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": 1,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[174.700, -36.800], [174.720, -36.800]],
                    },
                    "properties": {"TYPEOFFACILITY": "Separated cycle lane"},
                }
            ],
        },
    )
    sa1 = tmp_path / "sources" / "sa1.geojson"
    _write_json(
        sa1,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [174.69, -36.81],
                                [174.71, -36.81],
                                [174.71, -36.79],
                                [174.69, -36.79],
                                [174.69, -36.81],
                            ]
                        ],
                    },
                    "properties": {
                        "SA12023_V1_00": "a1",
                        "VAR_1_3": 100,
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [174.71, -36.81],
                                [174.73, -36.81],
                                [174.73, -36.79],
                                [174.71, -36.79],
                                [174.71, -36.81],
                            ]
                        ],
                    },
                    "properties": {
                        "SA12023_V1_00": "b1",
                        "VAR_1_3": 80,
                    },
                },
            ],
        },
    )
    sa2 = tmp_path / "sources" / "sa2.geojson"
    _write_json(
        sa2,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [174.68, -36.82],
                                [174.71, -36.82],
                                [174.71, -36.78],
                                [174.68, -36.78],
                                [174.68, -36.82],
                            ]
                        ],
                    },
                    "properties": {
                        "SA22023_V1_00": "a",
                        "SA22023_V1_00_NAME": "A",
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [174.71, -36.82],
                                [174.74, -36.82],
                                [174.74, -36.78],
                                [174.71, -36.78],
                                [174.71, -36.82],
                            ]
                        ],
                    },
                    "properties": {
                        "SA22023_V1_00": "b",
                        "SA22023_V1_00_NAME": "B",
                    },
                },
            ],
        },
    )
    boundary = tmp_path / "sources" / "boundary.geojson"
    _write_json(
        boundary,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [174.67, -36.83],
                                [174.75, -36.83],
                                [174.75, -36.77],
                                [174.67, -36.77],
                                [174.67, -36.83],
                            ]
                        ],
                    },
                    "properties": {
                        "TA2023_V1_00": "076",
                        "TA2023_V1_00_NAME": "Auckland",
                    },
                }
            ],
        },
    )
    margins = tmp_path / "sources" / "margins.json"
    _write_json(
        margins,
        {
            "records": [
                {**_margin("a"), "VAR_2_780": 6},
                {**_margin("b"), "VAR_2_780": 3},
            ]
        },
    )
    jobs = tmp_path / "sources" / "jobs.json"
    _write_json(
        jobs,
        {
            "records": [
                {"SA22023_V1_00": "a", "ec2024": 100},
                {"SA22023_V1_00": "b", "ec2024": 80},
            ]
        },
    )
    schools = tmp_path / "sources" / "schools.json"
    _write_json(
        schools,
        {
            "records": [
                {
                    "School_Id": "1",
                    "Statistical_Area_2_Code": "a",
                    "Longitude": "174.700",
                    "Latitude": "-36.800",
                    "Total": "40",
                    "Status": "Open",
                    "Roll_Date": "2026-07-01T00:00:00",
                },
                {
                    "School_Id": "2",
                    "Statistical_Area_2_Code": "b",
                    "Longitude": "174.720",
                    "Latitude": "-36.800",
                    "Total": None,
                    "Status": "Proposed",
                    "Roll_Date": None,
                },
            ]
        },
    )
    transit = tmp_path / "sources" / "transit.geojson"
    _write_json(
        transit,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [174.710, -36.800]},
                    "properties": {
                        "stop_id": "fixture-station",
                        "stop_name": "Fixture Station",
                        "kind": "rail+interchange",
                        "daily_trips": 100,
                    },
                }
            ],
        },
    )
    jtw = tmp_path / "sources" / "jtw.csv"
    jtw.write_text(
        "SA22023_V1_00_usual_residence_address,"
        "SA22023_V1_00_workplace_address,2023_Bicycle,2023_Total_stated\n"
        "a,a,3,20\n"
        "a,b,-999,-999\n"
        "a,outside,-999,9\n"
        "b,a,0,10\n"
        "b,b,-999,12\n",
        encoding="utf-8-sig",
    )
    dem = tmp_path / "sources" / "dem.tif"
    with rasterio.open(
        dem,
        "w",
        driver="GTiff",
        width=100,
        height=100,
        count=1,
        dtype="float32",
        crs="EPSG:2193",
        transform=from_origin(1_740_000, 5_940_000, 500, 500),
        nodata=-9999,
    ) as dataset:
        dataset.write(np.arange(10_000, dtype="float32").reshape(100, 100), 1)
    terrain_manifest = tmp_path / "sources" / "terrain-manifest.json"
    _write_json(
        terrain_manifest,
        {
            "schema_version": 1,
            "files": [
                {
                    "path": dem.name,
                    "size": dem.stat().st_size,
                    "sha256": sha256_file(dem),
                }
            ],
        },
    )
    return {
        "geofabrik_new_zealand_osm": _record("geofabrik_new_zealand_osm", osm),
        "auckland_transport_cycle_network": _record("auckland_transport_cycle_network", at),
        "stats_nz_sa1_geography": _record("stats_nz_sa1_geography", sa1),
        "stats_nz_sa2_geography": _record("stats_nz_sa2_geography", sa2),
        "stats_nz_auckland_boundary": _record("stats_nz_auckland_boundary", boundary),
        "stats_nz_sa2_transport_margins": _record("stats_nz_sa2_transport_margins", margins),
        "stats_nz_business_demography_sa2_2024": _record(
            "stats_nz_business_demography_sa2_2024", jobs
        ),
        "educationcounts_schools_auckland": _record("educationcounts_schools_auckland", schools),
        "major_transit_nodes": _record("major_transit_nodes", transit),
        "stats_nz_journey_to_work": _record("stats_nz_journey_to_work", jtw),
        "linz_auckland_dem": _record("linz_auckland_dem", dem),
        "linz_auckland_dem_manifest": _record("linz_auckland_dem_manifest", terrain_manifest),
    }


def test_compact_real_stages_require_pbf_before_production_routing(
    tmp_path: Path,
) -> None:
    sources = _write_stage_fixture(tmp_path)
    topology_context = _stage_context(
        tmp_path,
        stage_name="build-topology",
        sources=sources,
    )

    topology_result = build_auckland_topology_stage(topology_context)
    topology_artifact = topology_result.outputs["topology"]
    topology_path = topology_artifact / "topology.json"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))

    assert topology_result.metrics["row_counts"]["directed_physical_edges"] == 1
    assert len(topology["destination_pois"]) == 2
    demand_context = _stage_context(
        tmp_path,
        stage_name="prepare-demand",
        sources=sources,
        dependencies={"build-topology": {"topology": hash_path(topology_artifact)}},
    )
    demand_result = prepare_auckland_demand_stage(demand_context)
    demand_path = demand_result.outputs["demand"]
    demand = json.loads(demand_path.read_text(encoding="utf-8"))
    assert demand["publication_grade_ready"] is True
    assert demand_result.metrics["row_counts"]["outbound_or_special_zonal_od"] == 1
    assert demand_result.metrics["row_counts"]["school_destinations"] == 1
    assert demand_result.metrics["row_counts"]["excluded_non_open_schools"] == 1
    assert demand["purpose_surfaces"]["school"]["destinations"][0]["status"] == "open"
    assert demand_result.metrics["row_counts"]["school_od"] > 0
    assert demand_result.metrics["row_counts"]["everyday_od"] > 0
    assert demand_result.metrics["row_counts"]["transit_od"] > 0
    assert demand["confidentiality"]["hard_margin_constraint_applied"] is False
    routing_context = _stage_context(
        tmp_path,
        stage_name="assign-routes",
        sources=sources,
        dependencies={
            "build-topology": {"topology": hash_path(topology_artifact)},
            "prepare-demand": {"demand": hash_path(demand_path)},
        },
    )
    with pytest.raises(ProductionBlocker, match="exactly one bounded OSM PBF"):
        production_routing_stage(routing_context)


def test_official_geography_join_resolves_slivers_and_fails_on_overlap_ties(
    tmp_path: Path,
) -> None:
    sources = _write_stage_fixture(tmp_path)
    sa1 = sources["stats_nz_sa1_geography"].path
    sa2 = sources["stats_nz_sa2_geography"].path
    boundary = sources["stats_nz_auckland_boundary"].path

    polygons, supports, zones, diagnostics = _sa1_supports(
        sa1, sa2, boundary, target_crs="EPSG:2193"
    )

    assert set(polygons.index) == {"a", "b"}
    assert {support.zone_id for support in supports} == zones == {"a", "b"}
    assert diagnostics.scoped_auckland_sa1_features == 2
    assert diagnostics.missing_sa2_assignments == 0
    assert diagnostics.ambiguous_sa2_assignments == 0

    payload = json.loads(sa2.read_text(encoding="utf-8"))
    sliver = copy.deepcopy(payload["features"][0])
    sliver["properties"]["SA22023_V1_00"] = "sliver"
    sliver["geometry"] = {
        "type": "Polygon",
        "coordinates": [
            [
                [174.699, -36.801],
                [174.701, -36.801],
                [174.701, -36.799],
                [174.699, -36.799],
                [174.699, -36.801],
            ]
        ],
    }
    payload["features"].append(sliver)
    _write_json(sa2, payload)

    _, supports, _, diagnostics = _sa1_supports(sa1, sa2, boundary, target_crs="EPSG:2193")

    assert next(item for item in supports if item.id == "sa1-a1").zone_id == "a"
    assert diagnostics.ambiguous_sa2_assignments == 1
    assert diagnostics.resolved_ambiguous_sa2_assignments == 1
    assert diagnostics.unresolved_ambiguous_sa2_assignments == 0
    assert diagnostics.minimum_maximum_overlap_share is not None
    assert diagnostics.minimum_maximum_overlap_share > 0.9

    payload["features"].pop()
    duplicate = copy.deepcopy(payload["features"][0])
    duplicate["properties"]["SA22023_V1_00"] = "overlap"
    payload["features"].append(duplicate)
    _write_json(sa2, payload)

    with pytest.raises(ValueError, match="ambiguous=1"):
        _sa1_supports(sa1, sa2, boundary, target_crs="EPSG:2193")
